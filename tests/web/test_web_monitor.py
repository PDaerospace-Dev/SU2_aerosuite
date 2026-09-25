import json
import math
import time

import pandas as pd
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.overview import CaseOverview
from aerosuite.engine.jobs.runner import CaseState, JobRecord
from aerosuite.web.jobs import JobView
from aerosuite.web.layout import project_url
from aerosuite.web.pages.monitor import MAX_POINTS, default_case, line_options

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _start(project_dir, project, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))
    runner = LocalRunner()
    return runner, runner.submit(project_dir, project)


def _wait(runner, project_dir, job, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.refresh(project_dir, job)
        if until(job):
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out: {job.case_status}")


async def _open(user, project_dir):
    await user.open(project_url("monitor", project_dir))


async def test_a_finished_case_shows_charts_verdict_and_log(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A4  # the case that ran last
    residuals = _element(user, "chart-residuals").options
    assert [s["name"] for s in residuals["series"]] == ["rms[Rho]"]
    assert residuals["yAxis"]["name"] == "log10 residual"
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CL", "CD", "CMy"]
    assert _element(user, "monitor-verdict").text == "Convergence: Converged"
    assert "Running Case" in _element(user, "monitor-log").text
    await user.should_see(marker="badge-monitor-plain")


async def test_choosing_columns_and_cases(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    with user:
        _element(user, "monitor-columns").set_value(["CD"])
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CD"]
    with user:
        _element(user, "monitor-case").set_value(A0)
    assert _element(user, "monitor-status").text == f"CONVERGED in job {job.id}"
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CD"]


async def test_defaults_to_the_running_case(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        await user.should_see(marker="monitor-no-history")
    finally:
        runner.cancel(project_dir, job)


async def test_a_case_that_never_ran(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A0
    await user.should_see(marker="monitor-not-run")


def test_long_histories_are_thinned_but_keep_the_last_iteration():
    n = 25_001
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"], "value")["series"][0]["data"]
    assert len(series) <= MAX_POINTS
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_thinning_never_exceeds_max_points_at_the_boundary():
    # count = 4000 -> step = ceil(4000 / 2000) = 2 -> range(0, 4000, 2) is already 2000 indices
    # ending at 3998, so naively appending the last index (3999) would land at 2001 points.
    n = 4000
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"], "value")["series"][0]["data"]
    assert len(series) <= MAX_POINTS
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_short_histories_keep_every_point():
    n = 50
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"], "value")["series"][0]["data"]
    assert len(series) == n
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_nan_values_become_gaps():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.5, math.nan, 0.6]})
    data = line_options([0, 1, 2], df, ["CL"], "value")["series"][0]["data"]
    assert data == [[0, 0.5], [1, None], [2, 0.6]]


def test_default_case_prefers_the_older_jobs_last_started_case_when_the_newest_job_is_all_pending():
    # Right after a submit, every case of the newest job is still PENDING: default_case must not
    # fall through to names[0] when an older, finished job has a genuine last-run case.
    newest = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                        case_status={A0: CaseState.PENDING, A2: CaseState.PENDING, A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.PENDING})
    overview = CaseOverview(rows=[], problems=[], jobs=[newest, older])
    view = JobView(latest=newest, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4]) == A2


def test_default_case_prefers_a_running_case_in_the_newest_job():
    running_job = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                             case_status={A0: CaseState.CONVERGED, A2: CaseState.RUNNING,
                                          A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED,
                                    A4: CaseState.CONVERGED})
    overview = CaseOverview(rows=[], problems=[], jobs=[running_job, older])
    view = JobView(latest=running_job, active=running_job, overview=overview)
    assert default_case(view, [A0, A2, A4]) == A2


def test_default_case_falls_back_to_the_first_case_with_no_jobs():
    overview = CaseOverview(rows=[], problems=[], jobs=[])
    view = JobView(latest=None, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4]) == A0

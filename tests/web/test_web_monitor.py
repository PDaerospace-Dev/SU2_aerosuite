import json
import math
import time

import pandas as pd
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.overview import NOT_RUN, CaseOverview, CaseRow
from aerosuite.engine.jobs.runner import CaseState, JobRecord
from aerosuite.web.jobs import JobView
from aerosuite.web.layout import project_url
from aerosuite.web.pages.monitor import MAX_POINTS, data_job, default_case, line_options

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
    await user.should_see("Job log")  # the whole job's log, not just this case's solver output
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


async def test_a_never_started_cancelled_case_shows_the_older_jobs_data(user: User, ready_project):
    project_dir, project = ready_project
    runner1, job1 = _start(project_dir, project)
    _wait(runner1, project_dir, job1, lambda j: not j.is_active)
    runner2, job2 = _start(project_dir, project, **{A2: "hang"})
    _wait(runner2, project_dir, job2, lambda j: j.case_status[A2] is CaseState.RUNNING)
    job2 = runner2.cancel(project_dir, job2)
    # A4 never started in job2 (the sweep hung on A2 before reaching it) but is CANCELLED anyway.
    assert job2.case_status[A4] is CaseState.CANCELLED
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A2  # the case running when cancelled, not A4
    with user:
        _element(user, "monitor-case").set_value(A4)
    assert _element(user, "monitor-status").text == f"CANCELLED in job {job2.id}"
    assert _element(user, "monitor-data-job").text == f"Showing the run from job {job1.id}"
    assert _element(user, "monitor-verdict").text == "Convergence: Converged"


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


def _by_status(job: JobRecord) -> list:
    """Stand-in for the log-banner rule in tests that build JobRecords directly (no real log
    file to scan): "started" is every case not left at PENDING, in `job.cases` order."""
    return [n for n in job.cases if job.case_status.get(n, CaseState.PENDING) is not CaseState.PENDING]


def test_default_case_prefers_the_older_jobs_last_started_case_when_the_newest_job_is_all_pending():
    # Right after a submit, every case of the newest job is still PENDING: default_case must not
    # fall through to names[0] when an older, finished job has a genuine last-run case.
    newest = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                        case_status={A0: CaseState.PENDING, A2: CaseState.PENDING, A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.PENDING})
    overview = CaseOverview(rows=[], problems=[], jobs=[newest, older])
    view = JobView(latest=newest, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A2


def test_default_case_prefers_a_running_case_in_the_newest_job():
    running_job = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                             case_status={A0: CaseState.CONVERGED, A2: CaseState.RUNNING,
                                          A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED,
                                    A4: CaseState.CONVERGED})
    overview = CaseOverview(rows=[], problems=[], jobs=[running_job, older])
    view = JobView(latest=running_job, active=running_job, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A2


def test_default_case_falls_back_to_the_first_case_with_no_jobs():
    overview = CaseOverview(rows=[], problems=[], jobs=[])
    view = JobView(latest=None, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A0


def test_default_case_skips_a_cancelled_case_that_never_started():
    # Cancelling a job marks every not-yet-finished case CANCELLED, including ones the sweep never
    # reached. default_case must use the log-banner "started" rule, not case_status, to tell them
    # apart from the case that was genuinely running when the job was cancelled.
    newest = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                        case_status={A0: CaseState.CONVERGED, A2: CaseState.CANCELLED,
                                     A4: CaseState.CANCELLED})
    overview = CaseOverview(rows=[], problems=[], jobs=[newest])
    view = JobView(latest=newest, active=None, overview=overview)
    started = {"2": [A0, A2]}  # A4's banner never printed: the sweep hung on A2 before reaching it
    assert default_case(view, [A0, A2, A4], lambda job: started[job.id]) == A2


async def test_a_poll_while_running_updates_the_charts_in_place(user: User, ready_project, history_writer,
                                                                 monkeypatch):
    """Recreating the selects and charts every poll would close an open dropdown."""
    import asyncio

    from aerosuite.web.pages import monitor

    monkeypatch.setattr(monitor, "POLL_SECONDS", 0.05)
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    history = history_writer(project_dir / "runs" / A2, [0.5] * 10)
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        kept = {m: _element(user, m) for m in ("monitor-case", "monitor-columns", "chart-residuals",
                                                "chart-coefficients", "monitor-verdict", "monitor-log")}
        assert len(kept["chart-residuals"].options["series"][0]["data"]) == 10
        with history.open("a") as fh:
            for i in range(10, 15):
                fh.write(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {0.5:12.8f}, {0.02:12.8f}, {-0.1:12.8f}\n")
        deadline = time.monotonic() + 5
        while len(kept["chart-residuals"].options["series"][0]["data"]) != 15:
            assert time.monotonic() < deadline, "the residuals chart never showed the new rows"
            await asyncio.sleep(0.05)
        assert len(kept["chart-coefficients"].options["series"][0]["data"]) == 15
        assert {m: _element(user, m) for m in kept} == kept  # the very same elements, updated in place
    finally:
        runner.cancel(project_dir, job)


def _spy(started):
    calls = []

    def call(job):
        calls.append(job.id)
        return started[job.id]

    return call, calls


def test_data_job_only_scans_jobs_that_include_the_case():
    newest = JobRecord(id="2", backend="local", cases=[A0], log_path="job2.log",
                       case_status={A0: CaseState.CONVERGED})
    older = JobRecord(id="1", backend="local", cases=[A0, A2], log_path="job1.log",
                      case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED})
    rows = [CaseRow(A0, "CONVERGED", "2"), CaseRow(A2, "CONVERGED", "1"), CaseRow(A4, NOT_RUN, None)]
    view = JobView(latest=newest, active=None, overview=CaseOverview(rows=rows, problems=[], jobs=[newest, older]))
    started, calls = _spy({"2": [A0], "1": [A0, A2]})
    assert data_job(view, A2, started) is older
    assert calls == ["1"]  # job 2 never included A2: its log is not scanned
    calls.clear()
    assert data_job(view, A4, started) is None
    assert calls == []  # a case that never ran scans no log at all


def test_default_case_only_scans_jobs_that_include_a_current_case():
    newest = JobRecord(id="2", backend="local", cases=["old_case"], log_path="job2.log",
                       case_status={"old_case": CaseState.CONVERGED})
    older = JobRecord(id="1", backend="local", cases=[A0, A2], log_path="job1.log",
                      case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED})
    view = JobView(latest=newest, active=None, overview=CaseOverview(rows=[], problems=[], jobs=[newest, older]))
    started, calls = _spy({"2": ["old_case"], "1": [A0, A2]})
    assert default_case(view, [A0, A2, A4], started) == A2
    assert calls == ["1"]

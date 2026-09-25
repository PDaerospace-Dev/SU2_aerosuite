import json
import math
import time

import pandas as pd
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.web.layout import project_url
from aerosuite.web.pages.monitor import MAX_POINTS, line_options

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
    assert len(series) <= MAX_POINTS + 1
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_nan_values_become_gaps():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.5, math.nan, 0.6]})
    data = line_options([0, 1, 2], df, ["CL"], "value")["series"][0]["data"]
    assert data == [[0, 0.5], [1, None], [2, 0.6]]

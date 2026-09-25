import json
import time

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.runner import JobState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


@pytest.fixture
def su2_env(monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")


def _plan(project_dir, **cases):
    configs = project_dir / CONFIGS_DIR
    configs.mkdir(exist_ok=True)
    (configs / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))


def _run_to_end(project_dir, project, **cases):
    """Run every case once through the engine (not the page) and wait for the job to end."""
    generate_configs(project_dir, project)
    _plan(project_dir, **cases)
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    deadline = time.monotonic() + 20
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.1)
        job = runner.refresh(project_dir, job)
    assert not job.is_active
    return job


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


async def _open(user, project_dir):
    await user.open(project_url("run", project_dir))


async def test_preflight_errors_disable_submit(user: User, ready_project, monkeypatch):
    project_dir, _ = ready_project
    monkeypatch.delenv("SU2_RUN", raising=False)
    await _open(user, project_dir)
    await user.should_see("SU2_RUN is not set")
    assert not _element(user, "submit").enabled


async def test_submit_all_runs_every_case(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    _plan(project_dir)
    await _open(user, project_dir)
    assert _text(user, f"status-{A0}") == "Not run"
    await user.should_see(marker="badge-run-todo")
    await user.should_see(marker="history-none")
    user.find(marker="submit").click()
    await eventually(lambda: all(_text(user, f"status-{n}") == "CONVERGED" for n in (A0, A2, A4)), timeout=20)
    await user.should_see(marker="badge-run-done")
    jobs = list_jobs(project_dir)
    assert len(jobs) == 1 and jobs[0].cases == [A0, A2, A4]
    await user.should_see(marker=f"history-{jobs[0].id}")


async def test_rerun_failed_and_unconverged_cases(user: User, ready_project, su2_env, eventually):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail", A4: "diverge"})
    _plan(project_dir)  # everything converges from now on
    await _open(user, project_dir)
    assert _text(user, f"status-{A2}") == "FAILED"
    await user.should_see(marker=f"tail-{A2}")
    await user.should_see(marker="badge-run-attention")

    user.find(marker="select-failed").click()
    assert _element(user, f"tick-{A2}").value and not _element(user, f"tick-{A4}").value
    assert not _element(user, "continue").enabled  # A2 failed before writing a solution
    await user.should_see(marker="continue-missing")

    user.find(marker="select-unconverged").click()
    assert _element(user, f"tick-{A4}").value and not _element(user, f"tick-{A0}").value
    assert _element(user, "continue").value is True  # UNCONVERGED with a solution: on by default
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A4}") == "CONVERGED", timeout=20)
    latest = list_jobs(project_dir)[0]
    assert latest.cases == [A4]
    control = (project_dir / "jobs" / latest.id / "configs" / "run_control.txt").read_text()
    assert control.startswith(f"{A4}.cfg, custom, ")
    assert _text(user, f"status-{A2}") == "FAILED"  # not rerun


async def test_cancel_asks_first(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    _plan(project_dir, **{A0: "hang"})
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "RUNNING", timeout=20)
    await user.should_see(marker="badge-run-running")
    assert not _element(user, "submit").enabled
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-keep")
    user.find(marker="cancel-keep").click()
    assert list_jobs(project_dir)[0].is_active
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-confirm")
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "CANCELLED", timeout=20)
    assert list_jobs(project_dir)[0].state is JobState.CANCELLED


async def test_cases_changed_on_disk_follow_into_the_table(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="select-none").click()
    project = open_project(project_dir)
    update_sweep(project, alpha=[0.0, 6.0])  # another tab or the CLI rebuilds the sweep
    save_project(project_dir, project)
    await eventually(lambda: bool(user.find(marker="tick-M0p8_a6_b0").elements), timeout=10)
    await user.should_not_see(marker=f"tick-{A2}")
    assert not _element(user, "tick-M0p8_a6_b0").value

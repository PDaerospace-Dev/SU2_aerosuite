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
    user.find(marker="submit").click()
    await eventually(lambda: all(_text(user, f"status-{n}") == "CONVERGED" for n in (A0, A2, A4)), timeout=20)
    await user.should_see(marker="badge-run-done")
    jobs = list_jobs(project_dir)
    assert len(jobs) == 1 and jobs[0].cases == [A0, A2, A4]
    with user:
        _element(user, "run-tabs").set_value("history")
    await user.should_see(marker=f"history-{jobs[0].id}")


async def test_rerun_failed_and_unconverged_cases(user: User, ready_project, su2_env, eventually):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail", A4: "diverge"})
    _plan(project_dir)  # everything converges from now on
    await _open(user, project_dir)
    assert _text(user, f"status-{A2}") == "FAILED"
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


async def test_a_slow_cancel_does_not_freeze_the_page(user: User, ready_project, su2_env, eventually,
                                                     monkeypatch):
    """Stopping SU2 can take ~20 s; the page must stay responsive and show that it is cancelling."""
    from aerosuite.web.jobs import WATCHER

    project_dir, _ = ready_project
    _plan(project_dir, **{A0: "hang"})
    original = WATCHER.runner.cancel

    def slow_cancel(directory, job):
        time.sleep(1.5)
        return original(directory, job)

    monkeypatch.setattr(WATCHER.runner, "cancel", slow_cancel)
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "RUNNING", timeout=20)
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-confirm")
    user.find(marker="cancel-confirm").click()
    await user.should_see("Cancelling…", retries=10)
    assert list_jobs(project_dir)[0].is_active  # the page answered while the cancel was still running
    assert not _element(user, "cancel").enabled
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


async def test_a_poll_with_nothing_new_does_not_rebuild_the_page(user: User, ready_project, su2_env, eventually,
                                                                 monkeypatch):
    """Rebuilding every poll would collapse an open "Why it failed" and drop clicks mid-flight."""
    import asyncio

    from aerosuite.web.pages import run

    monkeypatch.setattr(run, "POLL_SECONDS", 0.05)
    project_dir, _ = ready_project
    _plan(project_dir, **{A0: "hang"})
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "RUNNING", timeout=20)
    shown = _element(user, f"status-{A0}")
    tick = _element(user, f"tick-{A2}")
    await asyncio.sleep(0.5)  # ~10 polls, the job still on A0
    assert _element(user, f"status-{A0}") is shown and _element(user, f"tick-{A2}") is tick
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-confirm")
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "CANCELLED", timeout=20)


from aerosuite.engine.jobs.overview import CaseRow
from aerosuite.web.pages.run import tile_counts


def test_tile_counts_group_the_statuses():
    rows = [CaseRow(n, s, None) for n, s in [("a", "CONVERGED"), ("b", "RUNNING"), ("c", "FAILED"),
                                             ("d", "UNCONVERGED"), ("e", "CANCELLED"), ("f", "PENDING"),
                                             ("g", "NOT_RUN"), ("h", "CONVERGED")]]
    assert tile_counts(rows) == (2, 1, 3, 2)


async def test_tiles_pills_and_the_failure_box(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail"})
    await _open(user, project_dir)
    assert (_text(user, "tile-converged"), _text(user, "tile-running"), _text(user, "tile-attention"),
            _text(user, "tile-pending")) == ("2", "0", "1", "0")
    assert "as-pill-failed" in _element(user, f"status-{A2}").classes
    assert "as-pill-done" in _element(user, f"status-{A0}").classes
    user.find(marker=f"status-{A2}").click()
    assert "as-failure" in _element(user, f"tail-{A2}").classes
    actions = _element(user, "page-actions")
    assert _element(user, "submit").parent_slot.parent is actions
    assert "as-btn-primary" in _element(user, "submit").classes


async def test_failure_details_are_collapsed_until_the_failed_status_is_clicked(user: User, ready_project, su2_env):
    """A sweep where many cases failed must not bury the table under their logs."""
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A0: "fail", A2: "fail"})
    await _open(user, project_dir)
    await user.should_not_see(marker=f"tail-{A0}")
    await user.should_not_see(marker=f"tail-{A2}")
    assert "as-pill-toggle" in _element(user, f"status-{A2}").classes  # it looks clickable
    assert "as-pill-toggle" not in _element(user, f"status-{A4}").classes  # converged: nothing to show

    user.find(marker=f"status-{A2}").click()
    await user.should_see(marker=f"tail-{A2}")
    await user.should_not_see(marker=f"tail-{A0}")  # only the one clicked

    user.find(marker=f"tick-{A4}").click()  # any change redraws the table; the open box stays open
    await user.should_see(marker=f"tail-{A2}")

    user.find(marker=f"status-{A2}").click()
    await user.should_not_see(marker=f"tail-{A2}")

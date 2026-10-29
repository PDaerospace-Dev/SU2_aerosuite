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
    await user.should_not_see(marker="submit")  # one job at a time: the panel shows the running job
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


async def test_counts_pills_and_the_failure_box(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail"})
    await _open(user, project_dir)
    assert (_text(user, "count-converged"), _text(user, "count-failed")) == ("2", "1")  # numbers in the bar
    assert _element(user, "count-failed").props["title"] == "1 failed"  # its words on hover
    await user.should_not_see(marker="count-running")
    assert _element(user, "select-failed").text == "Failed 1" and _element(user, "select-all").text == "All 3"
    assert "as-pill-failed" in _element(user, f"status-{A2}").classes
    assert "as-pill-done" in _element(user, f"status-{A0}").classes
    user.find(marker=f"status-{A2}").click()
    assert "as-failure" in _element(user, f"tail-{A2}").classes
    assert "as-btn-primary" in _element(user, "submit").classes  # in the panel on the right


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


async def test_warnings_are_folded_and_errors_stay_in_view(user: User, ready_project, monkeypatch):
    from aerosuite.engine.project import TEMPLATE_FILE

    project_dir, _ = ready_project
    monkeypatch.delenv("SU2_RUN", raising=False)
    template = project_dir / TEMPLATE_FILE
    template.write_text(template.read_text() + "oops\n")
    await _open(user, project_dir)
    await user.should_see("SU2_RUN is not set")  # an error: a banner
    group = _element(user, "run-warnings")
    assert "warning" in group._props["label"] and not group.value  # folded until opened
    with user:
        group.open()
    await user.should_see("is not an option or a comment")


async def test_the_machine_strip_shows_cores_and_what_the_study_asks(user: User, ready_project, monkeypatch,
                                                                     eventually):
    import aerosuite.web.pages.run as page
    from aerosuite.engine.machine import Machine

    project_dir, project = ready_project
    project.run.partitions = 16
    save_project(project_dir, project)
    monkeypatch.setattr(page, "machine", lambda: Machine(
        cores=64, physical_cores=32, load=60.2, memory_total_gb=503.0, memory_free_gb=120.4, su2_processes=48))
    from aerosuite.engine.machine import Usage
    monkeypatch.setattr(page, "usage", lambda: [Usage("daniel", "SU2_CFD", 47.6, 48), Usage("pdas", "paraview", 1.0, 1)])
    await _open(user, project_dir)
    await user.should_see(marker="run-machine")
    await eventually(lambda: _text(user, "machine-usage") != "")  # read in a worker thread, just after the page
    assert _text(user, "machine-usage") == "daniel · SU2_CFD × 48 · 47.6 cores\npdas · paraview · 1 core"
    assert _text(user, "machine-cores") == "64 (32 physical)"
    assert _text(user, "machine-free") == "about 4"
    assert _text(user, "machine-memory") == "120 of 503 GB"
    assert _text(user, "machine-su2") == "48"
    assert _element(user, "run-partitions").value == "16"
    assert "about 4 cores free now" in _text(user, "machine-note")


# -- the job bar, the list, the board and the panel on the right ----------------------------------


async def test_the_panel_says_what_will_run_and_sets_the_cores(user: User, ready_project, su2_env):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="run-panel")
    assert _text(user, "run-what") == "3" and _element(user, "submit").text == "Submit 3 cases"
    assert _text(user, "last-job") == "No job yet"
    user.find(marker="run-partitions").clear().type("12").trigger("blur")
    assert open_project(project_dir).run.partitions == 12
    user.find(marker="run-partitions").clear().type("0").trigger("blur")
    await user.should_see(marker="run-partitions-error")
    assert open_project(project_dir).run.partitions == 12
    user.find(marker="select-none").click()
    assert not _element(user, "submit").enabled and _text(user, "submit-blocked") == "Select at least one case"


async def test_the_panel_follows_a_running_job(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    _plan(project_dir, **{A2: "hang"})
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A2}") == "RUNNING", timeout=20)
    assert _text(user, "run-what") == "1 of 3" and _text(user, "run-current") == A2  # the second of three
    assert _text(user, "run-elapsed").startswith("Elapsed ") and "left" in _text(user, "run-elapsed")
    assert _element(user, "run-progress").value == pytest.approx(1 / 3)
    await user.should_not_see(marker="run-partitions")
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-confirm")
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: _text(user, f"status-{A2}") == "CANCELLED", timeout=20)
    assert "Cancelled" in _text(user, "last-job") and "3 cases" in _text(user, "last-job")


async def test_a_single_case_is_a_card(user: User, tmp_path, su2_env):
    from aerosuite.engine.study import create_study

    create_study(tmp_path / "one", use_reference_template=True)
    await _open(user, tmp_path / "one")
    await user.should_see(marker="case-not-run")
    await user.should_see(marker="case-conditions")
    await user.should_not_see(marker="run-tabs")
    await user.should_not_see(marker="select-all")
    assert _element(user, "submit").text == "Run case"
    await user.should_see(marker="history-none")


async def test_a_grid_of_cases_is_a_board(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    update_sweep(project, mach=[0.6, 0.8], alpha=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    save_project(project_dir, project)
    first = open_project(project_dir).cases[0].name  # M0p6_a0_b0
    await _open(user, project_dir)
    assert _element(user, "run-tabs").value == "board"
    await user.should_see(marker=f"tile-{first}")
    assert _text(user, "run-what") == "14"  # nothing has run: every case is selected
    user.find(marker="board-row-|0-0.6").click()  # a row's name: all selected, so unselect them
    assert _text(user, "run-what") == "7"
    user.find(marker="board-col-|0-3").click()  # a column: select its cases
    assert _text(user, "run-what") == "8"
    assert "as-tile-selected" not in _element(user, f"tile-{first}").classes
    user.find(marker=f"tile-{first}").click()  # a click shows its details
    await user.should_see(marker="case-details")
    assert _text(user, "details-name") == first
    with user:
        _element(user, "details-tick").set_value(True)
    assert _text(user, "run-what") == "9" and "as-tile-selected" in _element(user, f"tile-{first}").classes
    user.find(marker="details-close").click()
    await user.should_not_see(marker="case-details")
    with user:
        _element(user, "run-tabs").set_value("list")
    await user.should_see(marker=f"tick-{first}")
    await user.should_see(marker="list-not-run")


async def test_a_sweep_at_one_mach_is_a_board_with_altitude_rows(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    from aerosuite.engine.models import Case

    project.cases = [Case(name=f"M2p0_{h:g}km_a{a:g}", mach=2.0, alpha=a, beta=0.0, altitude_km=h)
                     for h in (25.0, 35.0) for a in (0.0, 15.0)]
    save_project(project_dir, project)
    await _open(user, project_dir)
    assert _element(user, "run-tabs").value == "board"
    await user.should_see(marker="board-M2|0")
    assert _text(user, "board-all-M2|0") == "km \\ α" and _text(user, "board-row-M2|0-35") == "35 km"
    assert _text(user, "run-what") == "4"
    user.find(marker="board-row-M2|0-35").click()  # a row: that altitude's cases
    assert _text(user, "run-what") == "2"


async def test_the_list_groups_cases_by_state(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail", A4: "diverge"})
    await _open(user, project_dir)
    assert _element(user, "run-tabs").value == "list"  # one Mach: no grid to draw
    await user.should_see(marker="list-attention")
    await user.should_see(marker="list-done")
    await user.should_not_see(marker="list-not-run")
    user.find(marker="list-select-attention").click()  # every case that needs a look
    assert _element(user, f"tick-{A2}").value and _element(user, f"tick-{A4}").value
    assert not _element(user, f"tick-{A0}").value
    user.find(marker="list-attention").click()  # folds
    await user.should_not_see(marker=f"tick-{A2}")
    assert "Failed" in _text(user, "last-job") and "1 converged" in _text(user, "last-job")


async def test_an_altitude_head_names_only_its_failed_cases(user: User, ready_project):
    from datetime import datetime

    from aerosuite.engine.jobs.runner import CaseState, JobRecord
    from aerosuite.engine.jobs.store import save_job

    project_dir, project = ready_project
    update_sweep(project, mach=[0.6, 0.8])  # a grid: two Machs by three αs
    save_project(project_dir, project)
    names = [case.name for case in project.cases]
    statuses = {names[0]: CaseState.FAILED, names[1]: CaseState.CONVERGED, names[2]: CaseState.UNCONVERGED}
    save_job(project_dir, JobRecord(id="j1", backend="local", cases=names[:3], log_path="jobs/j1.log",
                                    created=datetime(2026, 10, 27, 9, 0), state=JobState.DONE, case_status=statuses))
    await _open(user, project_dir)
    await user.should_see("1 failed", marker="board-failed-|0")
    head = _element(user, "board-head-|0")
    pills = [child.text for child in head.default_slot.children if "as-pill" in child.classes]
    assert pills == ["1 failed"]  # the other counts are in the bar only
    assert _text(user, "count-converged") == "1"
    user.find(marker="run-density-compact").click()
    await user.should_see(marker="run-density-compact")
    assert "as-icon-toggle-on" in _element(user, "run-density-compact").classes

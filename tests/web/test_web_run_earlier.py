"""Run's Earlier sweeps tab and Monitor's picker: cases an earlier sweep ran, kept but not in the next run."""
from datetime import datetime

from nicegui.testing import User

from aerosuite.engine.editing import update_sweep
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import save_job
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _earlier_sweep(project_dir, project) -> list[str]:
    """An altitude sweep that ran 0 km and then moved to 20 km: 0 km's three cases are an earlier sweep's."""
    project.settings.freestream.mode = "altitude"
    project.settings.freestream.reynolds_length = 1.0
    project.sweep.naming.include_altitude = True
    update_sweep(project, altitudes_km=[0.0])
    old = [case.name for case in project.cases]
    update_sweep(project, altitudes_km=[20.0])
    save_project(project_dir, project)
    statuses = {old[0]: CaseState.CONVERGED, old[1]: CaseState.UNCONVERGED, old[2]: CaseState.UNCONVERGED}
    save_job(project_dir, JobRecord(id="20261024-1151", backend="local", cases=old, log_path="jobs/x.log",
                                    created=datetime(2026, 10, 24, 11, 51), state=JobState.DONE,
                                    case_status=statuses))
    for name in old:
        (project_dir / "runs" / name).mkdir(parents=True)
    return old


async def test_earlier_sweeps_have_a_tab_of_their_own(user: User, ready_project):
    project_dir, project = ready_project
    old = _earlier_sweep(project_dir, project)
    await user.open(project_url("run", project_dir))
    await user.should_see("Earlier (3)", marker="run-tab-earlier")
    await user.should_not_see(marker="earlier-0")  # the board is as before: the current sweep only
    await user.open(project_url("run", project_dir) + "&tab=earlier")
    await user.should_see("1 converged · 2 unconverged · job 20261024-1151", marker="earlier-0")
    await user.should_not_see(marker=f"tile-{old[0]}")  # folded at first
    user.find(marker="earlier-head-0").click()
    await user.should_see(marker=f"tile-{old[0]}")
    await user.should_not_see(marker="select-all")  # nothing here is selected for a run


async def test_add_to_sweep_puts_the_altitude_back(user: User, ready_project):
    project_dir, project = ready_project
    old = _earlier_sweep(project_dir, project)
    await user.open(project_url("run", project_dir) + "&tab=earlier")
    user.find(marker="earlier-add-0").click()
    await user.should_see("0 km is in the sweep again")
    reopened = open_project(project_dir)
    assert reopened.sweep.altitudes_km == [0.0, 20.0]
    assert set(old) <= {case.name for case in reopened.cases}  # the same names: their outcomes come back
    await user.should_not_see(marker="run-tab-earlier")


async def test_monitor_lists_earlier_cases(user: User, ready_project):
    project_dir, project = ready_project
    old = _earlier_sweep(project_dir, project)
    await user.open(project_url("monitor", project_dir) + f"&case={old[0]}")
    picker = _element(user, "monitor-case")
    assert picker.value == old[0]
    assert picker.options[old[0]] == f"{old[0]} · earlier sweep"

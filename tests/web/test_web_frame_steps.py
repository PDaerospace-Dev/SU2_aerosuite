from nicegui.testing import User

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _switch(project_dir, *, profile=None, sweep=True):
    project = open_project(project_dir)
    project.profile = profile
    project.sweep.enabled = sweep
    project.cases = build_cases(project)
    save_project(project_dir, project)


async def test_sidebar_shows_config_and_hides_aircraft_without_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="badge-config-done")
    await user.should_see(marker="badge-sweep-done")
    await user.should_not_see(marker="badge-aircraft-done")


async def test_sidebar_with_a_profile_and_the_sweep_off(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, profile="x07", sweep=False)
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="badge-aircraft-done")
    await user.should_not_see(marker="badge-sweep-done")
    await user.should_not_see(marker="badge-sweep-todo")


async def test_sweep_page_when_the_sweep_is_off(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, sweep=False)
    await user.open(project_url("sweep", project_dir))
    await user.should_see(marker="sweep-off")
    await user.should_not_see(marker="generate")


async def test_sweep_off_is_an_info_banner(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, sweep=False)
    await user.open(project_url("sweep", project_dir))
    label = next(iter(user.find(marker="sweep-off").elements))
    assert "as-banner-info" in label.parent_slot.parent.classes

from nicegui.testing import User

from aerosuite.engine.profiles import PROFILE_FILE, user_profiles_dir
from aerosuite.engine.project import open_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def _open(user, project_dir):
    await user.open(project_url("setup", project_dir))


async def test_choose_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-profile").set_value("x07")
    assert open_project(project_dir).profile == "x07"
    await user.should_see(marker="badge-aircraft-done")
    with user:
        _element(user, "setup-profile").set_value("")
    assert open_project(project_dir).profile is None


async def test_apply_profile_defaults_asks_first(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-profile").set_value("x07")
    user.find(marker="setup-apply-profile").click()
    await user.should_see(marker="confirm-apply")
    user.find(marker="confirm-cancel").click()
    await user.should_not_see(marker="confirm-apply")
    assert open_project(project_dir).settings.reference.ref_area is None
    user.find(marker="setup-apply-profile").click()
    await user.should_see(marker="confirm-apply")
    user.find(marker="confirm-apply").click()
    await user.should_see("Applied X07 defaults")
    assert open_project(project_dir).settings.reference.ref_area == 16.213


async def test_save_as_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="setup-save-profile").click()
    await user.should_see(marker="profile-id")
    user.find(marker="profile-id").type("my_jet")
    user.find(marker="profile-name").type("My jet")
    user.find(marker="profile-save").click()
    await user.should_see("Saved profile My jet")
    assert (user_profiles_dir() / "my_jet" / PROFILE_FILE).is_file()
    assert open_project(project_dir).profile == "my_jet"

    user.find(marker="setup-save-profile").click()
    await user.should_see(marker="profile-id")
    user.find(marker="profile-id").type("my_jet")
    user.find(marker="profile-name").type("Renamed")
    user.find(marker="profile-save").click()
    await user.should_see("already exists")
    user.find(marker="profile-replace").click()
    await user.should_see("Saved profile Renamed")


async def test_sweep_switch(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-sweep").set_value(False)
    project = open_project(project_dir)
    assert project.sweep.enabled is False and [c.name for c in project.cases] == ["study"]
    await user.should_not_see(marker="badge-sweep-done")
    with user:
        _element(user, "setup-sweep").set_value(True)
    assert len(open_project(project_dir).cases) == 3

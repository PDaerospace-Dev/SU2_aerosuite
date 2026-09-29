"""The Profiles page: see and edit what a new study of an aircraft starts from."""
from nicegui.testing import User

from aerosuite.engine.profiles import load_profile, save_profile, user_profiles_dir
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _mine(ready_project, profile_id="jet"):
    project_dir, project = ready_project
    project.sweep.mach = [2.0, 3.0]
    project.run.partitions = 32
    return save_profile(project_dir, project, profile_id, "My jet", "for tests")


async def test_the_page_lists_profiles_and_shows_the_bundled_x07(user: User):
    await user.open("/profiles")
    await user.should_see(marker="profile-row-x07")
    await user.should_see(marker="profile-bundled-note")  # X07 is bundled: edits save your own copy
    assert _element(user, "profile-name").value == "X07"
    assert _element(user, "profile-ref_area").value == "16.213"
    await user.should_see("No template")


async def test_editing_fields_saves_the_profile(user: User, ready_project):
    _mine(ready_project)
    await user.open("/profiles?id=jet")
    assert _element(user, "profile-mach").value == "2, 3"
    assert _element(user, "profile-partitions").value == "32"
    user.find(marker="profile-mach").clear().type("0.8, 0.9").trigger("blur")
    user.find(marker="profile-ref_length").clear().type("7.5").trigger("blur")
    user.find(marker="profile-description").clear().type("changed").trigger("blur")
    user.find(marker="profile-altitudes_km").clear().type("0, 11").trigger("blur")
    data = load_profile("jet").data
    assert data.sweep["mach"] == [0.8, 0.9] and data.sweep["altitudes_km"] == [0.0, 11.0]
    assert data.settings["reference"]["ref_length"] == 7.5
    assert data.description == "changed"
    user.find(marker="profile-mach").clear().type("0").trigger("blur")
    await user.should_see("Mach numbers must be greater than 0")
    assert load_profile("jet").data.sweep["mach"] == [0.8, 0.9]


async def test_editing_x07_saves_your_copy_and_reset_brings_back_the_bundled_one(user: User):
    await user.open("/profiles?id=x07")
    user.find(marker="profile-partitions").clear().type("16").trigger("blur")
    assert not load_profile("x07").bundled and load_profile("x07").data.run["partitions"] == 16
    await user.open("/profiles?id=x07")
    user.find(marker="profile-delete").click()  # "Reset to bundled" for your copy of X07
    await user.should_see(marker="confirm-delete")
    user.find(marker="confirm-delete").click()
    await user.should_see(marker="profile-bundled-note")  # back on the bundled X07
    assert load_profile("x07").bundled


async def test_duplicate_and_delete(user: User, ready_project):
    _mine(ready_project)
    await user.open("/profiles?id=jet")
    user.find(marker="profile-duplicate").click()
    await user.should_see(marker="duplicate-id")
    user.find(marker="duplicate-id").type("jet_b")
    user.find(marker="duplicate-name").type("Jet B")
    user.find(marker="duplicate-save").click()
    await user.should_see(marker="profile-row-jet_b")
    assert load_profile("jet_b").data.sweep["mach"] == [2.0, 3.0]
    await user.open("/profiles?id=jet_b")
    user.find(marker="profile-delete").click()
    await user.should_see(marker="confirm-delete")
    user.find(marker="confirm-delete").click()
    await user.should_not_see(marker="profile-row-jet_b")
    assert not (user_profiles_dir() / "jet_b").exists()


async def test_the_aircraft_form_values_are_shown_read_only(user: User, ready_project):
    project_dir, project = ready_project
    project.settings.numerics.cfl = 5.0
    project.settings.overrides["CONV_FIELD"] = "LIFT"
    save_profile(project_dir, project, "jet", "My jet")
    await user.open("/profiles?id=jet")
    await user.should_see(marker="profile-form-values")
    await user.should_see("CFL_NUMBER")
    await user.should_see("CONV_FIELD")


async def test_profiles_are_reachable_from_projects_setup_and_the_switcher(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open("/")
    await user.should_see(marker="projects-profiles")
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="setup-manage-profiles")
    await user.should_see(marker="menu-profiles")

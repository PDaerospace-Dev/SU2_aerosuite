from nicegui.element_filter import ElementFilter
from nicegui.testing import User

from aerosuite.engine.project import open_project


def _element(user, marker):
    # `user.find()` hardcodes `only_visible=True`, so it cannot locate a hidden element to
    # check its `.visible` state (see the deviation note in the task report). Use
    # `ElementFilter` directly, which is what `user.find()` wraps, without that restriction.
    with user.client:
        return next(iter(ElementFilter(only_visible=False, local_scope=False, marker=marker)))


async def test_general_case_from_the_reference(user: User, tmp_path):
    await user.open("/")
    assert not _element(user, "new-profile").visible
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("nozzle")
    with user:
        _element(user, "new-use-reference").set_value(True)
    user.find(marker="new-create").click()
    await user.should_see(marker="project-name")
    project = open_project(tmp_path / "nozzle")
    assert project.sweep.enabled is False and project.profile is None
    assert "SOLVER=" in (tmp_path / "nozzle" / project.template).read_text(encoding="utf-8")


async def test_aircraft_study_needs_a_template_when_the_profile_has_none(user: User, tmp_path):
    await user.open("/")
    user.find(marker="new-kind-aircraft").click()
    assert _element(user, "new-profile").visible
    with user:
        _element(user, "new-profile").set_value("x07")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("x07_a")
    user.find(marker="new-create").click()
    await user.should_see("X07 has none")
    assert not (tmp_path / "x07_a").exists()
    with user:  # SU2's reference template is offered to an aircraft study too
        _element(user, "new-use-reference").set_value(True)
    user.find(marker="new-create").click()
    await user.should_see(marker="project-name")
    project = open_project(tmp_path / "x07_a")
    assert project.profile == "x07"
    assert "SOLVER=" in (tmp_path / "x07_a" / project.template).read_text(encoding="utf-8")


async def test_aircraft_study(user: User, tmp_path):
    template = tmp_path / "x07.cfg"
    template.write_text("MACH_NUMBER= 0.7\n")
    mesh = tmp_path / "x07.su2"
    mesh.write_text("MARKER_TAG= Wing\n")
    await user.open("/")
    user.find(marker="new-kind-aircraft").click()
    with user:
        _element(user, "new-profile").set_value("x07")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("x07_b")
    user.find(marker="new-template").type(str(template))
    user.find(marker="new-mesh").type(str(mesh))
    user.find(marker="new-create").click()
    await user.should_see(marker="badge-aircraft-done")
    project = open_project(tmp_path / "x07_b")
    assert project.profile == "x07" and project.sweep.enabled is True
    assert project.settings.reference.ref_area == 16.213
    assert project.mesh.markers == ["Wing"]

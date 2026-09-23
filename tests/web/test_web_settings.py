from nicegui.testing import User

from aerosuite.engine.project import open_project
from aerosuite.web.layout import project_url


async def _open(user, project_dir):
    await user.open(project_url("settings", project_dir))


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _preview(user):
    return _element(user, "preview").content


async def test_numeric_field_saves_and_updates_the_preview(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="freestream-temperature_K").type("250").trigger("blur")
    assert open_project(project_dir).settings.freestream.temperature_K == 250.0
    assert "FREESTREAM_TEMPERATURE= 250" in _preview(user)
    user.find(marker="freestream-temperature_K").clear().trigger("blur")
    assert open_project(project_dir).settings.freestream.temperature_K is None


async def test_invalid_numbers_are_not_saved(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="numerics-cfl").type("abc").trigger("blur")
    await user.should_see("CFL number: 'abc' is not a number")
    user.find(marker="numerics-iter").type("2.5").trigger("blur")
    await user.should_see("not a whole number")
    settings = open_project(project_dir).settings
    assert settings.numerics.cfl is None and settings.numerics.iter is None


async def test_markers_add_remove_and_delete(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see("Mesh markers: farfield, wall")
    user.find(marker="marker-new-key").type("MARKER_FAR")
    user.find(marker="marker-new-value").type("( farfield )")
    user.find(marker="marker-add").click()
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": "( farfield )"}

    switch = _element(user, "marker-MARKER_FAR-remove")
    with user:
        switch.set_value(True)
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": None}
    assert "MARKER_FAR=" not in _preview(user)

    user.find(marker="marker-MARKER_FAR-delete").click()
    assert open_project(project_dir).settings.markers == {}
    assert "MARKER_FAR= ( farfield )" in _preview(user)


async def test_editing_a_marker_value_to_none_rebuilds_the_row(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="marker-new-key").type("MARKER_FAR")
    user.find(marker="marker-new-value").type("( farfield )")
    user.find(marker="marker-add").click()
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": "( farfield )"}

    user.find(marker="marker-MARKER_FAR-value").clear().type("none").trigger("blur")
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": None}
    switch = _element(user, "marker-MARKER_FAR-remove")
    assert switch.value is True
    await user.should_not_see(marker="marker-MARKER_FAR-value")
    assert "MARKER_FAR=" not in _preview(user)


async def test_marker_keys_must_start_with_marker(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="marker-new-key").type("CFL_NUMBER")
    user.find(marker="marker-new-value").type("5")
    user.find(marker="marker-add").click()
    await user.should_see("Marker keys start with MARKER_")
    assert open_project(project_dir).settings.markers == {}


async def test_overrides_add_edit_delete_and_refuse_case_keys(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="override-new-key").type("cfl_number")
    user.find(marker="override-new-value").type("5")
    user.find(marker="override-add").click()
    assert open_project(project_dir).settings.overrides == {"CFL_NUMBER": "5"}
    assert "CFL_NUMBER= 5" in _preview(user)

    user.find(marker="override-CFL_NUMBER-value").clear().type("7").trigger("blur")
    assert open_project(project_dir).settings.overrides == {"CFL_NUMBER": "7"}

    user.find(marker="override-new-key").type("AOA")
    user.find(marker="override-new-value").type("3")
    user.find(marker="override-add").click()
    await user.should_see("set per case")

    user.find(marker="override-CFL_NUMBER-delete").click()
    assert open_project(project_dir).settings.overrides == {}


async def test_preview_follows_the_selected_case(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert "AOA= 0" in _preview(user)
    select = _element(user, "preview-case")
    with user:
        select.set_value("M0p8_a4_b0")
    assert "AOA= 4" in _preview(user)

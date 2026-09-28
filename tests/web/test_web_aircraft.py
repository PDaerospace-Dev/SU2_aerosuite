from nicegui.testing import User

from aerosuite.engine.profiles import apply_profile, load_profile
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _with_x07(project_dir, **numerics):
    project = open_project(project_dir)
    apply_profile(project_dir, project, load_profile("x07"))
    for name, value in numerics.items():
        setattr(project.settings.numerics, name, value)
    save_project(project_dir, project)


async def _open(user, project_dir):
    await user.open(project_url("aircraft", project_dir))


def _preview(user):
    return _element(user, "preview").content


async def test_without_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="aircraft-none")


async def test_profile_values_and_number_fields(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "reference-ref_area").value == "16.213"
    user.find(marker="freestream-temperature_K").type("250").trigger("blur")
    assert open_project(project_dir).settings.freestream.temperature_K == 250.0
    user.find(marker="numerics-cfl").clear().type("abc").trigger("blur")
    await user.should_see("CFL number: 'abc' is not a number")
    assert open_project(project_dir).settings.numerics.cfl == 1.0


async def test_dropdowns(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir, turb_model="SA_NEG")
    await _open(user, project_dir)
    conv = _element(user, "numerics-conv_method")
    assert conv.value == "ROE"
    with user:
        conv.set_value("JST")
    assert open_project(project_dir).settings.numerics.conv_method == "JST"
    with user:
        _element(user, "numerics-conv_method").set_value("")
    assert open_project(project_dir).settings.numerics.conv_method is None
    turb = _element(user, "numerics-turb_model")
    assert turb.value == "SA_NEG" and "SA_NEG" in turb.options


async def test_markers_include_and_value(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "marker-MARKER_HEATFLUX-value").props["placeholder"] == "( Fuselage, Wing, VT, HT )"
    assert _element(user, "marker-MARKER_FAR-value").props.get("stack-label") is True
    with user:
        _element(user, "marker-MARKER_FAR-include").set_value(False)
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": None}
    assert "MARKER_FAR=" not in _preview(user)
    with user:
        _element(user, "marker-MARKER_FAR-include").set_value(True)
    assert open_project(project_dir).settings.markers == {}
    user.find(marker="marker-MARKER_FAR-value").type("( far2 )").trigger("blur")
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": "( far2 )"}
    user.find(marker="marker-MARKER_FAR-value").clear().trigger("blur")
    assert open_project(project_dir).settings.markers == {}


async def test_placeholders(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="override-new-key").type("conv_field")
    user.find(marker="override-new-value").type("LIFT")
    user.find(marker="override-add").click()
    assert open_project(project_dir).settings.overrides == {"CONV_FIELD": "LIFT"}
    user.find(marker="override-CONV_FIELD-value").clear().type("DRAG").trigger("blur")
    assert open_project(project_dir).settings.overrides == {"CONV_FIELD": "DRAG"}
    user.find(marker="override-new-key").type("AOA")
    user.find(marker="override-new-value").type("3")
    user.find(marker="override-add").click()
    await user.should_see("set per case")
    user.find(marker="override-CONV_FIELD-delete").click()
    assert open_project(project_dir).settings.overrides == {}


async def test_clearing_a_placeholder_explains_how_to_go_back(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="override-new-key").type("conv_field")
    user.find(marker="override-new-value").type("LIFT")
    user.find(marker="override-add").click()
    user.find(marker="override-CONV_FIELD-value").clear().trigger("blur")
    await user.should_see("CONV_FIELD needs a value; remove the setting to go back to the template value")
    assert open_project(project_dir).settings.overrides == {"CONV_FIELD": "LIFT"}


async def test_insert_from_the_reference(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="ref-search").type("conv_cauchy_eps")
    user.find(marker="ref-insert-CONV_CAUCHY_EPS").click()
    overrides = open_project(project_dir).settings.overrides
    assert list(overrides) == ["CONV_CAUCHY_EPS"] and overrides["CONV_CAUCHY_EPS"]
    await user.should_see(marker="override-CONV_CAUCHY_EPS-value")
    user.find(marker="ref-search").clear().type("marker_euler")
    user.find(marker="ref-insert-MARKER_EULER").click()
    assert open_project(project_dir).settings.markers["MARKER_EULER"] == "( airfoil )"
    await user.should_see(marker="marker-MARKER_EULER-value")


async def test_aircraft_sections_are_cards(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    await user.should_see("Mesh markers: farfield, wall")
    assert "as-field" in _element(user, "numerics-conv_method").classes


async def test_no_profile_is_an_info_banner(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert "as-banner-info" in _element(user, "aircraft-none").parent_slot.parent.classes


from aerosuite.engine.freestream import naming_altitude
from aerosuite.engine.project import open_project as _open_project


def _shown(user, marker) -> bool:
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


async def test_freestream_switches_to_altitude_and_back_keeping_the_hand_values(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="freestream-temperature_K").clear().type("250").trigger("blur")
    _element(user, "freestream-mode").set_value("altitude")
    assert _open_project(project_dir).settings.freestream.mode == "altitude"
    await user.should_see(marker="freestream-altitude_km")
    assert not _shown(user, "freestream-temperature_K")
    user.find(marker="freestream-altitude_km").clear().type("11").trigger("blur")
    user.find(marker="freestream-reynolds_length").clear().type("6").trigger("blur")
    project = _open_project(project_dir)
    # (the ready project leaves the altitude out of case names, so check the label, not the names)
    assert project.settings.freestream.altitude_km == 11.0 and naming_altitude(project) == "11km"
    await user.should_see("216.65 K")
    await user.should_see(marker="freestream-kept")
    _element(user, "freestream-mode").set_value("manual")
    await user.should_see(marker="freestream-temperature_K")
    assert _element(user, "freestream-temperature_K").value == "250"


async def test_the_summary_shows_the_error_for_a_bad_altitude(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    _element(user, "freestream-mode").set_value("altitude")
    user.find(marker="freestream-altitude_km").clear().type("120").trigger("blur")
    await user.should_see(marker="freestream-summary-error")
    assert "outside the standard atmosphere" in _element(user, "freestream-summary-error").text


async def test_preview_and_reference_are_tabs_on_the_right(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    tabs = _element(user, "side-tabs")
    assert tabs.value == "preview"  # the preview shows without a switch
    assert "MACH_NUMBER= 0.8" in _preview(user)
    assert "as-side" in _element(user, "side-panel").classes  # the sticky right-hand column
    with user:
        tabs.set_value("reference")
    await user.should_see(marker="ref-search")


def _single_x07(project_dir):
    from aerosuite.engine.cfg import build_cases

    _with_x07(project_dir)
    project = open_project(project_dir)
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)


async def test_with_the_sweep_on_mach_comes_from_the_sweep(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "freestream-mach-sweep").text == "0.8"
    await user.should_not_see(marker="freestream-mach")


async def test_a_single_case_sets_mach_in_the_template(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "freestream-mach").value == "0.3"  # the template's MACH_NUMBER
    user.find(marker="freestream-mach").clear().type("0.55").trigger("blur")
    assert "MACH_NUMBER= 0.55" in (project_dir / "template.cfg").read_text()
    assert "MACH_NUMBER= 0.55" in _preview(user)
    user.find(marker="freestream-mach").clear().type("0").trigger("blur")
    await user.should_see("Mach must be greater than 0")
    assert "MACH_NUMBER= 0.55" in (project_dir / "template.cfg").read_text()


async def test_the_mach_field_names_a_placeholder_that_wins(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    project = open_project(project_dir)
    project.settings.overrides["MACH_NUMBER"] = "0.9"
    save_project(project_dir, project)
    await _open(user, project_dir)
    await user.should_see(marker="freestream-mach-wins")
    assert "0.9" in _element(user, "freestream-mach-wins").text

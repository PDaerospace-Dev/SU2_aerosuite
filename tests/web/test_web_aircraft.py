from nicegui.testing import User

from aerosuite.engine.editing import set_freestream, update_sweep
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


def _whole(user):
    """Switch the Config tab to the whole config (it opens on the written lines)."""
    if not _shown(user, "config-edit"):
        with user:
            _element(user, "config-view").set_value("whole")


def _preview(user):
    _whole(user)
    return _element(user, "config-edit").value


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


async def test_cfl_adaptation_is_set_with_the_cfl(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    await user.should_not_see(marker="cfl-adapt-box")
    await user.should_see(marker="numerics-cfl_adapt-template")  # off, as in the template
    with user:
        _element(user, "numerics-cfl_adapt").set_value(True)
    assert open_project(project_dir).settings.numerics.cfl_adapt == "YES"
    await user.should_see(marker="cfl-adapt-box")
    assert _element(user, "cfl-min").props["placeholder"] == "10.0"  # SU2's default: the template has none
    user.find(marker="cfl-min").type("1").trigger("blur")
    user.find(marker="cfl-max").clear().type("50").trigger("blur")  # now showing all six numbers
    numerics = open_project(project_dir).settings.numerics
    assert numerics.cfl_adapt_param == "( 0.1, 2.0, 1, 50, 0.001, 0 )"
    assert "CFL_ADAPT= YES" in _preview(user) and "CFL_ADAPT_PARAM= ( 0.1, 2.0, 1, 50, 0.001, 0 )" in _preview(user)
    user.find(marker="cfl-max").clear().type("0.5").trigger("blur")
    await user.should_see("min CFL 1 is above its max CFL 0.5", marker="cfl-max-error")
    assert open_project(project_dir).settings.numerics.cfl_adapt_param == "( 0.1, 2.0, 1, 50, 0.001, 0 )"
    user.find(marker="cfl-param-reset").click()  # back to the template's line
    assert open_project(project_dir).settings.numerics.cfl_adapt_param is None
    with user:
        _element(user, "numerics-cfl_adapt").set_value(False)
    assert open_project(project_dir).settings.numerics.cfl_adapt == "NO"
    await user.should_not_see(marker="cfl-adapt-box")


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
    assert _element(user, "form-tabs").value == "extra"  # where it went
    assert _element(user, "form-tab-extra-count").text == "1"
    user.find(marker="ref-search").clear().type("marker_euler")
    user.find(marker="ref-insert-MARKER_EULER").click()
    assert open_project(project_dir).settings.markers["MARKER_EULER"] == "( airfoil )"
    await user.should_see(marker="marker-MARKER_EULER-value")
    assert _element(user, "form-tabs").value == "boundaries"


async def test_the_form_is_in_tabs_under_the_case_strip(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    tabs = _element(user, "form-tabs")
    assert tabs.value == "flight"
    assert [_element(user, f"form-tab-{key}").props["label"] for key in
            ("flight", "solver", "boundaries", "reference", "start", "extra")] == [
        "Flight & air", "Solver", "Boundaries", "Reference", "Restarts", "Extra options"]  # the sweep is on
    assert "as-field" in _element(user, "numerics-conv_method").classes
    assert _element(user, "case-name-text").text == "3 cases"
    assert _element(user, "boundaries-mesh").text == "Mesh markers: farfield, wall"
    assert _element(user, "strip-alpha").text == "0, 2, 4°"


async def test_a_tab_opens_from_the_link_and_stays_open_through_a_redraw(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await user.open(project_url("aircraft", project_dir) + "&tab=solver")
    assert _element(user, "form-tabs").value == "solver"
    with user:
        _element(user, "form-tabs").set_value("reference")
    user.find(marker="refresh")  # the frame is there
    with user:
        _element(user, "aircraft-sweep").set_value(False)  # redraws the whole page
    assert _element(user, "form-tabs").value == "reference"


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
    # With the sweep on, the altitudes are the sweep's list, set here as on the Sweep page
    await user.should_see(marker="sweep-altitudes")
    await user.should_see(marker="flight-sweep-link")
    await user.should_not_see(marker="freestream-altitude_km")
    assert not _shown(user, "freestream-temperature_K")
    user.find(marker="freestream-reynolds_length").clear().type("6").trigger("blur")
    assert _open_project(project_dir).settings.freestream.reynolds_length == 6.0
    await user.should_see(marker="freestream-kept")
    _element(user, "freestream-mode").set_value("manual")
    await user.should_see(marker="freestream-temperature_K")
    assert _element(user, "freestream-temperature_K").value == "250"


async def test_the_summary_spans_the_swept_altitudes(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    project = open_project(project_dir)
    project.sweep.naming.include_altitude = True  # else both altitudes make the same names
    set_freestream(project, mode="altitude", reynolds_length=6.0)
    update_sweep(project, altitudes_km=[0.0, 11.0])
    save_project(project_dir, project)
    await _open(user, project_dir)
    assert _element(user, "sweep-altitudes").value == "0, 11"
    await user.should_see(marker="flight-sweep-summary")
    await user.should_see("216.65 K")
    await user.should_see("288.15 K")
    assert _element(user, "strip-altitude").text == "0, 11 km"


async def test_the_mode_is_a_toggle_and_the_inputs_share_one_row(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    toggle = _element(user, "freestream-mode")
    assert "One temperature and Reynolds number" in _element(user, "freestream-mode-hint").text
    with user:
        toggle.set_value("altitude")
    await user.should_see(marker="sweep-altitudes")
    assert "ISA temperature and pressure of its altitude" in _element(user, "freestream-mode-hint").text
    def row(*markers):
        return {_element(user, m).parent_slot.parent.parent_slot.parent.id for m in markers}

    conditions = row("sweep-mach", "sweep-alpha", "sweep-beta")
    air = row("sweep-altitudes", "freestream-reynolds_length")
    assert len(conditions) == 1 and len(air) == 1 and conditions != air  # Mach, AoA, β; then the air


async def test_a_single_case_sets_its_altitude_here(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    _element(user, "freestream-mode").set_value("altitude")
    await user.should_see(marker="freestream-altitude_km")
    user.find(marker="freestream-altitude_km").clear().type("11").trigger("blur")
    user.find(marker="freestream-reynolds_length").clear().type("6").trigger("blur")
    project = _open_project(project_dir)
    assert project.settings.freestream.altitude_km == 11.0 and naming_altitude(project) == "11km"
    await user.should_see("216.65 K")


async def test_the_summary_shows_the_error_for_a_bad_altitude(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    _element(user, "freestream-mode").set_value("altitude")
    user.find(marker="freestream-altitude_km").clear().type("120").trigger("blur")
    await user.should_see(marker="freestream-summary-error")
    assert "outside the standard atmosphere" in _element(user, "freestream-summary-error").text


async def test_config_and_reference_are_tabs_on_the_right(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    tabs = _element(user, "side-tabs")
    assert tabs.value == "config"  # the case's config shows without a switch
    await user.should_not_see(marker="side-tab-preview")
    assert "MACH_NUMBER= 0.8" in _preview(user)
    assert "as-side" in _element(user, "side-panel").classes  # the sticky right-hand column
    with user:
        tabs.set_value("reference")
    await user.should_see(marker="ref-search")


async def test_the_config_opens_on_the_lines_aerosuite_writes(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "config-view").value == "written"
    await user.should_not_see(marker="config-edit")
    await user.should_see("REF_AREA= 16.213", marker="config-written-REF_AREA")
    await user.should_see("MACH_NUMBER= 0.8", marker="config-written-MACH_NUMBER")
    await user.should_not_see(marker="config-written-MARKER_FAR")  # the template's own line
    assert "as-wl-form" in _element(user, "config-written-REF_AREA").classes
    assert "as-wl-case" in _element(user, "config-written-MACH_NUMBER").classes
    user.find(marker="config-written-REF_AREA").click()
    assert _element(user, "form-tabs").value == "reference"  # a click opens the tab that sets it
    with user:
        _element(user, "config-view").set_value("whole")
    await user.should_see(marker="config-edit")


def _single_x07(project_dir):
    from aerosuite.engine.cfg import build_cases, read_template

    _with_x07(project_dir)
    project = open_project(project_dir)
    project.sweep.enabled = False
    project.cases = build_cases(project, read_template(project_dir, project))
    save_project(project_dir, project)


async def test_with_the_sweep_on_the_lists_are_set_here(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "sweep-mach").value == "0.8"
    assert _element(user, "sweep-alpha").value == "0, 2, 4"
    assert _element(user, "sweep-beta").value == "0"
    await user.should_not_see(marker="freestream-mach")
    user.find(marker="sweep-mach").clear().type("0.6, 0.8").trigger("blur")
    project = open_project(project_dir)
    assert project.sweep.mach == [0.6, 0.8] and len(project.cases) == 6
    assert _element(user, "case-name-text").text == "6 cases"
    assert _element(user, "generate").text == "Generate 6 configs"


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


async def test_the_case_name_follows_the_mach_and_shows_in_the_strip(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    assert "M0p3" in _element(user, "case-name-text").text
    user.find(marker="freestream-mach").clear().type("0.55").trigger("blur")
    [case] = open_project(project_dir).cases
    assert case.name.startswith("M0p55") and case.mach == 0.55
    assert _element(user, "case-name-text").text == case.name
    assert _element(user, "strip-mach").text == "0.55"
    assert f"BREAKDOWN_FILENAME= {case.name}_FB.dat" in _preview(user)


async def test_a_single_case_is_named_with_the_parts_chosen_from_its_name(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    assert "_b0" in open_project(project_dir).cases[0].name
    user.find(marker="case-name").click()
    await user.should_see(marker="names-dialog")
    with user:  # the fixture names cases without the altitude and base name
        _element(user, "naming-include_beta").set_value(False)
        _element(user, "naming-include_altitude").set_value(True)
        _element(user, "naming-include_base").set_value(True)
    user.find(marker="sweep-base-name").type("clean").trigger("blur")
    user.find(marker="names-altitude-label").clear().type("cruise").trigger("blur")
    [case] = open_project(project_dir).cases
    assert case.name == "M0p3_cruise_a0_clean"
    assert _element(user, "names-preview").text == case.name
    assert _element(user, "case-name-text").text == case.name
    assert f"BREAKDOWN_FILENAME= {case.name}_FB.dat" in _preview(user)


async def test_opening_the_page_renames_a_case_left_behind_by_an_outside_edit(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    path = project_dir / "template.cfg"
    path.write_text(path.read_text().replace("MACH_NUMBER= 0.3", "MACH_NUMBER= 1.5"))
    await _open(user, project_dir)
    [case] = open_project(project_dir).cases
    assert case.name.startswith("M1p5")
    assert _element(user, "case-name-text").text == case.name


async def test_refresh_shows_a_template_edited_outside(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "freestream-mach").value == "0.3"
    path = project_dir / "template.cfg"
    path.write_text(path.read_text().replace("MACH_NUMBER= 0.3", "MACH_NUMBER= 0.6"))
    user.find(marker="refresh").click()
    await eventually(lambda: _element(user, "freestream-mach").value == "0.6")
    assert _element(user, "case-name-text").text.startswith("M0p6")


async def test_a_single_case_sets_aoa_and_sideslip_in_the_template(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "freestream-alpha").value == "0"  # the template's AOA
    user.find(marker="freestream-alpha").clear().type("2.5").trigger("blur")
    user.find(marker="freestream-beta").clear().type("-1").trigger("blur")
    text = (project_dir / "template.cfg").read_text()
    assert "AOA= 2.5" in text and "SIDESLIP_ANGLE= -1" in text
    assert "AOA= 2.5" in _preview(user) and "SIDESLIP_ANGLE= -1" in _preview(user)
    user.find(marker="freestream-alpha").clear().trigger("blur")
    await user.should_see("AoA α (deg) needs a value")
    assert "AOA= 2.5" in (project_dir / "template.cfg").read_text()


async def test_the_mach_field_names_a_placeholder_that_wins(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    project = open_project(project_dir)
    project.settings.overrides["MACH_NUMBER"] = "0.9"
    save_project(project_dir, project)
    await _open(user, project_dir)
    await user.should_see(marker="freestream-mach-wins")
    assert "0.9" in _element(user, "freestream-mach-wins").text


async def test_an_aircraft_study_has_no_cfg_setup_step(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    await user.should_see(marker="step-aircraft")
    await user.should_not_see(marker="step-config")


def _edit_config(user, change):
    _whole(user)
    editor = _element(user, "config-edit")
    with user:
        editor.set_value(change(editor.value))
    user.find(marker="config-edit").trigger("focusout")


async def test_a_template_line_edited_in_the_config_goes_into_the_template_in_place(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    before = (project_dir / "template.cfg").read_text()
    await _open(user, project_dir)
    _edit_config(user, lambda text: text.replace("MACH_NUMBER= 0.8\n", "MACH_NUMBER= 0.8\nMGLEVEL= 2\n"))
    after = (project_dir / "template.cfg").read_text()
    assert after == before.replace("MACH_NUMBER= 0.3\n", "MACH_NUMBER= 0.3\nMGLEVEL= 2\n")
    assert "MGLEVEL= 2" in _preview(user)


async def test_a_form_line_edited_in_the_config_changes_the_form(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    project = open_project(project_dir)
    project.settings.reference.ref_area = 10.0
    save_project(project_dir, project)
    before = (project_dir / "template.cfg").read_text()
    await _open(user, project_dir)
    _edit_config(user, lambda text: text.replace("REF_AREA= 10\n", "REF_AREA= 12.5\n"))
    assert open_project(project_dir).settings.reference.ref_area == 12.5
    assert (project_dir / "template.cfg").read_text() == before
    await user.should_see(marker="config-edit")  # the page redrew its form and this tab
    assert "REF_AREA= 12.5" in _preview(user)


async def test_a_per_case_line_goes_back_with_a_note(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    before = (project_dir / "template.cfg").read_text()
    await _open(user, project_dir)
    _edit_config(user, lambda text: text.replace("MACH_NUMBER= 0.8", "MACH_NUMBER= 0.95"))
    await user.should_see(marker="config-note")
    assert "change Mach on the Sweep page" in _element(user, "config-note").text
    assert "MACH_NUMBER= 0.8" in _preview(user) and (project_dir / "template.cfg").read_text() == before


async def test_the_switch_problems_and_generate_sit_together(user: User, ready_project):
    import json

    project_dir, _ = ready_project
    _single_x07(project_dir)
    await _open(user, project_dir)
    await user.should_see(marker="problem-badges")
    user.find(marker="generate").click()
    await user.should_see("Wrote 1 config")
    assert json.loads((project_dir / "configs" / "cases.json").read_text())
    with user:
        _element(user, "aircraft-sweep").set_value(True)
    assert open_project(project_dir).sweep.enabled is True
    await user.should_see("Generate 3 configs", marker="generate")  # once the page is drawn again


async def test_the_problems_are_badges_that_list_them(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    project = open_project(project_dir)
    project.settings.markers["MARKER_FAR"] = "( NONE )"  # farfield has no boundary condition now
    save_project(project_dir, project)
    await _open(user, project_dir)
    assert _element(user, "problems-errors").text == "1 error"
    assert not _element(user, "generate").enabled
    user.find(marker="problems-errors").click()
    await user.should_see(marker="problem-error")
    assert "farfield has no boundary condition" in _element(user, "problem-error").text


def _a_run_with_a_solution(project_dir, name="M0p8_0km_a2_b0"):
    solution = project_dir / "runs" / name / "restart_flow.dat"
    solution.parent.mkdir(parents=True)
    solution.write_text("solution")
    return solution.parent


async def test_with_the_sweep_on_start_is_the_restart_rule(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    await user.should_not_see(marker="restart-card")
    await user.should_see(marker="restart-rules")
    user.find(marker="restart-all-previous").click()
    assert [case.restart for case in open_project(project_dir).cases] == ["none", "previous", "previous"]
    assert _element(user, "strip-restart").text == "from the previous case"


async def test_a_single_case_restarts_from_one_of_this_projects_runs_or_starts_fresh(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    folder = _a_run_with_a_solution(project_dir)
    await _open(user, project_dir)
    assert "as-choice-selected" in _element(user, "restart-fresh").classes
    await user.should_see(marker="restart-continue-note")
    user.find(marker="restart-solution").click()  # the newest run is chosen for you
    [case] = open_project(project_dir).cases
    assert (case.restart, case.restart_ref) == ("custom", str(folder))
    await user.should_see(marker=f"restart-run-{folder.name}")
    assert "as-choice-selected" in _element(user, f"restart-run-{folder.name}").classes
    user.find(marker="restart-fresh").click()
    [case] = open_project(project_dir).cases
    assert (case.restart, case.restart_ref) == ("none", None)


async def test_a_single_case_restarts_from_another_file_or_folder(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    _a_run_with_a_solution(project_dir)
    other = tmp_path / "other_study" / "runs" / "M1p2_0km_a0_b0"
    other.mkdir(parents=True)
    await _open(user, project_dir)
    user.find(marker="restart-solution").click()
    user.find(marker="restart-other").click()
    assert "as-choice-selected" in _element(user, "restart-other").classes
    assert open_project(project_dir).cases[0].restart_ref is None
    user.find(marker="restart-ref").type(str(other)).trigger("blur")
    [case] = open_project(project_dir).cases
    assert (case.restart, case.restart_ref) == ("custom", str(other))
    assert "as-choice-selected" in _element(user, "restart-other").classes


async def test_the_restart_stays_when_the_mach_renames_the_case(user: User, ready_project):
    project_dir, _ = ready_project
    _single_x07(project_dir)
    folder = _a_run_with_a_solution(project_dir)
    await _open(user, project_dir)
    user.find(marker="restart-solution").click()
    user.find(marker="freestream-mach").clear().type("1.5").trigger("blur")
    [case] = open_project(project_dir).cases
    assert case.name.startswith("M1p5") and (case.restart, case.restart_ref) == ("custom", str(folder))


async def test_the_config_tab_shows_what_su2_says(user: User, ready_project, fake_su2, eventually):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    await eventually(lambda: _shown(user, "config-su2-ok"), 10)
    _edit_config(user, lambda text: text + "CFL_ADAPT= YES\nCFL_ADAPT_PARAM= ( 1.5, 0.5, 25.0, 100000.0 )\n")
    await eventually(lambda: _shown(user, "config-su2-error"), 10)
    text = _element(user, "config-su2-error").text
    assert "CFL adaption factor down should be less than 1.0" in text and "CFL_ADAPT_PARAM, template line" in text


async def test_saving_keeps_the_editor_so_it_keeps_its_place(user: User, ready_project):
    """A new editor would open at the top: a save updates the one there, for a template line and a form line."""
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    _whole(user)
    editor = _element(user, "config-edit")
    _edit_config(user, lambda text: text.replace("MACH_NUMBER= 0.8\n", "MACH_NUMBER= 0.8\nMGLEVEL= 2\n"))
    assert "MGLEVEL= 2" in (project_dir / "template.cfg").read_text()
    assert _element(user, "config-edit") is editor
    _edit_config(user, lambda text: text.replace("REF_AREA= 16.213\n", "REF_AREA= 12.5\n"))
    assert open_project(project_dir).settings.reference.ref_area == 12.5
    assert _element(user, "config-edit") is editor
    assert _element(user, "reference-ref_area").value == "12.5"  # the form shows it
    _edit_config(user, lambda text: text.replace("MACH_NUMBER= 0.8", "MACH_NUMBER= 0.95"))  # per case: goes back
    await user.should_see(marker="config-note")
    assert _element(user, "config-edit") is editor and "MACH_NUMBER= 0.8\n" in editor.value

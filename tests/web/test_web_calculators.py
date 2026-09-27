from nicegui.testing import User

from aerosuite.engine.cfg import build_cases

from aerosuite.engine.atmosphere import yplus as engine_yplus
from aerosuite.web.calculators.yplus import first_cell_text
from aerosuite.web.layout import calculators_url, project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _shown(user, marker) -> bool:
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


def test_calculators_url():
    assert calculators_url() == "/calculators"
    assert calculators_url(calc="yplus") == "/calculators?calc=yplus"
    assert calculators_url("C:/p").startswith("/calculators?project=C%3A%2Fp")


def test_first_cell_text_picks_a_unit():
    assert first_cell_text(5.134e-06) == "5.13 µm"
    assert first_cell_text(2.5e-3) == "2.5 mm"


async def test_the_icon_is_on_both_top_bars(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open("/")
    await user.should_see(marker="calculators")
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="calculators")


async def test_without_a_project_there_is_no_project_frame(user: User):
    await user.open("/calculators?calc=yplus")
    await user.should_see(marker="calc-item-yplus")
    await user.should_not_see(marker="project-switcher")


async def test_inside_a_project_the_breadcrumb_says_calculators(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(calculators_url(project_dir, "yplus"))
    assert _element(user, "crumb-page").text == "Calculators"


async def test_an_unknown_calculator_falls_back_to_the_first(user: User):
    await user.open("/calculators?calc=nope")
    await user.should_see(marker="isa-altitude")


async def test_yplus_results_for_the_defaults(user: User):
    await user.open("/calculators?calc=yplus")
    expected = engine_yplus(50.0, 1.225, 1.789e-5, 1.0, 1.0, "External")
    assert _element(user, "yplus-first-cell").text == first_cell_text(expected["y1"])
    assert _element(user, "yplus-layers").text == str(expected["n_layers"])
    assert not _shown(user, "yplus-range-note")  # Re = 3.4e6 is inside the turbulent range


async def test_out_of_range_note_and_input_errors(user: User):
    await user.open("/calculators?calc=yplus")
    user.find(marker="yplus-velocity").clear().type("300")
    await user.should_see(marker="yplus-range-note")
    user.find(marker="yplus-velocity").clear().type("abc")
    assert _element(user, "yplus-error").text == "Velocity (m/s): 'abc' is not a number"
    user.find(marker="yplus-velocity").clear().type("0")
    assert _element(user, "yplus-error").text == "Velocity (m/s) must be greater than 0"
    assert _element(user, "yplus-first-cell").text == "—"


async def test_internal_flow_uses_the_pipe_formula(user: User):
    await user.open("/calculators?calc=yplus")
    _element(user, "yplus-domain").set_value("Internal")
    assert "Pipe" in _element(user, "yplus-formula").text


from aerosuite.engine.freestream import naming_altitude
from aerosuite.engine.profiles import apply_profile, load_profile
from aerosuite.engine.project import open_project, save_project


def _x07(project_dir):
    project = open_project(project_dir)
    apply_profile(project_dir, project, load_profile("x07"), copy_template=False)
    save_project(project_dir, project)


def _isa_inputs(user, altitude="11", mach="0.8", length="6"):
    for marker, text in (("isa-altitude", altitude), ("isa-mach", mach), ("isa-length", length)):
        user.find(marker=marker).clear().type(text)


async def test_isa_results_for_known_inputs(user: User):
    await user.open("/calculators")
    _isa_inputs(user)
    assert _element(user, "isa-temperature").text == "216.65 K"
    assert _element(user, "isa-re").text == "3.48e7"
    assert not _shown(user, "isa-apply")  # no project


async def test_isa_input_error(user: User):
    await user.open("/calculators")
    _isa_inputs(user, altitude="120")
    assert "between 0 and 100" in _element(user, "isa-error").text
    assert _element(user, "isa-re").text == "—"


async def test_apply_to_an_aircraft_project(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    _x07(project_dir)
    await user.open(calculators_url(project_dir))
    _isa_inputs(user)
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-confirm")
    user.find(marker="apply-confirm").click()
    await eventually(lambda: open_project(project_dir).settings.freestream.mode == "altitude")
    project = open_project(project_dir)
    assert project.settings.freestream.altitude_km == 11.0 and naming_altitude(project) == "11km"


async def test_cancel_changes_nothing(user: User, ready_project):
    project_dir, _ = ready_project
    _x07(project_dir)
    before = (project_dir / "project.json").read_text()
    await user.open(calculators_url(project_dir))
    _isa_inputs(user)
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-cancel")
    user.find(marker="apply-cancel").click()
    await user.should_not_see(marker="apply-cancel")
    assert (project_dir / "project.json").read_text() == before


async def test_apply_to_a_general_single_case_writes_the_template(user: User, ready_project, eventually):
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)
    await user.open(calculators_url(project_dir))
    _isa_inputs(user, mach="0.3")
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-confirm")
    user.find(marker="apply-confirm").click()
    await eventually(lambda: "REYNOLDS_NUMBER= 13038595" in (project_dir / "template.cfg").read_text())


async def test_apply_is_disabled_for_a_general_sweep(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(calculators_url(project_dir))
    assert not _element(user, "isa-apply").enabled
    await user.should_see(marker="isa-apply-reason")


async def test_send_to_yplus_hands_over_the_flow(user: User):
    await user.open("/calculators")
    _isa_inputs(user)
    user.find(marker="isa-send-yplus").click()
    await user.should_see(marker="yplus-from")
    assert _element(user, "yplus-velocity").value == "236.056"  # the true airspeed, 6 significant figures
    assert _element(user, "yplus-length").value == "6"


async def test_send_to_yplus_with_mach_zero_shows_the_yplus_error(user: User):
    await user.open("/calculators")
    _isa_inputs(user, mach="0")
    user.find(marker="isa-send-yplus").click()
    await user.should_see(marker="yplus-from")
    assert _element(user, "yplus-error").text == "Velocity (m/s) must be greater than 0"


async def test_a_long_project_name_is_shortened_on_the_apply_button(user: User, ready_project):
    project_dir, project = ready_project
    project.name = "x07-high-alpha-buffet-study-with-a-deliberately-long-project-name"
    save_project(project_dir, project)
    await user.open(calculators_url(project_dir))
    text = _element(user, "isa-apply").text
    assert text.startswith("Apply to x07-high-alpha") and len(text) <= 40 and text.endswith("…")

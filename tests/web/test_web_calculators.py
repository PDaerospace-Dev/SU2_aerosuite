from nicegui.testing import User

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
    await user.should_see(marker="yplus-velocity")


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

"""The Results page: parameters and the picker, tiles, the table, folding, overlays (spec 2026-09-29-results)."""
import shutil

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url

HEADER = ["Inner_Iter", "rms[Rho]", "CL", "CD", "CMy", "CL(Wing)"]


def _write_histories(project_dir, project, wing=True, factor=1.0):
    generate_configs(project_dir, project)
    for case in project.cases:
        cl = factor * 0.1 * (case.alpha + 2)
        values = [-3.0, cl, 0.02 + 0.05 * cl * cl, -0.01 * case.alpha] + ([0.9 * cl] if wing else [])
        header = HEADER if wing else HEADER[:-1]
        run = project_dir / "runs" / case.name
        run.mkdir(parents=True, exist_ok=True)
        rows = [",".join(header)] + [",".join(str(v) for v in [i, *values]) for i in range(40)]
        (run / "history.csv").write_text("\n".join(rows) + "\n")


@pytest.fixture
def results_project(ready_project):
    project_dir, project = ready_project
    _write_histories(project_dir, project)
    return project_dir


async def _open(user, project_dir):
    await user.open(project_url("results", project_dir))


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


async def test_a_study_without_results_says_so(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="results-empty")


async def test_the_aero_package_is_on_when_the_history_has_it(user: User, results_project):
    await _open(user, results_project)
    for name in ("CL", "CD", "CMy", "L/D"):
        await user.should_see(marker=f"param-{name}")
    assert _text(user, "param-L/D") == "ƒ L/D"
    assert _text(user, "cell-0-M0p8_a2_b0-CL") == "0.4"
    assert _text(user, "cell-0-M0p8_a2_b0-L/D") == f"{0.4 / (0.02 + 0.05 * 0.16):.5g}"
    assert _text(user, "status-0-M0p8_a2_b0") == "CONVERGED"
    assert "3" in _element(user, "tile-shown").text


async def test_the_picker_searches_and_chooses(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="results-choose").click()
    await user.should_see(marker="picker-panel")
    user.find(marker="picker-search").type("wing")
    await user.should_see(marker="pick-CL(Wing)")
    await user.should_not_see(marker="pick-CD")
    user.find(marker="pick-CL(Wing)").click()
    assert "CL(Wing)" in open_project(results_project).results.parameters
    await user.should_see(marker="param-CL(Wing)")
    assert _text(user, "cell-0-M0p8_a2_b0-CL(Wing)") == "0.36"


async def test_removing_and_clearing_parameters(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="param-remove-CD").click()
    assert open_project(results_project).results.parameters == ["CL", "CMy", "L/D"]
    await user.should_not_see(marker="param-CD")
    user.find(marker="results-choose").click()
    user.find(marker="picker-clear").click()
    assert open_project(results_project).results.parameters == []
    await user.should_see(marker="results-none")


async def test_a_whole_group_is_chosen_with_its_tick(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="results-choose").click()
    user.find(marker="picker-tick-Residuals").click()
    assert "rms[Rho]" in open_project(results_project).results.parameters


async def test_folding_is_remembered(user: User, results_project):
    await _open(user, results_project)
    with user:
        _element(user, "section-results").set_value(False)
    assert open_project(results_project).results.folded == ["results"]
    await _open(user, results_project)
    assert _element(user, "section-results").value is False


async def test_the_average_window_is_saved(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="results-average").clear().type("20").trigger("blur")
    assert open_project(results_project).results.average_last == 20
    user.find(marker="results-average").clear().type("0").trigger("blur")
    await user.should_see("Average over at least 1 iteration")


async def test_another_design_is_drawn_with_this_studys_definitions(user: User, results_project, tmp_path):
    other = tmp_path / "wing-v2"
    shutil.copytree(results_project, other, ignore=shutil.ignore_patterns("runs", "jobs"))
    project = open_project(other)
    project.name = "wing-v2"
    save_project(other, project)
    _write_histories(other, project, wing=False, factor=1.1)
    here = open_project(results_project)
    here.results.compare = [str(other)]
    here.results.parameters = ["CL", "CL(Wing)", "L/D"]
    here.results.packages = ["aero"]
    save_project(results_project, here)
    await _open(user, results_project)
    await user.should_see(marker="design-1")
    assert _text(user, "cell-1-M0p8_a2_b0-CL") == "0.44"
    assert _text(user, "cell-1-M0p8_a2_b0-CL(Wing)") == "—"
    await user.should_see("wing-v2 has no CL(Wing)")
    user.find(marker="design-remove-1").click()
    assert open_project(results_project).results.compare == []
    await user.should_not_see(marker="design-1")


async def test_a_compared_study_that_is_gone_is_shown_as_a_problem(user: User, results_project, tmp_path):
    here = open_project(results_project)
    here.results.compare = [str(tmp_path / "moved-away")]
    save_project(results_project, here)
    await _open(user, results_project)
    await user.should_see(marker="design-problem")


# -- plots (Task 6) -------------------------------------------------------------


async def test_the_aero_package_draws_its_four_plots(user: User, results_project):
    await _open(user, results_project)
    for index in range(4):
        await user.should_see(marker=f"chart-aero-{index}")
    options = _element(user, "chart-aero-0").options
    assert options["title"]["text"] == "CL vs α"
    points = [p["value"] for p in options["series"][0]["data"]]
    assert points == [[0.0, pytest.approx(0.2)], [2.0, pytest.approx(0.4)], [4.0, pytest.approx(0.6)]]


async def test_switching_the_package_off_and_on(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="package-aero").click()
    results = open_project(results_project).results
    assert results.packages == [] and results.parameters == []
    await user.should_see(marker="plots-none")
    user.find(marker="package-aero").click()
    assert open_project(results_project).results.packages == ["aero"]
    await user.should_see(marker="chart-aero-3")


async def test_adding_and_removing_a_plot_with_two_y(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="plot-add").click()
    await user.should_see(marker="plot-dialog-add")
    assert _text(user, "plot-lines") == "One line, points joined along α"
    with user:
        _element(user, "plot-y").set_value(["CL(Wing)", "CL"])
    user.find(marker="plot-dialog-add").click()
    results = open_project(results_project).results
    assert [(p.x, p.y) for p in results.plots] == [("Alpha", ["CL(Wing)", "CL"])]
    assert "CL(Wing)" in results.parameters
    await user.should_see(marker="chart-own-0")
    names = [s["name"] for s in _element(user, "chart-own-0").options["series"]]
    assert names == ["study · CL(Wing)", "study · CL"]
    user.find(marker="plot-remove-0").click()
    assert open_project(results_project).results.plots == []


async def test_a_plot_needs_a_y(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="plot-add").click()
    await user.should_see(marker="plot-dialog-add")
    user.find(marker="plot-dialog-add").click()
    await user.should_see("Choose at least one Y parameter")
    assert open_project(results_project).results.plots == []


async def test_a_package_the_history_cannot_serve_is_disabled(user: User, ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    for case in project.cases:
        run = project_dir / "runs" / case.name
        run.mkdir(parents=True)
        rows = ["Inner_Iter,rms[Rho],Avg_Massflow(outlet)"] + [f"{i},-3,5.0" for i in range(30)]
        (run / "history.csv").write_text("\n".join(rows) + "\n")
    await _open(user, project_dir)
    chip = _element(user, "package-aero")
    assert chip.props.get("disable") is True and "Needs CD, CL, CMy" in chip.props.get("title", "")
    await user.should_see(marker="param-Avg_Massflow(outlet)")  # no package: the first flow parameters


async def test_monitor_opens_on_the_case_given(user: User, results_project):
    await user.open(project_url("monitor", results_project) + "&case=M0p8_a4_b0")
    assert _element(user, "monitor-case").value == "M0p8_a4_b0"

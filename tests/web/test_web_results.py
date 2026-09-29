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

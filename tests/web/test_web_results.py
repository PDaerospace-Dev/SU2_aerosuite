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


async def _panel(user, key):
    """Open one of the control panels from the icon strip."""
    user.find(marker=f"panel-{key}").click()
    await user.should_see(marker="results-panel")


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
    await _panel(user, "parameters")
    for name in ("CL", "CD", "CMy", "L/D"):
        await user.should_see(marker=f"param-{name}")
    assert _text(user, "param-L/D") == "ƒ L/D"
    assert _text(user, "cell-0-M0p8_a2_b0-CL") == "0.4"
    assert _text(user, "cell-0-M0p8_a2_b0-L/D") == f"{0.4 / (0.02 + 0.05 * 0.16):.5g}"
    assert _text(user, "status-0-M0p8_a2_b0") == "CONVERGED"
    assert _text(user, "results-count") == "3 cases"
    assert _text(user, "results-converged") == "3 / 3 converged"
    assert _text(user, "condition-Mach") == "0.8"


async def test_the_icon_strip_opens_one_panel_at_a_time(user: User, results_project):
    await _open(user, results_project)
    await user.should_see(marker="results-strip")
    await user.should_not_see(marker="results-panel")
    await _panel(user, "designs")
    await user.should_see(marker="design-add")
    await _panel(user, "average")
    await user.should_see(marker="results-average")
    await user.should_not_see(marker="design-add")
    user.find(marker="panel-average").click()  # a second click closes it
    await user.should_not_see(marker="results-panel")
    await _panel(user, "filters")
    user.find(marker="panel-close").click()
    await user.should_not_see(marker="results-panel")


async def test_the_picker_searches_and_chooses(user: User, results_project):
    await _open(user, results_project)
    await _panel(user, "parameters")
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
    await _panel(user, "parameters")
    user.find(marker="param-remove-CD").click()
    assert open_project(results_project).results.parameters == ["CL", "CMy", "L/D"]
    await user.should_not_see(marker="param-CD")
    user.find(marker="results-choose").click()
    user.find(marker="picker-clear").click()
    assert open_project(results_project).results.parameters == []
    await user.should_see(marker="results-none")


async def test_a_whole_group_is_chosen_with_its_tick(user: User, results_project):
    await _open(user, results_project)
    await _panel(user, "parameters")
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
    await _panel(user, "average")
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
    await _panel(user, "designs")
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
    await _panel(user, "designs")
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
    await _panel(user, "packages")
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
    assert names == ["CL(Wing)", "CL"]
    colors = [s["lineStyle"]["color"] for s in _element(user, "chart-own-0").options["series"]]
    assert colors[0] != colors[1]
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
    await _panel(user, "packages")
    chip = _element(user, "package-aero")
    assert chip.props.get("disable") is True and "Needs CD, CL, CMy" in chip.props.get("title", "")
    await _panel(user, "parameters")
    await user.should_see(marker="param-Avg_Massflow(outlet)")  # no package: the first flow parameters


async def test_monitor_opens_on_the_case_given(user: User, results_project):
    await user.open(project_url("monitor", results_project) + "&case=M0p8_a4_b0")
    assert _element(user, "monitor-case").value == "M0p8_a4_b0"


# -- derived and characteristic values, packages (Task 7) ----------------------------


async def _derived_dialog(user):
    await _panel(user, "parameters")
    user.find(marker="derived-add").click()
    await user.should_see(marker="derived-save")


def _fill(user, marker, text):
    user.find(marker=marker).clear().type(text)


async def test_a_derived_value_is_previewed_added_and_tabulated(user: User, results_project):
    await _open(user, results_project)
    await _derived_dialog(user)
    _fill(user, "derived-name", "CL share")
    _fill(user, "derived-formula", "{CL(Wing)} / CL")
    await user.should_see(marker="derived-preview-0")
    assert _text(user, "derived-preview-0").endswith("0.9")
    user.find(marker="derived-save").click()
    results = open_project(results_project).results
    assert [(d.name, d.formula) for d in results.derived] == [("CL share", "{CL(Wing)} / CL")]
    assert "CL share" in results.parameters
    assert _text(user, "cell-0-M0p8_a2_b0-CL share") == "0.9"


async def test_derived_values_are_checked_before_saving(user: User, results_project):
    await _open(user, results_project)
    await _derived_dialog(user)
    _fill(user, "derived-name", "CL")
    _fill(user, "derived-formula", "CL / {Avg_Mass}")
    await user.should_see("Avg_Mass is not a known name")
    user.find(marker="derived-save").click()
    await user.should_see("CL is already a parameter")
    assert open_project(results_project).results.derived == []


async def test_a_characteristic_value_is_added_per_curve(user: User, results_project):
    await _open(user, results_project)
    await _derived_dialog(user)
    with user:
        _element(user, "derived-kind").set_value("curve")
    _fill(user, "derived-name", "CLmax")
    _fill(user, "derived-formula", "max(CL)")
    user.find(marker="derived-save").click()
    assert [c.name for c in open_project(results_project).results.characteristics] == ["CLmax"]
    assert _text(user, "char-0-0-CLmax") == "0.6"


async def test_the_aero_characteristic_values_are_shown(user: User, results_project):
    await _open(user, results_project)
    await user.should_see(marker="section-characteristics")
    assert _text(user, "char-0-0-CLα") == "0.1"
    assert _text(user, "char-0-0-α₀") == "—"  # CL = 0 lies outside α 0 … 4 here: the reason is on hover
    assert "outside" in _element(user, "char-0-0-α₀").props.get("title", "")


async def test_the_studys_own_definitions_save_as_a_package(user: User, results_project):
    here = open_project(results_project)
    from aerosuite.engine.models import DerivedValue, PlotSpec
    here.results.derived = [DerivedValue(name="CL share", formula="{CL(Wing)} / CL")]
    here.results.plots = [PlotSpec(x="Alpha", y=["CL share"])]
    here.results.parameters = ["CL", "CL share"]
    save_project(results_project, here)
    await _open(user, results_project)
    user.find(marker="package-save").click()
    await user.should_see(marker="package-save-confirm")
    _fill(user, "package-id", "wing-share")
    _fill(user, "package-name", "Wing share")
    user.find(marker="package-save-confirm").click()
    from aerosuite.engine.packages import load_package
    package = load_package("wing-share")
    assert [d.name for d in package.derived] == ["CL share"] and package.parameters == ["CL", "CL share"]
    await _panel(user, "packages")
    await user.should_see(marker="package-wing-share")


# -- exports (Task 8) --------------------------------------------------------------


async def test_copy_table_puts_the_shown_rows_on_the_clipboard(user: User, results_project, monkeypatch):
    from nicegui import ui

    copied = []
    monkeypatch.setattr(ui.clipboard, "write", lambda text: copied.append(text))
    await _open(user, results_project)
    user.find(marker="results-copy").click()
    lines = copied[0].splitlines()
    assert lines[0] == "Case\tα (deg)\tCL\tCD\tCMy\tL/D\tStatus"  # α varies here, so it has a column
    assert lines[2].startswith("M0p8_a2_b0\t2\t0.4\t")


async def test_export_csv_writes_the_files_and_downloads_the_summary(user: User, results_project):
    await _open(user, results_project)
    user.find(marker="results-export").click()
    summary = results_project / "results" / "summary.csv"
    assert summary.is_file() and (results_project / "results" / "characteristics.csv").is_file()
    response = await user.download.next()
    assert response.content == summary.read_bytes()


# -- imported studies (import Task 4) -----------------------------------------------------------


def _old_runs(root, betas=(0, 2, 4)):
    runs = root / "old-runs"
    for part, offset in (("ht", 0.02), ("vt", 0.0)):
        for beta in betas:
            name = f"M1p2_10km_{part}_a0_b{beta}"
            folder = runs / name
            if folder.exists():
                continue
            folder.mkdir(parents=True)
            (folder / f"{name}.cfg").write_text(f"MACH_NUMBER= 1.2\nAOA= 0\nSIDESLIP_ANGLE= {beta}\n"
                                                "FREESTREAM_TEMPERATURE= 223.25\n")
            rows = ["Inner_Iter,rms[Rho],CL,CD,CSF"] + [f"{i},-3,{offset},0.05,{0.01 * beta}" for i in range(30)]
            (folder / "history.csv").write_text("\n".join(rows) + "\n")
    return runs


@pytest.fixture
def imported_study(tmp_path):
    from aerosuite.engine.imported import create_imported_study

    create_imported_study(tmp_path / "old-study", _old_runs(tmp_path))
    return tmp_path / "old-study"


async def test_an_imported_study_shows_its_cases_with_config_and_temperature(user: User, imported_study):
    await _open(user, imported_study)
    await _panel(user, "filters")
    await user.should_see(marker="filter-Config-vt")
    assert _text(user, "cell-0-M1p2_10km_vt_a0_b4-CL") == "0"
    header = [label.text for label in user.find(marker="results-table").elements.pop().default_slot.children
              if getattr(label, "text", None) in ("Config", "β (deg)")]
    assert header == ["Config", "β (deg)"]
    user.find(marker="filter-Config-vt").click()  # all shown: the click picks vt alone
    assert open_project(imported_study).results.filters == {"Config": ["vt"]}
    await user.should_not_see(marker="row-0-M1p2_10km_ht_a0_b0")


async def test_rescan_picks_up_new_case_folders(user: User, imported_study, tmp_path):
    await _open(user, imported_study)
    _old_runs(tmp_path, betas=(0, 2, 4, 6))
    user.find(marker="results-rescan").click()
    await user.should_see("2 cases added")
    assert len(open_project(imported_study).cases) == 8
    await user.should_see(marker="row-0-M1p2_10km_vt_a0_b6")


async def test_own_studies_have_no_rescan(user: User, results_project):
    await _open(user, results_project)
    await user.should_not_see(marker="results-rescan")


async def test_an_imported_study_opens_on_results_whichever_page_is_asked(user: User, imported_study):
    await user.open(project_url("setup", imported_study))
    await user.should_see(marker="results-body")
    await user.should_see(marker="step-results")
    await user.should_not_see(marker="step-run")


async def test_monitor_plots_an_imported_case(user: User, imported_study):
    await user.open(project_url("monitor", imported_study) + "&case=M1p2_10km_vt_a0_b4")
    assert _element(user, "monitor-case").value == "M1p2_10km_vt_a0_b4"
    await user.should_see(marker="chart-history")


async def test_characteristic_values_split_by_config_show_the_label(user: User, tmp_path):
    from aerosuite.engine.imported import create_imported_study
    from aerosuite.engine.models import DerivedValue

    runs = tmp_path / "runs"
    for part in ("ht", "vt"):
        for alpha in (0, 2, 4):
            folder = runs / f"M1p2_{part}_a{alpha}"
            folder.mkdir(parents=True)
            (folder / f"{folder.name}.cfg").write_text(f"MACH_NUMBER= 1.2\nAOA= {alpha}\n")
            rows = ["Inner_Iter,CL"] + [f"{i},{0.1 * alpha}" for i in range(20)]
            (folder / "history.csv").write_text("\n".join(rows) + "\n")
    project, _ = create_imported_study(tmp_path / "study", runs)
    project.results.parameters = ["CL"]
    project.results.characteristics = [DerivedValue(name="CLmax", formula="max(CL)")]
    save_project(tmp_path / "study", project)
    await _open(user, tmp_path / "study")
    await user.should_see(marker="characteristics-table")
    await user.should_see("vt")
    await _panel(user, "parameters")
    await _derived_dialog_open(user)
    with user:
        _element(user, "derived-kind").set_value("curve")
    _fill(user, "derived-formula", "max(CL)")
    await user.should_see(marker="derived-preview-0")
    assert "Config ht" in _text(user, "derived-preview-0")


async def _derived_dialog_open(user):
    user.find(marker="derived-add").click()
    await user.should_see(marker="derived-save")


async def test_filters_pick_values_and_show_all_again(user: User, imported_study):
    await _open(user, imported_study)
    await _panel(user, "filters")
    user.find(marker="filter-Beta-2").click()  # all shown: only β 2
    assert open_project(imported_study).results.filters == {"Beta": [2.0]}
    await user.should_not_see(marker="row-0-M1p2_10km_vt_a0_b0")
    user.find(marker="filter-Config-ht").click()
    assert open_project(imported_study).results.filters == {"Beta": [2.0], "Config": ["ht"]}
    user.find(marker="filter-all-Beta").click()
    assert open_project(imported_study).results.filters == {"Config": ["ht"]}
    user.find(marker="filters-clear").click()
    assert open_project(imported_study).results.filters == {}
    await user.should_see(marker="row-0-M1p2_10km_vt_a0_b0")


async def test_filters_that_match_no_case_say_so(user: User, tmp_path):
    from aerosuite.engine.imported import create_imported_study

    runs = tmp_path / "runs"
    for name in ("M0p3_10km_a0", "M2_30km_a0"):
        (runs / name).mkdir(parents=True)
        (runs / name / "history.csv").write_text("Inner_Iter,CL\n" + "".join(f"{i},0.1\n" for i in range(20)))
    project, _ = create_imported_study(tmp_path / "study", runs)
    project.results.filters = {"Mach": [0.3], "Altitude": [30.0]}  # each exists, never together
    save_project(tmp_path / "study", project)
    await _open(user, tmp_path / "study")
    await user.should_see(marker="results-filtered-out")
    await user.should_not_see(marker="results-empty")
    user.find(marker="filters-clear-empty").click()
    assert open_project(tmp_path / "study").results.filters == {}
    await user.should_see(marker="row-0-M0p3_10km_a0")


async def test_removing_a_parameter_takes_it_off_the_plots(user: User, results_project):
    await _open(user, results_project)
    await user.should_see(marker="chart-aero-0")  # CL vs α
    await _panel(user, "parameters")
    user.find(marker="param-remove-CL").click()
    await user.should_not_see(marker="chart-aero-0")
    await user.should_not_see(marker="chart-aero-3")  # CL vs CD
    await user.should_see(marker="chart-aero-1")  # CD vs α stays
    await user.should_see(marker="plots-hidden")
    user.find(marker="results-choose").click()
    user.find(marker="pick-CL").click()
    await user.should_see(marker="chart-aero-0")


async def test_a_reason_with_a_double_quote_is_one_hover_text(user: User, results_project):
    # A reason is an error message: it can quote a name. It must stay one title, not end at the quote.
    from aerosuite.web.ui_kit import titled
    await _open(user, results_project)
    with user:
        label = titled(ui.label("x"), 'file "a b" is missing = bad')
    assert label.props["title"] == 'file "a b" is missing = bad'
    assert set(label.props) == {"title"}


async def test_an_unreadable_job_does_not_break_the_page(user: User, results_project, monkeypatch):
    from aerosuite.engine.errors import JobError
    from aerosuite.web.pages import results

    def broken(directory, project):
        raise JobError("jobs/x.json cannot be read")

    monkeypatch.setattr(results.WATCHER, "state", broken)
    await _open(user, results_project)
    await user.should_see(marker="results-table")

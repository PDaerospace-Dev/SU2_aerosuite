"""A study's results: averaged parameters, derived values per case, characteristic values per curve, overlays."""
import json

import pytest

from aerosuite.engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, build_cases
from aerosuite.engine.formula import Missing
from aerosuite.engine.models import DerivedValue, ResultsSettings
from aerosuite.engine.packages import effective
from aerosuite.engine.project import create_project, save_project
from aerosuite.engine.study_results import study_results

ALPHAS = [-2.0, 0.0, 2.0, 4.0, 6.0]


def _study(folder, cl_slope=0.1, surface=True):
    """A small aero study: Mach 0.6 and 0.8, α -2 … 6, CL = slope (α + 2) (1 + (M - 0.6)), CD = 0.02 + 0.05 CL²."""
    project = create_project(folder)
    project.sweep.mach, project.sweep.alpha, project.sweep.beta = [0.6, 0.8], ALPHAS, [0.0]
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    (folder / project.template).write_text("MACH_NUMBER= 0.3\nREF_AREA= 10\n")
    save_project(folder, project)
    index = {}
    for case in project.cases:
        cl = cl_slope * (case.alpha + 2) * (1 + (case.mach - 0.6))
        cd = 0.02 + 0.05 * cl * cl
        header = ["Inner_Iter", "rms[Rho]", "CL", "CD", "CMy"] + (["CL(Wing)"] if surface else [])
        rows = [[i, -3.0, cl, cd, -0.01 * case.alpha] + ([0.9 * cl] if surface else []) for i in range(50)]
        run = folder / "runs" / case.name
        run.mkdir(parents=True)
        (run / "history.csv").write_text("\n".join(
            [",".join(header)] + [",".join(str(v) for v in row) for row in rows]) + "\n")
        index[case.name] = {"mach": case.mach, "alpha": case.alpha, "beta": case.beta}
    (folder / CONFIGS_DIR).mkdir()
    (folder / CONFIGS_DIR / CASE_INDEX_FILE).write_text(json.dumps(index))
    return project


def _definitions(extra_parameters=(), derived=()):
    settings = ResultsSettings(packages=["aero"], parameters=["CL", "CD", "CMy", "L/D", *extra_parameters],
                               derived=list(derived))
    return effective(settings, ["CL", "CD", "CMy", "CL(Wing)"])


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


def test_averages_derived_values_and_convergence(tmp_path):
    _study(tmp_path / "base")
    result = study_results(tmp_path / "base", _definitions())
    row = result.table.set_index("Case").loc["M0p6_sl_a4_b0"]
    assert row["CL"] == pytest.approx(0.6) and row["L/D"] == pytest.approx(0.6 / (0.02 + 0.05 * 0.36))
    assert bool(row["Converged"]) is True
    assert len(result.table) == 10 and result.notes == []


def test_derived_values_see_constants_and_earlier_derived(tmp_path):
    _study(tmp_path / "base")
    derived = [DerivedValue(name="Lift per q", formula="CL * S_ref"),
               DerivedValue(name="twice", formula="2 * {Lift per q}"),
               DerivedValue(name="bad", formula="CL / (CD - CD)"),
               DerivedValue(name="force", formula="CL * q_inf")]
    result = study_results(tmp_path / "base", _definitions(["Lift per q", "twice", "bad", "force"], derived))
    row = result.table.set_index("Case").loc["M0p6_sl_a4_b0"]
    assert row["Lift per q"] == pytest.approx(6.0) and row["twice"] == pytest.approx(12.0)
    assert result.reason("M0p6_sl_a4_b0", "bad") == "division by zero"
    assert result.reason("M0p6_sl_a4_b0", "force") == "q_inf needs the freestream from altitude"


def test_characteristic_values_per_curve(tmp_path):
    _study(tmp_path / "base")
    result = study_results(tmp_path / "base", _definitions())
    curves = {row.curve["Mach"]: row.values for row in result.characteristics}
    assert set(curves) == {0.6, 0.8}
    assert curves[0.6]["CLα"] == pytest.approx(0.1) and curves[0.8]["CLα"] == pytest.approx(0.12)
    assert curves[0.6]["α₀"] == pytest.approx(-2.0) and curves[0.6]["CD₀"] == pytest.approx(0.02)
    assert curves[0.6]["CMα"] == pytest.approx(-0.01)
    best = curves[0.6]["α at (L/D)max"]
    assert best in ALPHAS and curves[0.6]["(L/D)max"] == pytest.approx(
        max(0.1 * (a + 2) / (0.02 + 0.05 * (0.1 * (a + 2)) ** 2) for a in ALPHAS))


def test_an_overlay_uses_this_studys_definitions_and_notes_missing_columns(tmp_path):
    _study(tmp_path / "base")
    _study(tmp_path / "v2", cl_slope=0.11, surface=False)
    definitions = _definitions(["CL(Wing)"])
    other = study_results(tmp_path / "v2", definitions)
    assert other.name == "v2"
    assert other.table["L/D"].notna().all()
    assert other.notes == ["v2 has no CL(Wing)"]
    assert other.table["CL(Wing)"].isna().all()


def test_results_are_cached_until_a_history_changes(tmp_path, monkeypatch):
    import aerosuite.engine.study_results as module

    _study(tmp_path / "base")
    calls = []
    real = module.summarize
    monkeypatch.setattr(module, "summarize", lambda *a, **k: calls.append(1) or real(*a, **k))
    study_results(tmp_path / "base", _definitions())
    study_results(tmp_path / "base", _definitions())
    assert len(calls) == 1
    history = tmp_path / "base" / "runs" / "M0p6_sl_a0_b0" / "history.csv"
    history.write_text(history.read_text() + "50,-3,0.2,0.022,0\n")
    study_results(tmp_path / "base", _definitions())
    assert len(calls) == 2


def test_saving_the_page_settings_keeps_the_cache(tmp_path, monkeypatch):
    import aerosuite.engine.study_results as module
    from aerosuite.engine.project import open_project, save_project

    _study(tmp_path / "base")
    calls = []
    real = module.summarize
    monkeypatch.setattr(module, "summarize", lambda *a, **k: calls.append(1) or real(*a, **k))
    study_results(tmp_path / "base", _definitions())
    project = open_project(tmp_path / "base")
    project.results.filters = {"Mach": [0.6]}  # a filter, a fold, a panel: not the data
    project.results.folded = ["plots"]
    save_project(tmp_path / "base", project)
    study_results(tmp_path / "base", _definitions())
    assert len(calls) == 1
    project.name = "renamed"  # the study itself changed: read again
    save_project(tmp_path / "base", project)
    assert study_results(tmp_path / "base", _definitions()).name == "renamed"
    assert len(calls) == 2


def test_missing_values_are_reported_not_raised(tmp_path):
    _study(tmp_path / "base")
    result = study_results(tmp_path / "base", _definitions())
    assert result.reason("M0p6_sl_a4_b0", "L/D") is None
    assert isinstance(Missing("x"), Missing)


# -- imported studies: histories in their own folders, Temperature and Config (import Task 3) ------------------


def _old_runs(root):
    """ht and vt configurations at Mach 1.2, β 0 … 4; a history per case folder, its .cfg beside it."""
    runs = root / "old-runs"
    for part, offset in (("ht", 0.02), ("vt", 0.0)):
        for beta in (0, 2, 4):
            name = f"M1p2_10km_{part}_a0_b{beta}"
            folder = runs / name
            folder.mkdir(parents=True)
            (folder / f"{name}.cfg").write_text(f"MACH_NUMBER= 1.2\nAOA= 0\nSIDESLIP_ANGLE= {beta}\n"
                                                f"FREESTREAM_TEMPERATURE= 223.25\n")
            cl, csf = offset, 0.01 * beta
            rows = ["Inner_Iter,rms[Rho],CL,CD,CSF"] + [f"{i},-3,{cl},0.05,{csf}" for i in range(30)]
            (folder / "history.csv").write_text("\n".join(rows) + "\n")
    return runs


def test_an_imported_study_reads_its_case_folders(tmp_path):
    from aerosuite.engine.imported import create_imported_study
    from aerosuite.engine.models import ResultsSettings
    from aerosuite.engine.results import history_columns
    from aerosuite.engine.project import open_project

    runs = _old_runs(tmp_path)
    create_imported_study(tmp_path / "study", runs)
    project = open_project(tmp_path / "study")
    assert history_columns(tmp_path / "study", project) == ["rms[Rho]", "CL", "CD", "CSF"]
    settings = ResultsSettings(packages=[], parameters=["CSF", "T over 100"],
                               derived=[DerivedValue(name="T over 100", formula="Temperature / 100")],
                               characteristics=[DerivedValue(name="CSFβ", formula="slope(CSF, Beta, 0, 4)")])
    definitions = effective(settings, history_columns(tmp_path / "study", project))
    result = study_results(tmp_path / "study", definitions)
    table = result.table.set_index("Case")
    assert len(table) == 6
    row = table.loc["M1p2_10km_vt_a0_b4"]
    assert (row["Config"], row["Temperature"], row["Altitude"], row["Beta"]) == ("vt", 223.25, 10.0, 4.0)
    assert row["CSF"] == pytest.approx(0.04) and row["T over 100"] == pytest.approx(2.2325)
    curves = {row.curve["Config"]: row.values["CSFβ"] for row in result.characteristics}
    assert curves == {"ht": pytest.approx(0.01), "vt": pytest.approx(0.01)}  # one curve per configuration


def test_studies_without_temperature_or_config_have_no_such_columns(tmp_path):
    _study(tmp_path / "base")
    table = study_results(tmp_path / "base", _definitions()).table
    assert "Temperature" not in table.columns and "Config" not in table.columns

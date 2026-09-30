"""Importing existing SU2 runs: folder names, case folders, the scan (spec 2026-09-30-import-runs-design.md)."""
import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.imported import Skipped, read_case, read_name, scan


@pytest.mark.parametrize("name, mach, alpha, beta, altitude, temperature, base", [
    ("M2p5_30km_a50_T200K", 2.5, 50.0, None, 30.0, 200.0, ""),
    ("M1p2_10km_vt_a0_b6", 1.2, 0.0, 6.0, 10.0, None, "vt"),
    ("M0p8_sl_a2_b0", 0.8, 2.0, 0.0, 0.0, None, ""),
    ("M0p8_an4_b0_x07", 0.8, -4.0, 0.0, None, None, "x07"),
    ("M0p85_11000m_a2p5_bn2", 0.85, 2.5, -2.0, 11.0, None, ""),
    ("M0.8_A5m", 0.8, -5.0, None, None, None, ""),         # the old app's sign suffix
    ("m0p8_T216p65K_flaps20_a4", 0.8, 4.0, None, None, 216.65, "flaps20"),
    ("M0p8_M0p9_a2", 0.8, 2.0, None, None, None, "M0p9"),   # a part is used once
    ("baseline_run7", None, None, None, None, None, "baseline_run7"),
])
def test_names_are_read_part_by_part(name, mach, alpha, beta, altitude, temperature, base):
    values = read_name(name)
    assert (values.mach, values.alpha, values.beta, values.altitude_km, values.temperature_K, values.base) == (
        mach, alpha, beta, altitude, temperature, base)


def _case(root, name, cfg=None, history="history.csv", cfg_name=None):
    folder = root / name
    folder.mkdir(parents=True)
    if cfg is not None:
        (folder / (cfg_name or f"{name}.cfg")).write_text(cfg)
    if history:
        (folder / history).write_text('"Inner_Iter","CL"\n0,0.1\n1,0.1\n')
    return folder


CFG = "MACH_NUMBER= {m}\nAOA= {a}\nSIDESLIP_ANGLE= {b}\nFREESTREAM_TEMPERATURE= {t}\n"


def test_the_cfg_wins_and_the_name_fills_in(tmp_path):
    folder = _case(tmp_path, "M1p2_10km_vt_a0_b6", CFG.format(m=1.25, a=0, b=6, t=223.25))
    found = read_case(folder)
    assert (found.mach, found.alpha, found.beta, found.altitude_km, found.temperature_K, found.base) == (
        1.25, 0.0, 6.0, 10.0, 223.25, "vt")
    assert found.cfg == folder / "M1p2_10km_vt_a0_b6.cfg" and found.history == folder / "history.csv"
    assert [(d.option, d.cfg_value, d.name_value) for d in found.disagreements] == [("MACH_NUMBER", 1.25, 1.2)]


def test_a_folder_without_a_cfg_is_read_from_its_name(tmp_path):
    found = read_case(_case(tmp_path, "M0p8_a4", cfg=None))
    assert (found.mach, found.alpha, found.beta, found.cfg) == (0.8, 4.0, 0.0, None)  # β defaults to 0


def test_history_files(tmp_path):
    custom = _case(tmp_path, "c1", "MACH_NUMBER= 0.8\nAOA= 2\nCONV_FILENAME= conv\n", history="conv.csv")
    assert read_case(custom).history.name == "conv.csv"
    tecplot = _case(tmp_path, "c2", "MACH_NUMBER= 0.8\nAOA= 2\n", history="history.dat")
    assert read_case(tecplot).history.name == "history.dat"
    other = _case(tmp_path, "c3", "MACH_NUMBER= 0.8\nAOA= 2\n", history="history_restart.csv")
    assert read_case(other).history.name == "history_restart.csv"
    assert read_case(_case(tmp_path, "c4", "MACH_NUMBER= 0.8\nAOA= 2\n", history=None)) == Skipped(
        "c4", "no history file")


def test_which_cfg(tmp_path):
    several = _case(tmp_path, "c1", "MACH_NUMBER= 0.8\nAOA= 2\n", cfg_name="c1.cfg")
    (several / "old.cfg").write_text("MACH_NUMBER= 0.5\nAOA= 0\n")
    assert read_case(several).mach == 0.8  # the one named like the folder
    one_with_mach = _case(tmp_path, "c2", "MACH_NUMBER= 0.7\nAOA= 1\n", cfg_name="run.cfg")
    (one_with_mach / "mesh_deform.cfg").write_text("DV_KIND= FFD\n")
    assert read_case(one_with_mach).mach == 0.7  # else the one that sets MACH_NUMBER
    ambiguous = _case(tmp_path, "c3", "MACH_NUMBER= 0.7\nAOA= 1\n", cfg_name="a.cfg")
    (ambiguous / "b.cfg").write_text("MACH_NUMBER= 0.9\nAOA= 1\n")
    assert read_case(ambiguous) == Skipped("c3", "several .cfg files, none named like the folder")


def test_mach_and_alpha_are_required(tmp_path):
    assert read_case(_case(tmp_path, "run7", "SOLVER= EULER\n")) == Skipped(
        "run7", "no Mach (MACH_NUMBER in the .cfg or M… in the name)")
    assert read_case(_case(tmp_path, "M0p8_x", "SOLVER= EULER\n")) == Skipped(
        "M0p8_x", "no α (AOA in the .cfg or a… in the name)")


def test_scan_reads_the_case_folders_and_groups_warnings(tmp_path):
    runs = tmp_path / "old-runs"
    for a in (0, 10, 20):
        _case(runs, f"M2p5_30km_a{a}_T200K", CFG.format(m=2.5, a=a, b=0, t=216.65))
    _case(runs, "M1p2_10km_vt_a0_b6", CFG.format(m=1.25, a=0, b=6, t=223.25))
    _case(runs, "M1p2_10km_vt_a0_b8", CFG.format(m=1.2, a=0, b=8, t=223.25), history=None)
    (runs / "notes").mkdir()
    (runs / ".hidden").mkdir()
    (runs / "loose.txt").write_text("x")
    result = scan(runs)
    assert [c.name for c in result.cases] == ["M1p2_10km_vt_a0_b6", "M2p5_30km_a0_T200K", "M2p5_30km_a10_T200K",
                                              "M2p5_30km_a20_T200K"]
    assert result.warnings == [
        "M1p2_10km_vt_a0_b6: the cfg's MACH_NUMBER is 1.25, the name says 1.2 — 1.25 used",
        "3 cases (M2p5_30km_a0_T200K, …): the cfg's FREESTREAM_TEMPERATURE is 216.65, the name says 200 — "
        "216.65 used"]
    assert result.skipped == [Skipped("M1p2_10km_vt_a0_b8", "no history file")]  # the empty "notes" is left out


def test_scan_looks_into_group_folders(tmp_path):
    runs = tmp_path / "st_tail"
    for group in ("M0p9_10km", "M2_30km"):
        mach = group[1:].split("_")[0].replace("p", ".")
        for a in (0, 10):
            _case(runs / group, f"{group}_a{a}_b2", CFG.format(m=mach, a=a, b=2, t=223.15))
        (runs / group / "config_CFD.cfg").write_text("MACH_NUMBER= 0.5\nAOA= 0\n")  # the group's template
        (runs / group / f"{group}_a45_b2.cfg").write_text(CFG.format(m=mach, a=45, b=2, t=223.15))  # never ran
    _case(runs / "M2_30km" / "M2_30km_a0_b2", "inner", CFG.format(m=9, a=0, b=0, t=1))  # inside a case: not read
    _case(runs / "old" / "M4_30km", "M4_30km_a0_b2", CFG.format(m=4, a=0, b=2, t=223.15), history=None)
    (runs / "M1p5_10km").mkdir()
    (runs / "results").mkdir()
    (runs / "results" / "summary.csv").write_text("x")
    (runs / ".git" / "M0p3_a0").mkdir(parents=True)
    result = scan(runs)
    assert [(c.group, c.name, c.mach, c.alpha, c.base) for c in result.cases] == [
        ("M0p9_10km", "M0p9_10km_a0_b2", 0.9, 0.0, ""), ("M0p9_10km", "M0p9_10km_a10_b2", 0.9, 10.0, ""),
        ("M2_30km", "M2_30km_a0_b2", 2.0, 0.0, ""), ("M2_30km", "M2_30km_a10_b2", 2.0, 10.0, "")]
    assert result.skipped == [Skipped("old/M4_30km/M4_30km_a0_b2", "no history file")]  # only case-like folders


def test_scan_goes_four_levels_down_and_leaves_out_studies(tmp_path):
    runs = tmp_path / "runs"
    _case(runs / "a" / "b" / "c", "M0p8_a1", CFG.format(m=0.8, a=1, b=0, t=288))
    _case(runs / "a" / "b" / "c" / "d", "M0p8_a2", CFG.format(m=0.8, a=2, b=0, t=288))  # five down
    _case(runs / "study", "M0p8_a3", CFG.format(m=0.8, a=3, b=0, t=288))
    (runs / "study" / "project.json").write_text("{}")  # an AeroSuite study: not read
    assert [c.name for c in scan(runs).cases] == ["M0p8_a1"]


def test_clashing_names_take_their_group_as_config(tmp_path):
    runs = tmp_path / "st_tail"
    for group in ("M3_30km", "M3_30km_new"):
        _case(runs / group, "M3p0_30km_st_a0_b10", CFG.format(m=3, a=0, b=10, t=226.5))
    _case(runs / "M3_30km_new", "M3p0_30km_st_a10_b10", CFG.format(m=3, a=10, b=10, t=226.5))
    result = scan(runs)
    assert [(c.name, c.base) for c in result.cases] == [
        ("M3_30km/M3p0_30km_st_a0_b10", "M3_30km"), ("M3_30km_new/M3p0_30km_st_a0_b10", "M3_30km_new"),
        ("M3p0_30km_st_a10_b10", "st")]


def test_scan_needs_a_folder(tmp_path):
    with pytest.raises(ProjectError, match="not a folder"):
        scan(tmp_path / "missing")


# -- the imported study (Task 2) -------------------------------------------------------


def _runs(tmp_path):
    runs = tmp_path / "old-runs"
    for a in (0, 10):
        _case(runs, f"M2p5_30km_a{a}_T200K", CFG.format(m=2.5, a=a, b=0, t=216.65))
    _case(runs, "M1p2_10km_vt_a0_b6", CFG.format(m=1.2, a=0, b=6, t=223.25))
    return runs


def _snapshot(folder):
    return sorted((str(p.relative_to(folder)), p.stat().st_mtime_ns) for p in folder.rglob("*"))


def test_an_imported_study_holds_only_project_json_and_changes_nothing(tmp_path):
    from aerosuite.engine.imported import create_imported_study
    from aerosuite.engine.models import SCHEMA_VERSION
    from aerosuite.engine.project import open_project

    runs = _runs(tmp_path)
    before = _snapshot(runs)
    project, result = create_imported_study(tmp_path / "study", runs, name="Old runs")
    assert [p.name for p in (tmp_path / "study").iterdir()] == ["project.json"]
    assert _snapshot(runs) == before
    reopened = open_project(tmp_path / "study")
    assert SCHEMA_VERSION == 7 and reopened.schema_version == 7 and reopened.name == "Old runs"
    assert reopened.sweep.enabled is False
    assert reopened.imported.source == str(runs.resolve())
    first = reopened.imported.cases[0]
    assert (first.name, first.mach, first.beta, first.altitude_km, first.base) == (
        "M1p2_10km_vt_a0_b6", 1.2, 6.0, 10.0, "vt")
    assert first.history == str(runs.resolve() / "M1p2_10km_vt_a0_b6" / "history.csv")
    assert [c.name for c in reopened.cases] == [c.name for c in reopened.imported.cases]
    assert reopened.cases[0].altitude_km == 10.0


def test_importing_nothing_is_refused(tmp_path):
    from aerosuite.engine.imported import create_imported_study

    (tmp_path / "empty").mkdir()
    with pytest.raises(ProjectError, match="No case folders"):
        create_imported_study(tmp_path / "study", tmp_path / "empty")
    assert not (tmp_path / "study").exists()


def test_rescan_adds_drops_and_updates_and_keeps_the_results_settings(tmp_path):
    import shutil

    from aerosuite.engine.imported import create_imported_study, rescan
    from aerosuite.engine.project import open_project, save_project

    runs = _runs(tmp_path)
    project, _ = create_imported_study(tmp_path / "study", runs)
    project.results.parameters = ["CL"]
    save_project(tmp_path / "study", project)
    _case(runs, "M2p5_30km_a20_T200K", CFG.format(m=2.5, a=20, b=0, t=216.65))
    shutil.rmtree(runs / "M2p5_30km_a0_T200K")
    (runs / "M1p2_10km_vt_a0_b6" / "M1p2_10km_vt_a0_b6.cfg").write_text(CFG.format(m=1.25, a=0, b=6, t=223.25))
    project = open_project(tmp_path / "study")
    changes = rescan(project)
    assert (changes.added, changes.removed, changes.updated) == (
        ["M2p5_30km_a20_T200K"], ["M2p5_30km_a0_T200K"], ["M1p2_10km_vt_a0_b6"])
    assert [c.name for c in project.cases] == ["M1p2_10km_vt_a0_b6", "M2p5_30km_a10_T200K", "M2p5_30km_a20_T200K"]
    assert project.imported.cases[0].mach == 1.25 and project.results.parameters == ["CL"]
    assert "MACH_NUMBER is 1.25" in project.imported.warnings[0]


def test_older_studies_open_at_schema_7(tmp_path):
    import json

    from aerosuite.engine.project import PROJECT_FILE, create_project, open_project

    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 6
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    assert open_project(tmp_path).imported is None

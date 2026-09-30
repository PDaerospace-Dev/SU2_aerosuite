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
    assert result.skipped == [Skipped("M1p2_10km_vt_a0_b8", "no history file"), Skipped("notes", "no history file")]


def test_scan_needs_a_folder(tmp_path):
    with pytest.raises(ProjectError, match="not a folder"):
        scan(tmp_path / "missing")

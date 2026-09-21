import math
from pathlib import Path

from aerosuite.core.aerosummary import AeroSummary
from aerosuite.core.sweep_runner import SweepRunner

STEADY = [0.5] * 50
WOBBLY = [0.5 + 0.2 * math.sin(i) for i in range(50)]


def test_name_extraction_uses_engine_parser():
    assert AeroSummary.extract_mach_from_case_name("M0p85_a2p5_bn1") == 0.85
    assert AeroSummary.extract_alpha_from_case_name("M0p85_a2p5_bn1") == 2.5
    assert AeroSummary.extract_beta_from_case_name("M0p85_a2p5_bn1") == -1.0
    assert AeroSummary.extract_alpha_from_case_name("ht_M0p3_A5_B0_sl") == 5.0
    assert AeroSummary.extract_beta_from_case_name("M0p6_A10m") == 0.0
    assert AeroSummary.extract_mach_from_case_name("sl_a5") == 999.0
    assert AeroSummary.is_valid_case_name("sl_a5")
    assert not AeroSummary.is_valid_case_name("wing_baseline")


def test_consolidate_adds_beta_and_sorts(tmp_path, history_writer):
    for name in ["M0p8_a2_b1", "M0p8_a0_b1", "M0p8_a2_b0", "M0p8_a0_b0"]:
        history_writer(tmp_path / name, STEADY)
    df, _ = AeroSummary.consolidate_results(str(tmp_path), ["CL"], 10, log_callback=lambda m: None)
    assert df[["Beta", "Alpha"]].values.tolist() == [[0, 0], [0, 2], [1, 0], [1, 2]]


def test_plots_split_by_beta_only_when_several(tmp_path, history_writer):
    for name in ["M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a0_b1", "M0p8_a2_b1"]:
        history_writer(tmp_path / "runs" / name, STEADY)
    df, _ = AeroSummary.consolidate_results(str(tmp_path / "runs"), ["CL"], 10, log_callback=lambda m: None)
    files = AeroSummary.generate_plots(df, ["CL"], str(tmp_path / "plots"))
    assert sorted(Path(p).name for p in files) == [
        "M0p8_B0p0_CL_vs_Alpha.png", "M0p8_B1p0_CL_vs_Alpha.png",
    ]

    single = df[df["Beta"] == 0]
    files = AeroSummary.generate_plots(single, ["CL"], str(tmp_path / "plots2"))
    assert [Path(p).name for p in files] == ["M0p8_CL_vs_Alpha.png"]


def test_build_results_reports_convergence(tmp_path, history_writer):
    history_writer(tmp_path / "good", STEADY)
    history_writer(tmp_path / "wobbly", WOBBLY)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "error.log").write_text("boom")
    (tmp_path / "empty").mkdir()
    runner = SweepRunner(script_path="unused.py", cfg_dir=str(tmp_path), control_file="unused.txt")
    run_list = [
        {"cfg_file": f"{name}.cfg", "restart_option": "none", "restart_path": None}
        for name in ["good", "wobbly", "broken", "empty", "never"]
    ]
    statuses = {r["cfg_file"]: r["status"] for r in runner._build_results(run_list, {})}
    assert statuses == {
        "good.cfg": "CONVERGED",
        "wobbly.cfg": "UNCONVERGED",
        "broken.cfg": "FAILED",
        "empty.cfg": "FAILED",
        "never.cfg": "NOT RUN",
    }


def test_legacy_convergence_uses_default_columns_when_none_selected(tmp_path, history_writer):
    from aerosuite.engine.results import read_history

    wobbly = read_history(history_writer(tmp_path / "wobbly", WOBBLY))
    ok, message = AeroSummary.check_convergence(wobbly, ["rms[Rho]"])
    assert not ok and message.startswith("CL not converged")
    ok, _ = AeroSummary.check_convergence(wobbly, ["CD"])
    assert ok

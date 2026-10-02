"""What a study's history files offer, how it is grouped, and convergence judged on the chosen parameters."""
from pathlib import Path

import pytest

from aerosuite.engine.results import (GROUP_CONVERGENCE, GROUP_FLOW, GROUP_RESIDUALS, GROUP_SOLVER, GROUP_TOTALS,
                                      convergence_columns, group_of, history_columns, ordered_groups, summarize)

REAL_NAMES = ["Time_Iter", "Outer_Iter", "Inner_Iter", "Cur_Time", "rms[Rho]", "max[RhoE]", "bgs[k]", "LinSolRes",
              "LinSolIter", "Avg_CFL", "CL", "CD", "CMy", "CEff", "CL(Wing)", "CMy(HT)", "Avg_Massflow(outlet)",
              "Cauchy[CD]", "Pressure_Drop", "TotalHeatflux"]


def _history(folder, header, rows):
    folder.mkdir(parents=True, exist_ok=True)
    lines = [",".join(f'"{h}"' for h in header)] + [",".join(str(v) for v in row) for row in rows]
    (folder / "history.csv").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("column, group", [
    ("CL", GROUP_TOTALS), ("CEff", GROUP_TOTALS), ("CMy", GROUP_TOTALS),
    ("CL(Wing)", "Marker: Wing"), ("CMy(HT)", "Marker: HT"), ("Avg_Massflow(outlet)", "Marker: outlet"),
    ("rms[Rho]", GROUP_RESIDUALS), ("max[RhoE]", GROUP_RESIDUALS), ("bgs[k]", GROUP_RESIDUALS),
    ("Cauchy[CD]", GROUP_CONVERGENCE), ("LinSolRes", GROUP_SOLVER), ("Avg_CFL", GROUP_SOLVER),
    ("Pressure_Drop", GROUP_FLOW), ("TotalHeatflux", GROUP_FLOW),
])
def test_groups_follow_su2_names(column, group):
    assert group_of(column) == group


def test_group_order_puts_totals_first_and_residuals_last():
    columns = [c for c in REAL_NAMES if c not in ("Time_Iter", "Outer_Iter", "Inner_Iter", "Cur_Time")]
    assert ordered_groups(columns) == [GROUP_TOTALS, "Marker: HT", "Marker: Wing", "Marker: outlet", GROUP_FLOW,
                                       GROUP_CONVERGENCE, GROUP_SOLVER, GROUP_RESIDUALS]


def test_history_columns_are_the_union_without_iteration_counters(tmp_path):
    runs = tmp_path / "runs"
    _history(runs / "a", ["Inner_Iter", "rms[Rho]", "CL", "CD"], [[0, -1, 0.1, 0.02]])
    _history(runs / "b", ["Inner_Iter", "rms[Rho]", "CL", "CD", "CL(Wing)"], [[0, -1, 0.1, 0.02, 0.09]])
    (runs / "c").mkdir()  # a case that has not run yet
    assert history_columns(tmp_path) == ["rms[Rho]", "CL", "CD", "CL(Wing)"]
    assert history_columns(tmp_path / "nothing") == []


def test_convergence_is_judged_on_chosen_parameters_that_settle():
    assert convergence_columns(["CL", "rms[Rho]", "Cauchy[CD]", "LinSolRes", "L/D"], derived={"L/D"}) == ["CL"]
    assert convergence_columns(["rms[Rho]"]) == []


def test_a_duct_is_converged_on_its_own_parameters(tmp_path):
    runs = tmp_path / "runs"
    settled = [[i, -1 - 0.01 * i, 5.0, 101000.0] for i in range(200)]
    _history(runs / "M0p4_a0_b0", ["Inner_Iter", "rms[Rho]", "Avg_Massflow(outlet)", "Avg_TotalPress(outlet)"],
             settled)
    index = {"M0p4_a0_b0": {"mach": 0.4, "alpha": 0.0, "beta": 0.0}}
    columns = ["Avg_Massflow(outlet)", "Avg_TotalPress(outlet)"]
    summary, _ = summarize(runs, columns, case_index=index, convergence_columns=columns)
    assert summary["Converged"].tolist() == [True]
    old, _ = summarize(runs, columns, case_index=index)  # judged on CL/CD/CMy as before: none here
    assert old["Converged"].tolist() == [False]
    unjudged, warnings = summarize(runs, columns, case_index=index, convergence_columns=[])
    assert unjudged["Converged"].tolist() == [None]
    assert not any("not converged" in w or "No CL" in w for w in warnings)


def test_case_histories_for_own_and_imported_studies(tmp_path):
    from aerosuite.engine.models import ImportedCase, ImportedRuns, Project
    from aerosuite.engine.results import case_histories

    runs = tmp_path / "runs"
    _history(runs / "b", ["Inner_Iter", "CL"], [[0, 0.1]])
    _history(runs / "a", ["Inner_Iter", "CL"], [[0, 0.1]])
    own = Project(name="own")
    assert case_histories(tmp_path, own) == [("a", runs / "a" / "history.csv"), ("b", runs / "b" / "history.csv")]
    imported = Project(name="imp", imported=ImportedRuns(source="/old", cases=[
        ImportedCase(name="M0p8_a0", folder="/old/M0p8_a0", history="/old/M0p8_a0/history.csv", mach=0.8,
                     alpha=0.0)]))
    assert case_histories(tmp_path, imported) == [("M0p8_a0", Path("/old/M0p8_a0/history.csv"))]


def test_summarize_takes_given_histories_and_adds_temperature_and_config(tmp_path):
    _history(tmp_path / "elsewhere" / "x", ["Inner_Iter", "CL"], [[i, 0.3] for i in range(20)])
    index = {"x": {"mach": 1.2, "alpha": 0.0, "beta": 2.0, "altitude_km": 10.0, "temperature_K": 223.25,
                   "config": "vt"}}
    summary, _ = summarize(tmp_path / "runs", ["CL"], case_index=index,
                           histories=[("x", tmp_path / "elsewhere" / "x" / "history.csv")])
    assert summary.loc[0, ["Case", "Temperature", "Config"]].tolist() == ["x", 223.25, "vt"]
    assert summary.loc[0, "CL"] == pytest.approx(0.3)

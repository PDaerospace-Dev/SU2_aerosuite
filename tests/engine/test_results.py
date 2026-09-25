import json
import math

import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.results import (
    HistoryReader,
    check_convergence,
    load_case_index,
    read_history,
    summarize,
)

STEADY = [0.5] * 50
WOBBLY = [0.5 + 0.2 * math.sin(i) for i in range(50)]


def test_read_history_parses_su2_csv(tmp_path, history_writer):
    path = history_writer(tmp_path / "c", STEADY)
    df = read_history(path)
    assert list(df.columns) == ["Inner_Iter", "rms[Rho]", "CL", "CD", "CMy"]
    assert len(df) == 50
    assert df["CL"].iloc[-1] == pytest.approx(0.5)


def test_history_reader_returns_only_new_complete_rows(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text('"Inner_Iter", "CL"\n0, 0.1\n1, 0.2\n')
    reader = HistoryReader(path)
    assert len(reader.read_new()) == 2
    with open(path, "a") as fh:
        fh.write("2, 0.3\n3, 0.")  # last row incomplete
    new = reader.read_new()
    assert new["CL"].tolist() == [0.3]
    with open(path, "a") as fh:
        fh.write("4\n")
    assert reader.read_new()["CL"].tolist() == [0.4]


def test_history_reader_restarts_when_file_is_rewritten(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text('"Inner_Iter", "CL"\n0, 0.1\n1, 0.2\n2, 0.3\n')
    reader = HistoryReader(path)
    reader.read_new()
    path.write_text('"Inner_Iter", "CL"\n0, 0.9\n')
    assert reader.read_new()["CL"].tolist() == [0.9]


def test_read_history_legacy_tecplot_format(tmp_path):
    path = tmp_path / "history.dat"
    path.write_text('TITLE = "SU2"\nVARIABLES = "Iteration","CL"\nZONE T= "x"\n0, 0.1\n1, 0.2\n')
    df = read_history(path)
    assert list(df.columns) == ["Iteration", "CL"]
    assert len(df) == 2


def test_read_history_missing_file_is_empty(tmp_path):
    assert read_history(tmp_path / "none.csv").empty


def test_check_convergence(tmp_path, history_writer):
    steady = read_history(history_writer(tmp_path / "a", STEADY))
    wobbly = read_history(history_writer(tmp_path / "b", WOBBLY))
    short = read_history(history_writer(tmp_path / "c", STEADY[:5]))
    assert check_convergence(steady) == (True, "Converged")
    ok, message = check_convergence(wobbly)
    assert not ok and message.startswith("CL not converged")
    ok, message = check_convergence(short)
    assert not ok and "Insufficient iterations" in message


def test_load_case_index(tmp_path):
    assert load_case_index(tmp_path) == {}
    (tmp_path / "cases.json").write_text(json.dumps({"x": {"mach": 0.8, "alpha": 1.0, "beta": 0.0}}))
    assert load_case_index(tmp_path)["x"]["alpha"] == 1.0


def test_load_case_index_malformed_json(tmp_path):
    (tmp_path / "cases.json").write_text("{not json")
    with pytest.raises(ProjectError):
        load_case_index(tmp_path)


def test_summarize_uses_index_then_names_and_sorts(tmp_path, history_writer):
    runs = tmp_path / "runs"
    history_writer(runs / "M0p8_a2p5_b1", STEADY)
    history_writer(runs / "M0p8_a0_b0", STEADY)
    history_writer(runs / "M0p8_a5_b0", WOBBLY)
    history_writer(runs / "custom_name", STEADY)
    history_writer(runs / "no_angles_here", STEADY)
    index = {"custom_name": {"mach": 0.6, "alpha": 1.0, "beta": 0.0}}
    df, warnings = summarize(runs, ["CL", "CD", "Missing"], last_n=10, case_index=index)
    assert df["Case"].tolist() == ["custom_name", "M0p8_a0_b0", "M0p8_a5_b0", "M0p8_a2p5_b1"]
    assert df.loc[df["Case"] == "M0p8_a2p5_b1", "Beta"].item() == 1.0
    assert not df.loc[df["Case"] == "M0p8_a5_b0", "Converged"].item()
    assert df["CL"].iloc[0] == pytest.approx(0.5)
    assert df["Missing"].isna().all()
    assert any("no_angles_here" in w for w in warnings)
    assert any("M0p8_a5_b0" in w for w in warnings)


def test_summarize_skip_and_empty(tmp_path, history_writer):
    runs = tmp_path / "runs"
    history_writer(runs / "M0p8_a0_b0", STEADY)
    df, _ = summarize(runs, ["CL"], skip=["M0p8_a0_b0"])
    assert df.empty
    assert list(df.columns) == ["Case", "Mach", "Alpha", "Beta", "Converged", "CL"]


def test_check_convergence_without_coefficient_columns(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text('"Inner_Iter", "rms[Rho]"\n' + "".join(f"{i}, {-2 - 0.1 * i}\n" for i in range(50)))
    assert check_convergence(read_history(path)) == (
        False, "No CL/CD/CMy columns in history; add them to HISTORY_OUTPUT to judge convergence"
    )
    ok, message = check_convergence(read_history(path), ["CL"])
    assert not ok and message.startswith("No CL columns")


def test_check_convergence_near_zero_mean(tmp_path):
    """A symmetric case (CL about 1e-9) with CD/CMy steady converges although std/mean is large."""
    path = tmp_path / "history.csv"
    rows = [f"{i}, {1e-9 + 1e-10 * (-1) ** i:.6e}, 0.02, -0.1\n" for i in range(50)]
    path.write_text('"Inner_Iter", "CL", "CD", "CMy"\n' + "".join(rows))
    df = read_history(path)
    assert df["CL"].std() / abs(df["CL"].mean()) > 1e-3  # the relative rule alone would fail it
    assert check_convergence(df) == (True, "Converged")


def test_history_buffer_accumulates_and_starts_over(tmp_path, history_writer):
    from aerosuite.engine.results import HistoryBuffer

    path = history_writer(tmp_path / "case", [0.5] * 20)
    buffer = HistoryBuffer(path)
    assert len(buffer.read()) == 20
    history_writer(tmp_path / "case", [0.5] * 30)  # 10 rows appended
    assert len(buffer.read()) == 30
    history_writer(tmp_path / "case", [0.5] * 5)  # the case was re-run: the file shrank
    assert len(buffer.read()) == 5

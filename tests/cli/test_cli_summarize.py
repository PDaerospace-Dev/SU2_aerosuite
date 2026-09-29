import math

import pandas as pd
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.cfg import generate_configs

runner = CliRunner()


def test_summarize_writes_and_prints_the_table(ready_project, history_writer):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    for case in project.cases:
        history_writer(project_dir / "runs" / case.name, [0.5] * 50)
    history_writer(project_dir / "runs" / "M0p8_a4_b0", [0.5 + 0.2 * math.sin(i) for i in range(50)])

    result = runner.invoke(app, ["summarize", str(project_dir), "--last", "10", "--columns", "CL,CD"])
    assert result.exit_code == 0, result.output
    assert "Warning: M0p8_a4_b0: CL not converged" in result.output
    assert "Saved" in result.output
    df = pd.read_csv(project_dir / "results" / "summary.csv")
    assert df["Case"].tolist() == ["M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"]
    assert list(df.columns) == ["Case", "Mach", "Alpha", "Beta", "Converged", "CL", "CD"]
    assert "M0p8_a2_b0" in result.output


def test_summarize_without_results(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["summarize", str(project_dir)])
    assert result.exit_code == 1
    assert "Error: No results found" in result.output


def test_summarize_needs_a_project(tmp_path):
    result = runner.invoke(app, ["summarize", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: No project found" in result.output

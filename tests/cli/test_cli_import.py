"""aerosuite import: read existing SU2 runs into a read-only study (spec 2026-09-30-import-runs-design.md)."""
import pandas as pd
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.project import open_project

runner = CliRunner()


def _runs(root):
    runs = root / "old-runs"
    for name, cfg in (("M2p5_30km_a0_T200K", "MACH_NUMBER= 2.5\nAOA= 0\nFREESTREAM_TEMPERATURE= 216.65\n"),
                      ("M2p5_30km_a10_T200K", "MACH_NUMBER= 2.5\nAOA= 10\nFREESTREAM_TEMPERATURE= 216.65\n")):
        folder = runs / name
        folder.mkdir(parents=True)
        (folder / f"{name}.cfg").write_text(cfg)
        rows = ["Inner_Iter,rms[Rho],CL,CD"] + [f"{i},-3,0.1,0.05" for i in range(30)]
        (folder / "history.csv").write_text("\n".join(rows) + "\n")
    (runs / "notes").mkdir()
    return runs


def test_import_shows_what_it_read_and_creates_the_study(tmp_path):
    runs = _runs(tmp_path)
    result = runner.invoke(app, ["import", str(runs), str(tmp_path / "study"), "--name", "Old runs"])
    assert result.exit_code == 0, result.output
    assert "Found 2 cases" in result.output
    assert "M2p5_30km_a10_T200K" in result.output
    assert ("2 cases (M2p5_30km_a0_T200K, …): the cfg's FREESTREAM_TEMPERATURE is 216.65, the name says 200 — "
            "216.65 used") in result.output
    assert "Skipped notes: no history file" in result.output
    project = open_project(tmp_path / "study")
    assert project.name == "Old runs" and len(project.imported.cases) == 2
    shown = runner.invoke(app, ["show", str(tmp_path / "study")]).output
    assert f"Imported:  {runs.resolve()}" in shown and "M2p5_30km_a10_T200K" in shown
    summary = runner.invoke(app, ["summarize", str(tmp_path / "study")])
    assert summary.exit_code == 0, summary.output
    df = pd.read_csv(tmp_path / "study" / "results" / "summary.csv")
    assert df["Case"].tolist() == ["M2p5_30km_a0_T200K", "M2p5_30km_a10_T200K"]
    assert df["Temperature"].tolist() == [216.65, 216.65]


def test_import_of_nothing_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    result = runner.invoke(app, ["import", str(tmp_path / "empty"), str(tmp_path / "study")])
    assert result.exit_code == 1 and "No case folders" in result.output
    assert not (tmp_path / "study").exists()

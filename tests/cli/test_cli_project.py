import subprocess
import sys

from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.project import open_project

runner = CliRunner()


def _inputs(tmp_path):
    template = tmp_path / "master.cfg"
    template.write_text("MACH_NUMBER= 0.3\nAOA= 0.0\n")
    mesh = tmp_path / "wing.su2"
    mesh.write_text("NMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    return template, mesh


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "new" in result.output and "show" in result.output


def test_new_creates_project_with_template_and_mesh(tmp_path):
    template, mesh = _inputs(tmp_path)
    folder = tmp_path / "study"
    result = runner.invoke(app, ["new", str(folder), "--template", str(template), "--mesh", str(mesh)])
    assert result.exit_code == 0, result.output
    assert "Created project 'study'" in result.output
    project = open_project(folder)
    assert (folder / "template.cfg").read_text() == "MACH_NUMBER= 0.3\nAOA= 0.0\n"
    assert project.mesh.markers == ["farfield", "wall"]


def test_new_refuses_missing_inputs_without_creating_anything(tmp_path):
    folder = tmp_path / "study"
    result = runner.invoke(app, ["new", str(folder), "--template", str(tmp_path / "nope.cfg")])
    assert result.exit_code == 1
    assert "Error: Template not found" in result.output
    assert "Traceback" not in result.output
    assert not (folder / "project.json").exists()


def test_new_refuses_an_existing_project(tmp_path):
    runner.invoke(app, ["new", str(tmp_path / "p")])
    result = runner.invoke(app, ["new", str(tmp_path / "p")])
    assert result.exit_code == 1
    assert "Error:" in result.output and "already contains a project" in result.output


def test_show_describes_the_project(tmp_path):
    template, mesh = _inputs(tmp_path)
    folder = tmp_path / "study"
    runner.invoke(app, ["new", str(folder), "--template", str(template), "--mesh", str(mesh)])
    result = runner.invoke(app, ["show", str(folder)])
    assert result.exit_code == 0, result.output
    assert "Project:   study" in result.output
    assert "Markers:   farfield, wall" in result.output
    assert "Mach:      (none)" in result.output
    assert "Cases (0):" in result.output


def test_show_missing_project(tmp_path):
    result = runner.invoke(app, ["show", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: No project found" in result.output


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "aerosuite.cli", "--help"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0
    assert "generate" in result.stdout or "show" in result.stdout

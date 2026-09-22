from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.project import create_project, open_project

runner = CliRunner()


def _project(tmp_path):
    folder = tmp_path / "study"
    project = create_project(folder)
    return folder, project


def test_set_sweep_builds_cases(tmp_path):
    folder, _ = _project(tmp_path)
    result = runner.invoke(app, [
        "set", str(folder), "--mach", "0.6,0.8", "--alpha=-2:2:2", "--beta", "0",
        "--altitude", "10km", "--base-name", "x07",
    ])
    assert result.exit_code == 0, result.output
    assert "The sweep now has 6 cases." in result.output
    project = open_project(folder)
    assert project.sweep.alpha == [-2.0, 0.0, 2.0]
    assert project.cases[0].name == "M0p6_10km_an2_b0_x07"


def test_set_accepts_a_negative_value_as_a_separate_token(tmp_path):
    folder, _ = _project(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--alpha", "-4,0,4"])
    assert result.exit_code == 0, result.output
    assert open_project(folder).sweep.alpha == [-4.0, 0.0, 4.0]


def test_set_keys_unset_and_run_settings(tmp_path):
    folder, _ = _project(tmp_path)
    result = runner.invoke(app, [
        "set", str(folder), "--key", "CFL_NUMBER=5", "--key", "MARKER_PLOTTING=none",
        "--partitions", "64", "--sweep-python", "/opt/conda/bin/python3",
    ])
    assert result.exit_code == 0, result.output
    project = open_project(folder)
    assert project.settings.overrides == {"CFL_NUMBER": "5"}
    assert project.settings.markers == {"MARKER_PLOTTING": None}
    assert project.run.partitions == 64
    assert project.run.sweep_python == "/opt/conda/bin/python3"

    result = runner.invoke(app, ["set", str(folder), "--unset", "CFL_NUMBER"])
    assert result.exit_code == 0, result.output
    assert open_project(folder).settings.overrides == {}


def test_set_template_and_mesh(tmp_path):
    folder, _ = _project(tmp_path)
    template = tmp_path / "master.cfg"
    template.write_text("AOA= 0\n")
    mesh = tmp_path / "wing.su2"
    mesh.write_text("MARKER_TAG= wall\n")
    result = runner.invoke(app, ["set", str(folder), "--template", str(template), "--mesh", str(mesh)])
    assert result.exit_code == 0, result.output
    assert (folder / "template.cfg").read_text() == "AOA= 0\n"
    assert open_project(folder).mesh.markers == ["wall"]


def test_set_errors_change_nothing(tmp_path):
    folder, _ = _project(tmp_path)
    before = (folder / "project.json").read_text()
    for args in (["--mach", "abc"], ["--key", "AOA=3"], ["--key", "CFL_NUMBER"],
                 ["--unset", "ITER"], ["--mach", "0.8", "--key", "MACH_NUMBER=0.5"]):
        result = runner.invoke(app, ["set", str(folder), *args])
        assert result.exit_code == 1, (args, result.output)
        assert result.output.startswith("Error:"), (args, result.output)
    assert (folder / "project.json").read_text() == before


def test_set_partitions_must_be_positive(tmp_path):
    folder, _ = _project(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--partitions", "0"])
    assert result.exit_code != 0


def test_set_without_options(tmp_path):
    folder, _ = _project(tmp_path)
    result = runner.invoke(app, ["set", str(folder)])
    assert result.exit_code == 0
    assert "Nothing to change" in result.output

from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.project import create_project, open_project, save_project

runner = CliRunner()


def _sweep(tmp_path):
    folder = tmp_path / "study"
    create_project(folder)
    (folder / "template.cfg").write_text("MACH_NUMBER= 0.3\n")
    result = runner.invoke(app, ["set", str(folder), "--mach", "0.6,0.8", "--alpha", "0", "--beta", "0"])
    assert result.exit_code == 0, result.output
    return folder


def test_set_altitude_mode_renames_cases_and_show_lists_reynolds(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude-km", "11",
                                 "--reynolds-length", "6"])
    assert result.exit_code == 0, result.output
    project = open_project(folder)
    assert project.settings.freestream.mode == "altitude"
    assert "_11km_" in project.cases[0].name
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Altitudes: 11 km" in shown and "Freestream: from altitude, Reynolds length 6 m" in shown
    assert "Re=27193793" in shown and "Re=36258390" in shown


def test_the_typed_label_is_refused_in_altitude_mode(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude", "cruise"])
    assert result.exit_code != 0
    assert "follows the altitude" in result.output
    assert open_project(folder).settings.freestream.mode == "manual"  # nothing saved


def test_altitude_mode_without_an_altitude(tmp_path):
    folder = _sweep(tmp_path)
    assert runner.invoke(app, ["set", str(folder), "--freestream", "altitude"]).exit_code == 0
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Altitudes: (none)" in shown
    generated = runner.invoke(app, ["generate", str(folder)])
    assert generated.exit_code != 0 and "No altitudes in the sweep" in generated.output


def test_a_list_of_altitudes_sweeps_them(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude-km", "0,11",
                                 "--reynolds-length", "6"])
    assert result.exit_code == 0, result.output
    assert [c.name for c in open_project(folder).cases] == [
        "M0p6_0km_a0_b0", "M0p8_0km_a0_b0", "M0p6_11km_a0_b0", "M0p8_11km_a0_b0"]
    assert "Altitudes: 0, 11 km" in runner.invoke(app, ["show", str(folder)]).output


def test_a_single_case_takes_one_altitude(tmp_path):
    folder = _sweep(tmp_path)
    project = open_project(folder)
    project.sweep.enabled = False
    save_project(folder, project)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude-km", "0,11"])
    assert result.exit_code != 0 and "single case has one altitude" in result.output
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude-km", "11",
                                 "--reynolds-length", "6"])
    assert result.exit_code == 0, result.output
    assert "Freestream: from altitude 11 km, Reynolds length 6 m" in runner.invoke(app, ["show", str(folder)]).output


def test_a_bad_mode_is_refused(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "sky"])
    assert result.exit_code != 0


def test_manual_mode_show_is_unchanged_apart_from_the_mode_line(tmp_path):
    folder = _sweep(tmp_path)
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Freestream: set by hand" in shown and "Re=" not in shown

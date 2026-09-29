import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aerosuite.cli import app, project_cmds
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.project import create_project, open_project, save_project

FAKE_EDITOR = Path(__file__).resolve().parents[1] / "fixtures" / "fake_editor.py"
runner = CliRunner()


@pytest.fixture
def edit_project(tmp_path, monkeypatch):
    folder = tmp_path / "study"
    project = create_project(folder)
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    update_sweep(project, mach=[0.8], alpha=[0.0], beta=[0.0])
    save_project(folder, project)
    plan = tmp_path / "editor_plan.json"
    monkeypatch.setenv("FAKE_EDITOR_PLAN", str(plan))
    monkeypatch.setattr(project_cmds, "editor_command", lambda: [sys.executable, str(FAKE_EDITOR)])

    def with_actions(*actions):
        plan.write_text(json.dumps(list(actions)))
        return folder

    return with_actions


def test_valid_edit_is_saved(edit_project):
    folder = edit_project("rename:edited")
    result = runner.invoke(app, ["edit", str(folder)])
    assert result.exit_code == 0, result.output
    assert "Saved project.json" in result.output
    assert open_project(folder).name == "edited"


def test_unchanged_edit(edit_project):
    folder = edit_project("noop")
    result = runner.invoke(app, ["edit", str(folder)])
    assert result.exit_code == 0
    assert "No changes." in result.output


def test_sweep_edit_rebuilds_cases(edit_project):
    folder = edit_project("alpha:0,2,4")
    result = runner.invoke(app, ["edit", str(folder)])
    assert result.exit_code == 0, result.output
    assert "cases rebuilt (3)" in result.output
    assert [c.name for c in open_project(folder).cases] == ["M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"]


def test_invalid_edit_can_be_discarded(edit_project):
    folder = edit_project("break")
    before = (folder / "project.json").read_text()
    result = runner.invoke(app, ["edit", str(folder)], input="n\n")
    assert result.exit_code == 1
    assert "not valid JSON" in result.output
    assert "Discarded" in result.output
    assert (folder / "project.json").read_text() == before


def test_edit_that_is_not_utf8_can_be_discarded(edit_project):
    folder = edit_project("latin1")
    before = (folder / "project.json").read_bytes()
    result = runner.invoke(app, ["edit", str(folder)], input="n\n")
    assert result.exit_code == 1
    assert "Error: the edited file is not UTF-8 text" in result.output
    assert "Re-open the editor to fix it?" in result.output
    assert "Traceback" not in result.output
    assert (folder / "project.json").read_bytes() == before


def test_invalid_edit_can_be_fixed_by_reopening(edit_project):
    folder = edit_project("partitions:0", "partitions:4")
    result = runner.invoke(app, ["edit", str(folder)], input="y\n")
    assert result.exit_code == 0, result.output
    assert "not a valid project" in result.output
    assert open_project(folder).run.partitions == 4


def test_edit_reports_a_missing_editor(edit_project, monkeypatch):
    folder = edit_project("noop")
    monkeypatch.setattr(project_cmds, "editor_command", lambda: ["definitely-not-an-editor-xyz"])
    result = runner.invoke(app, ["edit", str(folder)])
    assert result.exit_code == 1
    assert "Error: Cannot start editor" in result.output


def test_editor_command_from_environment(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "code --wait")
    assert project_cmds.editor_command() == ["code", "--wait"]
    monkeypatch.setenv("VISUAL", "vim")
    assert project_cmds.editor_command() == ["vim"]
    monkeypatch.delenv("VISUAL")
    monkeypatch.delenv("EDITOR")
    assert project_cmds.editor_command() == (["notepad"] if sys.platform == "win32" else ["nano"])


def test_a_freestream_edit_that_changes_the_altitude_label_rebuilds_case_names(edit_project):
    folder = edit_project("altitude:11")
    project = open_project(folder)
    project.sweep.naming.include_altitude = True
    update_sweep(project, alpha=[0.0])  # rebuild the names with the label in them
    save_project(folder, project)
    result = runner.invoke(app, ["edit", str(folder)])
    assert result.exit_code == 0, result.output
    assert "cases rebuilt" in result.output
    assert [c.name for c in open_project(folder).cases] == ["M0p8_11km_a0_b0"]

import json

from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.settings import load_settings, settings_path

runner = CliRunner()


def test_settings_prints_path_and_defaults():
    result = runner.invoke(app, ["settings"])
    assert result.exit_code == 0, result.output
    assert str(settings_path()) in result.output
    assert "backend = local" in result.output
    assert "slurm.shared_root = '/data'" in result.output
    assert "slurm.partitions.node2.default_ntasks = 48" in result.output


def test_settings_set_saves():
    result = runner.invoke(app, ["settings", "set", "slurm.partitions.node2.default_ntasks", "32"])
    assert result.exit_code == 0, result.output
    assert "Saved" in result.output
    result = runner.invoke(app, ["settings", "set", "backend", "slurm"])
    assert result.exit_code == 0, result.output
    settings, _ = load_settings()
    assert settings.backend == "slurm"
    assert settings.slurm.partition("node2").default_ntasks == 32


def test_settings_set_rejects_bad_values():
    result = runner.invoke(app, ["settings", "set", "slurm.default_time_limit", "soon"])
    assert result.exit_code == 1
    assert "time limit" in result.output
    result = runner.invoke(app, ["settings", "set", "slurm.nope", "1"])
    assert result.exit_code == 1
    assert "Unknown setting" in result.output
    assert not settings_path().exists()


def test_settings_warns_about_a_broken_file():
    settings_path().parent.mkdir(parents=True)
    settings_path().write_text(json.dumps({"backend": "pbs"}))
    result = runner.invoke(app, ["settings"])
    assert result.exit_code == 0
    assert "Warning" in result.output and "default" in result.output

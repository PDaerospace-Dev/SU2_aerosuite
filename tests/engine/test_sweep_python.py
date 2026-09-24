"""The sweep script must run under the system Python (which imports SU2), not AeroSuite's env."""
import os
import sys
from pathlib import Path

from aerosuite.engine.jobs.runner import is_aerosuite_python, resolve_sweep_python, sweep_environment

BIN = "Scripts" if sys.platform == "win32" else "bin"


def _fake_executable(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + ".exe" if sys.platform == "win32" else name)
    path.write_text("")
    path.chmod(0o755)
    return path


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def test_sweep_environment_drops_env_bin_and_virtual_env(monkeypatch, tmp_path):
    env_bin = Path(sys.prefix) / BIN
    other = tmp_path / "system-bin"
    other.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join([str(env_bin), str(other)]))
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    env = sweep_environment()
    assert "VIRTUAL_ENV" not in env
    entries = [_norm(p) for p in env["PATH"].split(os.pathsep) if p]
    assert _norm(env_bin) not in entries
    assert _norm(other) in entries
    assert os.environ.get("VIRTUAL_ENV") == sys.prefix  # the process environment is untouched


def test_resolve_sweep_python_passes_paths_through():
    assert resolve_sweep_python(sys.executable) == sys.executable
    assert resolve_sweep_python("some/dir/python3") == "some/dir/python3"


def test_resolve_sweep_python_skips_aerosuite_env(monkeypatch, tmp_path):
    fake_prefix = tmp_path / "env"
    in_env = _fake_executable(fake_prefix / BIN, "fakepy")
    outside = _fake_executable(tmp_path / "system-bin", "fakepy")
    monkeypatch.setattr(sys, "prefix", str(fake_prefix))
    monkeypatch.setenv("PATH", os.pathsep.join([str(in_env.parent), str(outside.parent)]))
    assert _norm(resolve_sweep_python("fakepy")) == _norm(outside)


def test_resolve_sweep_python_not_found_returns_name(monkeypatch, tmp_path):
    fake_prefix = tmp_path / "env"
    in_env = _fake_executable(fake_prefix / BIN, "fakepy")
    monkeypatch.setattr(sys, "prefix", str(fake_prefix))
    monkeypatch.setenv("PATH", str(in_env.parent))
    assert resolve_sweep_python("fakepy") == "fakepy"


def test_is_aerosuite_python(tmp_path):
    assert is_aerosuite_python(sys.executable)
    assert not is_aerosuite_python(str(_fake_executable(tmp_path, "python3")))

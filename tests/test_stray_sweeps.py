"""The leak check of tests/conftest.py: it finds a fake sweep by the temp folder in its command line."""
import subprocess
import sys
from pathlib import Path

FAKE_SWEEP = Path(__file__).resolve().parent / "fixtures" / "fake_sweep.py"


def _hung_sweep(folder):
    """A fake sweep started outside any job (no record, no wrapper), hanging on its first case."""
    configs = folder / "configs"
    configs.mkdir(parents=True)
    (configs / "fake_plan.json").write_text('{"cases": {"a": "hang"}}')
    control = configs / "run_control.txt"
    control.write_text("a.cfg, none\n")
    proc = subprocess.Popen(
        [sys.executable, str(FAKE_SWEEP), "-d", str(configs), "-c", str(control)],
        cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
    )
    proc.stdin.write(b"yes\n")
    proc.stdin.close()
    return proc


def test_a_running_fake_sweep_is_found_only_under_its_own_folder(tmp_path, stray_sweeps):
    mine, other = tmp_path / "mine", tmp_path / "other"
    other.mkdir()
    proc = _hung_sweep(mine)
    try:
        assert [p.pid for p in stray_sweeps(mine)] == [proc.pid]
        assert [p.pid for p in stray_sweeps(tmp_path)] == [proc.pid]
        assert stray_sweeps(other) == []
    finally:
        proc.kill()
        proc.wait()
    assert stray_sweeps(tmp_path) == []

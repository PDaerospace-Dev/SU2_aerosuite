"""The lock other programs honour: a state file's read-change-save cannot be undone by another program's."""
import json
import multiprocessing
import subprocess
import sys
import time

import pytest

from aerosuite.engine.jobs.runner import CaseState, JobRecord
from aerosuite.engine.jobs.store import annotate_job, load_job, save_job
from aerosuite.engine.locking import LockError, file_lock

HOLD = """
import sys, time
from pathlib import Path
from aerosuite.engine.locking import file_lock
with file_lock(Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(float(sys.argv[2]))
"""


def _hold(target, seconds):
    """Another program holding the lock of `target` for `seconds`."""
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(target), str(seconds)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_another_program_waits_for_the_lock(tmp_path):
    target = tmp_path / "state.json"
    proc = _hold(target, 0.6)
    started = time.monotonic()
    with file_lock(target):
        waited = time.monotonic() - started
    proc.wait()
    assert waited > 0.3


def test_a_lock_held_too_long_is_an_error_that_names_the_file(tmp_path):
    target = tmp_path / "state.json"
    proc = _hold(target, 3)
    with pytest.raises(LockError, match="state.json is in use by another AeroSuite program"):
        with file_lock(target, timeout=0.2):
            pass
    proc.kill()
    proc.wait()
    with file_lock(target, timeout=0.5):  # the system dropped the lock with its program
        pass


def test_the_same_thread_can_take_its_lock_again(tmp_path):
    with file_lock(tmp_path / "state.json"):
        with file_lock(tmp_path / "state.json", timeout=0.2):
            pass


def _count(args):
    path, times = args
    from pathlib import Path
    from aerosuite.engine.locking import file_lock
    for _ in range(times):
        with file_lock(Path(path)):
            value = json.loads(Path(path).read_text())["n"]
            Path(path).write_text(json.dumps({"n": value + 1}))


def test_no_update_is_lost_between_programs(tmp_path):
    target = tmp_path / "count.json"
    target.write_text('{"n": 0}')
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        pool.map(_count, [(str(target), 25)] * 4)
    assert json.loads(target.read_text())["n"] == 100


def _job(**fields):
    return JobRecord(id="j", backend="local", cases=["a"], log_path="jobs/j.log", **fields)


def test_a_runners_save_keeps_a_note_edited_meanwhile(tmp_path):
    """The poller read the record, the note was edited from another program, the poller saves its statuses."""
    save_job(tmp_path, _job(note="first"))
    stale = load_job(tmp_path, "j")
    annotate_job(tmp_path, "j", note="#2nd_order", outcome="fine")
    stale.case_status = {"a": CaseState.CONVERGED}
    save_job(tmp_path, stale)
    saved = load_job(tmp_path, "j")
    assert (saved.note, saved.outcome, saved.case_status) == ("#2nd_order", "fine", {"a": CaseState.CONVERGED})
    assert stale.note == "#2nd_order"  # and the runner's copy is current again

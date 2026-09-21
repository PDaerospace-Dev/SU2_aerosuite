import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import psutil
import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.runner import (
    BUNDLED_SWEEP_SCRIPT,
    CaseState,
    JobRecord,
    JobState,
    new_job_id,
    sweep_script_path,
)
from aerosuite.engine.jobs.store import (
    active_lock,
    clear_lock,
    kill_tree,
    list_jobs,
    load_job,
    process_alive,
    read_lock,
    save_job,
    write_lock,
)
from aerosuite.engine.models import RunSettings


def _job(job_id="j1", created=None):
    return JobRecord(
        id=job_id, backend="local", cases=["a"], log_path=f"jobs/{job_id}.log",
        created=created or datetime.now(), case_status={"a": CaseState.PENDING},
    )


def test_job_round_trip_and_listing(tmp_path):
    old = _job("old", datetime.now() - timedelta(hours=1))
    new = _job("new")
    new.state = JobState.RUNNING
    save_job(tmp_path, old)
    save_job(tmp_path, new)
    assert load_job(tmp_path, "new") == new
    assert [j.id for j in list_jobs(tmp_path)] == ["new", "old"]
    assert new.is_active and not _job().model_copy(update={"state": JobState.DONE}).is_active


def test_load_missing_job(tmp_path):
    with pytest.raises(JobError):
        load_job(tmp_path, "nope")


def test_ids_and_script_path():
    assert new_job_id() != new_job_id()
    assert sweep_script_path(RunSettings()) == BUNDLED_SWEEP_SCRIPT
    assert BUNDLED_SWEEP_SCRIPT.is_file()
    assert str(sweep_script_path(RunSettings(sweep_script="/x/s.py"))).endswith("s.py")


def test_process_alive():
    me = psutil.Process()
    assert process_alive(os.getpid(), me.create_time())
    assert not process_alive(os.getpid(), me.create_time() - 1000)  # pid reused by another process
    assert not process_alive(2**22 + 12345, 0.0)


def test_lock_lifecycle(tmp_path):
    me = psutil.Process()
    write_lock(tmp_path, "j1", os.getpid(), me.create_time())
    with pytest.raises(JobError):
        write_lock(tmp_path, "j2", os.getpid(), me.create_time())
    assert active_lock(tmp_path)["job_id"] == "j1"
    clear_lock(tmp_path, "other-job")
    assert read_lock(tmp_path) is not None
    clear_lock(tmp_path, "j1")
    assert read_lock(tmp_path) is None


def test_stale_lock_is_removed(tmp_path):
    write_lock(tmp_path, "j1", os.getpid(), 0.0)  # start time does not match: stale
    assert active_lock(tmp_path) is None
    assert read_lock(tmp_path) is None


def test_corrupt_lock_is_removed(tmp_path):
    (tmp_path / ".lock").write_text("garbage", encoding="utf-8")
    assert active_lock(tmp_path) is None
    assert read_lock(tmp_path) is None


def test_process_alive_rejects_nonpositive_pid():
    assert not process_alive(-1, 0.0)
    assert not process_alive(0, 0.0)


def test_kill_tree_kills_children(tmp_path):
    code = (
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    parent = psutil.Process(proc.pid)
    deadline = time.monotonic() + 10
    while not parent.children() and time.monotonic() < deadline:
        time.sleep(0.05)
    children = parent.children(recursive=True)
    assert children
    tracked = [(p.pid, p.create_time()) for p in [parent, *children]]
    kill_tree(proc.pid)
    proc.wait(timeout=10)
    assert not any(process_alive(pid, ct) for pid, ct in tracked)


def test_kill_tree_on_dead_pid_is_harmless():
    kill_tree(2**22 + 12345)


def test_save_job_os_error_is_a_job_error(tmp_path):
    (tmp_path / "jobs").write_text("a file where the jobs folder should be")
    with pytest.raises(JobError, match="Cannot save job"):
        save_job(tmp_path, _job())


def test_process_we_cannot_inspect_counts_as_alive(monkeypatch):
    """A live job owned by another user must not have its lock cleared."""
    from aerosuite.engine.jobs import store

    class Denied:
        def __init__(self, pid):
            raise psutil.AccessDenied(pid)

    monkeypatch.setattr(store.psutil, "Process", Denied)
    assert process_alive(4242, 0.0)

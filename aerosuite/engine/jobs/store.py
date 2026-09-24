"""Job persistence, the per-project lock, and process helpers (psutil, all platforms)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import psutil
from pydantic import ValidationError

from ..errors import JobError
from .runner import JobRecord

JOBS_DIR = "jobs"
LOCK_FILE = ".lock"


def _job_file(project_dir: Path, job_id: str) -> Path:
    return Path(project_dir) / JOBS_DIR / f"{job_id}.json"


def save_job(project_dir: Path, job: JobRecord) -> None:
    path = _job_file(project_dir, job.id)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise JobError(f"Cannot save job record {path}: {exc}") from exc


def load_job(project_dir: Path, job_id: str) -> JobRecord:
    path = _job_file(project_dir, job_id)
    try:
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise JobError(f"No job {job_id} in {project_dir}") from None
    except (OSError, ValidationError) as exc:
        raise JobError(f"Cannot read job record {path}: {exc}") from exc


def list_jobs(project_dir: Path) -> list[JobRecord]:
    """All jobs of a project, newest first."""
    jobs_dir = Path(project_dir) / JOBS_DIR
    jobs = [load_job(project_dir, p.stem) for p in jobs_dir.glob("*.json")] if jobs_dir.is_dir() else []
    return sorted(jobs, key=lambda job: job.created, reverse=True)


def process_alive(pid: int, create_time: float) -> bool:
    """True if `pid` is running and is the same process (start time matches). Zombies count as dead.

    A process we may not inspect (AccessDenied) counts as alive: clearing the lock of
    a live job would let a second job start on top of it.
    """
    if pid <= 0:
        return False
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - create_time) > 1.0:
            return False
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.AccessDenied:
        return True
    except (psutil.NoSuchProcess, ValueError):
        return False


def _running(proc: psutil.Process) -> bool:
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_gone(procs: list[psutil.Process], timeout: float) -> list[psutil.Process]:
    deadline = time.monotonic() + timeout
    alive = list(procs)
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _running(p)]
        if alive:
            time.sleep(0.05)
    return alive


def kill_tree(pid: int, timeout: float = 5.0) -> None:
    """Terminate a process and all its descendants (mpirun, SU2 ranks); kill survivors."""
    try:
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for proc in procs:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    for proc in _wait_gone(procs, timeout):
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    _wait_gone(procs, timeout)


def write_lock(project_dir: Path, job_id: str, pid: int, create_time: float) -> None:
    path = Path(project_dir) / LOCK_FILE
    try:
        with open(path, "x", encoding="utf-8") as fh:
            json.dump({"job_id": job_id, "pid": pid, "create_time": create_time}, fh)
    except FileExistsError:
        raise JobError("A job is already running for this project") from None


def read_lock(project_dir: Path) -> Optional[dict]:
    path = Path(project_dir) / LOCK_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return {"job_id": "?", "pid": -1, "create_time": 0.0}  # unreadable: treated as stale


def clear_lock(project_dir: Path, job_id: Optional[str] = None) -> None:
    """Remove the lock; with job_id, only if the lock belongs to that job."""
    lock = read_lock(project_dir)
    if lock is None or (job_id is not None and lock.get("job_id") != job_id):
        return
    try:
        (Path(project_dir) / LOCK_FILE).unlink()
    except FileNotFoundError:
        pass


def active_lock(project_dir: Path) -> Optional[dict]:
    """The lock if its process is still alive; a stale lock is removed and None returned."""
    lock = read_lock(project_dir)
    if lock is None:
        return None
    if process_alive(int(lock.get("pid", -1)), float(lock.get("create_time", 0.0))):
        return lock
    clear_lock(project_dir)
    return None

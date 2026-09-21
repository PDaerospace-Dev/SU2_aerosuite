"""LocalRunner: runs the sweep script on this machine as a detached process.

All state is derived from disk and the OS (process liveness, the job log's
"Running Case i/n: <cfg>" banners, runs/<case>/error.log and history.csv), so a
fresh LocalRunner — e.g. after a server restart — reports the same state.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psutil

from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE
from ..errors import JobError
from ..models import Project
from ..results import HISTORY_FILE, check_convergence, read_history
from .runner import FINAL_CASE_STATES, CaseState, JobRecord, JobState, new_job_id, sweep_script_path
from .store import JOBS_DIR, active_lock, clear_lock, kill_tree, process_alive, save_job, write_lock

RUNS_DIR = "runs"
BANNER_RE = re.compile(r"Running Case\s+\d+/\d+:\s+(\S+?)\.cfg")
TAIL_LINES = 50


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _case_log_segment(log_text: str, name: str) -> str:
    """The part of the job log between this case's banner and the next one."""
    start = re.search(rf"Running Case\s+\d+/\d+:\s+{re.escape(name)}\.cfg", log_text)
    if not start:
        return ""
    rest = log_text[start.start():]
    following = BANNER_RE.search(rest, 1)
    return rest[: following.start()] if following else rest


class LocalRunner:
    backend = "local"

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        # job id -> (bytes of the log already scanned, case names whose banner was seen)
        self._scan: dict[str, tuple[int, list[str]]] = {}

    # -- Runner interface ---------------------------------------------------

    def submit(self, project_dir: Path, project: Project) -> JobRecord:
        project_dir = Path(project_dir).resolve()
        configs = project_dir / CONFIGS_DIR
        control = configs / RUN_CONTROL_FILE
        if not control.is_file():
            raise JobError(f"{control} not found; generate configs first")
        if active_lock(project_dir):
            raise JobError("A job is already running for this project")

        job_id = new_job_id()
        job = JobRecord(
            id=job_id,
            backend=self.backend,
            cases=[case.name for case in project.cases],
            log_path=f"{JOBS_DIR}/{job_id}.log",
            case_status={case.name: CaseState.PENDING for case in project.cases},
        )
        (project_dir / JOBS_DIR).mkdir(exist_ok=True)
        runs = project_dir / RUNS_DIR
        runs.mkdir(exist_ok=True)

        cmd = [
            project.run.sweep_python, str(sweep_script_path(project.run)),
            "-d", str(configs), "-c", str(control), "-n", str(project.run.partitions),
        ]
        if project.run.initial_restart:
            cmd += ["-r", project.run.initial_restart]
        if sys.platform == "win32":
            detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            detach = {"start_new_session": True}  # closing AeroSuite must not kill SU2
        # aoa_sweep_v8.py prints its "Running Case" banners without flushing, so with
        # stdout redirected to a file the child block-buffers; force unbuffered output
        # so the log (and therefore refresh()) reflects progress promptly.
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            with open(project_dir / job.log_path, "wb") as log:
                proc = subprocess.Popen(
                    cmd, cwd=runs, stdin=subprocess.PIPE, stdout=log,
                    stderr=subprocess.STDOUT, env=env, **detach,
                )
        except OSError as exc:
            raise JobError(f"Cannot start the sweep script ({' '.join(cmd)}): {exc}") from exc

        try:  # the script asks "Proceed with this execution plan? (yes/no)"
            proc.stdin.write(b"yes\n")
            proc.stdin.close()
        except OSError:
            pass
        try:
            create_time = psutil.Process(proc.pid).create_time()
        except psutil.NoSuchProcess:
            create_time = 0.0

        job.backend_ref = {"pid": proc.pid, "create_time": create_time}
        job.state = JobState.RUNNING
        try:
            write_lock(project_dir, job.id, proc.pid, create_time)
        except JobError:
            kill_tree(proc.pid)
            proc.wait()
            raise
        self._procs[job.id] = proc
        save_job(project_dir, job)
        return job

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        alive = self._alive(job)
        self._update_cases(project_dir, job, alive)
        if not alive:
            self._finish(project_dir, job)
        save_job(project_dir, job)
        return job

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        alive = self._alive(job)
        self._update_cases(project_dir, job, alive)  # mark the case that is running now
        if alive:
            kill_tree(job.backend_ref["pid"])
        proc = self._procs.pop(job.id, None)
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for name, state in job.case_status.items():
            if state in (CaseState.PENDING, CaseState.RUNNING):
                job.case_status[name] = CaseState.CANCELLED
        job.state = JobState.CANCELLED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(job.id, None)
        save_job(project_dir, job)
        return job

    # -- internals ------------------------------------------------------------

    def _alive(self, job: JobRecord) -> bool:
        proc = self._procs.get(job.id)
        if proc is not None:  # we started it: poll() also reaps it
            if proc.poll() is None:
                return True
            self._procs.pop(job.id, None)
            return False
        ref = job.backend_ref
        return process_alive(int(ref.get("pid", -1)), float(ref.get("create_time", 0.0)))

    def _started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        """Case names whose banner is in the log, reading only bytes not scanned yet."""
        offset, started = self._scan.get(job.id, (0, []))
        try:
            with open(project_dir / job.log_path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except FileNotFoundError:
            return started
        end = chunk.rfind(b"\n")
        if end >= 0:
            text = chunk[: end + 1].decode("utf-8", errors="replace")
            started = started + BANNER_RE.findall(text)
            offset += end + 1
        self._scan[job.id] = (offset, started)
        return started

    def _update_cases(self, project_dir: Path, job: JobRecord, alive: bool) -> None:
        started = self._started_cases(project_dir, job)
        current = started[-1] if (alive and started) else None
        runs = project_dir / RUNS_DIR
        for name in job.cases:
            if job.case_status.get(name) in FINAL_CASE_STATES:
                continue
            if name not in started:
                job.case_status[name] = CaseState.PENDING
            elif name == current:
                job.case_status[name] = CaseState.RUNNING
            else:
                self._evaluate_finished_case(project_dir, job, runs / name, name)

    def _evaluate_finished_case(self, project_dir: Path, job: JobRecord, folder: Path, name: str) -> None:
        error_log = folder / "error.log"
        if error_log.is_file():
            segment = _case_log_segment(_read_text(project_dir / job.log_path), name)
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = _tail(_read_text(error_log) + "\n" + segment)
            return
        history = folder / HISTORY_FILE
        df = read_history(history) if history.is_file() else None
        if df is None or df.empty:
            segment = _case_log_segment(_read_text(project_dir / job.log_path), name)
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = "No history.csv was written.\n" + _tail(segment)
            return
        converged, _message = check_convergence(df)
        job.case_status[name] = CaseState.CONVERGED if converged else CaseState.UNCONVERGED

    def _finish(self, project_dir: Path, job: JobRecord) -> None:
        log_tail = _tail(_read_text(project_dir / job.log_path))
        for name, state in job.case_status.items():
            if state is CaseState.PENDING:
                job.case_status[name] = CaseState.FAILED
                job.failure_tail[name] = "The sweep process exited before this case started.\n" + log_tail
        ok = {CaseState.CONVERGED, CaseState.UNCONVERGED}
        job.state = JobState.DONE if all(s in ok for s in job.case_status.values()) else JobState.FAILED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(job.id, None)

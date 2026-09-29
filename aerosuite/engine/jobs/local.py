"""LocalRunner: runs the sweep script on this machine as a detached process.

All state is derived from disk and the OS (process liveness, the job log's
"Running Case i/n: <cfg>" banners, runs/<case>/error.log and history.csv, and the
exit code sweep_wrapper.py writes to jobs/<id>.exit), so a fresh LocalRunner — e.g.
after a server restart — reports the same state.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import psutil

from ..cfg import RUN_CONTROL_FILE
from ..errors import JobError
from ..models import Project
from ..restarts import RUNS_DIR
from ..results import HISTORY_FILE, check_convergence, read_history
from .plan import RESTART_DIR, prepare_job
from .runner import (
    FINAL_CASE_STATES,
    CaseState,
    JobRecord,
    JobState,
    new_job_id,
    resolve_sweep_python,
    sweep_environment,
    sweep_script_path,
)
from .store import JOBS_DIR, active_lock, clear_lock, kill_tree, load_job, process_alive, save_job, write_lock

BANNER_RE = re.compile(r"Running Case\s+\d+/\d+:\s+(\S+?)\.cfg")
TAIL_LINES = 50
WRAPPER = Path(__file__).resolve().parent / "sweep_wrapper.py"


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


def control_cases(control: Path) -> list[str]:
    """Case names in run_control.txt order: first field of each line, ".cfg" stripped."""
    try:
        text = control.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise JobError(f"Cannot read {control}: {exc}") from exc
    names = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split(",")[0].strip()
        names.append(name[:-4] if name.endswith(".cfg") else name)
    return names


def _remove_restart_copies(project_dir: Path, job: JobRecord) -> None:
    """Delete jobs/<id>/restart/ (solutions set aside for this job): nothing reads them any more."""
    shutil.rmtree(project_dir / JOBS_DIR / job.id / RESTART_DIR, ignore_errors=True)


def _discard(project_dir: Path, job: JobRecord) -> None:
    """Remove a job that never got going: its jobs/<id>/ folder, its log and any exit code."""
    shutil.rmtree(project_dir / JOBS_DIR / job.id, ignore_errors=True)
    for name in (job.log_path, f"{JOBS_DIR}/{job.id}.exit"):
        try:
            (project_dir / name).unlink()
        except OSError:
            pass


class LocalRunner:
    backend = "local"

    def __init__(self) -> None:
        # Keyed by (project folder, job id): job names are unique only within a project.
        self._procs: dict[tuple[Path, str], subprocess.Popen] = {}
        # -> (bytes of the log already scanned, case names whose banner was seen)
        self._scan: dict[tuple[Path, str], tuple[int, list[str]]] = {}

    # -- Runner interface ---------------------------------------------------

    def submit(self, project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None,
               continue_cases: Iterable[str] = ()) -> JobRecord:
        """Run `cases` (default: every case) from the job's own configs (see jobs/plan.py)."""
        project_dir = Path(project_dir).resolve()
        if active_lock(project_dir):
            raise JobError("A job is already running for this project")
        runs = project_dir / RUNS_DIR
        for folder in (project_dir / JOBS_DIR, runs):
            try:
                folder.mkdir(exist_ok=True)
            except OSError as exc:
                raise JobError(f"Cannot create {folder}: {exc}") from exc

        python = resolve_sweep_python(project.run.sweep_python)
        if shutil.which(python, path=sweep_environment().get("PATH", "")) is None and not Path(python).is_file():
            raise JobError(f"Cannot start the sweep script: Python not found: {project.run.sweep_python}")
        selected = [case.name for case in project.cases] if cases is None else list(cases)
        job_id = new_job_id(project_dir)
        configs = prepare_job(project_dir, project, job_id, selected, continue_cases)
        control = configs / RUN_CONTROL_FILE
        names = control_cases(control)
        job = JobRecord(
            id=job_id,
            backend=self.backend,
            cases=names,
            log_path=f"{JOBS_DIR}/{job_id}.log",
            case_status={name: CaseState.PENDING for name in names},
        )
        exit_file = f"{JOBS_DIR}/{job_id}.exit"
        sweep = [
            python, str(sweep_script_path(project.run)),
            "-d", str(configs), "-c", str(control), "-n", str(project.run.partitions),
        ]
        # -I: the sweep environment's PYTHONPATH (SU2's) must not reach AeroSuite's own Python.
        cmd = [sys.executable, "-I", str(WRAPPER), str(project_dir / exit_file), *sweep]
        if sys.platform == "win32":
            detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            detach = {"start_new_session": True}  # closing AeroSuite must not kill SU2
        # aoa_sweep_v8.py prints its "Running Case" banners without flushing, so with
        # stdout redirected to a file the child block-buffers; force unbuffered output
        # so the log (and therefore refresh()) reflects progress promptly.
        env = {**sweep_environment(), "PYTHONUNBUFFERED": "1"}
        try:
            with open(project_dir / job.log_path, "wb") as log:
                proc = subprocess.Popen(
                    cmd, cwd=runs, stdin=subprocess.PIPE, stdout=log,
                    stderr=subprocess.STDOUT, env=env, **detach,
                )
        except OSError as exc:
            _discard(project_dir, job)
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

        job.backend_ref = {"pid": proc.pid, "create_time": create_time, "exit_file": exit_file}
        job.state = JobState.RUNNING
        try:
            write_lock(project_dir, job.id, proc.pid, create_time)
        except JobError:  # another submit won the lock after our check: undo this one
            kill_tree(proc.pid)
            proc.wait()
            _discard(project_dir, job)
            raise
        self._procs[_key(project_dir, job)] = proc
        save_job(project_dir, job)
        return job

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        # The caller's copy may be stale: another process (the web, `aerosuite cancel`) may have
        # cancelled or finished the job since. Never overwrite that with this copy's view.
        try:
            job = load_job(project_dir, job.id)
        except JobError:
            pass  # unreadable or gone: carry on with the caller's copy
        if not job.is_active:
            return job
        alive = self._alive(project_dir, job)
        self._update_cases(project_dir, job, alive)
        if not alive:
            self._finish(project_dir, job)
        save_job(project_dir, job)
        return job

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        alive = self._alive(project_dir, job)
        self._update_cases(project_dir, job, alive)  # mark the case that is running now
        if not alive:  # the sweep already ended: report its real outcome, as refresh() would
            self._finish(project_dir, job)
            save_job(project_dir, job)
            return job
        kill_tree(job.backend_ref["pid"])
        proc = self._procs.pop(_key(project_dir, job), None)
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for name, state in job.case_status.items():
            if state in (CaseState.PENDING, CaseState.RUNNING):
                job.case_status[name] = CaseState.CANCELLED
        if "exit_file" in job.backend_ref:  # in case the script ended as the wrapper was stopped
            (project_dir / job.backend_ref["exit_file"]).unlink(missing_ok=True)
        job.state = JobState.CANCELLED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(_key(project_dir, job), None)
        _remove_restart_copies(project_dir, job)
        save_job(project_dir, job)
        return job

    # -- internals ------------------------------------------------------------

    def _alive(self, project_dir: Path, job: JobRecord) -> bool:
        key = _key(project_dir, job)
        proc = self._procs.get(key)
        if proc is not None:  # we started it: poll() also reaps it
            if proc.poll() is None:
                return True
            self._procs.pop(key, None)
            return False
        ref = job.backend_ref
        return process_alive(int(ref.get("pid", -1)), float(ref.get("create_time", 0.0)))

    def started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        """Case names whose banner is in the log, reading only bytes not scanned yet.

        Cached incrementally per project and job: a finished job's log never changes again, so
        once fully scanned it is not re-read. Safe to call for any job, active or not.
        """
        key = _key(project_dir, job)
        offset, started = self._scan.get(key, (0, []))
        try:
            with open(Path(project_dir) / job.log_path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except FileNotFoundError:
            return started
        end = chunk.rfind(b"\n")
        if end >= 0:
            text = chunk[: end + 1].decode("utf-8", errors="replace")
            started = started + BANNER_RE.findall(text)
            offset += end + 1
        self._scan[key] = (offset, started)
        return started

    def _update_cases(self, project_dir: Path, job: JobRecord, alive: bool) -> None:
        started = self.started_cases(project_dir, job)
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
            # error.log first, so SU2 output can never push the reason out of the tail
            job.failure_tail[name] = _read_text(error_log).rstrip() + "\n" + _tail(segment)
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
        ended = "The sweep script exited"
        if "exit_file" in job.backend_ref:  # jobs started before the wrapper have no exit code
            job.exit_code = _take_exit_code(project_dir / job.backend_ref["exit_file"])
            if job.exit_code != 0:
                ended = f"The sweep script stopped ({_reason(job.exit_code)})"
                self._fail_interrupted_case(project_dir, job)
        for name, state in job.case_status.items():
            if state is CaseState.PENDING:
                job.case_status[name] = CaseState.FAILED
                job.failure_tail[name] = f"{ended} before this case started.\n" + log_tail
        ok = {CaseState.CONVERGED, CaseState.UNCONVERGED}
        job.state = JobState.DONE if all(s in ok for s in job.case_status.values()) else JobState.FAILED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(_key(project_dir, job), None)
        _remove_restart_copies(project_dir, job)


    def _fail_interrupted_case(self, project_dir: Path, job: JobRecord) -> None:
        """The sweep ended abnormally: the last case it started stopped part-way (unless it converged)."""
        started = [name for name in self.started_cases(project_dir, job) if name in job.case_status]
        if not started or job.case_status[started[-1]] is CaseState.CONVERGED:
            return
        name = started[-1]
        detail = job.failure_tail.get(name) or _tail(_case_log_segment(_read_text(project_dir / job.log_path), name))
        job.case_status[name] = CaseState.FAILED
        job.failure_tail[name] = f"The sweep stopped during this case ({_reason(job.exit_code)}).\n" + detail


def _take_exit_code(path: Path) -> Optional[int]:
    """The code sweep_wrapper.py wrote (the file is then removed: the job record keeps it), or None."""
    try:
        code = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return code


def _reason(code: Optional[int]) -> str:
    """Why an abnormal sweep ended: 'exit code 1', 'killed by signal 9', or 'it was killed' (no code)."""
    if code is None:
        return "it was killed"
    return f"killed by signal {-code}" if code < 0 else f"exit code {code}"  # < 0: POSIX signal


def _key(project_dir: Path, job: JobRecord) -> tuple[Path, str]:
    return Path(project_dir).resolve(), job.id

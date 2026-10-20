"""The web server's single view of jobs.

One LocalRunner for the whole server (it keeps the processes it started so it can reap them),
an active local job refreshed at most every REFRESH_SECONDS per project however many tabs ask, and
one incremental history buffer per (project, job, case), plus one per opened file (for the
Monitor page's "Open file..."). Slurm jobs are never refreshed here: the server's poller
(slurm_watch.py) updates their records, and state() only tells it which jobs to watch.
No NiceGUI and no pandas import here.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..engine.errors import JobError
from ..engine.jobs.executors import SlurmOptions, backend_of, runner_for
from ..engine.jobs.local import RUNS_DIR, LocalRunner
from ..engine.jobs.overview import CaseOverview, case_overview
from ..engine.jobs.runner import FINAL_CASE_STATES, CaseState, JobRecord
from ..engine.models import Project
from ..engine.results import HISTORY_FILE, HistoryBuffer
from .slurm_watch import WATCH, SlurmWatch

REFRESH_SECONDS = 2.0
LOG_TAIL_LINES = 40
LOG_TAIL_BYTES = 64 * 1024
FILE_BUFFER_LIMIT = 8  # opened-file history buffers kept; least-recently-used evicted past this


@dataclass(frozen=True)
class JobView:
    latest: Optional[JobRecord]  # the newest job, active or not
    active: Optional[JobRecord]  # the running job, if any
    overview: CaseOverview


@dataclass(frozen=True)
class JobProgress:
    finished: int
    total: int
    current: Optional[str]  # the case running now, if any

    @property
    def text(self) -> str:
        text = f"{self.finished} / {self.total}"
        return f"{text} · {self.current}" if self.current else text

    @property
    def percent(self) -> int:
        return round(100 * self.finished / self.total) if self.total else 0


def job_progress(view: JobView) -> Optional[JobProgress]:
    """How far the active job is, for the top bar's job indicator; None when no job is active."""
    job = view.active
    if job is None:
        return None
    finished = sum(1 for name in job.cases if job.case_status.get(name) in FINAL_CASE_STATES)
    current = next((name for name in job.cases if job.case_status.get(name) is CaseState.RUNNING), None)
    return JobProgress(finished, len(job.cases), current)


class JobWatcher:
    def __init__(self, runner: Optional[LocalRunner] = None,
                 clock: Callable[[], float] = time.monotonic, slurm_runner=None,
                 slurm_watch: Optional[SlurmWatch] = None) -> None:
        self.runner = runner if runner is not None else LocalRunner()
        self._slurm_runner = slurm_runner
        self.slurm_watch = slurm_watch if slurm_watch is not None else WATCH
        self._clock = clock
        # One entry per project with an active job: (job_id, time of its last refresh).
        # Dropped as soon as the project has no active job, so this never grows past
        # the number of *currently* active jobs.
        self._refreshed: dict[Path, tuple[str, float]] = {}
        self._buffers: dict[tuple[Path, str, str], HistoryBuffer] = {}
        # Most-recently-used last; evicted past FILE_BUFFER_LIMIT so opening many different
        # files over a session does not grow this without bound.
        self._file_buffers: "OrderedDict[Path, HistoryBuffer]" = OrderedDict()
        # Projects whose job is being cancelled (in a worker thread, see cancel()): not refreshed meanwhile.
        self._cancelling: set[Path] = set()

    @property
    def slurm_runner(self):
        return self._slurm_runner if self._slurm_runner is not None else runner_for("slurm")

    def runner_of(self, job: JobRecord):
        return self.slurm_runner if job.backend == "slurm" else self.runner

    def state(self, project_dir: Path, project: Project) -> JobView:
        directory = Path(project_dir).resolve()
        view = self._view(directory, project)
        latest = view.latest
        if latest is not None and latest.backend == "slurm" and (
                latest.is_active or self.slurm_runner.pending_stats(latest)):
            self.slurm_watch.track(directory, latest.id)  # the poller keeps its record current
        if view.active is not None and view.active.backend == "slurm":
            self._refreshed.pop(directory, None)
            return view
        if view.active is None:
            self._refreshed.pop(directory, None)
            return view
        if directory in self._cancelling:  # a refresh now could record the dying job as Failed
            return view
        now = self._clock()
        entry = self._refreshed.get(directory)
        # Refresh immediately for a newly active job (different id, or none seen yet),
        # otherwise at most once every REFRESH_SECONDS for the same job.
        if entry is None or entry[0] != view.active.id or now - entry[1] >= REFRESH_SECONDS:
            self._refreshed[directory] = (view.active.id, now)
            self.runner.refresh(directory, view.active)  # saves the job record
            view = self._view(directory, project)
            if view.active is None:
                self._refreshed.pop(directory, None)
        return view

    def _view(self, directory: Path, project: Project) -> JobView:
        overview = case_overview(directory, project)
        latest = overview.jobs[0] if overview.jobs else None
        active = next((job for job in overview.jobs if job.is_active), None)
        return JobView(latest, active, overview)

    def submit(self, project_dir: Path, project: Project, cases: Sequence[str],
               continue_cases: Iterable[str] = (), options: Optional[SlurmOptions] = None) -> JobRecord:
        directory = Path(project_dir).resolve()
        if backend_of(project) == "slurm":
            job = self.slurm_runner.submit(directory, project, cases=list(cases),
                                           continue_cases=list(continue_cases), options=options)
            self.slurm_watch.track(directory, job.id)
            return job
        return self.runner.submit(directory, project, cases=list(cases), continue_cases=list(continue_cases))

    def add_cases(self, project_dir: Path, project: Project, job_id: str, cases: Sequence[str],
                  continue_cases: Iterable[str] = (), options: Optional[SlurmOptions] = None) -> JobRecord:
        """Submit more cases inside the running Slurm job `job_id` (see SlurmRunner.add_cases)."""
        directory = Path(project_dir).resolve()
        job = next((job for job in self._view(directory, project).overview.jobs if job.id == job_id), None)
        if job is None or job.backend != "slurm":
            raise JobError(f"No Slurm job {job_id} in this project")
        job = self.slurm_runner.add_cases(directory, project, job, list(cases), list(continue_cases), options)
        self.slurm_watch.track(directory, job.id)
        return job

    def resubmit(self, project_dir: Path, project: Project, job_id: str, cases: Sequence[str],
                 options: Optional[SlurmOptions] = None) -> JobRecord:
        """Submit NODE_FAIL / OUT_OF_MEMORY cases of a Slurm job again (see SlurmRunner.resubmit)."""
        directory = Path(project_dir).resolve()
        job = next((job for job in self._view(directory, project).overview.jobs if job.id == job_id), None)
        if job is None or job.backend != "slurm":
            raise JobError(f"No Slurm job {job_id} in this project")
        job = self.slurm_runner.resubmit(directory, project, job, list(cases), options=options)
        self.slurm_watch.track(directory, job.id)
        return job

    def cancel(self, project_dir: Path, project: Project) -> Optional[JobRecord]:
        """Cancel the project's active job. Stopping SU2 can take ~20 s, so the web calls this in a worker
        thread (run.io_bound); meanwhile state() leaves the job alone and is_cancelling() is True."""
        directory = Path(project_dir).resolve()
        active = self._view(directory, project).active
        if active is None:
            return None
        self._cancelling.add(directory)
        try:
            return self.runner_of(active).cancel(directory, active)
        finally:
            self._cancelling.discard(directory)

    def is_cancelling(self, project_dir: Path) -> bool:
        return Path(project_dir).resolve() in self._cancelling

    def started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        """Case names whose "Running Case" banner is in `job`'s log (see LocalRunner.started_cases)."""
        directory = Path(project_dir).resolve()
        return self.runner_of(job).started_cases(directory, job)

    def case_log(self, project_dir: Path, job: JobRecord, case: str) -> Optional[Path]:
        """The file with `case`'s solver output in `job` (local: the job log; Slurm: its slurm-<id>.out)."""
        return self.runner_of(job).case_log(Path(project_dir).resolve(), job, case)

    def history(self, project_dir: Path, job_id: str, case: str):
        """Every history row of `case` written in job `job_id` so far (a DataFrame, maybe empty)."""
        directory = Path(project_dir).resolve()
        key = (directory, job_id, case)
        if key not in self._buffers:
            # A newer job for the same case replaces older buffers (they are never asked for again).
            for old in [k for k in self._buffers if k[0] == directory and k[2] == case]:
                del self._buffers[old]
            self._buffers[key] = HistoryBuffer(directory / RUNS_DIR / case / HISTORY_FILE)
        return self._buffers[key].read()

    def file_history(self, path: Path):
        """Every row of the history file at `path` read so far (a DataFrame, maybe empty).

        One incremental buffer per path (like `history()`, but keyed on the file itself rather
        than a job/case), least-recently-used evicted past FILE_BUFFER_LIMIT.
        """
        path = Path(path).resolve()
        buffer = self._file_buffers.pop(path, None)
        if buffer is None:
            buffer = HistoryBuffer(path)
        self._file_buffers[path] = buffer  # (re-)insert as most-recently-used
        while len(self._file_buffers) > FILE_BUFFER_LIMIT:
            self._file_buffers.popitem(last=False)
        return buffer.read()

    def log_tail(self, project_dir: Path, job: JobRecord, lines: int = LOG_TAIL_LINES,
                 max_bytes: int = LOG_TAIL_BYTES) -> Optional[str]:
        """The last `lines` lines of the job's log, reading at most `max_bytes`; None if unreadable."""
        return _tail_file(Path(project_dir) / job.log_path, lines, max_bytes)

    def solver_tail(self, project_dir: Path, job: JobRecord, lines: int = LOG_TAIL_LINES,
                    max_bytes: int = LOG_TAIL_BYTES) -> Optional[tuple[str, Path, str]]:
        """A Slurm job's solver output: (case, its slurm-<id>.out, last lines) of the case running now, else of the
        last one that started; None for a local job (its log already holds the solver output) or before any ran."""
        if job.backend != "slurm":
            return None
        started = self.started_cases(project_dir, job)
        running = [name for name in started if job.case_status.get(name) is CaseState.RUNNING]
        case = (running or started or [None])[-1]
        if case is None:
            return None
        path = self.case_log(project_dir, job, case)
        text = _tail_file(path, lines, max_bytes) if path is not None else None
        return None if text is None else (case, path, text)


def _tail_file(path: Path, lines: int, max_bytes: int) -> Optional[str]:
    """The last `lines` lines of `path`, reading at most `max_bytes`; None if unreadable."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - max_bytes))
            data = fh.read()
    except OSError:
        return None
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


WATCHER = JobWatcher()

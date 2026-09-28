"""The web server's single view of jobs.

One LocalRunner for the whole server (it keeps the processes it started so it can reap them),
an active job refreshed at most every REFRESH_SECONDS per project however many tabs ask, and
one incremental history buffer per (project, job, case), plus one per opened file (for the
Monitor page's "Open file..."). No NiceGUI and no pandas import here.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..engine.jobs.local import RUNS_DIR, LocalRunner
from ..engine.jobs.overview import CaseOverview, case_overview
from ..engine.jobs.runner import FINAL_CASE_STATES, CaseState, JobRecord
from ..engine.models import Project
from ..engine.results import HISTORY_FILE, HistoryBuffer

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
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.runner = runner if runner is not None else LocalRunner()
        self._clock = clock
        # One entry per project with an active job: (job_id, time of its last refresh).
        # Dropped as soon as the project has no active job, so this never grows past
        # the number of *currently* active jobs.
        self._refreshed: dict[Path, tuple[str, float]] = {}
        self._buffers: dict[tuple[Path, str, str], HistoryBuffer] = {}
        # Most-recently-used last; evicted past FILE_BUFFER_LIMIT so opening many different
        # files over a session does not grow this without bound.
        self._file_buffers: "OrderedDict[Path, HistoryBuffer]" = OrderedDict()

    def state(self, project_dir: Path, project: Project) -> JobView:
        directory = Path(project_dir).resolve()
        view = self._view(directory, project)
        if view.active is None:
            self._refreshed.pop(directory, None)
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
               continue_cases: Iterable[str] = ()) -> JobRecord:
        return self.runner.submit(Path(project_dir).resolve(), project, cases=list(cases),
                                  continue_cases=list(continue_cases))

    def cancel(self, project_dir: Path, project: Project) -> Optional[JobRecord]:
        directory = Path(project_dir).resolve()
        active = self._view(directory, project).active
        if active is None:
            return None
        return self.runner.cancel(directory, active)

    def started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        """Case names whose "Running Case" banner is in `job`'s log (see LocalRunner.started_cases)."""
        directory = Path(project_dir).resolve()
        return self.runner.started_cases(directory, job)

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
        path = Path(project_dir) / job.log_path
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - max_bytes))
                data = fh.read()
        except OSError:
            return None
        return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


WATCHER = JobWatcher()

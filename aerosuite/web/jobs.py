"""The web server's single view of jobs.

One LocalRunner for the whole server (it keeps the processes it started so it can reap them),
an active job refreshed at most every REFRESH_SECONDS per project however many tabs ask, and
one incremental history buffer per (project, job, case). No NiceGUI and no pandas import here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..engine.jobs.local import RUNS_DIR, LocalRunner
from ..engine.jobs.overview import CaseOverview, case_overview
from ..engine.jobs.runner import JobRecord
from ..engine.models import Project
from ..engine.results import HISTORY_FILE, HistoryBuffer

REFRESH_SECONDS = 2.0
LOG_TAIL_LINES = 40
LOG_TAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class JobView:
    latest: Optional[JobRecord]  # the newest job, active or not
    active: Optional[JobRecord]  # the running job, if any
    overview: CaseOverview


class JobWatcher:
    def __init__(self, runner: Optional[LocalRunner] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.runner = runner if runner is not None else LocalRunner()
        self._clock = clock
        self._refreshed: dict[tuple[Path, str], float] = {}
        self._buffers: dict[tuple[Path, str, str], HistoryBuffer] = {}

    def state(self, project_dir: Path, project: Project) -> JobView:
        directory = Path(project_dir).resolve()
        view = self._view(directory, project)
        if view.active is not None:
            key = (directory, view.active.id)
            now = self._clock()
            last = self._refreshed.get(key)
            if last is None or now - last >= REFRESH_SECONDS:
                self._refreshed[key] = now
                self.runner.refresh(directory, view.active)  # saves the job record
                view = self._view(directory, project)
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

    def log_tail(self, project_dir: Path, job: JobRecord, lines: int = LOG_TAIL_LINES) -> Optional[str]:
        """The last `lines` lines of the job's log, reading at most LOG_TAIL_BYTES; None if unreadable."""
        path = Path(project_dir) / job.log_path
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - LOG_TAIL_BYTES))
                data = fh.read()
        except OSError:
            return None
        return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


WATCHER = JobWatcher()

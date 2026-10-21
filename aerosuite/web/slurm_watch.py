"""The server's one Slurm poller: an asyncio task that, every poll interval, makes one squeue call (and at most one
sacct call) for every Slurm job of every project the server knows, applies it to the job records, fetches seff for
cases that just finished, and reads sinfo while some page shows the cluster.

Pages never run a Slurm command: they read `snapshot` / `cluster` and the job records. The poller idles (no calls)
when no Slurm job is active and no page shows the cluster. Nothing raised in a poll escapes the loop.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from ..engine import slurm as sl
from ..engine.errors import JobError
from ..engine.jobs.executors import runner_for
from ..engine.jobs.store import load_job
from ..engine.settings import current_settings

SEFF_PER_POLL = 4
RECENT_SECONDS = 300.0  # the 7-day sacct: at most this often, and only while a Cluster page is open
log = logging.getLogger("aerosuite.slurm")


def slurm_available() -> bool:
    """Slurm's commands are installed here (the Cluster button and page are shown only then)."""
    return shutil.which("sinfo") is not None


class SlurmWatch:
    def __init__(self, runner_provider: Callable = lambda: runner_for("slurm"),
                 settings_loader: Callable = current_settings) -> None:
        self._runner = runner_provider
        self._settings = settings_loader
        self._tracked: dict[Path, set[str]] = {}  # project folder -> AeroSuite job ids to watch
        self._viewers = 0
        self._wake: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None
        self.snapshot: Optional[sl.Snapshot] = None
        self.cluster: Optional[sl.ClusterInfo] = None
        self.last_ok: Optional[float] = None  # time of the last poll Slurm answered
        self.polls = 0
        self._pages = 0
        self._recent_due = False
        self.recent: Optional[sl.RecentJobs] = None
        self.user = sl.current_user()

    # -- what to watch -------------------------------------------------------------------------------------

    def track(self, project_dir: Path, job_id: str) -> None:
        """Watch this job until it has ended and its seff figures are in."""
        jobs = self._tracked.setdefault(Path(project_dir).resolve(), set())
        if job_id not in jobs:
            jobs.add(job_id)
            self._poke()

    def show_cluster(self) -> None:
        """A page shows the Cluster button (top bar): read sinfo -N too, until hide_cluster."""
        self._viewers += 1
        self._poke()

    def hide_cluster(self) -> None:
        self._viewers = max(0, self._viewers - 1)

    @property
    def viewers(self) -> int:
        return self._viewers

    def show_page(self) -> None:
        """A Cluster page is open: read the recent history (sacct) too, until hide_page."""
        self._pages += 1
        self._recent_due = True
        self._poke()

    def hide_page(self) -> None:
        self._pages = max(0, self._pages - 1)

    @property
    def pages(self) -> int:
        return self._pages

    def _poke(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def _records(self) -> list[tuple[Path, object]]:
        """(project folder, job record) of every tracked job still worth a look; the others are dropped."""
        found = []
        for directory, ids in list(self._tracked.items()):
            for job_id in list(ids):
                try:
                    job = load_job(directory, job_id)
                except JobError:
                    ids.discard(job_id)
                    continue
                if job.backend != "slurm" or not (job.is_active or self._runner().pending_stats(job)):
                    ids.discard(job_id)
                    continue
                found.append((directory, job))
            if not ids:
                del self._tracked[directory]
        return found

    # -- one poll ------------------------------------------------------------------------------------------

    async def poll_once(self) -> None:
        records = self._records()
        active = [(directory, job) for directory, job in records if job.is_active]
        runner = self._runner()
        if active or self._viewers or self._pages:
            watched = [slurm_id for _directory, job in active for slurm_id in runner.watched_ids(job)]
            snapshot = await sl.snapshot_async(watched)
            self.snapshot = snapshot
            self.polls += 1
            if snapshot.ok:
                self.last_ok = snapshot.taken
                if any(slurm_id not in snapshot.queue for slurm_id in watched):
                    self._recent_due = True  # a case left the queue: the history has something new
            for directory, job in active:
                await asyncio.to_thread(runner.apply_snapshot, directory, job, snapshot)
        if self._viewers or self._pages:
            self.cluster = await sl.nodes_async()
        if self._pages and (self._recent_due or self.recent is None
                            or time.time() - self.recent.taken >= RECENT_SECONDS):
            self.recent = await sl.recent_async()
            self._recent_due = False
        await self._fetch_seff(runner)

    async def _fetch_seff(self, runner) -> None:
        budget = SEFF_PER_POLL
        for directory, job in self._records():
            for name in runner.pending_stats(job):
                if budget <= 0:
                    return
                budget -= 1
                try:
                    stats = sl.parse_seff(await sl.run_async(sl.seff_args(job.slurm[name].job_id)))
                except sl.SlurmUnavailable:
                    stats = None
                job = await asyncio.to_thread(runner.add_seff, directory, job, name, stats)

    # -- the loop ------------------------------------------------------------------------------------------

    def interval(self) -> float:
        try:
            return float(self._settings().slurm.poll_seconds)
        except Exception:
            return 12.0

    async def run_forever(self) -> None:
        self._wake = asyncio.Event()
        while True:
            started = time.monotonic()
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let a poll take the loop (or the server) down
                log.exception("Slurm poll failed")
            self._wake.clear()
            wait = max(1.0, self.interval() - (time.monotonic() - started))
            try:
                await asyncio.wait_for(self._wake.wait(), wait)
                await asyncio.sleep(1.0)  # a burst of pokes (submit + page open) makes one poll
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run_forever())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


WATCH = SlurmWatch()

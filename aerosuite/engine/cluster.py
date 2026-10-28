"""The user's AeroSuite cases on Slurm across every study, found from Slurm itself: an AeroSuite case's job runs in
<study>/runs/<case> and is named <study name>/<case> (the job script sets both), so a job's working directory leads to
its study and that study's job records give AeroSuite's view of it."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from .ascii_export import JOB_SUFFIX
from .jobs.diagnose import diagnose
from .jobs.runner import CaseState, JobRecord
from .jobs.slurm import job_name
from .jobs.store import JOBS_DIR, scan_jobs
from .project import PROJECT_FILE
from .restarts import RUNS_DIR
from .slurm import QUEUED_STATES, RESUBMITTABLE, RUNNING_STATES, HistoryRow, QueueRow

MAX_ROWS = 500
ACTIVE_STATES = QUEUED_STATES | RUNNING_STATES


TASKS = {JOB_SUFFIX: "ASCII files"}  # job name suffix -> what a case's extra job does, in words


def split_task(name: str) -> tuple[str, str]:
    """(the job name without a task suffix, the task in words; "" for the case's run itself)."""
    for suffix, task in TASKS.items():
        if name.endswith(suffix):
            return name[:-len(suffix)], task
    return name, ""


def aerosuite_case(workdir: str, name: str) -> Optional[tuple[Path, str, str]]:
    """(study folder, study name, case) when a job looks like an AeroSuite case (or another job of a case, such as
    writing its ASCII files), else None."""
    if not workdir or not name or "/" not in name:
        return None
    folder = Path(workdir)
    if folder.parent.name != RUNS_DIR:
        return None
    study_name, _, case = name.rpartition("/")
    if case != folder.name and split_task(case)[0] != folder.name:
        return None
    return folder.parent.parent, study_name, folder.name


def study_of(workdir: str, name: str) -> Optional[Path]:
    """The study folder of an AeroSuite case's job, when it is still there and still that study."""
    found = aerosuite_case(workdir, name)
    if found is None:
        return None
    study, _study_name, case = found
    project_name = _project_name(study)
    if project_name is None or job_name(project_name, case) != split_task(name)[0]:
        return None
    return study


_PROJECT_NAMES: dict[Path, tuple[int, Optional[str]]] = {}  # study folder -> (project.json mtime, its name)


def _project_name(study: Path) -> Optional[str]:
    """The study's name from its project.json, read again only when the file changes (pages ask every 2 s)."""
    path = study / PROJECT_FILE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _PROJECT_NAMES.get(study)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = str(data.get("name", "")) if isinstance(data, dict) else None
    except (OSError, ValueError):
        name = None
    _PROJECT_NAMES[study] = (stamp, name)
    return name


class RecordIndex:
    """Slurm id -> (job record, case) per study; a study's records are read again only when its jobs/ folder
    changes (every record save replaces a file there, which changes the folder's mtime)."""

    def __init__(self) -> None:
        self._studies: dict[Path, tuple[int, dict[str, tuple[JobRecord, str]]]] = {}

    def lookup(self, study: Path, slurm_id: str) -> Optional[tuple[JobRecord, str]]:
        try:
            stamp = (Path(study) / JOBS_DIR).stat().st_mtime_ns
        except OSError:
            return None
        cached = self._studies.get(study)
        if cached is None or cached[0] != stamp:
            index: dict[str, tuple[JobRecord, str]] = {}
            jobs, _problems = scan_jobs(study)
            for job in reversed(jobs):  # oldest first, so a newer job wins
                for case, sc in job.slurm.items():
                    for seen in (*sc.attempts, sc.job_id):
                        index[seen] = (job, case)
            cached = (stamp, index)
            self._studies[study] = cached
        return cached[1].get(slurm_id)


@dataclass(frozen=True)
class MyJob:
    slurm_id: str
    study: Optional[Path]  # None: the study folder is gone, moved or no longer this study
    study_name: str
    case: str
    slurm_state: str
    case_state: Optional[str]  # AeroSuite's (a CaseState value) for the case's current attempt; None without one
    job_id: Optional[str]  # the AeroSuite job holding it
    partition: str
    node: str
    elapsed: str
    exit_code: str
    reason: str
    active: bool
    current_id: Optional[str]  # the case's current Slurm id (differs for an earlier attempt)
    resubmittable: bool
    submitted: Optional[float] = None  # when it was submitted (time.time() seconds); None when unknown
    failure: str = ""  # why it failed, in words (jobs/diagnose.py); "" unless it failed
    task: str = ""  # another job of the case (TASKS), e.g. "ASCII files"; "" for the case's run

    @property
    def earlier_attempt(self) -> bool:
        return self.current_id is not None and self.current_id != self.slurm_id


def _timestamp(text: str) -> Optional[float]:
    """Seconds since the epoch for Slurm's local ISO time ("2026-10-20T17:39:12"); None for "Unknown" or ""."""
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def active_records(queue: Mapping[str, QueueRow], recent: Mapping[str, HistoryRow], user: str,
                   index: RecordIndex) -> set[tuple[Path, str]]:
    """(study folder, AeroSuite job id) of every job record still active that has a case among the user's Slurm
    jobs, queued, running or of the recent history: what a server just started must watch, whether or not a page
    shows the study (a job that ended while it was down is brought up to date and ended)."""
    jobs = [(job_id, row.name, row.workdir) for job_id, row in recent.items()]
    jobs += [(job_id, row.name, row.workdir) for job_id, row in queue.items() if row.user == user]
    found = set()
    for job_id, name, workdir in jobs:
        study = study_of(workdir, name)
        if study is None or split_task(name)[1]:
            continue
        record = index.lookup(study, job_id)
        if record is not None and record[0].is_active:
            found.add((study, record[0].id))
    return found


def my_jobs(queue: Mapping[str, QueueRow], recent: Mapping[str, HistoryRow], user: str, index: RecordIndex,
            limit: int = MAX_ROWS) -> tuple[list[MyJob], int]:
    """The user's AeroSuite cases in the queue and in the recent history, newest first, at most `limit`, and how many
    more there were. Hand-written jobs (not in a study's runs/ folder under its study/case name) are left out."""
    seen: dict[str, tuple] = {}
    for job_id, row in recent.items():
        seen[job_id] = (row.name, row.workdir, row.state, row.partition, row.node, row.elapsed, row.exit_code, "",
                        _timestamp(row.submit))
    for job_id, row in queue.items():  # the queue is newer than accounting
        if row.user == user:
            submitted = seen[job_id][8] if job_id in seen else None
            seen[job_id] = (row.name, row.workdir, row.state, "", row.node, row.time, "", row.reason, submitted)
    rows = []
    for job_id, (name, workdir, state, partition, node, elapsed, exit_code, reason, submitted) in seen.items():
        found = aerosuite_case(workdir, name)
        if found is None:
            continue
        _folder, study_name, case = found
        study = study_of(workdir, name)
        task = split_task(name)[1]
        record = index.lookup(study, job_id) if study is not None and not task else None
        case_state = job = current = None
        resubmittable = False
        failure = ""
        if record is not None:
            job, case = record[0], record[1]
            sc = job.slurm[case]
            current = sc.job_id
            partition = partition or sc.partition
            if sc.job_id == job_id:
                submitted = sc.submitted or submitted
                status = job.case_status.get(case)
                case_state = status.value if status is not None else None
                resubmittable = status is CaseState.FAILED and sc.state in RESUBMITTABLE
                if status in (CaseState.FAILED, CaseState.BLOCKED) and job.failure_tail.get(case):
                    failure = diagnose(job.failure_tail[case], sc.state, sc.time_limit).summary
        rows.append(MyJob(job_id, study, study_name, case, state, case_state, job.id if job else None, partition,
                          node, elapsed, exit_code, reason, state in ACTIVE_STATES, current, resubmittable,
                          submitted, failure, task))
    rows.sort(key=lambda row: (len(row.slurm_id), row.slurm_id), reverse=True)
    return rows[:limit], max(0, len(rows) - limit)

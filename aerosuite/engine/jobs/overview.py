"""Each case's latest outcome across every job of a project (the Run table and the Run badge)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from ..attempts import current_override
from ..models import Project
from ..restarts import RUNS_DIR, find_restart_file
from .runner import JobRecord
from .store import scan_jobs

NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class CaseRow:
    name: str
    status: str  # a CaseState value, or NOT_RUN
    job_id: Optional[str]  # the newest job that included the case
    failure_tail: str = ""


@dataclass(frozen=True)
class CaseOverview:
    rows: list[CaseRow]
    problems: list[str]  # job records that could not be read
    jobs: list[JobRecord]  # newest first
    # Cases a running or queued job still has that the project no longer makes (the sweep changed after they were
    # submitted, e.g. 0 km became 10 km and the new cases were added to the job), in the job's order
    others: list[CaseRow] = field(default_factory=list)

    @property
    def all_rows(self) -> list[CaseRow]:
        return self.rows + self.others


def case_overview(project_dir: Path, project: Project) -> CaseOverview:
    jobs, problems = scan_jobs(project_dir)
    rows = []
    for case in project.cases:
        job = next((job for job in jobs if case.name in job.case_status), None)
        made_current = current_override(project_dir, case.name)
        if made_current and (job is None or made_current["made_current"] > job.created.timestamp()):
            # an earlier attempt brought back: its own outcome, until a newer job runs the case
            rows.append(CaseRow(case.name, made_current.get("status") or NOT_RUN, made_current.get("job_id")))
            continue
        if job is None:
            rows.append(CaseRow(case.name, NOT_RUN, None))
        else:
            rows.append(CaseRow(
                case.name, job.case_status[case.name].value, job.id, job.failure_tail.get(case.name, "")
            ))
    names = {case.name for case in project.cases}
    others = []
    for job in jobs:
        if not job.is_active:
            continue
        for name in job.cases:
            if name not in names and name in job.case_status:
                names.add(name)
                others.append(CaseRow(name, job.case_status[name].value, job.id, job.failure_tail.get(name, "")))
    return CaseOverview(rows, problems, jobs, others)


@dataclass(frozen=True)
class RunSolution:
    name: str  # the run folder: a case, maybe one of an earlier condition
    folder: Path
    modified: float  # when its restart file was written (time.time())
    status: Optional[str]  # its newest job's outcome (a CaseState value); None when no job record names it


def run_solutions(project_dir: Path, exclude: Sequence[str] = ()) -> list[RunSolution]:
    """This project's run folders holding a restart file, newest first (a single case's Restart choices)."""
    runs = Path(project_dir) / RUNS_DIR
    if not runs.is_dir():
        return []
    jobs, _problems = scan_jobs(project_dir)
    found = []
    for folder in runs.iterdir():
        if not folder.is_dir() or folder.name in exclude:
            continue
        solution = find_restart_file(folder)
        if solution is None:
            continue
        job = next((job for job in jobs if folder.name in job.case_status), None)
        try:
            modified = solution.stat().st_mtime
        except OSError:
            continue
        found.append(RunSolution(folder.name, folder, modified,
                                 job.case_status[folder.name].value if job is not None else None))
    return sorted(found, key=lambda solution: solution.modified, reverse=True)

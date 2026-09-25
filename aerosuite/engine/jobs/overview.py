"""Each case's latest outcome across every job of a project (the Run table and the Run badge)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import Project
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


def case_overview(project_dir: Path, project: Project) -> CaseOverview:
    jobs, problems = scan_jobs(project_dir)
    rows = []
    for case in project.cases:
        job = next((job for job in jobs if case.name in job.case_status), None)
        if job is None:
            rows.append(CaseRow(case.name, NOT_RUN, None))
        else:
            rows.append(CaseRow(
                case.name, job.case_status[case.name].value, job.id, job.failure_tail.get(case.name, "")
            ))
    return CaseOverview(rows, problems, jobs)

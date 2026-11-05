"""Judging finished runs again: a job keeps the verdict AeroSuite's convergence check gave when each case ended, so
a change of the check (results.check_convergence) reaches older runs only through `rejudge`."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import AeroSuiteError
from ..restarts import RUNS_DIR
from ..results import HISTORY_FILE, check_convergence, read_history
from .runner import CaseState
from .store import save_job, scan_jobs

_VERDICTS = (CaseState.CONVERGED, CaseState.UNCONVERGED)
_NEVER_RAN = (CaseState.CANCELLED, CaseState.BLOCKED, CaseState.PENDING)


@dataclass(frozen=True)
class Rejudged:
    job_id: str
    case: str
    old: CaseState
    new: CaseState
    reason: str  # the check's words now


def rejudge(project_dir: Path, write: bool = True) -> list[Rejudged]:
    """The verdicts (Converged / Not Converged) the check gives now that differ from the ones jobs recorded, and with
    `write` the job records changed to them. Only the newest job that ran a case is judged: runs/<case> holds its
    history. Active jobs are left to their runners."""
    project_dir = Path(project_dir)
    jobs, _problems = scan_jobs(project_dir)  # newest first
    seen: set[str] = set()
    changed: list[Rejudged] = []
    for job in jobs:
        updates: dict[str, CaseState] = {}
        for case in job.cases:
            state = job.case_status.get(case)
            if case in seen or state in _NEVER_RAN or state is None:
                continue
            seen.add(case)
            if job.is_active or state not in _VERDICTS:
                continue
            history = project_dir / RUNS_DIR / case / HISTORY_FILE
            try:
                df = read_history(history) if history.is_file() else None
            except (OSError, ValueError, AeroSuiteError):
                continue
            if df is None or df.empty:
                continue
            converged, reason = check_convergence(df)
            new = CaseState.CONVERGED if converged else CaseState.UNCONVERGED
            if new is not state:
                updates[case] = new
                changed.append(Rejudged(job.id, case, state, new, reason))
        if updates and write:
            job.case_status.update(updates)
            save_job(project_dir, job)
    return changed

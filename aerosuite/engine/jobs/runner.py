"""Job records and the Runner interface every backend (local, later Slurm) implements."""
from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from ..models import Project, RunSettings

BUNDLED_SWEEP_SCRIPT = Path(__file__).resolve().parents[2] / "resources" / "aoa_sweep_v8.py"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CaseState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CONVERGED = "CONVERGED"
    UNCONVERGED = "UNCONVERGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_JOB_STATES = {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
FINAL_CASE_STATES = {CaseState.CONVERGED, CaseState.UNCONVERGED, CaseState.FAILED, CaseState.CANCELLED}


class JobRecord(BaseModel):
    id: str
    backend: str
    backend_ref: dict[str, Any] = Field(default_factory=dict)  # local: {"pid", "create_time"}
    cases: list[str]
    log_path: str  # relative to the project directory
    created: datetime = Field(default_factory=datetime.now)
    finished: Optional[datetime] = None
    state: JobState = JobState.QUEUED
    case_status: dict[str, CaseState] = Field(default_factory=dict)
    failure_tail: dict[str, str] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state not in TERMINAL_JOB_STATES


class Runner(Protocol):
    def submit(self, project_dir: Path, project: Project) -> JobRecord: ...

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord: ...

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord: ...


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def sweep_script_path(run: RunSettings) -> Path:
    return Path(run.sweep_script) if run.sweep_script else BUNDLED_SWEEP_SCRIPT

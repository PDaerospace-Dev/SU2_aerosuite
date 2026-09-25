"""Job records and the Runner interface every backend (local, later Slurm) implements."""
from __future__ import annotations

import os
import secrets
import shutil
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, Sequence

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
    def submit(self, project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None,
               continue_cases: Iterable[str] = ()) -> JobRecord: ...

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord: ...

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord: ...


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def sweep_script_path(run: RunSettings) -> Path:
    return Path(run.sweep_script) if run.sweep_script else BUNDLED_SWEEP_SCRIPT


# -- the interpreter that runs the sweep script ------------------------------
# AeroSuite runs in its own (uv) environment, but the sweep script must run under
# the system Python, because only that one can import SU2. `uv run` puts the
# environment's bin folder first on PATH, so a bare "python3" would find the wrong one.


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _env_bin_dir() -> Path:
    return Path(sys.prefix) / ("Scripts" if sys.platform == "win32" else "bin")


def sweep_environment() -> dict[str, str]:
    """os.environ without VIRTUAL_ENV and without AeroSuite's own env bin folder on PATH."""
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    if "PATH" in env:
        env_bin = _norm(str(_env_bin_dir()))
        entries = env["PATH"].split(os.pathsep)
        env["PATH"] = os.pathsep.join(e for e in entries if not (e and _norm(e) == env_bin))
    return env


def resolve_sweep_python(python: str) -> str:
    """A path is used as given; a bare name is looked up on PATH outside AeroSuite's env.

    Returns the name unchanged when it is not found (the launch or preflight reports it).
    """
    if os.path.isabs(python) or os.sep in python or (os.altsep and os.altsep in python):
        return python
    return shutil.which(python, path=sweep_environment().get("PATH", "")) or python


def is_aerosuite_python(path: str) -> bool:
    """True when `path` is the interpreter of AeroSuite's own environment."""
    prefix = _norm(sys.prefix)
    candidates = {os.path.normcase(os.path.abspath(path)), _norm(path)}
    if any(c == prefix or c.startswith(prefix.rstrip(os.sep) + os.sep) for c in candidates):
        return True
    # On Linux the env's python is a symlink to a uv-managed interpreter outside sys.prefix.
    return _norm(path) == _norm(sys.executable)

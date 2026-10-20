"""Which backend runs a project's jobs, the runner for each backend, and the Slurm options of a run.

A job is always refreshed and cancelled by the backend that started it (`runner_of(job)`), whatever the settings
or the project say now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..errors import JobError
from ..models import Project
from ..settings import AppSettings, current_settings
from .runner import JobRecord, Runner

_RUNNERS: dict[str, Runner] = {}


def backend_of(project: Project, settings: Optional[AppSettings] = None) -> str:
    """The project's own choice, else the server default."""
    if project.run.backend:
        return project.run.backend
    return (settings or current_settings()).backend


def runner_for(backend: str) -> Runner:
    """The one runner of `backend` in this process (the local one keeps the processes it started)."""
    runner = _RUNNERS.get(backend)
    if runner is None:
        if backend == "local":
            from .local import LocalRunner

            runner = LocalRunner()
        elif backend == "slurm":
            from .slurm import SlurmRunner

            runner = SlurmRunner()
        else:
            raise JobError(f"Unknown backend {backend!r}")
        _RUNNERS[backend] = runner
    return runner


def runner_of(job: JobRecord) -> Runner:
    return runner_for(job.backend)


@dataclass(frozen=True)
class SlurmOptions:
    partition: str
    ntasks: int
    time_limit: str  # "" = no -t
    exclusive: bool
    account: str  # "" = no -A


def slurm_options(project: Project, settings: AppSettings, partition: Optional[str] = None,
                  ntasks: Optional[int] = None, time_limit: Optional[str] = None) -> SlurmOptions:
    """Given values, else the project's, else the settings' defaults (tasks: the partition's default). The time limit
    is the settings' one unless given for this run (a study does not keep its own)."""
    slurm = settings.slurm
    chosen = partition or project.run.slurm.partition or slurm.default_partition
    part = slurm.partition(chosen)
    tasks = ntasks or project.run.slurm.ntasks or (part.default_ntasks if part else 1)
    if time_limit is None:
        time_limit = slurm.default_time_limit
    return SlurmOptions(chosen, tasks, time_limit, slurm.exclusive, slurm.account)

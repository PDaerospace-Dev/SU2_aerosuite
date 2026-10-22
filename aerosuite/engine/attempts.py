"""Earlier attempts of a case. Before a rerun empties runs/<case>/, its run is moved to
attempts/<case>/<n>-<job>/ without its volume files (the big flow.* files): the restart solution, the history,
the config, the surface files and the Slurm output stay, so a rerun can start from it again, Monitor can draw it
before the current run, and "Make current" can bring it back. The last KEEP attempts of each case are kept.

attempt.json in each holds the job that ran it, how it ended and what it ran with (jobs/rerun.py). A run made
current again carries that file back into runs/<case>/, where case_overview reads it while no newer job ran the
case.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .errors import JobError
from .restarts import RUNS_DIR, find_restart_file

ATTEMPTS_DIR = "attempts"
KEEP = 3
INFO_FILE = "attempt.json"
VOLUME_SUFFIXES = {".vtu", ".vtk", ".vtm", ".dat", ".plt", ".szplt", ".csv", ".pvtu", ""}
_VOLUME_RE = re.compile(r"^\s*VOLUME_FILENAME\s*=\s*(\S+)", re.MULTILINE)
_HISTORY_FILE = "history.csv"


@dataclass(frozen=True)
class Attempt:
    case: str
    folder: Path
    job_id: Optional[str]
    status: Optional[str]  # how it ended (a CaseState value); None when unknown
    changes: dict = field(default_factory=dict)  # what it ran with, for that job only
    archived: float = 0.0  # when it was put aside (time.time())

    @property
    def solution(self) -> Optional[Path]:
        return find_restart_file(self.folder)

    @property
    def history(self) -> Optional[Path]:
        path = self.folder / _HISTORY_FILE
        return path if path.is_file() else None


def _volume_name(folder: Path) -> str:
    for cfg in sorted(folder.glob("*.cfg")):
        try:
            match = _VOLUME_RE.search(cfg.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if match:
            return Path(match.group(1)).stem
    return "flow"


def _drop_volume(folder: Path) -> None:
    """Delete the volume output (flow.vtu, flow_0.vtu, flow.vtm and its folder, ...): most of a run's size."""
    name = _volume_name(folder)
    for path in folder.iterdir():
        stem = path.name.split(".")[0]
        if (stem == name or re.fullmatch(rf"{re.escape(name)}_\d+", stem)) and path.suffix.lower() in VOLUME_SUFFIXES:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def _number(folder: Path) -> int:
    head = folder.name.split("-", 1)[0]
    return int(head) if head.isdigit() else 0


def _folders(project_dir: Path, case: str) -> list[Path]:
    root = Path(project_dir) / ATTEMPTS_DIR / case
    if not root.is_dir():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=_number)


def _has_a_run(folder: Path) -> bool:
    return (folder / _HISTORY_FILE).is_file() or find_restart_file(folder) is not None


def _read_info(folder: Path) -> dict:
    try:
        return json.loads((folder / INFO_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def archive(project_dir: Path, case: str, job_id: Optional[str] = None, status: Optional[str] = None,
            changes: Optional[dict] = None, drop_volume: bool = True) -> Optional[Path]:
    """Move runs/<case>/ aside as an attempt (without its volume files, unless `drop_volume` is False: a job
    drops them when it ends, or puts the run back if the case never started); returns the attempt's folder, or
    None when there was no run there (nothing ran, or only a config)."""
    source = Path(project_dir) / RUNS_DIR / case
    if not source.is_dir() or not _has_a_run(source):
        return None
    info = _read_info(source)  # a run made current again keeps what it was
    job_id = info.get("job_id", job_id)
    folders = _folders(project_dir, case)
    number = (_number(folders[-1]) + 1) if folders else 1
    target = Path(project_dir) / ATTEMPTS_DIR / case / f"{number:03d}-{job_id or 'run'}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)  # the same filesystem: instant, and hard links set aside stay valid
    except OSError:
        try:
            shutil.move(str(source), str(target))
        except OSError as exc:
            raise JobError(f"Cannot keep the earlier run of {case} in {target}: {exc}") from exc
    if drop_volume:
        _drop_volume(target)
    record = {"job_id": job_id, "status": info.get("status", status), "changes": info.get("changes", changes or {}),
              "archived": time.time()}
    (target / INFO_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    for old in _folders(project_dir, case)[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def attempts(project_dir: Path, case: str) -> list[Attempt]:
    """A case's earlier attempts, oldest first."""
    found = []
    for folder in _folders(project_dir, case):
        info = _read_info(folder)
        found.append(Attempt(case, folder, info.get("job_id"), info.get("status"), info.get("changes") or {},
                             float(info.get("archived") or 0.0)))
    return found


def make_current(project_dir: Path, attempt: Attempt) -> None:
    """Bring `attempt` back as the case's run; the current run becomes an attempt in its place."""
    from .jobs.store import active_lock

    if active_lock(project_dir):
        raise JobError("A job is running for this project: wait for it, or cancel it, first")
    if not attempt.folder.is_dir():
        raise JobError(f"The attempt {attempt.folder.name} of {attempt.case} is gone")
    runs = Path(project_dir) / RUNS_DIR / attempt.case
    current = _current_status(project_dir, attempt.case)
    held = runs.parent / f".{attempt.case}.making-current"
    try:
        os.replace(attempt.folder, held)  # out of attempts/, so archiving below cannot prune it
        archive(project_dir, attempt.case, *current)
        if runs.exists():
            shutil.rmtree(runs)
        os.replace(held, runs)
    except OSError as exc:
        raise JobError(f"Cannot make {attempt.folder.name} current: {exc}") from exc
    info = _read_info(runs)
    info["made_current"] = time.time()
    (runs / INFO_FILE).write_text(json.dumps(info, indent=2), encoding="utf-8")


def _current_status(project_dir: Path, case: str) -> tuple[Optional[str], Optional[str], dict]:
    """(job id, status, changes) of the case's current run, from the newest job that ran it."""
    from .jobs.store import scan_jobs

    jobs, _problems = scan_jobs(project_dir)
    job = next((job for job in jobs if case in job.case_status), None)
    if job is None:
        return None, None, {}
    return job.id, job.case_status[case].value, job.changes.get(case, {})


def archive_before_rerun(project_dir: Path, cases: list[str]) -> dict[str, str]:
    """Keep each case's current run as an attempt before a job empties its folder; returns {case: attempt folder}
    for the job to settle when it ends (settle_attempts)."""
    kept = {}
    for case in cases:
        folder = archive(project_dir, case, *_current_status(project_dir, case), drop_volume=False)
        if folder is not None:
            kept[case] = str(folder)
    return kept


def settle_attempts(project_dir: Path, archived: dict[str, str], started: set[str]) -> None:
    """When a job ends: drop the volume files of the runs it put aside, and put back the run of each case that never
    started in it (cancelled or failed before it), so that case's current run is the one it had."""
    for case, name in archived.items():
        folder = Path(name)
        if not folder.is_dir():
            continue
        runs = Path(project_dir) / RUNS_DIR / case
        if case not in started and not (runs.is_dir() and _has_a_run(runs)):
            try:
                shutil.rmtree(runs, ignore_errors=True)  # only this job's config and script
                os.replace(folder, runs)
                (runs / INFO_FILE).unlink(missing_ok=True)
                continue
            except OSError:
                pass  # left as an attempt: Make current brings it back
        _drop_volume(folder)


def current_override(project_dir: Path, case: str) -> Optional[dict]:
    """attempt.json of a run made current again ({"job_id", "status", "changes", "made_current"}), if any."""
    info = _read_info(Path(project_dir) / RUNS_DIR / case)
    return info if info.get("made_current") else None

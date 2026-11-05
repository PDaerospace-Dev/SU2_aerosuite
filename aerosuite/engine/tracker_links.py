"""Linked run-matrix sheets ($AEROSUITE_HOME/tracker.json): which sheet of which workbook follows which projects'
jobs, and a log of what was written. What a link would write now (its report) and writing it."""
from __future__ import annotations

import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field, ValidationError

from .errors import AeroSuiteError, TrackerError
from .home import aerosuite_home
from .jobs.store import JOBS_DIR
from .tracker import (CellValue, Change, Matrix, Plan, collect_statuses, completion_date, job_counts, lock_files,
                      new_sheet, plan_changes, read_matrix, verdict_reason, write_statuses)

LOG_LENGTH = 50
REASONS_AT_MOST = 300  # kept verdicts whose history is read for the reason

_lock = threading.Lock()


class LinkedProject(BaseModel):
    path: str
    elevator: float


class Link(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    workbook: str
    sheet: str
    projects: list[LinkedProject] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)  # only jobs whose note has one of these #tags
    skip_tags: list[str] = Field(default_factory=list)  # never jobs with one of these
    overwrite: bool = False  # a job's verdict replaces one entered by hand
    auto: bool = True  # written as cases start and finish


class LogEntry(BaseModel):
    at: datetime = Field(default_factory=datetime.now)
    link: str
    workbook: str
    sheet: str
    written: int = 0
    trigger: str = "manual"  # "manual" (the Write button), "auto", "new-sheet" (the sheet was made from a template)
    completed_on: Optional[date] = None  # the write also filled in "Completed on"
    error: str = ""


class TrackerFile(BaseModel):
    links: list[Link] = Field(default_factory=list)
    log: list[LogEntry] = Field(default_factory=list)  # newest first


def tracker_file() -> Path:
    return aerosuite_home() / "tracker.json"


def load_tracker() -> TrackerFile:
    """The saved links and log; an empty one when there is no file or it cannot be read."""
    try:
        return TrackerFile.model_validate_json(tracker_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return TrackerFile()


def _save(data: TrackerFile) -> None:
    path = tracker_file()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise TrackerError(f"Cannot save {path}: {exc}") from exc


def save_link(link: Link) -> Link:
    """Add the link, or replace the one with its id."""
    with _lock:
        data = load_tracker()
        data.links = [link if old.id == link.id else old for old in data.links]
        if all(old.id != link.id for old in data.links):
            data.links.append(link)
        _save(data)
    return link


def remove_link(link_id: str) -> None:
    with _lock:
        data = load_tracker()
        data.links = [link for link in data.links if link.id != link_id]
        _save(data)


def set_auto(link_ids: Iterable[str], auto: bool) -> None:
    ids = set(link_ids)
    with _lock:
        data = load_tracker()
        for link in data.links:
            if link.id in ids:
                link.auto = auto
        _save(data)


def find_link(link_id: str) -> Optional[Link]:
    return next((link for link in load_tracker().links if link.id == link_id), None)


def log_write(entry: LogEntry) -> None:
    with _lock:
        data = load_tracker()
        data.log = [entry] + data.log[:LOG_LENGTH - 1]
        _save(data)


@dataclass
class ProjectReport:
    path: str
    name: str
    elevator: float
    jobs_chosen: int = 0
    jobs: int = 0
    matched: int = 0  # matrix rows whose status comes from this project
    error: str = ""


@dataclass
class LinkReport:
    link: Link
    matrix: Optional[Matrix] = None
    plan: Optional[Plan] = None
    projects: list[ProjectReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""  # the workbook or sheet cannot be used: nothing else is known
    reasons: dict[int, str] = field(default_factory=dict)  # kept verdicts: sheet row -> the convergence check's words
    completed_on: Optional[date] = None  # what the blank "Completed on" cell gets: every run has a verdict

    @property
    def sheet_counts(self) -> Counter:
        """The sheet's Status values as they are now ("" for blank)."""
        return Counter(row.status for row in self.matrix.rows) if self.matrix else Counter()

    @property
    def no_job(self) -> int:
        if self.matrix is None or self.plan is None:
            return 0
        return len(self.matrix.rows) - len(self.plan.changes) - self.plan.unchanged - len(self.plan.kept)


def report(link: Link, reasons: bool = False) -> LinkReport:
    """What the link would write now. Job records are read as they are: the server's pollers keep them current."""
    result = LinkReport(link)
    result.projects = [ProjectReport(p.path, Path(p.path).name, p.elevator) for p in link.projects]
    try:
        result.matrix = read_matrix(Path(link.workbook), link.sheet)
    except (AeroSuiteError, OSError) as exc:
        result.error = str(exc)
        return result
    pairs = []
    for project in result.projects:
        try:
            project.jobs_chosen, project.jobs = job_counts(Path(project.path), link.tags, link.skip_tags)
            pairs.append((Path(project.path), project.elevator))
        except (AeroSuiteError, OSError) as exc:
            project.error = str(exc)
    try:
        statuses, result.warnings = collect_statuses(pairs, link.tags, link.skip_tags, refresh=False)
    except (AeroSuiteError, OSError) as exc:
        result.error = str(exc)
        return result
    result.plan = plan_changes(result.matrix, statuses, overwrite=link.overwrite)
    result.completed_on = completion_date(result.matrix, result.plan, statuses)
    by_folder = {project.path: project for project in result.projects}
    known = {row.key for row in result.matrix.rows}
    for case_key, entry in statuses.items():
        if case_key in known and entry.folder in by_folder:
            by_folder[entry.folder].matched += 1
    if reasons:
        for change in result.plan.kept[:REASONS_AT_MOST]:
            result.reasons[change.row.row] = verdict_reason(Path(change.source.folder), change.source.case)
    return result


def write_link(link: Link, accepted: Iterable[Change] = (), trigger: str = "manual") -> int:
    """Write the link's changes, plus kept verdicts the user chose to replace (`accepted`), and log it. Returns how
    many Status cells were written; a failure is logged and raised."""
    result = report(link)
    entry = LogEntry(link=link.id, workbook=link.workbook, sheet=link.sheet, trigger=trigger)
    try:
        if result.error:
            raise TrackerError(result.error)
        values = {change.row.row: change.status for change in result.plan.changes}
        current = {change.row.row: change.status for change in result.plan.kept}
        values.update({change.row.row: change.status for change in accepted
                       if current.get(change.row.row) == change.status})  # still what the job says
        also = {result.matrix.completed_on: result.completed_on} if result.completed_on else {}
        if values or also:
            write_statuses(Path(link.workbook), link.sheet, result.matrix.status_column, values, also)
        entry.written = len(values)
        entry.completed_on = result.completed_on
    except (AeroSuiteError, OSError) as exc:
        entry.error = str(exc)
        log_write(entry)
        raise TrackerError(str(exc)) from exc
    if entry.written or entry.completed_on or trigger == "manual":
        log_write(entry)
    return entry.written


def create_sheet(link: Link, template: str, details: dict[int, CellValue], levels: list[list[float]],
                 keep: bool = True) -> Path:
    """Add `link.sheet` to `link.workbook` as a copy of sheet `template` (see tracker.new_sheet) and log it; with
    `keep`, save the link too, so its Status follows the projects' jobs. Returns the backup."""
    backup = new_sheet(Path(link.workbook), template, link.sheet, details, levels)
    log_write(LogEntry(link=link.id if keep else "", workbook=link.workbook, sheet=link.sheet, trigger="new-sheet"))
    if keep:
        save_link(link)
    return backup


def link_stamp(link: Link) -> tuple:
    """What changes when the link may have something new to write: its projects' job records, the workbook, and
    Excel's or LibreOffice's lock file beside it (so a write skipped while it was open is tried again once it is
    closed)."""
    workbook = Path(link.workbook)
    parts: list = []
    for path in (workbook, *(path for _, path in lock_files(workbook))):
        try:
            stat = path.stat()
            parts.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append((str(path), None))
    for project in link.projects:
        jobs = Path(project.path) / JOBS_DIR
        try:
            parts.append(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in jobs.glob("*.json")))
        except OSError:
            parts.append(None)
    return tuple(map(str, parts))


def last_write(log: list[LogEntry], workbook: str) -> Optional[LogEntry]:
    return next((entry for entry in log if entry.workbook == workbook and not entry.error), None)


def candidate_projects(workbook: str, extra: Iterable[str] = ()) -> list[Path]:
    """Project folders a link may use: next to the workbook, the recent projects, and `extra`, each once, by name."""
    from .home import load_recent
    from .project import PROJECT_FILE

    found: dict[str, Path] = {}
    folder = Path(workbook).parent if workbook else None
    if folder is not None and folder.is_dir():
        try:
            for child in sorted(folder.iterdir()):
                if (child / PROJECT_FILE).is_file():
                    found[str(child)] = child
        except OSError:
            pass
    for path in [*load_recent(), *map(Path, extra)]:
        found.setdefault(str(path), path)
    return sorted(found.values(), key=lambda path: path.name)

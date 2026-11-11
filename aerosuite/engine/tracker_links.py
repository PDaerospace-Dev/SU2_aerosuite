"""Linked run-matrix sheets ($AEROSUITE_HOME/tracker.json): which sheet of which workbook follows which projects'
jobs, and a log of what was written. What a link would write now (its report) and writing it."""
from __future__ import annotations

import shutil
import threading
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import AeroSuiteError, TrackerError
from .home import aerosuite_home
from .jobs.store import JOBS_DIR
from .locking import file_lock
from .tracker import (VERDICTS, CaseStatus, CellValue, Change, Key, Matrix, Plan, collect_statuses, completion_date,
                      job_counts, lock_files, new_sheet, plan_changes, read_matrix, verdict_reason, write_statuses)

LOG_LENGTH = 50
REASONS_AT_MOST = 300  # kept verdicts whose history is read for the reason

_lock = threading.Lock()


class _Kept(BaseModel):
    """A part of tracker.json. What this version does not know (a setting a newer AeroSuite wrote) is kept on a save,
    not dropped."""
    model_config = ConfigDict(extra="allow")


class LinkedProject(_Kept):
    path: str
    elevator: float


class Link(_Kept):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    workbook: str
    sheet: str
    projects: list[LinkedProject] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)  # only jobs whose note has one of these #tags
    skip_tags: list[str] = Field(default_factory=list)  # never jobs with one of these
    order: str = ""  # "1st" / "2nd": only cases a job ran at that solver order (its config's MUSCL_FLOW); "" for any
    overwrite: bool = False  # a job's verdict replaces one entered by hand
    auto: bool = True  # written as cases start and finish
    completed: Optional[bool] = None  # None: done once every run has a verdict; True / False: set by hand


class LogEntry(_Kept):
    at: datetime = Field(default_factory=datetime.now)
    link: str
    workbook: str
    sheet: str
    written: int = 0
    trigger: str = "manual"  # "manual" (the Write button), "auto", "new-sheet" (the sheet was made from a template),
    # "edit" (Status or Notes set by hand on the coverage page: `written` counts the runs)
    completed_on: Optional[date] = None  # the write also filled in "Completed on"
    error: str = ""


class TrackerFile(_Kept):
    links: list[Link] = Field(default_factory=list)
    log: list[LogEntry] = Field(default_factory=list)  # newest first


def tracker_file() -> Path:
    return aerosuite_home() / "tracker.json"


def backup_file() -> Path:
    """The tracker file as it was before its last save."""
    return tracker_file().with_name("tracker.json.bak")


def load_tracker() -> TrackerFile:
    """The saved links and log; an empty one when there is no file yet. A file that is there but cannot be read is an
    error, never an empty tracker: a save after it would replace every link with nothing."""
    path = tracker_file()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return TrackerFile()
    except OSError as exc:
        raise TrackerError(f"Cannot read the run-matrix links in {path}: {exc}") from exc
    try:
        return TrackerFile.model_validate_json(text)
    except (ValueError, ValidationError) as exc:
        reason = str(exc).splitlines()[0]
        raise TrackerError(f"The run-matrix links in {path} cannot be read ({reason}). Nothing was changed. Repair "
                           f"the file, or put back its last good copy: {backup_file()}") from exc


def saved_links() -> list[Link]:
    """The links, for a list that is only a convenience (chips, suggestions): none when the file cannot be read (the
    Run matrix page reports that)."""
    try:
        return load_tracker().links
    except TrackerError:
        return []


@contextmanager
def _changing() -> Iterator[TrackerFile]:
    """The tracker file to change in the block; saved after it. Under the thread lock and the file's own lock, so the
    server, a second server and `aerosuite tracker` cannot undo each other's saves. The file before the save is
    kept as tracker.json.bak."""
    with _lock, file_lock(tracker_file()):
        data = load_tracker()
        yield data
        _save(data)


def _save(data: TrackerFile) -> None:
    path = tracker_file()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        if path.is_file():
            shutil.copy2(path, backup_file())
        tmp.replace(path)
    except OSError as exc:
        raise TrackerError(f"Cannot save {path}: {exc}") from exc


def save_link(link: Link) -> Link:
    """Add the link, or replace the one with its id."""
    with _changing() as data:
        data.links = [link if old.id == link.id else old for old in data.links]
        if all(old.id != link.id for old in data.links):
            data.links.append(link)
    return link


def remove_link(link_id: str) -> None:
    with _changing() as data:
        data.links = [link for link in data.links if link.id != link_id]


def set_completed(link_id: str, completed: Optional[bool]) -> None:
    """Mark a linked sheet completed or ongoing by hand (None: by its runs again)."""
    with _changing() as data:
        for link in data.links:
            if link.id == link_id:
                link.completed = completed


def set_auto(link_ids: Iterable[str], auto: bool) -> None:
    ids = set(link_ids)
    with _changing() as data:
        for link in data.links:
            if link.id in ids:
                link.auto = auto


def find_link(link_id: str) -> Optional[Link]:
    return next((link for link in saved_links() if link.id == link_id), None)


def log_write(entry: LogEntry) -> None:
    with _changing() as data:
        data.log = [entry] + data.log[:LOG_LENGTH - 1]


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
    statuses: dict[Key, CaseStatus] = field(default_factory=dict)  # what the jobs say, by run
    completed_on: Optional[date] = None  # what the blank "Completed on" cell gets: every run has a verdict

    @property
    def sheet_counts(self) -> Counter:
        """The sheet's Status values as they are now ("" for blank)."""
        return Counter(row.status for row in self.matrix.rows) if self.matrix else Counter()

    @property
    def done(self) -> bool:
        """Completed: marked so by hand, or (unless marked ongoing) every run has a verdict."""
        if self.link.completed is not None:
            return self.link.completed
        return bool(self.matrix and self.matrix.rows) and all(row.status in VERDICTS for row in self.matrix.rows)

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
            project.jobs_chosen, project.jobs = job_counts(Path(project.path), link.tags, link.skip_tags, link.order)
            pairs.append((Path(project.path), project.elevator))
        except (AeroSuiteError, OSError) as exc:
            project.error = str(exc)
    try:
        statuses, result.warnings = collect_statuses(pairs, link.tags, link.skip_tags, refresh=False,
                                                            order=link.order)
    except (AeroSuiteError, OSError) as exc:
        result.error = str(exc)
        return result
    result.statuses = statuses
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


# Status values a run can be given by hand (the template's list, less Running and Pending, which only a job knows), and
# "" for a blank cell
HAND_STATUSES = ("Converged", "Not Converged", "Diverged", "Failed", "Hold", "")


@dataclass(frozen=True)
class RunEdit:
    status: Optional[str] = None  # None leaves the Status cell as it is; "" blanks it
    notes: Optional[str] = None  # None leaves the Notes cell as it is


def edit_runs(link: Link, edits: dict[str, RunEdit]) -> int:
    """Set runs' Status and Notes cells by hand ({run ID: edit}), keeping every other byte of the workbook, and log it.
    A verdict set this way is kept by later writes, as one typed in Excel is. Returns how many runs changed; a failure
    is logged and raised."""
    entry = LogEntry(link=link.id, workbook=link.workbook, sheet=link.sheet, trigger="edit")
    try:
        matrix = read_matrix(Path(link.workbook), link.sheet)
        rows = {row.run_id: row for row in matrix.rows}
        cells: dict[str, CellValue] = {}
        changed = set()
        for run_id, edit in edits.items():
            row = rows.get(run_id)
            if row is None:
                raise TrackerError(f"{run_id} is not a run of {link.sheet}")
            if edit.status is not None and edit.status != row.status:
                if edit.status not in HAND_STATUSES:
                    raise TrackerError(f"{edit.status!r} is not a status that can be set by hand")
                cells[f"{matrix.status_column}{row.row}"] = edit.status
                changed.add(run_id)
            notes = None if edit.notes is None else edit.notes.strip()
            if notes is not None and notes != row.notes:
                if not matrix.notes_column:
                    raise TrackerError(f"{link.sheet} has no Notes column")
                if row.notes.startswith("="):
                    raise TrackerError(f"{run_id}: its Notes cell holds a formula; change it in Excel")
                cells[f"{matrix.notes_column}{row.row}"] = notes
                changed.add(run_id)
        if cells:
            write_statuses(Path(link.workbook), link.sheet, matrix.status_column, {}, cells)
        entry.written = len(changed)
    except (AeroSuiteError, OSError) as exc:
        entry.error = str(exc)
        log_write(entry)
        raise TrackerError(str(exc)) from exc
    if entry.written:
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

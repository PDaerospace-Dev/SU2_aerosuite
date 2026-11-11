"""Run-matrix workbooks: the Status column of a full-factorial run matrix sheet (Mach x altitude x AoA x elevator x
sideslip, as the CFD run-matrix template lays it out), kept in step with the projects' job records; and new sheets
copied from the workbook's template sheet.

The sheet is read with openpyxl. It is written by editing only the cells concerned in the sheet's XML (a new sheet:
adding a copy of the template's XML and listing it), every other part of the file copied byte for byte, so what
openpyxl would drop on a save (text boxes, add-ins, SharePoint properties) survives."""
from __future__ import annotations

import html
import os
import posixpath
import re
import shutil
import threading
import uuid
import zipfile
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from math import prod
from pathlib import Path
from typing import Callable, Iterable, Optional, Union
from xml.etree import ElementTree

from .cfg import CONFIGS_DIR
from .errors import AeroSuiteError, TrackerError
from .imported import read_name
from .jobs.diagnose import diagnose
from .jobs.executors import runner_of
from .jobs.runner import CaseState, JobRecord
from .jobs.store import JOBS_DIR, scan_jobs
from .locking import file_lock
from .restarts import RUNS_DIR
from .results import HISTORY_FILE, check_convergence, load_case_index, read_history

Key = tuple[float, float, float, float, float]  # Mach, altitude (km), AoA, elevator, beta (deg)

# The template's Status list (its data validation): what each case state reads as there.
STATUS_TEXT = {
    CaseState.CONVERGED: "Converged",
    CaseState.UNCONVERGED: "Not Converged",
    CaseState.FAILED: "Failed",
    CaseState.RUNNING: "Running",
    CaseState.PENDING: "Pending",
    CaseState.CANCELLED: "Hold",
    CaseState.BLOCKED: "Hold",
}
_NEVER_RAN = {CaseState.CANCELLED, CaseState.BLOCKED}  # shown only when no job has a result for the case
_LIVE = {CaseState.RUNNING, CaseState.PENDING}  # true only while the job is active
NOT_CONVERGED, FAILED, HOLD = (STATUS_TEXT[state] for state in (CaseState.UNCONVERGED, CaseState.FAILED,
                                                                 CaseState.CANCELLED))
DIVERGED = "Diverged"  # a failed case whose output says SU2 found NaN (diagnose), or set by hand
# The solver order a sheet can be kept to: read from the config each job ran a case with (MUSCL_FLOW), so a note with a
# missing or mistyped tag cannot put a run in the wrong sheet.
ORDERS = {"1st": "1st order", "2nd": "2nd order"}
ORDER_TAG = "2nd_order"  # decides for a job that kept no config: 2nd order with this #tag in its note, else 1st
_MUSCL_RE = re.compile(r"^[ \t]*MUSCL_FLOW[ \t]*=[ \t]*(\w+)", re.MULTILINE | re.IGNORECASE)
_orders: dict[tuple[str, str], Optional[str]] = {}  # by (job folder, case): a job's own configs never change
VERDICTS = {STATUS_TEXT[CaseState.CONVERGED], NOT_CONVERGED, DIVERGED, FAILED}

_SWEEP_HEADERS = (("mach",), ("alt",), ("aoa", "alpha"), ("elev",), ("beta", "sideslip"))
_SWEEP_LEVELS = 100  # the template's input rows per parameter
_SEARCH_ROWS = 200
_ELEVATOR_RE = re.compile(r"(?:^|_)del_?(\d+(?:p\d+)?)([mp]?)(?:_|$)", re.IGNORECASE)
_ROW_OFFSET_RE = re.compile(r"ROW\(\)\s*-\s*(\d+)", re.IGNORECASE)
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def key(mach: float, altitude: float, aoa: float, elevator: float, beta: float) -> Key:
    return tuple(round(float(v), 6) for v in (mach, altitude, aoa, elevator, beta))  # type: ignore[return-value]


def elevator_of(project_dir: Path) -> float:
    """The elevator deflection a project folder's name gives: del0 -> 0, del20p -> 20, del30m / del_60m -> -30 / -60."""
    name = Path(project_dir).name
    match = _ELEVATOR_RE.search(name)
    if not match:
        raise TrackerError(f"Cannot tell the elevator deflection from the folder name {name!r} (expected del0, "
                           f"del20p, del30m...); give it as {project_dir}=<degrees>")
    value = float(match[1].lower().replace("p", "."))
    return -value if match[2].lower() == "m" else value


# --- what the projects' jobs say -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseStatus:
    status: str  # as the sheet writes it
    project: str  # the project folder's name
    job_id: str
    case: str
    folder: str = ""  # the project folder
    key: Optional[Key] = None  # the run it is for
    finished: Optional[datetime] = None  # when its job ended


def _case_values(name: str, index: dict) -> Optional[tuple[float, float, float, float]]:
    """Mach, altitude, AoA, beta of a case: from configs/cases.json, else from its name (an earlier Generate's case)."""
    if name in index:
        values = index[name]
        mach, altitude, alpha, beta = (values.get(k) for k in ("mach", "altitude_km", "alpha", "beta"))
    else:
        parsed = read_name(name)
        mach, altitude, alpha, beta = parsed.mach, parsed.altitude_km, parsed.alpha, parsed.beta
    if mach is None or altitude is None or alpha is None:
        return None
    return mach, altitude, alpha, beta or 0.0


def has_tag(note: str, tag: str) -> bool:
    """Whether a job note has #tag. Read from the text, not note_tags(): that takes only tags starting with a letter,
    and run-matrix sheets are often split by #1st_order / #2nd_order."""
    return re.search(rf"#{re.escape(tag.lstrip('#'))}(?![\w-])", note, re.IGNORECASE) is not None


def solver_order(project_dir: Path, job_id: str, case: str) -> Optional[str]:
    """The order the job ran the case at, from its own config: "2nd" with MUSCL_FLOW on (SU2's default when the config
    does not say), "1st" with it off; None when the job kept no config for the case. A case added to the job later has
    its config in the newest add-N folder."""
    folder = Path(project_dir) / JOBS_DIR / job_id
    known = (str(folder), case)
    if known in _orders:
        return _orders[known]
    added = sorted(folder.glob(f"add-*/{CONFIGS_DIR}/{case}.cfg"),
                   key=lambda path: int(path.parts[-3][4:]) if path.parts[-3][4:].isdigit() else 0, reverse=True)
    order = None
    for path in added + [folder / CONFIGS_DIR / f"{case}.cfg"]:
        try:
            found = _MUSCL_RE.findall(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        order = "1st" if found and found[-1].upper() == "NO" else "2nd"
        break
    _orders[known] = order
    return order


def case_order(project_dir: Path, job: JobRecord, case: str) -> str:
    """solver_order, or what the job's note says (ORDER_TAG) when it kept no config."""
    return solver_order(project_dir, job.id, case) or ("2nd" if has_tag(job.note, ORDER_TAG) else "1st")


def _diverged(job: JobRecord, case: str) -> bool:
    """A failed case whose output ends in SU2's divergence message."""
    tail = job.failure_tail.get(case, "")
    slurm = job.slurm.get(case)
    return bool(tail) and diagnose(tail, getattr(slurm, "state", None)).kind == "diverged"


def _refreshed(project_dir: Path, job: JobRecord) -> JobRecord:
    """An active job as its runner sees it now (as `aerosuite status` does); the record on disk if that fails."""
    try:
        return runner_of(job).refresh(project_dir, job)
    except AeroSuiteError:
        return job


def collect_statuses(
    projects: Iterable[tuple[Path, float]],
    tags: Iterable[str] = (),
    skip_tags: Iterable[str] = (),
    refresh: bool = True,
    order: str = "",
) -> tuple[dict[Key, CaseStatus], list[str]]:
    """Each case's status from the newest job that ran it, over (project folder, elevator) pairs, and warnings.

    With `tags`, only jobs whose note has one of them count; jobs with any of `skip_tags` never do. With `order`
    ("1st" or "2nd"), only cases a job ran at that solver order count (case_order). A case a newer job cancelled (or
    never started) keeps an older job's result; Hold is shown only when no job has one. A failed case that diverged
    reads Diverged."""
    tags, skip_tags = list(tags), list(skip_tags)
    jobs: list[tuple[datetime, Path, float, JobRecord, dict]] = []
    warnings: list[str] = []
    for project_dir, elevator in projects:
        project_dir = Path(project_dir)
        found, problems = scan_jobs(project_dir)
        warnings += [f"{project_dir.name}: {problem}" for problem in problems]
        index = load_case_index(project_dir / CONFIGS_DIR)
        for job in found:
            if (tags and not any(has_tag(job.note, t) for t in tags)) or any(has_tag(job.note, t) for t in skip_tags):
                continue
            if refresh and job.is_active:
                job = _refreshed(project_dir, job)
            jobs.append((job.created, project_dir, elevator, job, index))
    statuses: dict[Key, CaseStatus] = {}
    fallback: dict[Key, CaseStatus] = {}
    unknown: dict[str, list[str]] = {}
    for _created, project_dir, elevator, job, index in sorted(jobs, key=lambda item: item[0], reverse=True):
        for case in job.cases:
            state = job.case_status.get(case)
            if state is None or (state in _LIVE and not job.is_active):
                continue
            if order and case_order(project_dir, job, case) != order:
                continue
            values = _case_values(case, index)
            if values is None:
                names = unknown.setdefault(project_dir.name, [])
                if case not in names:
                    names.append(case)
                continue
            mach, altitude, alpha, beta = values
            case_key = key(mach, altitude, alpha, elevator, beta)
            text = DIVERGED if state is CaseState.FAILED and _diverged(job, case) else STATUS_TEXT[state]
            entry = CaseStatus(text, project_dir.name, job.id, case, str(project_dir), case_key, job.finished)
            if state in _NEVER_RAN:
                fallback.setdefault(case_key, entry)
            else:
                statuses.setdefault(case_key, entry)
    for case_key, entry in fallback.items():
        statuses.setdefault(case_key, entry)
    for project, names in unknown.items():
        warnings.append(f"{project}: no Mach, altitude or AoA known for {len(names)} case(s), left out: "
                        f"{', '.join(names[:5])}{' ...' if len(names) > 5 else ''}")
    return statuses, warnings


def job_counts(project_dir: Path, tags: Iterable[str] = (), skip_tags: Iterable[str] = (),
               order: str = "") -> tuple[int, int]:
    """How many of a project's jobs the tags and the order choose (a job with any case at that order), and how many
    it has."""
    tags, skip_tags = list(tags), list(skip_tags)
    jobs, _ = scan_jobs(Path(project_dir))
    chosen = [job for job in jobs if (not tags or any(has_tag(job.note, t) for t in tags))
              and not any(has_tag(job.note, t) for t in skip_tags)
              and (not order or any(case_order(Path(project_dir), job, case) == order for case in job.cases))]
    return len(chosen), len(jobs)


def verdict_reason(folder: Path, case: str) -> str:
    """Why AeroSuite's convergence check judged a case as it did, from its history now; "" when there is none."""
    path = Path(folder) / RUNS_DIR / case / HISTORY_FILE
    if not path.is_file():
        return ""
    try:
        return check_convergence(read_history(path))[1]
    except (OSError, ValueError, AeroSuiteError):
        return ""


# --- the sheet -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MatrixRow:
    row: int  # the sheet's row number
    run_id: str
    key: Key
    status: str  # in the sheet now; "" when blank
    notes: str = ""  # its Notes cell


@dataclass(frozen=True)
class Matrix:
    sheet: str
    status_column: str  # its letter, e.g. "M"
    rows: list[MatrixRow]
    levels: list[list[float]]  # the values entered per sweep parameter: Mach, altitude, AoA, elevator, beta
    completed_on: str = ""  # the cell beside "Completed on", e.g. "D11", while it is blank
    notes_column: str = ""  # its letter; "" when the header row has no Notes column


_loaded: dict[tuple, object] = {}  # workbooks as last read, by (path, mtime, size): the web pages read one often
_loaded_lock = threading.Lock()


def _load(workbook: Path):
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    stat = workbook.stat()
    stamp = (str(workbook.resolve()), stat.st_mtime_ns, stat.st_size)
    with _loaded_lock:
        if stamp in _loaded:
            return _loaded[stamp]
    try:
        wb = load_workbook(workbook)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TrackerError(f"Cannot read {workbook} as an .xlsx workbook: {exc}") from exc
    with _loaded_lock:
        for old in [s for s in _loaded if s[0] == stamp[0]]:
            del _loaded[old]
        while len(_loaded) >= 4:
            del _loaded[next(iter(_loaded))]
        _loaded[stamp] = wb
    return wb


def sheet_names(workbook: Path) -> list[str]:
    return list(_load(Path(workbook)).sheetnames)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sweep_row(ws, workbook: Path) -> int:
    """The sweep table's header row (Mach, Altitude, AoA, Elevator, Sideslip in columns A-E). The row below it counts
    the levels; the values start the row after."""
    for row in range(1, _SEARCH_ROWS + 1):
        headers = [_text(ws.cell(row, column).value).lower() for column in range(1, 6)]
        if headers[0].startswith("mach") and all(any(word in header for word in words)
                                                 for header, words in zip(headers, _SWEEP_HEADERS)):
            return row
    raise TrackerError(f"{ws.title} in {workbook.name} has no sweep table (Mach, Altitude, AoA, Elevator, Sideslip "
                       f"headers in columns A-E)")


def _sweep_levels(ws, workbook: Path) -> list[list[float]]:
    """The values entered for each sweep parameter (Mach, altitude, AoA, elevator, beta), in sheet order."""
    row = _sweep_row(ws, workbook)
    levels = []
    for column in range(1, 6):
        values = []
        for value_row in range(row + 2, row + 2 + _SWEEP_LEVELS):
            value = ws.cell(value_row, column).value
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TrackerError(f"{ws.title}: {ws.cell(value_row, column).coordinate} is {value!r}, not a number")
            values.append(float(value))
        levels.append(values)
    return levels


def _sheet(workbook: Path, sheet: str):
    wb = _load(workbook)
    if sheet not in wb.sheetnames:
        raise TrackerError(f"No sheet {sheet!r} in {workbook.name}; it has: {', '.join(wb.sheetnames)}")
    return wb[sheet]


def _run_columns(ws) -> tuple[int, int, int]:
    """The Run ID and Status columns (numbers), and the row of the first run."""
    run_column, status_column, _notes, first_row = _header_columns(ws)
    return run_column, status_column, first_row


def _header_columns(ws) -> tuple[int, int, int, int]:
    """The Run ID, Status and Notes columns (numbers; Notes 0 when there is none), and the row of the first run."""
    header_row = status_column = run_column = None
    notes_column = 0
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, _SEARCH_ROWS)):
        status = next((cell for cell in row if _text(cell.value).lower() == "status"), None)
        if status is not None:
            header_row, status_column = status.row, status.column
            run_column = next((cell.column for cell in row if _text(cell.value).lower().startswith("run id")), None)
            notes_column = next((cell.column for cell in row if _text(cell.value).lower().startswith("note")), 0)
            break
    if header_row is None or run_column is None:
        raise TrackerError(f"{ws.title}: no header row with 'Run ID' and 'Status' columns")
    first_row = header_row + 1
    for row in range(header_row + 1, header_row + 6):
        match = _ROW_OFFSET_RE.search(_text(ws.cell(row, run_column).value))
        if match:
            first_row = int(match[1]) + 1
            break
    return run_column, status_column, notes_column, first_row


def _completed_cell(ws, workbook: Path) -> str:
    """The value cell (column D) of the "Completed on" detail above the sweep table, when it is blank; else ""."""
    for row in range(1, _sweep_row(ws, workbook)):
        if _text(ws.cell(row, 1).value).lower().startswith("completed"):
            value = ws.cell(row, 4).value
            blank = value is None or (isinstance(value, str) and not value.strip())
            return ws.cell(row, 4).coordinate if blank else ""
    return ""


def read_matrix(workbook: Path, sheet: str) -> Matrix:
    """The sheet's run matrix, laid out as its formulas lay it out: Mach slowest, then altitude, AoA, elevator, beta."""
    from openpyxl.utils import get_column_letter

    workbook = Path(workbook)
    ws = _sheet(workbook, sheet)
    run_column, status_column, notes_column, first_row = _header_columns(ws)
    levels = _sweep_levels(ws, workbook)
    total = prod(max(1, len(values)) for values in levels) if any(levels) else 0
    counts = [max(1, len(values)) for values in levels]
    rows = []
    for i in range(total):
        row = first_row + i
        if ws.cell(row, run_column).value is None:  # past the template's formula rows
            break
        indices, rest = [], i
        for count in reversed(counts):
            indices.append(rest % count)
            rest //= count
        indices.reverse()
        values = [level[index] if level else 0.0 for level, index in zip(levels, indices)]
        value = ws.cell(row, notes_column).value if notes_column else None
        notes = "" if value is None else str(value).strip()  # a formula reads as its text, "=..."
        rows.append(MatrixRow(row, f"RUN-{i + 1:04d}", key(*values), _text(ws.cell(row, status_column).value), notes))
    return Matrix(sheet, get_column_letter(status_column), rows, levels, _completed_cell(ws, workbook),
                  get_column_letter(notes_column) if notes_column else "")


@dataclass(frozen=True)
class Change:
    row: MatrixRow
    status: str  # the new one
    source: CaseStatus


@dataclass(frozen=True)
class Plan:
    changes: list[Change]
    unchanged: int  # rows a job knows that already agree, or where it has nothing better than the sheet
    kept: list[Change]  # verdicts entered by hand that a job disagrees with: what it would have set
    outside: list[CaseStatus]  # cases no row of the matrix is for


def plan_changes(matrix: Matrix, statuses: dict[Key, CaseStatus], overwrite: bool = False) -> Plan:
    """The Status cells to change. A verdict in the sheet (Converged, Not Converged, Diverged, Failed) is kept when a
    job gives another one, unless `overwrite`: it may be a judgement AeroSuite's convergence check does not make.
    Running and Pending always replace it (the case runs again); Hold (a job that never ran it) never does, and
    Diverged stays when a job says Not Converged or Failed. Failed becomes Diverged when the job says so: the same
    failure, said more exactly."""
    changes, kept, unchanged = [], [], 0
    for row in matrix.rows:
        entry = statuses.get(row.key)
        if entry is None:
            continue
        verdict = row.status in VERDICTS
        if row.status == entry.status or (verdict and entry.status == HOLD) or (
                row.status == DIVERGED and entry.status in (NOT_CONVERGED, FAILED)):
            unchanged += 1
        elif verdict and entry.status in VERDICTS and not overwrite and not (
                row.status == FAILED and entry.status == DIVERGED):
            kept.append(Change(row, entry.status, entry))
        else:
            changes.append(Change(row, entry.status, entry))
    in_matrix = {row.key for row in matrix.rows}
    outside = [entry for case_key, entry in statuses.items() if case_key not in in_matrix]
    return Plan(changes, unchanged, kept, outside)


_SWEEP_NAMES = ("Mach", "altitude", "AoA", "elevator", "sideslip")


def outside_reason(matrix: Matrix, case_key: Key) -> str:
    """Why no row of the matrix is for a case: the first of its values the sheet's sweep does not have."""
    from .naming import format_value

    for name, value, level in zip(_SWEEP_NAMES, case_key, matrix.levels):
        if round(value, 6) not in {round(v, 6) for v in (level or [0.0])}:
            return f"{name} {format_value(value)} is not in the sheet's sweep"
    return "the sheet's run matrix stops before its row"


def completion_date(matrix: Matrix, plan: Plan, statuses: dict[Key, CaseStatus]) -> Optional[date]:
    """What "Completed on" becomes with the plan written: the day the last of the runs' jobs ended, once every run
    has a verdict (Converged, Not Converged, Diverged, Failed). None while one has not, or when the cell is not
    blank: a date entered by hand stays."""
    if not matrix.completed_on or not matrix.rows:
        return None
    status = {row.row: row.status for row in matrix.rows} | {change.row.row: change.status for change in plan.changes}
    if any(text not in VERDICTS for text in status.values()):
        return None
    ended = [entry.finished for row in matrix.rows if (entry := statuses.get(row.key)) and entry.finished]
    return max(ended).date() if ended else date.today()


# --- writing ---------------------------------------------------------------------------------------------------------

def lock_files(workbook: Path) -> list[tuple[str, Path]]:
    """(application, lock file) for each office program that marks the workbook open beside it: Excel's owner file
    (~$name; Excel drops two characters of a long name) and LibreOffice's .~lock.name#."""
    return [("Excel", workbook.with_name("~$" + workbook.name)), ("Excel", workbook.with_name("~$" + workbook.name[2:])),
            ("LibreOffice", workbook.with_name(f".~lock.{workbook.name}#"))]


def _office_lock(workbook: Path) -> Optional[tuple[str, Path]]:
    """The application that has the workbook open, and its lock file; None when no lock file is there."""
    return next(((app, path) for app, path in lock_files(workbook) if path.exists()), None)


def _sheet_part(archive: zipfile.ZipFile, sheet: str) -> str:
    """The zip entry holding a sheet, e.g. xl/worksheets/sheet3.xml."""
    book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rel_id = next((element.get(f"{{{_REL_NS}}}id") for element in book.iter(f"{{{_MAIN_NS}}}sheet")
                   if element.get("name") == sheet), None)
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = next((element.get("Target") for element in rels.iter(f"{{{_PKG_REL_NS}}}Relationship")
                   if element.get("Id") == rel_id), None)
    if rel_id is None or target is None:
        raise TrackerError(f"No sheet {sheet!r} in the workbook")
    return target.lstrip("/") if target.startswith("/") else f"xl/{target}"


def _column_number(reference: str) -> int:
    number = 0
    for char in re.match(r"[A-Z]+", reference)[0]:
        number = number * 26 + ord(char) - 64
    return number


_CELL_RE = re.compile(r"<c\b(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</c>)", re.DOTALL)
_REF_RE = re.compile(r'\br="([A-Z]+\d+)"')
_EXCEL_EPOCH = datetime(1899, 12, 30)

CellValue = object  # text, a number, a date or None (an empty cell)


def _cell_xml(attrs: str, value: CellValue) -> str:
    """A <c> element with `attrs` (its r and style; any type is replaced) holding `value`. A date is written as
    Excel's day number: the cell's style shows it as a date."""
    attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if isinstance(value, datetime):
        value = (value - _EXCEL_EPOCH).total_seconds() / 86400
    if value is None or value == "":
        return f"<c{attrs}/>"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"<c{attrs}><v>{float(value):.15g}</v></c>"
    return f'<c{attrs} t="inlineStr"><is><t>{html.escape(str(value), quote=False)}</t></is></c>'


def _set_cell(row_xml: str, reference: str, value: CellValue) -> str:
    """A <row> element's inner XML with cell `reference` holding `value` (its style kept)."""
    column = _column_number(reference)
    new = _cell_xml(f' r="{reference}"', value)
    for match in _CELL_RE.finditer(row_xml):
        found = _REF_RE.search(match["attrs"])
        if found is None:
            continue
        if found[1] == reference:
            return f'{row_xml[:match.start()]}{_cell_xml(match["attrs"], value)}{row_xml[match.end():]}'
        if _column_number(found[1]) > column:
            return f'{row_xml[:match.start()]}{new}{row_xml[match.start():]}'
    return f'{row_xml}{new}'


def _set_cells(sheet_xml: str, cells: dict[str, CellValue]) -> str:
    """The sheet's XML with each cell ({"M5": value}) set; a row the XML lacks is added in its place."""
    by_row: dict[int, dict[str, CellValue]] = {}
    for reference, value in cells.items():
        by_row.setdefault(int(re.search(r"\d+", reference)[0]), {})[reference] = value

    def replace(match: re.Match) -> str:
        row = int(match["row"])
        if row not in by_row:
            return match[0]
        done.add(row)
        inner = match["inner"] or ""
        for reference, value in by_row[row].items():
            inner = _set_cell(inner, reference, value)
        return f'{match["open"].rstrip("/").rstrip()}>{inner}</row>'

    done: set[int] = set()
    pattern = re.compile(r'(?P<open><row\b[^>]*?\br="(?P<row>\d+)"[^>]*?)(?:/>|>(?P<inner>.*?)</row>)', re.DOTALL)
    sheet_xml = pattern.sub(replace, sheet_xml)
    for row in sorted(set(by_row) - done):
        filled = sorted((ref, value) for ref, value in by_row[row].items() if value is not None and value != "")
        if not filled:
            continue
        new = f'<row r="{row}">' + "".join(_cell_xml(f' r="{ref}"', value) for ref, value in
                                           sorted(filled, key=lambda item: _column_number(item[0]))) + "</row>"
        after = next((match for match in pattern.finditer(sheet_xml) if int(match["row"]) > row), None)
        if after is not None:
            sheet_xml = sheet_xml[:after.start()] + new + sheet_xml[after.start():]
        elif "</sheetData>" in sheet_xml:
            sheet_xml = sheet_xml.replace("</sheetData>", new + "</sheetData>", 1)
        elif re.search(r"<sheetData\s*/>", sheet_xml):
            sheet_xml = re.sub(r"<sheetData\s*/>", f"<sheetData>{new}</sheetData>", sheet_xml, count=1)
        else:
            raise TrackerError("The sheet's XML has no sheetData")
    return sheet_xml


def _recalculate_on_open(book_xml: str) -> str:
    """Ask Excel to recalculate on open, so the scorecard's COUNTIFs count the new statuses."""
    if re.search(r'<calcPr\b[^>]*\bfullCalcOnLoad=', book_xml):
        return re.sub(r'(<calcPr\b[^>]*\bfullCalcOnLoad=")[^"]*"', r'\g<1>1"', book_xml, count=1)
    if "<calcPr" in book_xml:
        return book_xml.replace("<calcPr", '<calcPr fullCalcOnLoad="1"', 1)
    return book_xml  # no calcPr to amend; Excel counts again on the next edit


def _bytes(data: Union[str, bytes]) -> bytes:
    return data.encode("utf-8") if isinstance(data, str) else data


BACKUPS_KEPT = 7  # daily copies of a workbook: a week of the days it was written on


def backups_dir(workbook: Path) -> Path:
    """Where a workbook's daily copies are kept: <name>.backups beside it."""
    workbook = Path(workbook)
    return workbook.with_name(f"{workbook.stem}.backups")


def daily_backups(workbook: Path) -> list[tuple[date, Path]]:
    """The workbook's daily copies, newest first: each is the workbook as it was before that day's first write."""
    workbook = Path(workbook)
    found = []
    for path in backups_dir(workbook).glob(f"{workbook.stem}.*{workbook.suffix}"):
        try:
            found.append((date.fromisoformat(path.name[len(workbook.stem) + 1:-len(workbook.suffix)]), path))
        except ValueError:
            continue  # not one of ours
    return sorted(found, reverse=True)


def _keep_daily(workbook: Path) -> None:
    """Before the day's first write: a copy of the workbook in backups_dir, named by the day. The .bak beside the
    workbook is only one write old, and automatic writes come often; these go back a week. Older ones are removed."""
    folder = backups_dir(workbook)
    today = folder / f"{workbook.stem}.{date.today():%Y-%m-%d}{workbook.suffix}"
    if today.exists():
        return
    folder.mkdir(exist_ok=True)
    shutil.copy2(workbook, today)
    for _day, old in daily_backups(workbook)[BACKUPS_KEPT:]:
        old.unlink(missing_ok=True)


def _rewrite(workbook: Path, edit: Callable[[zipfile.ZipFile], dict[str, Union[str, bytes]]], again: str) -> Path:
    """Save the workbook with the parts `edit` returns ({zip entry: XML or bytes}, new ones added at the end), every
    other entry copied byte for byte. The previous file is kept as <name>.bak.xlsx (still a workbook Excel opens), which
    is returned, and the day's first write keeps a daily copy (_keep_daily). `again` ends the message when Excel has
    it open. One program writes a workbook at a time (the lock is in its backups folder)."""
    workbook = Path(workbook)
    with file_lock(backups_dir(workbook) / ".write") if workbook.is_file() else nullcontext():
        return _rewrite_locked(workbook, edit, again)


def _rewrite_locked(workbook: Path, edit: Callable[[zipfile.ZipFile], dict[str, Union[str, bytes]]],
                    again: str) -> Path:
    lock = _office_lock(workbook)
    if lock is not None:
        raise TrackerError(f"{workbook.name} is open in {lock[0]} ({lock[1].name} exists); close it and {again}")
    backup = workbook.with_name(f"{workbook.stem}.bak{workbook.suffix}")
    tmp = workbook.with_name(f".{workbook.name}.tmp")
    try:
        with zipfile.ZipFile(workbook) as archive:
            parts = edit(archive)
            with zipfile.ZipFile(tmp, "w") as out:
                for info in archive.infolist():
                    data = parts.pop(info.filename, None)
                    out.writestr(info, archive.read(info) if data is None else _bytes(data))
                for name, data in parts.items():
                    info = zipfile.ZipInfo(name, date_time=datetime.now().timetuple()[:6])
                    info.compress_type = zipfile.ZIP_DEFLATED
                    out.writestr(info, _bytes(data))
        shutil.copymode(workbook, tmp)
        _keep_daily(workbook)
        shutil.copy2(workbook, backup)
        os.replace(tmp, workbook)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        tmp.unlink(missing_ok=True)
        raise TrackerError(f"Cannot update {workbook}: {exc}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup


def write_statuses(workbook: Path, sheet: str, column: str, values: dict[int, str],
                   also: Optional[dict[str, CellValue]] = None) -> Path:
    """Set Status cells ({row: text}), and the cells `also` names ({"D11": value}), in place, keeping every other byte
    of the workbook. Returns the backup."""
    def edit(archive: zipfile.ZipFile) -> dict[str, str]:
        part = _sheet_part(archive, sheet)
        cells = {f"{column}{row}": text for row, text in values.items()} | (also or {})
        return {part: _set_cells(archive.read(part).decode("utf-8"), cells),
                "xl/workbook.xml": _recalculate_on_open(archive.read("xl/workbook.xml").decode("utf-8"))}

    return _rewrite(workbook, edit, "sync again")


# --- a new sheet from a template sheet -------------------------------------------------------------------------------

_BAD_NAME_RE = re.compile(r"[\[\]:*?/\\]")
_WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_COPIED_RELS = ("/drawing", "/printerSettings")  # a sheet's own parts (a text box, print settings) a copy copies


@dataclass(frozen=True)
class Detail:
    row: int
    label: str  # in column A, e.g. "Case Name"
    value: CellValue  # in column D of the template: text, a number, a date or None


@dataclass(frozen=True)
class Template:
    sheet: str
    details: list[Detail]  # the case's description above the sweep table
    sweep_row: int  # the sweep table's header row: the values go from two rows below, at most 100 per parameter
    runs: int  # how many runs its formula rows hold
    status_column: str
    first_row: int  # of the runs


def read_template(workbook: Path, sheet: str) -> Template:
    """What a new sheet copied from `sheet` can be given: the details in column D (a label in A, and no formula, above
    the sweep table) and the sweep values; and how many runs it holds."""
    from openpyxl.utils import get_column_letter

    workbook = Path(workbook)
    ws = _sheet(workbook, sheet)
    run_column, status_column, first_row = _run_columns(ws)
    sweep_row = _sweep_row(ws, workbook)
    covered = {(row, 4) for merged in ws.merged_cells.ranges for row in range(merged.min_row, merged.max_row + 1)
               if merged.min_col < 4 <= merged.max_col}  # D inside a merge from further left: a heading
    details = []
    for row in range(1, sweep_row):
        label, value = ws.cell(row, 1).value, ws.cell(row, 4).value
        if not isinstance(label, str) or not label.strip() or label.startswith("=") or (row, 4) in covered:
            continue
        if (isinstance(value, str) and value.startswith("=")) or not (
                value is None or isinstance(value, (str, int, float, datetime))):
            continue  # a formula
        details.append(Detail(row, label.strip(), value))
    runs = 0
    while ws.cell(first_row + runs, run_column).value is not None:
        runs += 1
    return Template(sheet, details, sweep_row, runs, get_column_letter(status_column), first_row)


def template_sheets(workbook: Path) -> list[str]:
    """The workbook's sheets named as templates, the likeliest first: the visible ones from the last."""
    wb = _load(Path(workbook))
    named = [ws for ws in wb.worksheets if "template" in ws.title.lower()]
    return [ws.title for ws in reversed(named) if ws.sheet_state == "visible"] + [
        ws.title for ws in named if ws.sheet_state != "visible"]


def parse_values(text: str, what: str) -> list[float]:
    """Sweep values typed as a list: "0.3, 0.6, 0.9" (commas or spaces between them)."""
    try:
        return [float(part) for part in re.split(r"[,;\s]+", text.strip()) if part]
    except ValueError:
        raise TrackerError(f"{what}: give numbers separated by commas, e.g. 0.3, 0.6, 0.9") from None


def detail_value(detail: Detail, text: str) -> CellValue:
    """A case detail typed as text, as the cell takes it: a number or a date (YYYY-MM-DD) where the template has one."""
    text = text.strip()
    if not text:
        return None
    if isinstance(detail.value, datetime):
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            raise TrackerError(f"{detail.label}: give a date as YYYY-MM-DD, not {text!r}") from None
    if isinstance(detail.value, (int, float)):
        try:
            return float(text)
        except ValueError:
            raise TrackerError(f"{detail.label}: give a number, not {text!r}") from None
    return text


def sheet_name_problem(workbook: Path, name: str) -> str:
    """Why Excel would not take `name` for a new sheet of the workbook; "" when it would."""
    if not name.strip():
        return "Give the new sheet a name."
    if len(name) > 31:
        return f"A sheet name has at most 31 characters; this one has {len(name)}."
    if _BAD_NAME_RE.search(name):
        return "A sheet name cannot contain : \\ / ? * [ or ]."
    if name.startswith("'") or name.endswith("'"):
        return "A sheet name cannot start or end with an apostrophe."
    if name.strip().lower() == "history":
        return "Excel keeps the name History for itself."
    taken = next((existing for existing in sheet_names(workbook) if existing.lower() == name.lower()), None)
    return f"The workbook already has a sheet named {taken}." if taken else ""


def project_levels(projects: Iterable[tuple[Path, float]]) -> list[list[float]]:
    """The sweep the projects' cases make, each parameter's values sorted: Mach, altitude, AoA and sideslip from the
    cases in configs/cases.json, those their jobs ran and their run folders; the elevator from each project's."""
    seen: list[set[float]] = [set() for _ in range(5)]
    for folder, elevator in projects:
        folder = Path(folder)
        index = load_case_index(folder / CONFIGS_DIR)
        names = set(index)
        jobs, _ = scan_jobs(folder)
        for job in jobs:
            names.update(job.cases)
        runs = folder / RUNS_DIR
        if runs.is_dir():
            names.update(path.name for path in runs.iterdir() if path.is_dir())
        seen[3].add(round(float(elevator), 6))
        for name in names:
            values = _case_values(name, index)
            if values is not None:
                for i, value in zip((0, 1, 2, 4), values):
                    seen[i].add(round(float(value), 6))
    return [sorted(values) for values in seen]


def _quoted(sheet: str) -> str:
    return "'" + sheet.replace("'", "''") + "'"


def _renamed(text: str, old: str, new: str) -> str:
    """Formula text with references to sheet `old` made references to `new`."""
    text = text.replace(html.escape(_quoted(old), quote=False) + "!", html.escape(_quoted(new), quote=False) + "!")
    if re.fullmatch(r"\w+", old):
        text = re.sub(rf"(?<![\w'.]){re.escape(old)}!", html.escape(_quoted(new), quote=False) + "!", text)
    return text


def _free(names: set[str], pattern: str) -> str:
    number = 1
    while pattern.format(number) in names:
        number += 1
    return pattern.format(number)


def _rels_of(part: str) -> str:
    folder, _, name = part.rpartition("/")
    return f"{folder}/_rels/{name}.rels"


def _part_of(source: str, target: str) -> str:
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(
        posixpath.join(posixpath.dirname(source), target))


def _attr(element: str, name: str) -> Optional[str]:
    found = re.search(rf'\s{name}="([^"]*)"', element)
    return html.unescape(found[1]) if found else None


def _content_type(types: str, part: str) -> Optional[str]:
    found = re.search(rf'<Override\b[^>]*PartName="/{re.escape(part)}"[^>]*>', types)
    return _attr(found[0], "ContentType") if found else None


def _sheet_copy(sheet_xml: str, template: str, name: str) -> str:
    """The template's XML as its copy's: its own ids, not the selected tab, no code name (Excel gives it one)."""
    ids: dict[str, str] = {}

    def new_id(match: re.Match) -> str:
        return f'{match[1]}"{ids.setdefault(match[2], "{" + str(uuid.uuid4()).upper() + "}")}"'

    sheet_xml = re.sub(r'(\bxr\d?:uid=)"([^"]*)"', new_id, sheet_xml)
    sheet_xml = re.sub(r'\s+tabSelected="[^"]*"', "", sheet_xml)
    sheet_xml = re.sub(r'(<sheetPr\b[^>]*?)\s+codeName="[^"]*"', r"\1", sheet_xml)
    return re.sub(r"<f\b([^>]*)>(.*?)</f>", lambda m: f"<f{m[1]}>{_renamed(m[2], template, name)}</f>", sheet_xml,
                  flags=re.DOTALL)


def _listed(app_xml: str, name: str) -> str:
    """docProps/app.xml with `name` added to its list of worksheets; unchanged if the list is not as Excel writes it."""
    heads = re.search(r"<HeadingPairs>(.*?)</HeadingPairs>", app_xml, re.DOTALL)
    titles = re.search(r'(<TitlesOfParts>\s*<vt:vector size=")(\d+)("[^>]*>)(.*?)(</vt:vector>)', app_xml, re.DOTALL)
    if heads is None or titles is None:
        return app_xml
    pairs = re.findall(r"<vt:lpstr>([^<]*)</vt:lpstr>\s*</vt:variant>\s*<vt:variant>\s*<vt:i4>(\d+)</vt:i4>",
                       heads[1])
    offset = 0
    for heading, count in pairs:
        if heading == "Worksheets":
            break
        offset += int(count)
    else:
        return app_xml
    items = re.findall(r"<vt:lpstr>.*?</vt:lpstr>", titles[4], re.DOTALL)
    at = offset + int(dict(pairs)["Worksheets"])
    items.insert(at, f"<vt:lpstr>{html.escape(name, quote=False)}</vt:lpstr>")
    counted = re.sub(r"(<vt:lpstr>Worksheets</vt:lpstr>\s*</vt:variant>\s*<vt:variant>\s*<vt:i4>)(\d+)",
                     lambda m: f"{m[1]}{int(m[2]) + 1}", heads[0], count=1)
    app_xml = app_xml.replace(heads[0], counted, 1)
    return app_xml.replace(titles[0], f"{titles[1]}{len(items)}{titles[3]}{''.join(items)}{titles[5]}", 1)


def _add_sheet(archive: zipfile.ZipFile, template: str, name: str,
               cells: dict[str, CellValue]) -> dict[str, Union[str, bytes]]:
    """The parts that make a copy of sheet `template`, named `name`, the workbook's last sheet: its XML (with `cells`
    set) and its own text box, and the workbook's list of sheets, parts and content types."""
    names = set(archive.namelist())
    book = archive.read("xl/workbook.xml").decode("utf-8")
    book_rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    types = archive.read("[Content_Types].xml").decode("utf-8")
    part = _sheet_part(archive, template)
    new_part = _free(names, "xl/worksheets/sheet{}.xml")
    copied = _set_cells(archive.read(part).decode("utf-8"), cells)
    parts: dict[str, Union[str, bytes]] = {new_part: _sheet_copy(copied, template, name)}
    overrides = [(new_part, _content_type(types, part))]
    if _rels_of(part) in names:
        rels = archive.read(_rels_of(part)).decode("utf-8")
        for element in re.findall(r"<Relationship\b[^>]*>", rels):
            kind, target = _attr(element, "Type") or "", _attr(element, "Target") or ""
            if _attr(element, "TargetMode") == "External":
                continue
            if not kind.endswith(_COPIED_RELS):
                raise TrackerError(f"{template} has a {kind.rpartition('/')[2]} part AeroSuite cannot copy; copy the "
                                   f"sheet in Excel instead")
            source = _part_of(part, target)
            numbered = re.sub(r"\d*(\.\w+)$", r"{}\1", source)  # xl/drawings/drawing1.xml -> drawing{}.xml
            copy = _free(names | set(parts), numbered)
            parts[copy] = archive.read(source)
            if _rels_of(source) in names:
                own = archive.read(_rels_of(source)).decode("utf-8")
                if "/chart" in own:
                    raise TrackerError(f"{template} has a chart AeroSuite cannot copy; copy the sheet in Excel instead")
                parts[_rels_of(copy)] = own  # its pictures are shared
            overrides.append((copy, _content_type(types, source)))
            rels = rels.replace(element, element.replace(
                f'Target="{target}"', f'Target="{posixpath.relpath(copy, posixpath.dirname(new_part))}"'))
        parts[_rels_of(new_part)] = rels
    # the workbook's list: the copy's <sheet> after the last, with the template's own names (its filter range)
    sheets = re.findall(r"<sheet\b[^>]*/>", book)
    index = next((i for i, element in enumerate(sheets) if _attr(element, "name") == template), None)
    rel_ids = set(re.findall(r'\bId="([^"]+)"', book_rels))
    rel_id = _free(rel_ids, "rId{}")
    sheet_id = max(int(_attr(element, "sheetId") or 0) for element in sheets) + 1
    element = re.sub(r'\s+state="[^"]*"', "", sheets[index])
    element = re.sub(r'\bname="[^"]*"', f'name="{html.escape(name, quote=True)}"', element)
    element = re.sub(r'\bsheetId="\d+"', f'sheetId="{sheet_id}"', element)
    element = re.sub(r'(:id=)"[^"]*"', rf'\1"{rel_id}"', element)
    book = book.replace(sheets[-1], sheets[-1] + element, 1)
    local = [found for found in re.findall(r"<definedName\b[^>]*>.*?</definedName>", book, re.DOTALL)
             if _attr(found, "localSheetId") == str(index)]
    copies = "".join(re.sub(r'localSheetId="\d+"', f'localSheetId="{len(sheets)}"', _renamed(found, template, name))
                     for found in local)
    if copies:
        book = book.replace("</definedNames>", copies + "</definedNames>", 1)
    parts["xl/workbook.xml"] = _recalculate_on_open(book)
    parts["xl/_rels/workbook.xml.rels"] = book_rels.replace(
        "</Relationships>", f'<Relationship Id="{rel_id}" Type="{_WORKSHEET_REL}" '
                            f'Target="{posixpath.relpath(new_part, "xl")}"/></Relationships>', 1)
    added = "".join(f'<Override PartName="/{copy}" ContentType="{content}"/>' for copy, content in overrides if content)
    parts["[Content_Types].xml"] = types.replace("</Types>", added + "</Types>", 1)
    if "docProps/app.xml" in names:
        parts["docProps/app.xml"] = _listed(archive.read("docProps/app.xml").decode("utf-8"), name)
    return parts


def new_sheet(workbook: Path, template: str, name: str, details: dict[int, CellValue],
              levels: list[list[float]]) -> Path:
    """Add sheet `name` to the workbook, last: a copy of sheet `template` with its details ({row: value}, in column D)
    and sweep values (Mach, altitude, AoA, elevator, sideslip, in columns A-E) set and its Status column empty.
    Every other part of the file is kept byte for byte. Returns the backup."""
    workbook = Path(workbook)
    problem = sheet_name_problem(workbook, name)
    if problem:
        raise TrackerError(problem)
    layout = read_template(workbook, template)
    if len(levels) != 5:
        raise TrackerError("Give the sweep's values for Mach, altitude, AoA, elevator and sideslip")
    for axis, values in zip(_SWEEP_NAMES, levels):
        if len(values) > _SWEEP_LEVELS:
            raise TrackerError(f"The sheet takes at most {_SWEEP_LEVELS} {axis} values; {len(values)} were given")
        if len({round(v, 6) for v in values}) != len(values):
            raise TrackerError(f"A {axis} value is given twice")
    if not levels[0]:
        raise TrackerError("Give at least one Mach number")
    runs = prod(max(1, len(values)) for values in levels)
    if runs > layout.runs:
        raise TrackerError(f"The sweep makes {runs} runs; {template} has rows for {layout.runs}")
    rows = {detail.row for detail in layout.details}
    unknown = sorted(set(details) - rows)
    if unknown:
        raise TrackerError(f"Row(s) {', '.join(map(str, unknown))} of {template} hold no case detail")
    ws = _sheet(workbook, template)
    cells: dict[str, CellValue] = {f"D{row}": value for row, value in details.items()}
    for column, values in enumerate(levels, 1):
        for i in range(_SWEEP_LEVELS):
            row = layout.sweep_row + 2 + i
            value = values[i] if i < len(values) else None
            if value is not None or ws.cell(row, column).value is not None:
                cells[f"{'ABCDE'[column - 1]}{row}"] = value
    status = _column_number(layout.status_column)
    for row in range(layout.first_row, layout.first_row + layout.runs):
        if ws.cell(row, status).value is not None:
            cells[f"{layout.status_column}{row}"] = None
    return _rewrite(workbook, lambda archive: _add_sheet(archive, template, name, cells), "try again")

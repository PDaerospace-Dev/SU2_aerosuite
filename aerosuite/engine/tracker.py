"""Run-matrix workbooks: the Status column of a full-factorial run matrix sheet (Mach x altitude x AoA x elevator x
sideslip, as the CFD run-matrix template lays it out), kept in step with the projects' job records.

The sheet is read with openpyxl. It is written by editing only its Status cells in the sheet's XML, every other part
of the file copied byte for byte, so what openpyxl would drop on a save (text boxes, add-ins, SharePoint properties)
survives."""
from __future__ import annotations

import html
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from math import prod
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree

from .cfg import CONFIGS_DIR
from .errors import AeroSuiteError, TrackerError
from .imported import read_name
from .jobs.executors import runner_of
from .jobs.runner import CaseState, JobRecord
from .jobs.store import scan_jobs
from .results import load_case_index

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
DIVERGED = "Diverged"  # set by hand: AeroSuite cannot tell divergence from non-convergence
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
) -> tuple[dict[Key, CaseStatus], list[str]]:
    """Each case's status from the newest job that ran it, over (project folder, elevator) pairs, and warnings.

    With `tags`, only jobs whose note has one of them count; jobs with any of `skip_tags` never do. A case a newer
    job cancelled (or never started) keeps an older job's result; Hold is shown only when no job has one."""
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
            values = _case_values(case, index)
            if values is None:
                names = unknown.setdefault(project_dir.name, [])
                if case not in names:
                    names.append(case)
                continue
            mach, altitude, alpha, beta = values
            case_key = key(mach, altitude, alpha, elevator, beta)
            entry = CaseStatus(STATUS_TEXT[state], project_dir.name, job.id, case)
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


# --- the sheet -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MatrixRow:
    row: int  # the sheet's row number
    run_id: str
    key: Key
    status: str  # in the sheet now; "" when blank


@dataclass(frozen=True)
class Matrix:
    sheet: str
    status_column: str  # its letter, e.g. "M"
    rows: list[MatrixRow]


def _load(workbook: Path):
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        return load_workbook(workbook)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TrackerError(f"Cannot read {workbook} as an .xlsx workbook: {exc}") from exc


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sweep_levels(ws, workbook: Path) -> list[list[float]]:
    """The values entered for each sweep parameter (Mach, altitude, AoA, elevator, beta), in sheet order."""
    for row in range(1, _SEARCH_ROWS + 1):
        headers = [_text(ws.cell(row, column).value).lower() for column in range(1, 6)]
        if not headers[0].startswith("mach"):
            continue
        if not all(any(word in header for word in words) for header, words in zip(headers, _SWEEP_HEADERS)):
            continue
        levels = []
        for column in range(1, 6):
            values = []
            for value_row in range(row + 2, row + 2 + _SWEEP_LEVELS):  # the row in between counts the levels
                value = ws.cell(value_row, column).value
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TrackerError(f"{ws.title}: {ws.cell(value_row, column).coordinate} is {value!r}, "
                                       f"not a number")
                values.append(float(value))
            levels.append(values)
        return levels
    raise TrackerError(f"{ws.title} in {workbook.name} has no sweep table (Mach, Altitude, AoA, Elevator, Sideslip "
                       f"headers in columns A-E)")


def read_matrix(workbook: Path, sheet: str) -> Matrix:
    """The sheet's run matrix, laid out as its formulas lay it out: Mach slowest, then altitude, AoA, elevator, beta."""
    from openpyxl.utils import get_column_letter

    workbook = Path(workbook)
    wb = _load(workbook)
    if sheet not in wb.sheetnames:
        raise TrackerError(f"No sheet {sheet!r} in {workbook.name}; it has: {', '.join(wb.sheetnames)}")
    ws = wb[sheet]
    header_row = status_column = run_column = None
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, _SEARCH_ROWS)):
        status = next((cell for cell in row if _text(cell.value).lower() == "status"), None)
        if status is not None:
            header_row, status_column = status.row, status.column
            run_column = next((cell.column for cell in row if _text(cell.value).lower().startswith("run id")), None)
            break
    if header_row is None or run_column is None:
        raise TrackerError(f"{sheet}: no header row with 'Run ID' and 'Status' columns")
    first_row = header_row + 1
    for row in range(header_row + 1, header_row + 6):
        match = _ROW_OFFSET_RE.search(_text(ws.cell(row, run_column).value))
        if match:
            first_row = int(match[1]) + 1
            break
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
        rows.append(MatrixRow(row, f"RUN-{i + 1:04d}", key(*values), _text(ws.cell(row, status_column).value)))
    return Matrix(sheet, get_column_letter(status_column), rows)


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
    Diverged stays when a job says Not Converged or Failed."""
    changes, kept, unchanged = [], [], 0
    for row in matrix.rows:
        entry = statuses.get(row.key)
        if entry is None:
            continue
        verdict = row.status in VERDICTS
        if row.status == entry.status or (verdict and entry.status == HOLD) or (
                row.status == DIVERGED and entry.status in (NOT_CONVERGED, FAILED)):
            unchanged += 1
        elif verdict and entry.status in VERDICTS and not overwrite:
            kept.append(Change(row, entry.status, entry))
        else:
            changes.append(Change(row, entry.status, entry))
    in_matrix = {row.key for row in matrix.rows}
    outside = [entry for case_key, entry in statuses.items() if case_key not in in_matrix]
    return Plan(changes, unchanged, kept, outside)


# --- writing ---------------------------------------------------------------------------------------------------------

def _excel_lock(workbook: Path) -> Optional[Path]:
    """Excel's owner file next to a workbook it has open (~$name; Excel drops two characters of a long name)."""
    for name in ("~$" + workbook.name, "~$" + workbook.name[2:]):
        path = workbook.with_name(name)
        if path.exists():
            return path
    return None


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


def _set_cell(row_xml: str, reference: str, text: str) -> str:
    """A <row> element's inner XML with cell `reference` holding the inline string `text` (its style kept)."""
    value = f'<is><t>{html.escape(text, quote=False)}</t></is>'
    column = _column_number(reference)
    for match in _CELL_RE.finditer(row_xml):
        found = _REF_RE.search(match["attrs"])
        if found is None:
            continue
        if found[1] == reference:
            attrs = re.sub(r'\s+t="[^"]*"', "", match["attrs"])
            return f'{row_xml[:match.start()]}<c{attrs} t="inlineStr">{value}</c>{row_xml[match.end():]}'
        if _column_number(found[1]) > column:
            return f'{row_xml[:match.start()]}<c r="{reference}" t="inlineStr">{value}</c>{row_xml[match.start():]}'
    return f'{row_xml}<c r="{reference}" t="inlineStr">{value}</c>'


def _set_cells(sheet_xml: str, column: str, values: dict[int, str]) -> str:
    def replace(match: re.Match) -> str:
        row = int(match["row"])
        if row not in values:
            return match[0]
        done.add(row)
        inner = _set_cell(match["inner"] or "", f"{column}{row}", values[row])
        return f'{match["open"].rstrip("/").rstrip()}>{inner}</row>'

    done: set[int] = set()
    pattern = re.compile(r'(?P<open><row\b[^>]*?\br="(?P<row>\d+)"[^>]*?)(?:/>|>(?P<inner>.*?)</row>)', re.DOTALL)
    sheet_xml = pattern.sub(replace, sheet_xml)
    missing = sorted(set(values) - done)
    if missing:
        raise TrackerError(f"Row(s) {', '.join(map(str, missing[:5]))} are not in the sheet's XML")
    return sheet_xml


def _recalculate_on_open(book_xml: str) -> str:
    """Ask Excel to recalculate on open, so the scorecard's COUNTIFs count the new statuses."""
    if re.search(r'<calcPr\b[^>]*\bfullCalcOnLoad=', book_xml):
        return re.sub(r'(<calcPr\b[^>]*\bfullCalcOnLoad=")[^"]*"', r'\g<1>1"', book_xml, count=1)
    if "<calcPr" in book_xml:
        return book_xml.replace("<calcPr", '<calcPr fullCalcOnLoad="1"', 1)
    return book_xml  # no calcPr to amend; Excel counts again on the next edit


def write_statuses(workbook: Path, sheet: str, column: str, values: dict[int, str]) -> Path:
    """Set Status cells ({row: text}) in place, keeping every other byte of the workbook. The previous file is kept
    as <name>.bak.xlsx (still a workbook Excel opens), which is returned."""
    workbook = Path(workbook)
    lock = _excel_lock(workbook)
    if lock is not None:
        raise TrackerError(f"{workbook.name} is open in Excel ({lock.name} exists); close it and sync again")
    backup = workbook.with_name(f"{workbook.stem}.bak{workbook.suffix}")
    tmp = workbook.with_name(f".{workbook.name}.tmp")
    try:
        with zipfile.ZipFile(workbook) as archive:
            part = _sheet_part(archive, sheet)
            with zipfile.ZipFile(tmp, "w") as out:
                for info in archive.infolist():
                    data = archive.read(info)
                    if info.filename == part:
                        data = _set_cells(data.decode("utf-8"), column, values).encode("utf-8")
                    elif info.filename == "xl/workbook.xml":
                        data = _recalculate_on_open(data.decode("utf-8")).encode("utf-8")
                    out.writestr(info, data)
        shutil.copymode(workbook, tmp)
        shutil.copy2(workbook, backup)
        os.replace(tmp, workbook)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        tmp.unlink(missing_ok=True)
        raise TrackerError(f"Cannot update {workbook}: {exc}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup

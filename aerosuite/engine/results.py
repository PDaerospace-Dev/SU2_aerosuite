"""SU2 results: history files, convergence and batch summaries."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import pandas as pd

from .cfg import CASE_INDEX_FILE
from .errors import ProjectError
from .naming import parse_case_name

HISTORY_FILE = "history.csv"
DEFAULT_CONVERGENCE_COLUMNS = ("CL", "CD", "CMy")
MIN_CONVERGENCE_ITERATIONS = 10
CONVERGENCE_THRESHOLD = 1e-3
ABSOLUTE_TOLERANCE = 1e-6  # a column this steady is converged whatever its mean
SUMMARY_KEY_COLUMNS = ["Case", "Mach", "Alpha", "Beta", "Converged"]
RESULTS_DIR = "results"
SUMMARY_FILE = "summary.csv"
ITERATION_COLUMNS = frozenset({"Time_Iter", "Outer_Iter", "Inner_Iter", "Cur_Time", "Iteration"})

# Parameter groups for the Results page's picker, from SU2's column names
GROUP_TOTALS = "Total coefficients"
GROUP_FLOW = "Flow & other"
GROUP_CONVERGENCE = "Convergence monitors"
GROUP_SOLVER = "Solver"
GROUP_RESIDUALS = "Residuals"
MARKER_GROUP = "Marker: {}"
_GROUP_RANK = {GROUP_TOTALS: 0, GROUP_FLOW: 2, GROUP_CONVERGENCE: 3, GROUP_SOLVER: 4, GROUP_RESIDUALS: 5}
# Groups that describe the solver, not the flow: never used to judge convergence
_NOT_FLOW = (GROUP_CONVERGENCE, GROUP_SOLVER, GROUP_RESIDUALS)


def _fields(line: str) -> list[str]:
    return [field.strip().strip('"').replace(" ", "") for field in line.split(",")]


class HistoryReader:
    """Reads an SU2 history file incrementally.

    Each read_new() returns only the complete rows appended since the previous call,
    so live monitoring never re-reads the whole file. If the file shrinks (the case
    was re-run), reading starts over.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.columns: list[str] = []
        self._offset = 0
        self.restarts = 0

    def read_new(self) -> pd.DataFrame:
        try:
            if self.path.stat().st_size < self._offset:
                self._offset, self.columns = 0, []
                self.restarts += 1
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read()
        except FileNotFoundError:
            return pd.DataFrame(columns=self.columns)
        end = chunk.rfind(b"\n")
        if end < 0:
            return pd.DataFrame(columns=self.columns)
        complete = chunk[: end + 1]
        self._offset += len(complete)
        rows = []
        for raw in complete.decode("utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("TITLE", "ZONE", "#")):
                continue
            if not self.columns:
                if line.startswith("VARIABLES"):
                    line = line.split("=", 1)[1]
                self.columns = _fields(line)
                continue
            try:
                values = [float(field) for field in _fields(line)]
            except ValueError:
                continue
            if len(values) == len(self.columns):
                rows.append(values)
        return pd.DataFrame(rows, columns=self.columns)


def read_history(path: Path) -> pd.DataFrame:
    return HistoryReader(path).read_new()


class HistoryBuffer:
    """Every row of a history file read so far, growing incrementally (for live monitoring)."""

    def __init__(self, path: Path):
        self._reader = HistoryReader(path)
        self._restarts = 0
        self.frame = pd.DataFrame()

    def read(self) -> pd.DataFrame:
        new = self._reader.read_new()
        if self._reader.restarts != self._restarts:  # the file shrank: the case was re-run
            self._restarts = self._reader.restarts
            self.frame = pd.DataFrame()
        if not new.empty:
            self.frame = new if self.frame.empty else pd.concat([self.frame, new], ignore_index=True)
        return self.frame


def check_convergence(
    df: pd.DataFrame, columns: Sequence[str] = DEFAULT_CONVERGENCE_COLUMNS
) -> tuple[bool, str]:
    """Converged when, over the last 10% (at least 10 rows), every column is steady.

    Steady: std below ABSOLUTE_TOLERANCE, or std/mean below CONVERGENCE_THRESHOLD.
    Without any of the requested columns there is no evidence, so not converged.
    """
    if len(df) < MIN_CONVERGENCE_ITERATIONS:
        return False, f"Insufficient iterations ({len(df)} < {MIN_CONVERGENCE_ITERATIONS})"
    check = [col for col in columns if col in df.columns]
    if not check:
        wanted = "/".join(columns)
        return False, f"No {wanted} columns in history; add them to HISTORY_OUTPUT to judge convergence"
    tail = df.tail(max(10, int(len(df) * 0.1)))
    for col in check:
        std = tail[col].std()
        if std < ABSOLUTE_TOLERANCE:
            continue
        mean = abs(tail[col].mean())
        if mean > 0 and std / mean > CONVERGENCE_THRESHOLD:
            return False, f"{col} not converged (std/mean = {std / mean:.2e})"
    return True, "Converged"


def history_header(path: Path) -> list[str]:
    """The column names of a history file (its first data header), or [] when it has none yet."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith(("TITLE", "ZONE", "#")):
                    continue
                if line.startswith("VARIABLES"):
                    line = line.split("=", 1)[1]
                return _fields(line)
    except OSError:
        pass
    return []


def case_histories(project_dir: Path, project=None) -> list[tuple[str, Path]]:
    """(case, history file) for every case with one: an imported study's recorded files, else runs/<case>/."""
    if project is not None and project.imported is not None:
        return [(case.name, Path(case.history)) for case in project.imported.cases]
    return [(path.parent.name, path) for path in sorted((Path(project_dir) / "runs").glob(f"*/{HISTORY_FILE}"))]


def imported_case_index(project) -> dict[str, dict]:
    """The case values of an imported study, as a case index (like configs/cases.json)."""
    return {case.name: {"mach": case.mach, "alpha": case.alpha, "beta": case.beta, "altitude_km": case.altitude_km,
                        "temperature_K": case.temperature_K, "config": case.base or None}
            for case in project.imported.cases}


def history_columns(project_dir: Path, project=None) -> list[str]:
    """Every parameter the study's history files hold (the union over cases, first seen first), without the
    iteration counters."""
    seen: dict[str, None] = {}
    for _, history in case_histories(project_dir, project):
        for column in history_header(history):
            if column not in ITERATION_COLUMNS:
                seen.setdefault(column)
    return list(seen)


def group_of(column: str) -> str:
    """The picker group of a history column: totals, one group per marker (CL(Wing), Avg_Massflow(outlet)), …"""
    if re.match(r"^(rms|max|bgs)\[", column, re.IGNORECASE):
        return GROUP_RESIDUALS
    if column.startswith("Cauchy"):
        return GROUP_CONVERGENCE
    if re.match(r"^(LinSol|Avg_CFL|Min_CFL|Max_CFL)", column):
        return GROUP_SOLVER
    marker = re.match(r"^(.+)\((.+)\)$", column)
    if marker:
        return MARKER_GROUP.format(marker.group(2))
    if re.match(r"^C[A-Z][A-Za-z]{0,3}$", column):
        return GROUP_TOTALS
    return GROUP_FLOW


def ordered_groups(columns: Iterable[str]) -> list[str]:
    """The groups present, totals first, then markers (by name), flow, and the solver groups last."""
    groups = dict.fromkeys(group_of(column) for column in columns)
    return sorted(groups, key=lambda group: (_GROUP_RANK.get(group, 1), group))


def convergence_columns(chosen: Iterable[str], derived: Iterable[str] = ()) -> list[str]:
    """The chosen parameters convergence is judged on: history columns that describe the flow."""
    derived = set(derived)
    return [c for c in chosen if c not in derived and group_of(c) not in _NOT_FLOW]


def load_case_index(configs_dir: Path) -> dict[str, dict[str, float]]:
    """cases.json written by generate_configs, or {} for legacy runs."""
    path = Path(configs_dir) / CASE_INDEX_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"Cannot read {path}: {exc}") from exc


def summarize(
    runs_dir: Path,
    columns: Sequence[str],
    last_n: int = 100,
    case_index: Optional[Mapping[str, Mapping[str, float]]] = None,
    skip: Iterable[str] = (),
    convergence_columns: Optional[Sequence[str]] = None,
    histories: Optional[Sequence[tuple[str, Path]]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Average the last `last_n` rows of every case's history into one table.

    The histories are `histories` ((case, file) pairs), else every history file under `runs_dir`. Converged is
    judged on `convergence_columns` (default: CL, CD, CMy); an empty list means not judged (None). Temperature
    and Config columns appear when the case index gives them.
    """
    case_index = case_index or {}
    skip = set(skip)
    rows, warnings = [], []
    if histories is None:
        histories = [(path.parent.name, path) for path in sorted(Path(runs_dir).rglob(HISTORY_FILE))]
    for name, history in histories:
        if name in skip:
            continue
        altitude = temperature = config = None
        if name in case_index:
            values = case_index[name]
            mach, alpha, beta = values.get("mach"), values.get("alpha"), values.get("beta")
            altitude = values.get("altitude_km")
            temperature, config = values.get("temperature_K"), values.get("config")
        else:
            mach, alpha, beta = parse_case_name(name)
        if alpha is None:
            warnings.append(f"{name}: cannot determine alpha from the case name, skipped")
            continue
        df = read_history(history)
        if df.empty:
            warnings.append(f"{name}: history file is empty, skipped")
            continue
        if convergence_columns is None:
            converged, message = check_convergence(df)
        elif not convergence_columns:
            converged, message = None, ""
        else:
            converged, message = check_convergence(df, convergence_columns)
        if converged is False:
            warnings.append(f"{name}: {message}")
        averages = df.tail(max(1, min(last_n, len(df)))).mean(numeric_only=True)
        row = {"Case": name, "Config": config, "Altitude": altitude, "Temperature": temperature, "Mach": mach,
               "Alpha": alpha, "Beta": beta, "Converged": converged}
        for col in columns:
            row[col] = averages.get(col, float("nan"))
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=SUMMARY_KEY_COLUMNS + list(columns)), warnings
    summary = pd.DataFrame(rows)
    order = ["Mach", "Beta", "Alpha"]
    for column in ("Temperature", "Altitude", "Config"):  # only when some case has one: else as before
        if summary[column].isna().all():
            summary = summary.drop(columns=column)
        else:
            order.insert(0, column)
    summary = summary.sort_values(order, na_position="last").reset_index(drop=True)
    return summary, warnings


def write_summary(project_dir: Path, summary: pd.DataFrame) -> Path:
    """Save a summary table to results/summary.csv and return its path."""
    path = Path(project_dir) / RESULTS_DIR / SUMMARY_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(path, index=False)
    except OSError as exc:
        raise ProjectError(f"Cannot write {path}: {exc}") from exc
    return path

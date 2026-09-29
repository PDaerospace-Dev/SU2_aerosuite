"""SU2 results: history files, convergence and batch summaries."""
from __future__ import annotations

import json
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
) -> tuple[pd.DataFrame, list[str]]:
    """Average the last `last_n` rows of every case's history into one table."""
    case_index = case_index or {}
    skip = set(skip)
    rows, warnings = [], []
    for history in sorted(Path(runs_dir).rglob(HISTORY_FILE)):
        name = history.parent.name
        if name in skip:
            continue
        altitude = None
        if name in case_index:
            values = case_index[name]
            mach, alpha, beta = values.get("mach"), values.get("alpha"), values.get("beta")
            altitude = values.get("altitude_km")
        else:
            mach, alpha, beta = parse_case_name(name)
        if alpha is None:
            warnings.append(f"{name}: cannot determine alpha from the case name, skipped")
            continue
        df = read_history(history)
        if df.empty:
            warnings.append(f"{name}: history file is empty, skipped")
            continue
        converged, message = check_convergence(df)
        if not converged:
            warnings.append(f"{name}: {message}")
        averages = df.tail(max(1, min(last_n, len(df)))).mean(numeric_only=True)
        row = {"Case": name, "Altitude": altitude, "Mach": mach, "Alpha": alpha, "Beta": beta, "Converged": converged}
        for col in columns:
            row[col] = averages.get(col, float("nan"))
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=SUMMARY_KEY_COLUMNS + list(columns)), warnings
    summary = pd.DataFrame(rows)
    order = ["Mach", "Beta", "Alpha"]
    if summary["Altitude"].isna().all():  # no altitude sweep: the table is as before
        summary = summary.drop(columns="Altitude")
    else:
        order.insert(0, "Altitude")
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

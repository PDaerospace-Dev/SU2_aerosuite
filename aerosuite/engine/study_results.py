"""A study's results for the Results page: averaged parameters, derived values per case and characteristic values
per curve, computed with the page's definitions (a compared study is read with the current study's definitions)."""
from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

import pandas as pd

from .atmosphere import ISACalculator
from .cfg import CONFIGS_DIR, CASE_INDEX_FILE, case_mach, read_template
from .errors import AeroSuiteError
from .formula import FormulaError, Missing, curve_axes, evaluate, evaluate_curve, parse
from .freestream import altitude_error, case_altitude
from .models import Case, Project
from .project import PROJECT_FILE, open_project
from .restarts import RUNS_DIR
from .results import (RESULTS_DIR, case_histories, convergence_columns, history_columns, imported_case_index,
                      load_case_index, summarize, write_summary)

if TYPE_CHECKING:
    from .packages import Definitions

SWEEP_NAMES = ("Mach", "Alpha", "Beta", "Altitude", "Temperature")  # the summary's numeric case columns
CONFIG = "Config"  # the base name of an imported case (a label, not a number)
CURVE_KEYS = (CONFIG, "Altitude", "Temperature", "Mach", "Beta")  # a curve is one value of each, along α
ISA_NAMES = ("rho_inf", "p_inf", "T_inf", "V_inf", "q_inf")
CONSTANT_NAMES = ("S_ref", "L_ref") + ISA_NAMES
_ISA_KEYS = {"rho_inf": "density", "p_inf": "pressure", "T_inf": "temperature", "V_inf": "true_airspeed",
             "q_inf": "dynamic_pressure"}
_CACHE_SIZE = 32
CHARACTERISTICS_FILE = "characteristics.csv"
_KEY_COLUMNS = ("Case", CONFIG, "Altitude", "Temperature", "Mach", "Alpha", "Beta", "Converged")


def _template_number(template: str, key: str) -> Optional[float]:
    match = re.search(rf"^\s*{key}\s*=\s*([^\s%]+)", template, re.MULTILINE)
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None


def study_constants(project: Project, case: Case, template: str) -> dict[str, Union[float, Missing]]:
    """S_ref and L_ref (the reference settings, else the template), and with the freestream from altitude the
    ISA density, pressure, temperature, airspeed and dynamic pressure at the case's altitude and Mach."""
    ref = project.settings.reference
    values: dict[str, Union[float, Missing]] = {}
    for name, setting, key, what in (("S_ref", ref.ref_area, "REF_AREA", "area"),
                                     ("L_ref", ref.ref_length, "REF_LENGTH", "length")):
        value = setting if setting is not None else _template_number(template, key)
        values[name] = value if value is not None else Missing(f"no reference {what} ({key})")
    if project.settings.freestream.mode != "altitude":
        values.update({name: Missing(f"{name} needs the freestream from altitude") for name in ISA_NAMES})
        return values
    altitude = case_altitude(project, case)
    error = altitude_error(altitude)
    if error:
        values.update({name: Missing(error) for name in ISA_NAMES})
        return values
    isa = ISACalculator.calculate(altitude, case_mach(project, case, template), 1.0)
    values.update({name: isa[key] for name, key in _ISA_KEYS.items()})
    return values


@dataclass
class CurveValues:
    curve: dict[str, float]  # the curve's sweep values, e.g. {"Mach": 0.8}
    values: dict[str, Union[float, Missing]]  # characteristic value name -> value


@dataclass
class StudyResults:
    name: str
    folder: Path
    table: pd.DataFrame  # Case, the sweep columns, Converged (True/False/None), parameters, derived values
    characteristics: list[CurveValues] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # e.g. "v2 has no CL(Wing)"
    warnings: list[str] = field(default_factory=list)  # per case, from reading the histories
    reasons: dict[tuple[str, str], str] = field(default_factory=dict)  # (case, derived name) -> why it is empty

    def reason(self, case: str, column: str) -> Optional[str]:
        return self.reasons.get((case, column))


_cache: "OrderedDict[tuple, StudyResults]" = OrderedDict()


def _stamp(folder: Path) -> tuple:
    """Changes whenever a history, the case index or the study changes (an imported study's histories are listed in
    its project.json, which is read for them). The Results settings (filters, folds, …) are left out: saving them
    must not read every history again; the definitions they give are in the cache key on their own."""
    try:
        project = open_project(folder)
    except AeroSuiteError:
        project = None
    paths = [path for _, path in case_histories(folder, project)]
    paths += [folder / CONFIGS_DIR / CASE_INDEX_FILE]
    if project is None:
        paths.append(folder / PROJECT_FILE)
    stamp = [project.model_dump_json(exclude={"results", "modified"}) if project is not None else None]
    for path in paths:
        try:
            info = path.stat()
            stamp.append((str(path), info.st_size, info.st_mtime_ns))
        except OSError:
            stamp.append((str(path), None, None))
    return tuple(stamp)


def _definitions_key(definitions: "Definitions") -> str:
    return json.dumps({"parameters": definitions.parameters,
                       "derived": [d.model_dump() for d in definitions.derived],
                       "characteristics": [c.model_dump() for c in definitions.characteristics]})


def study_results(folder: Path, definitions: "Definitions", last_n: int = 100) -> StudyResults:
    """The study's results with `definitions`; cached until a history, the case index or project.json changes."""
    folder = Path(folder).resolve()
    key = (str(folder), last_n, _definitions_key(definitions), _stamp(folder))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    result = _compute(folder, definitions, last_n)
    _cache[key] = result
    while len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return result


def _parsed(definitions: list, curve: bool) -> list:
    out = []
    for definition in definitions:
        try:
            out.append((definition, parse(definition.formula, curve=curve)))
        except FormulaError as exc:
            out.append((definition, Missing(f"formula error: {exc}")))
    return out


def _compute(folder: Path, definitions: "Definitions", last_n: int) -> StudyResults:
    project = open_project(folder)
    derived_names = definitions.derived_names
    derived = _parsed(definitions.derived, curve=False)
    characteristics = _parsed(definitions.characteristics, curve=True)
    special = set(SWEEP_NAMES) | set(CONSTANT_NAMES) | derived_names
    needed = [p for p in definitions.parameters if p not in special]
    for _, formula in derived + characteristics:
        if not isinstance(formula, Missing):
            needed += sorted(formula.names)
    needed = [n for n in dict.fromkeys(needed) if n not in special]
    available = set(history_columns(folder, project))
    notes = [f"{project.name} has no {name}" for name in needed if name not in available]

    index = imported_case_index(project) if project.imported else load_case_index(folder / CONFIGS_DIR)
    table, warnings = summarize(
        folder / RUNS_DIR, needed, last_n=last_n, case_index=index, histories=case_histories(folder, project),
        convergence_columns=convergence_columns(definitions.parameters, derived_names))
    try:
        template = read_template(folder, project)
    except AeroSuiteError:
        template = ""
    reasons: dict[tuple[str, str], str] = {}
    if derived and not table.empty:
        cases = {case.name: case for case in project.cases}
        columns = {d.name: [] for d, _ in derived}
        for _, row in table.iterrows():
            case = cases.get(row["Case"]) or Case(
                name=row["Case"], mach=_number(row.get("Mach")), alpha=_number(row.get("Alpha")),
                beta=_number(row.get("Beta")), altitude_km=_optional(row.get("Altitude")))
            values: dict = {name: _optional(row.get(name)) for name in needed}
            values.update({name: _optional(row.get(name)) for name in SWEEP_NAMES})
            values.update(study_constants(project, case, template))
            for definition, formula in derived:
                value = formula if isinstance(formula, Missing) else evaluate(formula, values)
                if isinstance(value, Missing):
                    reasons[(row["Case"], definition.name)] = value.reason
                    columns[definition.name].append(math.nan)
                else:
                    columns[definition.name].append(value)
                values[definition.name] = value
        for name, column in columns.items():
            table[name] = column
    return StudyResults(project.name, folder, table, _curves(table, characteristics), notes, warnings, reasons)


def _number(value) -> float:
    number = _optional(value)
    return 0.0 if number is None else number


def _optional(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _along(formula) -> str:
    """The sweep variable a characteristic value's curve runs along: its curve functions' X, else α."""
    axes = curve_axes(formula) & set(SWEEP_NAMES) if not isinstance(formula, Missing) else set()
    return next(iter(axes)) if len(axes) == 1 else "Alpha"


def _curves(table: pd.DataFrame, characteristics: list) -> list[CurveValues]:
    """Each characteristic value on each curve: the rows with one value of every other case variable, taken in
    order along the curve's variable (α unless the formula reads along another, e.g. slope(CSF, Beta, 0, 4))."""
    if not characteristics or table.empty:
        return []
    rows: dict[tuple, CurveValues] = {}
    for characteristic, formula in characteristics:
        along = _along(formula)
        keys = [k for k in CURVE_KEYS if k in table.columns and k != along and table[k].notna().any()]
        groups = [(tuple(), table)] if not keys else [
            ((key if isinstance(key, tuple) else (key,)), group)
            for key, group in table.groupby(keys if len(keys) > 1 else keys[0], sort=True)]
        for key, group in groups:
            if along in group.columns:
                group = group.sort_values(along)
            series = {column: group[column].tolist() for column in group.columns if column not in ("Case", "Converged")}
            value = formula if isinstance(formula, Missing) else evaluate_curve(formula, series)
            curve = {name: (k if name == CONFIG else float(k)) for name, k in zip(keys, key)}
            row = rows.setdefault(tuple(sorted(curve.items(), key=lambda item: CURVE_KEYS.index(item[0]))),
                                  CurveValues(curve, {}))
            row.values[characteristic.name] = value
    return list(rows.values())


def summary_frame(result: StudyResults, parameters: list[str]) -> pd.DataFrame:
    """The table as exported: the key columns, then the chosen parameters in order (not the helper columns)."""
    table = result.table
    keys = [c for c in _KEY_COLUMNS if c in table.columns]
    return table[keys + [p for p in parameters if p in table.columns and p not in keys]]


def characteristics_frame(result: StudyResults) -> pd.DataFrame:
    rows = [{**row.curve, **{name: (math.nan if isinstance(v, Missing) else v) for name, v in row.values.items()}}
            for row in result.characteristics]
    return pd.DataFrame(rows)


def write_results(project_dir: Path, result: StudyResults, parameters: list[str]) -> list[Path]:
    """results/summary.csv, and results/characteristics.csv when there are characteristic values."""
    paths = [write_summary(project_dir, summary_frame(result, parameters))]
    if result.characteristics:
        path = Path(project_dir) / RESULTS_DIR / CHARACTERISTICS_FILE
        try:
            characteristics_frame(result).to_csv(path, index=False)
        except OSError as exc:
            raise AeroSuiteError(f"Cannot write {path}: {exc}") from exc
        paths.append(path)
    return paths

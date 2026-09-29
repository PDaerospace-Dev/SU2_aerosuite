"""The Results page's rules without NiceGUI: pinning automatic choices, filters, rows and counts."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import pandas as pd

from ..engine.models import ResultsSettings
from ..engine.naming import format_value
from ..engine.packages import Definitions
from ..engine.study_results import SWEEP_NAMES

SWEEP_LABELS = {"Mach": "Mach", "Alpha": "α", "Beta": "β", "Altitude": "Altitude"}
SWEEP_UNITS = {"Alpha": "deg", "Beta": "deg", "Altitude": "km"}


def pin(settings: ResultsSettings, definitions: Definitions) -> None:
    """Before the first change, write down what the page chose automatically (packages, parameters)."""
    if settings.packages is None:
        settings.packages = list(definitions.packages)
    if settings.parameters is None:
        settings.parameters = list(definitions.parameters)


def add_parameter(settings: ResultsSettings, definitions: Definitions, name: str) -> None:
    pin(settings, definitions)
    if name not in settings.parameters:
        settings.parameters.append(name)


def remove_parameter(settings: ResultsSettings, definitions: Definitions, name: str) -> None:
    pin(settings, definitions)
    settings.parameters = [p for p in settings.parameters if p != name]


def sweep_values(tables: Iterable[pd.DataFrame]) -> dict[str, list[float]]:
    """Every value of each sweep variable in the results (all designs together), sorted."""
    values: dict[str, set] = {}
    for table in tables:
        for name in SWEEP_NAMES:
            if name in table.columns:
                values.setdefault(name, set()).update(float(v) for v in table[name].dropna())
    return {name: sorted(found) for name, found in values.items() if found}


def shown_values(settings: ResultsSettings, values: Mapping[str, Sequence[float]], comparing: bool
                 ) -> dict[str, list[float]]:
    """The values each sweep variable shows: the saved filter (while it still matches), else all; with other
    designs overlaid, only the first Mach until the user picks more."""
    shown = {}
    for name, available in values.items():
        chosen = [v for v in settings.filters.get(name, []) if v in available]
        if chosen:
            shown[name] = chosen
        elif name == "Mach" and comparing and available:
            shown[name] = [available[0]]
        else:
            shown[name] = list(available)
    return shown


def toggle_filter(settings: ResultsSettings, name: str, value: float, current: Sequence[float]) -> None:
    """Show or hide one value; the last value shown stays."""
    chosen = [v for v in current if v != value] if value in current else sorted([*current, value])
    if chosen:
        settings.filters = {**settings.filters, name: chosen}


def filter_rows(table: pd.DataFrame, shown: Mapping[str, Sequence[float]]) -> pd.DataFrame:
    keep = pd.Series(True, index=table.index)
    for name, values in shown.items():
        if name in table.columns:
            keep &= table[name].isin(values) | table[name].isna()
    return table[keep]


def status_counts(tables: Iterable[pd.DataFrame]) -> dict[str, int]:
    counts = {"shown": 0, "converged": 0, "unconverged": 0, "not_judged": 0}
    for table in tables:
        for converged in table.get("Converged", pd.Series(dtype=object)):
            counts["shown"] += 1
            if converged is None or (isinstance(converged, float) and converged != converged):
                counts["not_judged"] += 1
            elif bool(converged):
                counts["converged"] += 1
            else:
                counts["unconverged"] += 1
    return counts


def varying(values: Mapping[str, Sequence[float]]) -> list[str]:
    """The sweep variables with more than one value (they get a table column and can split lines)."""
    return [name for name in SWEEP_NAMES if len(values.get(name, [])) > 1]


def status_text(converged) -> str:
    if converged is None or (isinstance(converged, float) and converged != converged):
        return "Not judged"
    return "Converged" if bool(converged) else "Unconverged"


def _cell(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if number != number else f"{number:.6g}"


def table_text(designs: Sequence[tuple[str, pd.DataFrame]], sweep: Sequence[str], parameters: Sequence[str]
               ) -> str:
    """The shown rows as tab-separated text (pastes into a spreadsheet)."""
    several = len(designs) > 1
    header = (["Design"] if several else []) + ["Case"]
    header += [SWEEP_LABELS[n] + (f" ({SWEEP_UNITS[n]})" if n in SWEEP_UNITS else "") for n in sweep]
    lines = ["\t".join(header + list(parameters) + ["Status"])]
    for name, table in designs:
        for _, row in table.iterrows():
            cells = ([name] if several else []) + [str(row["Case"])]
            cells += [format_value(row[n]) if n in row and row[n] == row[n] else "" for n in sweep]
            cells += [_cell(row.get(p)) for p in parameters] + [status_text(row.get("Converged"))]
            lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"

"""The Results page's rules without NiceGUI: pinning automatic choices, filters, rows and counts."""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

import pandas as pd

from ..engine.models import ResultsSettings
from ..engine.naming import format_value
from ..engine.packages import Definitions
from ..engine.study_results import CONFIG, SWEEP_NAMES

VARIABLES = (CONFIG, *SWEEP_NAMES)  # the case variables: the Config label first, then the numbers

SWEEP_LABELS = {"Mach": "Mach", "Alpha": "α", "Beta": "β", "Altitude": "Altitude", "Temperature": "T",
                "Config": "Config"}
SWEEP_UNITS = {"Alpha": "deg", "Beta": "deg", "Altitude": "km", "Temperature": "K"}


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


def sweep_values(tables: Iterable[pd.DataFrame]) -> dict[str, list]:
    """Every value of each case variable in the results (all designs together), sorted: numbers, and the
    Config labels."""
    values: dict[str, set] = {}
    for table in tables:
        for name in VARIABLES:
            if name in table.columns:
                convert = str if name == CONFIG else float
                values.setdefault(name, set()).update(convert(v) for v in table[name].dropna() if v != "")
    return {name: sorted(found) for name, found in values.items() if found}


def variable_text(value) -> str:
    """A case variable's value as shown: a number shortest-exact, a label as it is, blank as —."""
    if value is None or (isinstance(value, float) and value != value) or value == "":
        return "—"
    return value if isinstance(value, str) else format_value(value)


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


def toggle_filter(settings: ResultsSettings, name: str, value, current: Sequence, available: Sequence) -> None:
    """A click on a value: with every value shown it picks that value alone; after that it adds or removes the
    value, and removing the last one shows all again."""
    if list(current) == list(available):
        chosen = [value]
    elif value in current:
        chosen = [v for v in current if v != value]
    else:
        chosen = sorted([*current, value], key=lambda v: (isinstance(v, str), v))
    filters = {k: v for k, v in settings.filters.items() if k != name}
    if chosen and list(chosen) != list(available):
        filters[name] = chosen
    settings.filters = filters


def clear_filters(settings: ResultsSettings, name: Optional[str] = None) -> None:
    """Show every value of one variable, or of all of them."""
    settings.filters = {} if name is None else {k: v for k, v in settings.filters.items() if k != name}


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


CONDITION_ORDER = ("Mach", "Altitude", "Temperature", "Alpha", "Beta", CONFIG)
LISTED = 4  # up to this many values are listed; more read as a range


def conditions(tables: Iterable[pd.DataFrame]) -> list[tuple[str, str]]:
    """The case variables of the shown rows as (label with unit, text): one value, a short list, or a range with
    the count ("-10 … 45 · 5"); variables without a value left out."""
    values = sweep_values(tables)
    items = []
    for name in CONDITION_ORDER:
        found = values.get(name)
        if not found:
            continue
        label = SWEEP_LABELS[name] + (f" ({SWEEP_UNITS[name]})" if name in SWEEP_UNITS else "")
        if len(found) <= LISTED:
            text = ", ".join(variable_text(v) for v in found)
        elif name == CONFIG:
            text = f"{len(found)} configs"
        else:
            text = f"{variable_text(found[0])} … {variable_text(found[-1])} · {len(found)}"
        items.append((label, text))
    return items


def converged_text(counts: Mapping[str, int]) -> tuple[str, str]:
    """The strip's convergence pill: its text and its tone (a pill tone of ui_kit)."""
    judged = counts["shown"] - counts["not_judged"]
    if not judged:
        return "convergence not judged", "pending"
    return f"{counts['converged']} / {judged} converged", "unconverged" if counts["unconverged"] else "done"


def varying(values: Mapping[str, Sequence[float]]) -> list[str]:
    """The sweep variables with more than one value (they get a table column and can split lines)."""
    return [name for name in VARIABLES if len(values.get(name, [])) > 1]


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
            cells += [variable_text(row[n]).replace("—", "") if n in row else "" for n in sweep]
            cells += [_cell(row.get(p)) for p in parameters] + [status_text(row.get("Converged"))]
            lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"

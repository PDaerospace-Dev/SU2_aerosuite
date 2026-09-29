"""The Results page's plots without NiceGUI: which points make one line, and ECharts options.

Colour = design; line style = the splitting value (e.g. the Mach); marker shape = the Y parameter; an unconverged
point is hollow. A line runs along the X axis when X is a sweep variable, else along α (the polar CL vs CD).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

import pandas as pd

from ..engine.models import PlotSpec
from ..engine.naming import format_value
from ..engine.study_results import SWEEP_NAMES
from .results_view import SWEEP_LABELS, SWEEP_UNITS
from .theme import HAIRLINE, MUTED

LINE_STYLES = ["solid", "dashed", "dotted", [8, 3, 2, 3]]  # the last: dash-dot
MARKERS = ["circle", "rect", "triangle", "diamond", "pin", "arrow"]


@dataclass(frozen=True)
class ChartDesign:
    name: str
    color: str
    rows: pd.DataFrame  # the shown rows of this design
    folder: str  # its study folder (a clicked point opens Monitor there)


def along(x: str) -> str:
    """The sweep variable a line runs along."""
    return x if x in SWEEP_NAMES else "Alpha"


def split_keys(x: str, table: pd.DataFrame, split: Optional[str]) -> list[str]:
    """The sweep variables that make one line each: the chosen one, else every one that varies (not the axis)."""
    runs_along = along(x)
    varying = [name for name in SWEEP_NAMES
               if name in table.columns and name != runs_along and table[name].nunique(dropna=True) > 1]
    if split and split != runs_along and split in varying:
        return [split]
    return varying


def _label(name: str) -> str:
    return SWEEP_LABELS.get(name, name)


def describe_lines(x: str, keys: list[str]) -> str:
    joined = f"points joined along {_label(along(x))}"
    if not keys:
        return f"One line, {joined}"
    return f"One line per {' and '.join(_label(k) for k in keys)}, {joined}"


def axis_options(name: str, units: Mapping[str, str]) -> dict:
    unit = SWEEP_UNITS.get(name) or units.get(name)
    return {"type": "value", "scale": True, "name": _label(name) + (f" ({unit})" if unit else ""),
            "nameLocation": "middle", "axisLine": {"onZero": False},
            "splitLine": {"lineStyle": {"color": HAIRLINE}}, "nameTextStyle": {"color": MUTED}}


def _number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def chart_options(plot: PlotSpec, designs: list[ChartDesign], units: Mapping[str, str] = {}, title: str = ""
                  ) -> tuple[dict, list[str]]:
    """ECharts options for `plot` over the designs, and the study folder behind each series (in order)."""
    combined = pd.concat([d.rows for d in designs]) if designs else pd.DataFrame()
    keys = split_keys(plot.x, combined, plot.split) if not combined.empty else []
    runs_along = along(plot.x)
    if combined.empty:
        key_values = []
    elif keys:  # each combination of the splitting values, e.g. (0.6,), (0.8,)
        key_values = sorted({tuple(row) for row in combined[keys].dropna().itertuples(index=False)})
    else:
        key_values = [()]
    series, owners = [], []
    for design in designs:
        for k, y in enumerate(plot.y):
            for j, key in enumerate(key_values):
                part = design.rows
                for name, value in zip(keys, key):
                    part = part[part[name] == value]
                if part.empty:
                    continue
                if runs_along in part.columns:
                    part = part.sort_values(runs_along)
                marker = MARKERS[k % len(MARKERS)]
                data = []
                for _, row in part.iterrows():
                    converged = row.get("Converged")
                    hollow = converged is not None and not _is_nan(converged) and not bool(converged)
                    data.append({"value": [_number(row.get(plot.x)), _number(row.get(y))], "name": row["Case"],
                                 "symbol": ("empty" + marker) if hollow else marker,
                                 "symbolSize": 10 if hollow else 7})
                label = " · ".join(f"{_label(n)} {format_value(v)}" for n, v in zip(keys, key))
                series.append({
                    "type": "line", "name": " · ".join(p for p in (design.name, y, label) if p), "data": data,
                    "symbol": marker, "connectNulls": False,
                    "lineStyle": {"color": design.color, "width": 2, "type": LINE_STYLES[j % len(LINE_STYLES)]},
                    "itemStyle": {"color": design.color},
                })
                owners.append(design.folder)
    options = {
        "animation": False,
        "title": {"text": title, "left": 6, "top": 2, "textStyle": {"fontSize": 13, "fontWeight": 600}},
        "grid": {"left": 64, "right": 16, "top": 36, "bottom": 70 if len(series) > 1 else 44},
        "tooltip": {"trigger": "item"},
        "toolbox": {"right": 8, "top": 0, "feature": {"saveAsImage": {"title": "PNG", "name": title or "plot"}}},
        "legend": {"show": len(series) > 1, "type": "scroll", "bottom": 0, "textStyle": {"fontSize": 11}},
        "xAxis": {**axis_options(plot.x, units), "nameGap": 26},
        "yAxis": {**axis_options(plot.y[0] if len(plot.y) == 1 else "", units), "nameGap": 50},
        "series": series,
    }
    return options, owners


def _is_nan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)

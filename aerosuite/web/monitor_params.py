"""Monitor's Parameters tab: plots of any columns of the shown history file against iteration (each plot with
its own value axis, zoomed on its own), and for every plotted column its mean over the last iterations.

The plots and the number of iterations averaged are kept per project while the server runs; they are not
written to project.json.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

from nicegui import ui

from ..engine.results import ITERATION_COLUMNS, group_of, ordered_groups
from .fields import text_field
from .theme import HAIRLINE, SERIES_COLORS
from .ui_kit import card, field as kit_field, hint, primary_button, secondary_button, titled

CHART_HEIGHT = "260px"
FULL = 0.01  # percent: a zoom this close to both ends is the whole run
NOT_IN_FILE = "not in this file"
OTHER_GROUP = "Not in this file"


@dataclass
class Plot:
    id: int
    names: list[str]


@dataclass
class ParamState:
    """One project's Parameters tab, shared by every page showing it."""
    average: int
    tab: str = "convergence"
    plots: list[Plot] = field(default_factory=list)
    next_id: int = 1

    def add(self, names: Sequence[str]) -> Plot:
        plot = Plot(self.next_id, list(names))
        self.next_id += 1
        self.plots.append(plot)
        return plot


_STATES: dict[Path, ParamState] = {}  # by project folder; kept while the server runs


def param_state(directory: Path, default_average: int) -> ParamState:
    key = Path(directory).resolve()
    if key not in _STATES:
        _STATES[key] = ParamState(average=default_average)
    return _STATES[key]


def thinned_indices(count: int, limit: int) -> list[int]:
    """At most `limit` row indices spread evenly over `count` rows, always ending on the last row."""
    step = max(1, math.ceil(count / limit))
    indices = list(range(0, count, step))  # length <= limit, since step >= count / limit
    if count and indices[-1] != count - 1:
        if len(indices) < limit:
            indices.append(count - 1)  # room to spare: add the last index as an extra point
        else:
            indices[-1] = count - 1  # already at the bound: swap in the last index, don't grow
    return indices


def plottable_columns(df) -> list[str]:
    """Every numeric column of a history file except the iteration counters."""
    if df is None:
        return []
    return [column for column in df.columns
            if column not in ITERATION_COLUMNS and df[column].dtype.kind in "fiu"]


class Stats(NamedTuple):
    mean: Optional[float]  # over the last rows
    latest: Optional[float]  # the last value that is a number
    spread: Optional[float]  # max - min over the last rows


def window_stats(values: Sequence[float], last_n: int) -> Stats:
    """A column's mean and range over its last `last_n` rows (like the Results page's average) and its latest
    value; rows that are not numbers are left out."""
    tail = [v for v in values[-max(1, last_n):] if v is not None and math.isfinite(v)]
    latest = next((v for v in reversed(values) if v is not None and math.isfinite(v)), None)
    if not tail:
        return Stats(None, latest, None)
    return Stats(sum(tail) / len(tail), latest, max(tail) - min(tail))


def number_text(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.5g}"


class Window(NamedTuple):
    """The iterations a zoomed plot shows. `following`: the view ends on the newest iteration and moves with it."""
    start: float
    end: float
    following: bool


def zoom_percent(args) -> Optional[tuple[float, float]]:
    """(start, end) in percent from an ECharts datazoom event: the slider sends them directly, the mouse wheel
    and dragging send a batch."""
    if not isinstance(args, dict):
        return None
    batch = args.get("batch")
    source = batch[0] if isinstance(batch, list) and batch and isinstance(batch[0], dict) else args
    start, end = source.get("start"), source.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return float(start), float(end)


def window_of(start: float, end: float, x_min: float, x_max: float) -> Optional[Window]:
    """The window a zoom of `start`..`end` percent shows on a run from `x_min` to `x_max`; None: the whole run."""
    if start <= FULL and end >= 100 - FULL:
        return None
    span = x_max - x_min
    return Window(x_min + span * start / 100, x_min + span * end / 100, following=end >= 100 - FULL)


def window_range(window: Optional[Window], x_min: float, x_max: float) -> Optional[tuple[float, float]]:
    """What `window` shows now that the run reaches `x_max`: the same iterations, or — following — the same
    number of them ending on the newest one."""
    if window is None:
        return None
    if not window.following:
        return window.start, window.end
    return max(x_min, x_max - (window.end - window.start)), x_max


def param_options(x: list, df, names: Sequence[str], colors: dict, shown: Optional[tuple[float, float]],
                  limit: int) -> dict:
    """ECharts options: `names` (those in `df`) against iteration on one value axis, thinned to `limit` points
    a line, with wheel/drag zoom and a zoom bar. `shown`: the iterations in view, None for all."""
    indices = thinned_indices(len(x), limit)
    series = []
    for name in names:
        if name not in df.columns:
            continue
        values = df[name].tolist()
        data = [[x[i], None if values[i] is None or not math.isfinite(values[i]) else values[i]] for i in indices]
        series.append({"name": name, "type": "line", "showSymbol": False, "data": data, "color": colors[name]})
    span = {"start": 0, "end": 100} if shown is None else {"startValue": shown[0], "endValue": shown[1]}
    return {
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 64, "right": 18, "top": 14, "bottom": 58},
        "xAxis": {"type": "value", "min": "dataMin", "max": "dataMax", "axisLine": {"onZero": False},
                  "splitLine": {"lineStyle": {"color": HAIRLINE}}},
        "yAxis": {"type": "value", "scale": True, "splitLine": {"lineStyle": {"color": HAIRLINE}}},
        "dataZoom": [{"type": "inside", "xAxisIndex": 0, **span},
                     {"type": "slider", "xAxisIndex": 0, "height": 16, "bottom": 8, "showDetail": False, **span}],
        "series": series,
    }


def plot_colors(names: Sequence[str]) -> dict:
    return {name: SERIES_COLORS[i % len(SERIES_COLORS)] for i, name in enumerate(names)}


class ParametersTab:
    """The plots (in `plots_box`) and the "Latest values" block (in `values_box`). `show(df, x, note)` feeds it
    the history the Monitor page shows; charts are updated in place, so a zoom or an open tooltip survives."""

    def __init__(self, state: ParamState, plots_box: ui.element, values_box: ui.element, limit: int) -> None:
        self.state = state
        self.plots_box = plots_box
        self.values_box = values_box
        self.limit = limit
        self.df = None
        self.x: list = []
        self.note = ""
        self.active = False  # the Parameters tab is the one showing
        self.windows: dict[int, Optional[Window]] = {}  # this page's zoom of each plot, by plot id
        self._shape: Optional[tuple] = None  # what the plots and values were built for
        self._charts: dict[int, ui.echart] = {}
        self._chips: dict[tuple[int, str], ui.label] = {}
        self._values: dict[str, tuple[ui.label, ui.label]] = {}

    # -- the number of iterations averaged ------------------------------------------

    def average_box(self) -> None:
        """"Average the last N iterations" (built where the caller stands)."""
        ui.label("Average the last").classes("as-label")
        with ui.element("div").classes("w-20"):
            # no label prop at all: an empty one still keeps room for a label above the number
            text_field("", self.state.average, self._set_average, mark="monitor-average").props(remove="label")
        ui.label("iterations").classes("as-label")

    def _set_average(self, text: str) -> Optional[str]:
        try:
            value = int(text)
        except ValueError:
            return "A whole number"
        if value < 1:
            return "At least 1"
        self.state.average = value
        self._refresh()
        return None

    # -- drawing --------------------------------------------------------------------

    def show(self, df, x: list, note: str = "") -> None:
        self.df, self.x, self.note = df, x, note
        shape = (tuple((plot.id, tuple(plot.names)) for plot in self.state.plots), tuple(plottable_columns(df)),
                 note)
        if shape != self._shape:
            self._shape = shape
            self._build()
        self._refresh()

    def redraw(self) -> None:
        """After the plots changed (here or on another page of this project)."""
        self.show(self.df, self.x, self.note)

    def set_active(self, active: bool) -> None:
        self.active = active
        self._values_visibility()

    def _values_visibility(self) -> None:
        self.values_box.set_visibility(self.active and bool(self.state.plots))

    def _names(self) -> list[str]:
        return list(dict.fromkeys(name for plot in self.state.plots for name in plot.names))

    def _build(self) -> None:
        columns = set(plottable_columns(self.df))
        self._charts, self._chips, self._values = {}, {}, {}
        self.plots_box.clear()
        with self.plots_box:
            if self.note:
                hint(self.note).mark("params-note")
            with ui.element("div").classes("as-plots"):
                for plot in self.state.plots:
                    self._plot_card(plot, columns)
                tile = ui.row().classes("as-add-plot").props('tabindex=0 role=button').mark("params-add")
                tile.on("click", lambda: self.open_picker(None))
                tile.on("keydown.enter", lambda: self.open_picker(None))
                with tile:
                    ui.icon("add")
                    ui.label("Add plot")
        self.values_box.clear()
        self._values_visibility()
        with self.values_box:
            with ui.column().classes("w-full gap-0"):
                ui.label("Values").classes("as-card-title")
                self._window_label = ui.label("").classes("as-card-subtitle").mark("params-window")
            for name in self._names():
                with ui.column().classes("as-value-row w-full gap-0").mark(f"params-value-{name}"):
                    titled(ui.label(name).classes("as-label as-truncate"), name)
                    mean = ui.label("").classes("as-value-mean").mark(f"params-mean-{name}")
                    latest = ui.label("").classes("as-hint").mark(f"params-latest-{name}")
                self._values[name] = (mean, latest)

    def _plot_card(self, plot: Plot, columns: set) -> None:
        colors = plot_colors(plot.names)
        with card() as box:
            box.mark(f"params-plot-{plot.id}")
            with ui.row().classes("w-full items-center gap-2"):
                for name in plot.names:
                    with ui.row().classes("as-design-chip items-center gap-2 no-wrap"):
                        ui.element("span").classes("as-swatch").style(f"background: {colors[name]}")
                        ui.label(name)
                        self._chips[(plot.id, name)] = ui.label("").classes("as-mono as-strong").mark(
                            f"params-chip-{plot.id}-{name}")
                ui.space()
                for icon, title, action, mark in (
                        ("zoom_out_map", "Show the whole run", self._reset_zoom, "zoom-reset"),
                        ("tune", "Change the parameters", self.open_picker, "edit"),
                        ("close", "Remove this plot", self._remove, "remove")):
                    titled(ui.button(icon=icon, color=None, on_click=lambda p=plot, a=action: a(p)).props(
                        "flat round dense size=sm"), title).mark(f"params-{mark}-{plot.id}")
            if not any(name in columns for name in plot.names):
                ui.label("None of these parameters is in this file." if self.df is not None and columns
                         else "Nothing to plot yet.").classes("as-muted").mark(f"params-empty-{plot.id}")
                return
            chart = ui.echart({}).classes("w-full").style(f"height: {CHART_HEIGHT}").mark(f"params-chart-{plot.id}")
            chart.on("chart:datazoom", lambda e, p=plot: self._zoomed(p, e.args))
            self._charts[plot.id] = chart

    def _refresh(self) -> None:
        df = self.df
        columns = set(plottable_columns(df))
        stats = {name: window_stats(df[name].tolist(), self.state.average) if name in columns else None
                 for name in self._names()}
        if self._values:
            count = self.state.average
            self._window_label.set_text(f"mean of the last {count} iteration{'' if count == 1 else 's'}")
        for name, (mean, latest) in self._values.items():
            found = stats.get(name)
            if found is None:
                mean.set_text("—")
                latest.set_text(NOT_IN_FILE if df is not None and columns else "no history yet")
            else:
                mean.set_text(number_text(found.mean))
                latest.set_text(f"latest {number_text(found.latest)} · range {number_text(found.spread)}")
        for (_, name), label in self._chips.items():
            found = stats.get(name)
            label.set_text(NOT_IN_FILE if found is None else number_text(found.latest))
            label.classes(**({"add": "as-muted"} if found is None else {"remove": "as-muted"}))
        for plot in self.state.plots:
            chart = self._charts.get(plot.id)
            if chart is None or df is None or not self.x:
                continue
            shown = window_range(self.windows.get(plot.id), self.x[0], self.x[-1])
            chart.options.clear()
            chart.options.update(param_options(self.x, df, plot.names, plot_colors(plot.names), shown, self.limit))
            chart.update()

    # -- zoom -----------------------------------------------------------------------

    def _zoomed(self, plot: Plot, args) -> None:
        percent = zoom_percent(args)
        if percent is None or not self.x:
            return
        self.windows[plot.id] = window_of(percent[0], percent[1], self.x[0], self.x[-1])

    def _reset_zoom(self, plot: Plot) -> None:
        self.windows.pop(plot.id, None)
        self._refresh()

    # -- adding, changing and removing plots ------------------------------------------

    def _remove(self, plot: Plot) -> None:
        self.state.plots[:] = [p for p in self.state.plots if p.id != plot.id]
        self.windows.pop(plot.id, None)
        self.redraw()

    async def open_picker(self, plot: Optional[Plot]) -> None:
        """Tick the columns of one plot: a new one (`plot` None) or an existing one."""
        columns = plottable_columns(self.df)
        chosen = list(plot.names) if plot is not None else []
        missing = [name for name in chosen if name not in columns]
        if not columns and not chosen:
            ui.notify("No history file to choose parameters from yet", type="warning")
            return
        ticked = set(chosen)
        boxes: list[tuple[str, ui.element]] = []
        heads: list[tuple[list[str], ui.element]] = []

        def confirm_text() -> str:
            count = len(ticked)
            verb = "Add plot" if plot is None else "Save"
            return f"{verb} · {count} parameter{'' if count == 1 else 's'}" if count else verb

        def tick(name: str, on: bool) -> None:
            (ticked.add if on else ticked.discard)(name)
            confirm.set_text(confirm_text())
            error.set_text("")

        def search(text: str) -> None:
            words = (text or "").lower().split()
            shown = {name for name, _ in boxes if all(word in name.lower() for word in words)}
            for name, box in boxes:
                box.set_visibility(name in shown)
            for names, head in heads:
                head.set_visibility(any(name in shown for name in names))

        def group(title: str, names: list[str]) -> None:
            head = ui.label(title).classes("as-label")
            heads.append((names, head))
            with ui.element("div").classes("as-grid-3 as-param-grid"):
                for name in names:
                    box = ui.checkbox(name, value=name in ticked,
                                      on_change=lambda e, n=name: tick(n, e.value)).props("dense").classes(
                        "as-mono").mark(f"params-pick-{name}")
                    boxes.append((name, box))

        def submit() -> None:
            if not ticked:
                error.set_text("Tick at least one parameter")
                return
            answer([name for name in [*columns, *missing] if name in ticked])

        def answer(names: Optional[list]) -> None:
            # Deleted in the same click, not after `await dialog` resumes: until then its buttons would still
            # be on the page, beside those of a picker opened right after it.
            dialog.submit(names)
            dialog.delete()

        # Built from the plots' holder, which is never deleted: the tile or button that was clicked can be gone
        # by now (a redraw after the previous dialog), and a dialog cannot be made from a deleted element.
        with self.plots_box:
            with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
                ui.label("Add a plot" if plot is None else "Change the plot's parameters").classes("as-dialog-title")
                hint("Tick one or more columns of this history file; they share one plot against iteration.")
                kit_field(ui.input(placeholder=f"Search {len(columns)} columns",
                                   on_change=lambda e: search(e.value))).props("dense clearable").classes(
                    "w-full").mark("params-search")
                with ui.column().classes("w-full gap-2 max-h-96 overflow-auto"):
                    for title in ordered_groups(columns):
                        group(title, [c for c in columns if group_of(c) == title])
                    if missing:
                        group(OTHER_GROUP, missing)
                error = ui.label("").classes("as-error-text").mark("params-pick-error")
                with ui.row().classes("w-full justify-end gap-2"):
                    secondary_button("Cancel", on_click=lambda: answer(None)).mark("params-pick-cancel")
                    confirm = primary_button(confirm_text(), on_click=submit).mark("params-pick-confirm")
        names = await dialog
        if not names:
            return
        if plot is None:
            self.state.add(names)
        else:
            plot.names[:] = names
        self.redraw()


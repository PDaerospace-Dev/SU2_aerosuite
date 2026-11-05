"""Coverage of a linked run-matrix sheet: every run's Status laid out by its sweep values, in three views.

Panels (one small grid per altitude x elevator), Table (one table per altitude) and Pivot (any two parameters, each
box gathering the runs that share them). Clicking a run, or a pivot box, lists it below the view."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from itertools import product
from typing import Optional
from urllib.parse import quote

from nicegui import run, ui

from ...engine.naming import format_value
from ...engine.tracker import Key
from ...engine.tracker_links import Link, LinkReport, load_tracker, report
from ..ui_kit import banner, card, hint

VIEWS = {"panels": "Panels", "table": "Table", "pivot": "Pivot"}
AXES = [("Mach", ""), ("Altitude", " km"), ("AoA", "°"), ("Elevator δe", "°"), ("Sideslip β", "°")]
MACH, ALT, AOA, ELEV, BETA = range(5)
RUNS_LISTED = 60  # runs a pivot box lists
# the sheet's Status -> the square's colour (the overview bar's segments, failures apart)
TONES = {"Converged": "converged", "Not Converged": "not", "Failed": "failed", "Diverged": "failed",
         "Running": "live", "Pending": "live", "Hold": "hold"}


def coverage_url(link_id: str, view: str = "") -> str:
    return f"/tracker/coverage?link={quote(link_id)}" + (f"&view={quote(view)}" if view else "")


@dataclass(frozen=True)
class Run:
    run_id: str
    key: Key
    status: str  # in the sheet now; "" when blank
    new: Optional[str]  # what the link would write, if it differs


def runs_of(result: LinkReport) -> list[Run]:
    changes = {change.row.row: change.status for change in result.plan.changes} if result.plan else {}
    return [Run(row.run_id, row.key, row.status, changes.get(row.row)) for row in result.matrix.rows]


def _value(axis: int, value: float) -> str:
    return f"{format_value(value)}{AXES[axis][1]}"


def run_text(run: Run) -> str:
    mach, alt, aoa, elev, beta = run.key
    text = f"M {format_value(mach)} · {_value(ALT, alt)} · α {_value(AOA, aoa)} · δe {_value(ELEV, elev)}"
    return text + (f" · β {_value(BETA, beta)}" if beta else "")


def square(run: Run, size: str = "") -> str:
    """A run as a coloured square (a ring when a write is waiting); a click lists it below the view."""
    tone = TONES.get(run.status, "none")
    tip = f"{run.run_id} · {run_text(run)}\n{run.status or 'no status'}" + (f" → {run.new} (to write)" if run.new
                                                                            else "")
    classes = f"as-cov-cell as-cov-{tone}{' as-cov-change' if run.new else ''}{size}"
    return (f'<span class="{classes}" title="{escape(tip)}" data-run="{run.run_id}" '
            f"onclick=\"emitEvent('as-cov-run', '{run.run_id}')\"></span>")


def bar(counts: Counter, total: int) -> str:
    from .tracker import bar_html  # the overview's bar
    return bar_html(counts, total)


def legend() -> None:
    with ui.row().classes("as-legend as-cov-legend w-full"):
        for tone, text in (("converged", "Converged"), ("not", "Not converged"), ("failed", "Failed / diverged"),
                           ("live", "Running / queued"), ("hold", "Hold"), ("none", "No status yet")):
            with ui.row().classes("as-legend-item"):
                ui.element("span").classes(f"as-swatch as-cov-{tone}")
                ui.label(text)
        with ui.row().classes("as-legend-item"):
            ui.html('<span class="as-cov-cell as-cov-none as-cov-change as-cov-small"></span>', sanitize=False)
            ui.label("Waiting to be written")


def _converged(runs: list[Run]) -> str:
    return f"{sum(run.status == 'Converged' for run in runs)}/{len(runs)} converged"


class Coverage:
    def __init__(self, link: Link, view: str) -> None:
        self.link = link
        self.view = view if view in VIEWS else "panels"
        self.result: Optional[LinkReport] = None
        self.runs: list[Run] = []
        self.by_id: dict[str, Run] = {}
        self.altitude: Optional[float] = None
        self.beta: Optional[float] = None
        self.pivot_rows: Optional[int] = None
        self.pivot_columns: Optional[int] = None
        self.picked: Optional[tuple] = None  # a pivot box's (row value, column value)
        self.body = ui.column().classes("w-full gap-4")
        with self.body:
            hint("Reading the workbook and the jobs…").mark("coverage-loading")
        ui.on("as-cov-run", lambda event: self.show_runs([self.by_id[event.args]], "The run you clicked")
              if event.args in self.by_id else None)
        ui.timer(0, self.load, once=True)

    async def load(self) -> None:
        self.result = await run.io_bound(report, self.link)
        if self.result.matrix is not None:
            self.runs = runs_of(self.result)
            self.by_id = {run.run_id: run for run in self.runs}
            levels = self.levels
            self.altitude = levels[ALT][0]
            self.beta = levels[BETA][0]
            swept = [axis for axis in range(5) if len(levels[axis]) > 1] or [MACH]
            self.pivot_columns = swept[0]
            self.pivot_rows = AOA if AOA in swept and AOA != swept[0] else swept[-1]
        self.draw()

    @property
    def levels(self) -> list[list[float]]:
        return [level or [0.0] for level in self.result.matrix.levels]

    def draw(self) -> None:
        self.body.clear()
        with self.body:
            if self.result.error:
                banner("error", self.result.error).mark("coverage-error")
                return
            counts = Counter(run.status for run in self.runs)
            with card():
                with ui.row().classes("w-full items-center no-wrap gap-3"):
                    with ui.column().classes("grow gap-1 min-w-0"):
                        ui.label(f"{self.link.sheet} — {len(self.runs)} runs").classes("as-card-title")
                        ui.html(bar(counts, len(self.runs)), sanitize=False).classes("w-full")
                        from .tracker import bar_text
                        hint(bar_text(counts, len(self.runs))).mark("coverage-progress")
                    ui.toggle(VIEWS, value=self.view, on_change=lambda e: self.set_view(e.value)).props(
                        "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark("coverage-view")
            with card():
                self.view_box = ui.column().classes("w-full gap-3")
                self.detail = ui.column().classes("w-full gap-1 as-cov-detail").mark("coverage-detail")
            self.draw_view()

    def set_view(self, view: str) -> None:
        self.view = view
        self.picked = None
        ui.navigate.history.replace(coverage_url(self.link.id, view))
        self.draw_view()

    def draw_view(self) -> None:
        self.view_box.clear()
        self.detail.clear()
        with self.view_box:
            legend()
            {"panels": self.panels, "table": self.table, "pivot": self.pivot}[self.view]()
        if self.view != "pivot" or self.picked is None:
            with self.detail:
                hint("Click a run to see it here." if self.view != "pivot" else "Click a box to list its runs.")

    # --- Panels: one grid per altitude x elevator (x sideslip), AoA against Mach ---------------------------------------

    def panels(self) -> None:
        levels = self.levels
        machs, aoas = levels[MACH], sorted(levels[AOA], reverse=True)
        columns = list(product(levels[ELEV], levels[BETA]))
        by_key = {(run.key[ALT], run.key[ELEV], run.key[BETA], run.key[AOA], run.key[MACH]): run
                  for run in self.runs}
        html = [f'<div class="as-cov-panels" style="grid-template-columns: auto repeat({len(columns)}, max-content)">'
                "<div></div>"]
        for elev, beta in columns:
            name = f"δe {_value(ELEV, elev)}" + (f" · β {_value(BETA, beta)}" if len(levels[BETA]) > 1 else "")
            html.append(f'<div class="as-cov-colhead">{name}</div>')
        for alt in levels[ALT]:
            html.append(f'<div class="as-cov-rowhead">{_value(ALT, alt)}</div>')
            for elev, beta in columns:
                inside = [run for run in self.runs if run.key[ALT] == alt and run.key[ELEV] == elev
                          and run.key[BETA] == beta]
                grid = [f'<div class="as-cov-panel"><div class="as-cov-grid" style="grid-template-columns: auto '
                        f'repeat({len(machs)}, 24px)"><div></div>']
                grid += [f'<div class="as-cov-axis">{format_value(m)}</div>' for m in machs]
                for aoa in aoas:
                    grid.append(f'<div class="as-cov-axis as-cov-axis-r">{_value(AOA, aoa)}</div>')
                    for mach in machs:
                        found = by_key.get((alt, elev, beta, aoa, mach))
                        grid.append(square(found) if found else "<div></div>")
                grid.append(f'</div><div class="as-cov-axis as-cov-foot">{_converged(inside)}</div></div>')
                html.append("".join(grid))
        html.append("</div>")
        hint("One panel per altitude and elevator deflection: AoA down, Mach across.")
        with ui.element("div").classes("as-cov-scroll w-full"):
            ui.html("".join(html), sanitize=False).mark("coverage-panels")

    # --- Table: one altitude (and sideslip) at a time; Mach across, split by elevator ----------------------------------

    def table(self) -> None:
        levels = self.levels
        with ui.row().classes("items-center gap-3"):
            ui.label("Altitude").classes("as-label")
            ui.toggle({a: _value(ALT, a) for a in levels[ALT]}, value=self.altitude,
                      on_change=lambda e: self._pick_table(altitude=e.value)).props(
                "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark("coverage-altitude")
            if len(levels[BETA]) > 1:
                ui.label("Sideslip").classes("as-label")
                ui.toggle({b: _value(BETA, b) for b in levels[BETA]}, value=self.beta,
                          on_change=lambda e: self._pick_table(beta=e.value)).props(
                    "dense no-caps unelevated toggle-color=primary").classes("as-toggle")
        machs, elevs = levels[MACH], levels[ELEV]
        by_key = {(run.key[AOA], run.key[MACH], run.key[ELEV]): run for run in self.runs
                  if run.key[ALT] == self.altitude and run.key[BETA] == self.beta}
        sep = '<td class="as-cov-sep"></td>'
        head = ["<tr><th></th>" + sep.join(f'<th class="as-cov-group" colspan="{len(elevs)}">M {format_value(m)}</th>'
                                           for m in machs) + "<th></th></tr>",
                "<tr><th></th>" + sep.join("".join(f"<th>{format_value(e)}°</th>" for e in elevs) for _ in machs)
                + '<th class="as-cov-pct">conv.</th></tr>']
        body = []
        per_mach: dict[float, list[Run]] = defaultdict(list)
        for aoa in sorted(levels[AOA], reverse=True):
            row_runs = []
            groups = []
            for mach in machs:
                cells = ""
                for elev in elevs:
                    found = by_key.get((aoa, mach, elev))
                    cells += f"<td>{square(found) if found else ''}</td>"
                    if found:
                        row_runs.append(found)
                        per_mach[mach].append(found)
                groups.append(cells)
            body.append(f'<tr><th class="as-cov-axis-r">α {_value(AOA, aoa)}</th>{sep.join(groups)}'
                        f'<td class="as-cov-pct">{_percent(row_runs)}</td></tr>')
        foot = ('<tr><th class="as-cov-pct">conv.</th>'
                + sep.join(f'<td class="as-cov-pct as-cov-center" colspan="{len(elevs)}">{_percent(per_mach[m])}</td>'
                           for m in machs) + "<td></td></tr>")
        hint("AoA down; Mach across, each split by elevator deflection. Converged share per row and per Mach.")
        with ui.element("div").classes("as-cov-scroll w-full"):
            ui.html(f'<table class="as-cov-table">{"".join(head)}{"".join(body)}{foot}</table>', sanitize=False).mark(
                "coverage-table")

    def _pick_table(self, altitude: Optional[float] = None, beta: Optional[float] = None) -> None:
        self.altitude = self.altitude if altitude is None else altitude
        self.beta = self.beta if beta is None else beta
        self.draw_view()

    # --- Pivot: any two parameters; each box gathers the runs that share their values ----------------------------------

    def pivot(self) -> None:
        levels = self.levels
        swept = {axis: AXES[axis][0] for axis in range(5) if len(levels[axis]) > 1} or {MACH: AXES[MACH][0]}
        with ui.row().classes("items-center gap-3"):
            ui.label("Rows").classes("as-label")
            ui.select(swept, value=self.pivot_rows, on_change=lambda e: self._pick_axes(rows=e.value)).props(
                "dense outlined").classes("w-40").mark("coverage-pivot-rows")
            ui.label("Columns").classes("as-label")
            ui.select(swept, value=self.pivot_columns, on_change=lambda e: self._pick_axes(columns=e.value)).props(
                "dense outlined").classes("w-40").mark("coverage-pivot-columns")
        rows, columns = self.pivot_rows, self.pivot_columns
        groups: dict[tuple, list[Run]] = defaultdict(list)
        for found in self.runs:
            groups[(found.key[rows], found.key[columns])].append(found)
        hint("Each box gathers every run with that pair of values. Click one to list its runs.")
        with ui.element("div").classes("as-cov-scroll w-full"):
            with ui.element("table").classes("as-cov-pivot").mark("coverage-pivot"):
                with ui.element("tr"):
                    ui.element("th")
                    for column in levels[columns]:
                        with ui.element("th"):
                            ui.label(_value(columns, column))
                for row in sorted(levels[rows], reverse=rows == AOA):
                    with ui.element("tr"):
                        with ui.element("th").classes("as-cov-axis-r"):
                            ui.label(_value(rows, row))
                        for column in levels[columns]:
                            inside = groups.get((row, column), [])
                            counts = Counter(found.status for found in inside)
                            box = ui.element("td").classes("as-cov-picked" if self.picked == (row, column) else "")
                            box.mark(f"coverage-box-{format_value(row)}-{format_value(column)}")
                            box.on("click", lambda _, pick=(row, column): self._pick_box(pick))
                            with box:
                                ui.html(bar(counts, len(inside)), sanitize=False)
                                ui.html(f'<div class="as-cov-count"><b>{counts["Converged"]}</b>/{len(inside)} '
                                        f"conv.</div>", sanitize=False)
        if self.picked is not None:
            row, column = self.picked
            self.show_runs(groups.get(self.picked, []),
                           f"{AXES[rows][0]} {_value(rows, row)} · {AXES[columns][0]} {_value(columns, column)}")

    def _pick_axes(self, rows: Optional[int] = None, columns: Optional[int] = None) -> None:
        self.pivot_rows = self.pivot_rows if rows is None else rows
        self.pivot_columns = self.pivot_columns if columns is None else columns
        self.picked = None
        self.draw_view()

    def _pick_box(self, pick: tuple) -> None:
        self.picked = None if self.picked == pick else pick
        self.draw_view()

    # --- the runs listed below the view ----------------------------------------------------------------------------------

    def show_runs(self, runs: list[Run], title: str) -> None:
        from .tracker import bar_text
        self.detail.clear()
        with self.detail:
            counts = Counter(found.status for found in runs)
            ui.label(f"{title} — {len(runs)} run{'' if len(runs) == 1 else 's'} · {bar_text(counts, len(runs))}"
                     if len(runs) > 1 else title).classes("as-card-subtitle").mark("coverage-detail-title")
            lines = []
            for found in runs[:RUNS_LISTED]:
                waiting = f' <span class="as-muted">→ {escape(found.new)} (to write)</span>' if found.new else ""
                lines.append(f'<div class="as-cov-line">{square(found, " as-cov-small")}'
                             f'<span class="as-mono">{found.run_id}</span>{escape(run_text(found))}'
                             f'<span class="as-muted">{escape(found.status or "no status")}</span>{waiting}</div>')
            ui.html(f'<div class="as-cov-lines">{"".join(lines)}</div>', sanitize=False).mark("coverage-detail-runs")
            if len(runs) > RUNS_LISTED:
                hint(f"and {len(runs) - RUNS_LISTED} more")


def _percent(runs: list[Run]) -> str:
    return f"{round(100 * sum(run.status == 'Converged' for run in runs) / len(runs))}%" if runs else ""


def sheet_chips(current: Link, view: str) -> None:
    """The linked sheets, to switch to in the same view."""
    with ui.row().classes("gap-2"):
        for link in load_tracker().links:
            on = link.id == current.id
            ui.link(link.sheet, coverage_url(link.id, view)).classes(
                "as-chip as-cov-chip" + (" as-chip-on" if on else "")).mark(f"coverage-sheet-{link.id}")

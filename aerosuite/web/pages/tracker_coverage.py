"""Coverage of a linked run-matrix sheet: every run's Status laid out by its sweep values, in three views.

Panels (one small grid per altitude x elevator), Table (one table per altitude) and Pivot (any two parameters, each
box gathering the runs that share them). Clicking a run opens it below the view, to set its Status and Notes by hand;
shift-click, a drag, or a Mach / AoA label selects several, and a bar marks them all at once."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from itertools import product
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from nicegui import run, ui

from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.tracker import VERDICTS, Key, verdict_reason
from ...engine.tracker_links import Link, LinkReport, RunEdit, discard_queued, edit_or_queue, report, saved_links
from ..layout import project_url
from ..ui_kit import banner, card, flat_button, hint, primary_button, secondary_button

VIEWS = {"panels": "Panels", "table": "Table", "pivot": "Pivot"}
AXES = [("Mach", ""), ("Altitude", " km"), ("AoA", "°"), ("Elevator δe", "°"), ("Sideslip β", "°")]
MACH, ALT, AOA, ELEV, BETA = range(5)
RUNS_LISTED = 60  # runs a pivot box lists
# the sheet's Status -> the square's colour (the overview bar's segments, failures apart)
TONES = {"Converged": "converged", "Not Converged": "not", "Failed": "failed", "Diverged": "failed",
         "Running": "live", "Pending": "live", "Hold": "hold"}
# what a run's Status can be set to by hand (the sheet's text: its label), "" blanking it
STATUS_CHOICES = {"Converged": "Converged", "Not Converged": "Not converged", "Diverged": "Diverged",
                  "Failed": "Failed", "Hold": "Hold", "": "Blank"}
PICK_EVENT = "as-cov-pick"
# A click on a run (or a Mach / AoA label: its runs) sends its run IDs; shift / Ctrl / ⌘ adds to the selection, and a
# drag across runs selects them all.
PICK_JS = f"""
<script>
if (!window.asCovPick) {{
  window.asCovPick = true;
  let drag = null;
  const target = (e) => e.target.closest ? e.target.closest('[data-run], [data-runs]') : null;
  document.addEventListener('mousedown', (e) => {{
    const el = target(e);
    if (!el || e.button !== 0) return;
    e.preventDefault();
    drag = {{ids: el.dataset.run ? [el.dataset.run] : el.dataset.runs.split(','),
             add: e.shiftKey || e.ctrlKey || e.metaKey, cells: !!el.dataset.run}};
    el.classList.add('as-cov-dragging');
  }});
  document.addEventListener('mouseover', (e) => {{
    const el = drag && drag.cells ? target(e) : null;
    if (!el || !el.dataset.run || drag.ids.includes(el.dataset.run)) return;
    drag.ids.push(el.dataset.run);
    el.classList.add('as-cov-dragging');
  }});
  document.addEventListener('mouseup', () => {{
    if (!drag) return;
    document.querySelectorAll('.as-cov-dragging').forEach((el) => el.classList.remove('as-cov-dragging'));
    emitEvent('{PICK_EVENT}', {{ids: drag.ids, add: drag.add, many: !drag.cells || drag.ids.length > 1}});
    drag = null;
  }});
}}
</script>
"""


def coverage_url(link_id: str, view: str = "") -> str:
    return f"/tracker/coverage?link={quote(link_id)}" + (f"&view={quote(view)}" if view else "")


@dataclass(frozen=True)
class Run:
    run_id: str
    key: Key
    status: str  # in the sheet now; "" when blank
    new: Optional[str]  # what the link would write, if it differs
    notes: str = ""
    queued: Optional[RunEdit] = None  # a hand edit waiting for the workbook to close


def runs_of(result: LinkReport) -> list[Run]:
    changes = {change.row.row: change.status for change in result.plan.changes} if result.plan else {}
    runs = []
    for row in result.matrix.rows:
        queued = result.queued.get(row.run_id)
        new = queued.status if queued is not None and queued.status is not None else changes.get(row.row)
        runs.append(Run(row.run_id, row.key, row.status, new if new != row.status else None, row.notes, queued))
    return runs


def _value(axis: int, value: float) -> str:
    return f"{format_value(value)}{AXES[axis][1]}"


def run_text(run: Run) -> str:
    mach, alt, aoa, elev, beta = run.key
    text = f"M {format_value(mach)} · {_value(ALT, alt)} · α {_value(AOA, aoa)} · δe {_value(ELEV, elev)}"
    return text + (f" · β {_value(BETA, beta)}" if beta else "")


def square(run: Run, size: str = "", chosen: bool = False) -> str:
    """A run as a coloured square (a ring when a write is waiting, a tick when selected); a click opens it below the
    view (PICK_JS)."""
    tone = TONES.get(run.status, "none")
    waiting = "queued: the workbook is open" if run.queued else "to write"
    tip = f"{run.run_id} · {run_text(run)}\n{run.status or 'no status'}" + (
        f" → {run.new or 'blank'} ({waiting})" if run.new is not None else "")
    tip += f"\n{run.notes}" if run.notes else ""
    classes = (f"as-cov-cell as-cov-{tone}{' as-cov-change' if run.new is not None or run.queued else ''}"
               f"{' as-cov-sel' if chosen else ''}"
               f"{size}")
    return f'<span class="{classes}" title="{escape(tip)}" data-run="{run.run_id}"></span>'


def picker(text: str, runs: list[Run], tag: str = "div", classes: str = "") -> str:
    """An axis label that selects its runs (a row or column of a grid) when clicked."""
    ids = ",".join(run.run_id for run in runs)
    if not ids:
        return f'<{tag} class="{classes}">{text}</{tag}>'
    return (f'<{tag} class="{classes} as-cov-pickable" data-runs="{ids}" '
            f'title="Select these {len(runs)} runs">{text}</{tag}>')


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
        self.selected: list[str] = []  # run IDs, for the bar
        self.body = ui.column().classes("w-full gap-4")
        with self.body:
            hint("Reading the workbook and the jobs…").mark("coverage-loading")
        self._bar()
        ui.add_body_html(PICK_JS)
        ui.on(PICK_EVENT, self._on_pick)
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

    async def refresh(self, editing: Optional[str] = None) -> None:
        """Read the sheet and the jobs again, keeping the view as it is (and the run being edited open)."""
        self.result = await run.io_bound(report, self.link)
        if self.result.matrix is not None:
            self.runs = runs_of(self.result)
            self.by_id = {found.run_id: found for found in self.runs}
            self.selected = [run_id for run_id in self.selected if run_id in self.by_id]
        self.draw()
        self.show_selection()
        if editing in self.by_id:
            await self.edit(self.by_id[editing])

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
            self._detail_hint()

    def _detail_hint(self) -> None:
        self.detail.clear()
        with self.detail:
            hint("Click a run to see it here and set its status or notes. Shift-click, drag, or click a Mach or AoA "
                 "label to select several." if self.view != "pivot" else "Click a box to list its runs.")

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
                grid += [picker(format_value(m), [r for r in inside if r.key[MACH] == m], classes="as-cov-axis")
                         for m in machs]
                for aoa in aoas:
                    grid.append(picker(_value(AOA, aoa), [r for r in inside if r.key[AOA] == aoa],
                                       classes="as-cov-axis as-cov-axis-r"))
                    for mach in machs:
                        found = by_key.get((alt, elev, beta, aoa, mach))
                        grid.append(self._square(found) if found else "<div></div>")
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
        in_table = list(by_key.values())
        head = ["<tr><th></th>" + sep.join(picker(f"M {format_value(m)}", [r for r in in_table if r.key[MACH] == m], "th",
                                                  "as-cov-group").replace("<th ", f'<th colspan="{len(elevs)}" ', 1)
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
                    cells += f"<td>{self._square(found) if found else ''}</td>"
                    if found:
                        row_runs.append(found)
                        per_mach[mach].append(found)
                groups.append(cells)
            body.append(f'<tr>{picker(f"α {_value(AOA, aoa)}", row_runs, "th", "as-cov-axis-r")}{sep.join(groups)}'
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
            if len(runs) > 1:
                flat_button(f"Select these {len(runs)}", lambda: self.select([found.run_id for found in runs]),
                            icon="checklist").classes("self-start").mark("coverage-detail-select")
            lines = []
            for found in runs[:RUNS_LISTED]:
                waiting = (f' <span class="as-muted">→ {escape(found.new or "blank")} '
                           f'({"queued" if found.queued else "to write"})</span>' if found.new is not None else "")
                lines.append(f'<div class="as-cov-line" data-run="{found.run_id}">'
                             f'{self._square(found, " as-cov-small")}'
                             f'<span class="as-mono">{found.run_id}</span>{escape(run_text(found))}'
                             f'<span class="as-muted">{escape(found.status or "no status")}</span>{waiting}</div>')
            ui.html(f'<div class="as-cov-lines">{"".join(lines)}</div>', sanitize=False).mark("coverage-detail-runs")
            if len(runs) > RUNS_LISTED:
                hint(f"and {len(runs) - RUNS_LISTED} more")

    def _square(self, found: Run, size: str = "") -> str:
        return square(found, size, found.run_id in self.selected)

    # --- one run: its Status and Notes, set by hand ----------------------------------------------------------------------

    async def _on_pick(self, event) -> None:
        args = event.args if isinstance(event.args, dict) else {}
        ids = [run_id for run_id in dict.fromkeys(args.get("ids") or []) if run_id in self.by_id]
        if not ids:
            return
        if args.get("add"):
            if all(run_id in self.selected for run_id in ids):
                self.select([run_id for run_id in self.selected if run_id not in ids])
            else:
                self.select(self.selected + [run_id for run_id in ids if run_id not in self.selected])
        elif len(ids) == 1 and not args.get("many"):
            self.select([])
            await self.edit(self.by_id[ids[0]])
        else:
            self.select(ids)

    async def edit(self, found: Run) -> None:
        """The run below the view: its Status and Notes to set, beside what the jobs say about it."""
        from .tracker import status_pill
        source = self.result.statuses.get(found.key)
        notes_column = self.result.matrix.notes_column
        queued = found.queued
        now_status = queued.status if queued is not None and queued.status is not None else found.status
        now_notes = queued.notes if queued is not None and queued.notes is not None else found.notes
        self.detail.clear()
        with self.detail:
            with ui.column().classes("as-run-edit w-full").mark("run-edit"):
                with ui.row().classes("w-full items-start no-wrap"):
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(found.run_id).classes("as-card-title").mark("run-edit-title")
                        ui.label(run_text(found)).classes("as-mono as-muted")
                    ui.button(icon="close", on_click=self._detail_hint).props("flat round dense size=sm").mark(
                        "run-edit-close")
                with ui.row().classes("as-run-edit-body w-full"):
                    with ui.column().classes("gap-2 grow min-w-0"):
                        ui.label("Status in the sheet").classes("as-label")
                        status = ui.toggle(STATUS_CHOICES, value=now_status if now_status in STATUS_CHOICES
                                           else None).props("dense no-caps unelevated toggle-color=dark").classes(
                            "as-toggle as-run-status").mark("run-edit-status")
                        said = hint().mark("run-edit-hint")
                        status.on_value_change(lambda e: said.set_text(self._status_hint(e.value, found, source)))
                        said.set_text(self._status_hint(status.value, found, source))
                        ui.label("Notes").classes("as-label q-mt-sm")
                        if notes_column and not found.notes.startswith("="):
                            notes = ui.textarea(value=now_notes, placeholder="Add a note").props(
                                "outlined dense autogrow").classes("w-full as-field").mark("run-edit-notes")
                        else:
                            notes = None
                            hint("This sheet has no Notes column." if not notes_column
                                 else "Its Notes cell holds a formula: change it in Excel.")
                    with ui.column().classes("as-run-edit-side"):
                        ui.label("What the jobs say").classes("as-label")
                        if source is None:
                            hint("No job has run this case yet.").mark("run-edit-nojob")
                        else:
                            status_pill(source.status).classes("self-start").mark("run-edit-job")
                            reason = ui.label().classes("as-muted")
                            ui.label(f"{source.project} · job {source.job_id}").classes("as-mono as-muted")
                            ui.label(source.case).classes("as-mono as-muted as-truncate")
                            ui.link("Open in Monitor", project_url("monitor", source.folder)
                                    + f"&case={quote(source.case)}").classes("as-link")
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    if queued is not None:
                        with ui.row().classes("grow items-center gap-2"):
                            ui.label(f"Queued: written when the workbook is closed"
                                     f"{' in ' + self.result.open_in if self.result.open_in else ''}.").classes(
                                "as-tag-hint").mark("run-edit-queued")
                            ui.label("Discard it").classes("as-link").mark("run-edit-discard").on(
                                "click", lambda: self._discard(found.run_id))
                    elif self.result.open_in:
                        hint(f"The workbook is open in {self.result.open_in}: Save keeps this edit and writes it when "
                             "the workbook is closed.").classes("grow").mark("run-edit-open")
                    else:
                        hint("Saved into the workbook (a backup is kept beside it).").classes("grow")
                    secondary_button("Cancel", self._detail_hint).mark("run-edit-cancel")
                    save = primary_button("Save", icon="save").mark("run-edit-save")
                    save.on_click(lambda: self._save({found.run_id: RunEdit(
                        status=status.value, notes=notes.value if notes is not None else None)}, found.run_id))
        if source is not None and source.status in VERDICTS:
            text = await run.io_bound(verdict_reason, Path(source.folder), source.case)
            if not reason.is_deleted:  # still open
                reason.set_text(text)

    def _status_hint(self, value: Optional[str], found: Run, source) -> str:
        if value is None:
            return f"Now {found.status}: a job sets this one." if found.status in ("Running", "Pending") else ""
        if value in VERDICTS:
            return ("This link overwrites verdicts: the next write puts back what the jobs say." if self.link.overwrite
                    else "A verdict set here is kept: later writes won't change it.")
        if source is not None and source.status != (value or None):
            return f"The next write sets it to {source.status}, as the jobs say."
        return ""

    async def _save(self, edits: dict[str, RunEdit], editing: Optional[str] = None) -> bool:
        try:
            changed, queued = await run.io_bound(edit_or_queue, self.link, edits)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return False
        name = Path(self.link.workbook).name
        if queued:
            ui.notify(f"{name} is open: {queued} edit{'' if queued == 1 else 's'} queued, written when it is closed",
                      type="warning", multi_line=True)
        else:
            ui.notify(f"Saved {changed} run{'' if changed == 1 else 's'} to {name}" if changed
                      else "Nothing to save: it is already so", type="positive" if changed else "info")
        await self.refresh(editing)
        return True

    async def _discard(self, run_id: str) -> None:
        await run.io_bound(discard_queued, self.link.id, [run_id])
        ui.notify(f"The queued edit of {run_id} was discarded")
        await self.refresh(run_id)

    # --- several runs: the bar ---------------------------------------------------------------------------------------

    def _bar(self) -> None:
        with ui.row().classes("as-cov-bar no-wrap").mark("coverage-bar") as self.bar:
            self.bar_count = ui.label().classes("as-cov-bar-count").mark("coverage-bar-count")
            ui.element("span").classes("as-cov-bar-sep")
            ui.label("Mark as").classes("as-cov-bar-text")
            for value, label in STATUS_CHOICES.items():
                tone = TONES.get(value, "none")
                ui.button(label, on_click=lambda value=value: self.mark_selected(value), color=None).props(
                    "flat dense no-caps text-color=white").classes(f"as-cov-bar-btn as-cov-bar-{tone}").mark(
                    f"coverage-bar-{(value or 'blank').lower().replace(' ', '-')}")
            ui.element("span").classes("as-cov-bar-sep")
            self.note_button = ui.button("Add a note", icon="edit_note", on_click=self._note_dialog, color=None).props(
                "flat dense no-caps text-color=white").classes("as-cov-bar-btn").mark("coverage-bar-note")
            ui.button(icon="close", on_click=lambda: self.select([]), color=None).props("flat dense round text-color=white").classes(
                "as-cov-bar-btn").mark("coverage-bar-close")
        self.bar.set_visibility(False)

    def select(self, ids: list[str]) -> None:
        self.selected = list(dict.fromkeys(ids))
        self.show_selection()

    def show_selection(self) -> None:
        count = len(self.selected)
        self.bar.set_visibility(bool(count))
        self.bar_count.set_text(f"{count} run{'' if count == 1 else 's'} selected")
        self.note_button.set_visibility(bool(self.result and self.result.matrix and self.result.matrix.notes_column))
        self.bar.client.run_javascript(f"const chosen = new Set({json.dumps(self.selected)}); document.querySelectorAll("
                          f"'.as-cov-cell[data-run]').forEach((c) => c.classList.toggle('as-cov-sel', "
                          f"chosen.has(c.dataset.run)));")

    async def mark_selected(self, status: str) -> None:
        if await self._save({run_id: RunEdit(status=status) for run_id in self.selected}):
            self.select([])

    def _note_dialog(self) -> None:
        count = len(self.selected)
        with ui.dialog() as dialog, ui.card().classes("as-dialog").mark("coverage-note-dialog"):
            ui.label(f"A note for {count} run{'' if count == 1 else 's'}").classes("as-card-title")
            text = ui.textarea(placeholder="e.g. residuals blow up after 3k iterations").props(
                "outlined dense autogrow autofocus").classes("w-full as-field").mark("coverage-note-text")
            replace = ui.checkbox("Replace their notes (otherwise it goes after them)").mark("coverage-note-replace")

            async def save() -> None:
                note = (text.value or "").strip()
                if not note:
                    ui.notify("Write a note first", type="warning")
                    return
                edits = {}
                for run_id in self.selected:
                    found = self.by_id[run_id]
                    old = found.queued.notes if found.queued and found.queued.notes is not None else found.notes
                    edits[run_id] = RunEdit(notes=note if replace.value or not old else f"{old}; {note}")
                if await self._save(edits):
                    dialog.close()
                    self.select([])

            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", dialog.close)
                primary_button("Save", save, icon="save").mark("coverage-note-save")
        dialog.open()


def _percent(runs: list[Run]) -> str:
    return f"{round(100 * sum(run.status == 'Converged' for run in runs) / len(runs))}%" if runs else ""


def sheet_chips(current: Link, view: str) -> None:
    """The linked sheets, to switch to in the same view."""
    with ui.row().classes("gap-2"):
        for link in saved_links():
            on = link.id == current.id
            ui.link(link.sheet, coverage_url(link.id, view)).classes(
                "as-chip as-cov-chip" + (" as-chip-on" if on else "")).mark(f"coverage-sheet-{link.id}")

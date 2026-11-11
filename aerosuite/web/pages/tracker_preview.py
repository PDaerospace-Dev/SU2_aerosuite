"""Run matrix › Preview: what a write would change, the verdicts entered by hand that a job disagrees with, and
the cases the sheet has no row for."""
from pathlib import Path

from nicegui import run, ui

from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.tracker import backups_dir, outside_reason
from ...engine.tracker_links import Link, report, write_link
from ..tracker_view import pill_html
from ..ui_kit import (
    banner,
    card,
    chip_button,
    flat_button,
    hint,
    html_table,
    html_td,
    html_th,
    ok_line,
    primary_button,
    secondary_button,
    table,
    td,
    td_box,
    th,
    warning_group,
)
from .tracker_coverage import coverage_url
from .tracker_parts import ROWS_AT_MOST, edit_url, status_pill

# --- preview ----------------------------------------------------------------------------------------------------------

class Preview:
    def __init__(self, link: Link) -> None:
        self.link = link
        self.accepted: set[int] = set()  # kept verdicts' rows whose job verdict the user takes
        self.tab = "write"
        self.holder = ui.column().classes("w-full gap-4")
        with self.holder:
            hint("Reading the workbook and the jobs…").mark("preview-loading")
        ui.timer(0, self.load, once=True)

    async def load(self) -> None:
        self.result = await run.io_bound(report, self.link, True)
        if not self.holder.is_deleted:
            self.render()

    def render(self) -> None:
        result = self.result
        self.holder.clear()
        with self.holder:
            if result.error:
                banner("error", result.error).mark("preview-error")
                secondary_button("Change the link", lambda: ui.navigate.to(edit_url(self.link.id)))
                return
            plan = result.plan
            with ui.row().classes("as-conditions w-full"):
                for label, value, mark in (("To write", len(plan.changes), "preview-changes"),
                                           ("Unchanged", plan.unchanged, "preview-unchanged"),
                                           ("Your verdicts kept", len(plan.kept), "preview-kept"),
                                           ("No job yet", result.no_job, "preview-no-job"),
                                           ("Cases not in the sheet", len(plan.outside), "preview-outside")):
                    with ui.column().classes("as-condition gap-0"):
                        ui.label(label).classes("as-condition-label")
                        ui.label(str(value)).classes("as-condition-value").mark(mark)
            problems = result.warnings + [f"{p.name}: {p.error}" for p in result.projects if p.error]
            if problems:
                warning_group(problems, mark="preview-warnings")
            with card(flush=True):
                with ui.tabs(value=self.tab, on_change=lambda e: setattr(self, "tab", e.value)).props(
                        "dense no-caps align=left inline-label").classes("as-tabs w-full").mark("preview-tabs") as tabs:
                    for key, label, count in (("write", "To write", len(plan.changes)),
                                              ("kept", "Your verdicts kept", len(plan.kept)),
                                              ("outside", "Not in the sheet", len(plan.outside))):
                        with ui.tab(key, label).mark(f"preview-tab-{key}"):
                            ui.label(str(count)).classes("as-tab-count")
                with ui.tab_panels(tabs, value=self.tab).props("keep-alive").classes("as-tab-panels w-full"):
                    with ui.tab_panel("write"):
                        self._changes()
                    with ui.tab_panel("kept"):
                        self.kept_box = ui.column().classes("w-full gap-0")
                        self._kept()
                    with ui.tab_panel("outside"):
                        self._outside()
            if self.result.completed_on:
                ok_line(f"Every run has a verdict: Completed on ({self.result.matrix.completed_on}) will be set to "
                        f"{self.result.completed_on:%Y-%m-%d}, the day the last job ended.").mark("preview-completed")
            with ui.row().classes("w-full items-center gap-2"):
                workbook = Path(self.link.workbook)
                hint(f"Only the Status cells (and a blank Completed on) change. The previous file is kept as "
                     f"{workbook.stem}.bak{workbook.suffix}, and a copy per day for a week in "
                     f"{backups_dir(workbook).name}.").classes("grow")
                flat_button("Coverage", lambda: ui.navigate.to(coverage_url(self.link.id)), icon="grid_view").mark(
                    "preview-coverage")
                flat_button("Change the link", lambda: ui.navigate.to(edit_url(self.link.id))).mark("preview-edit")
                secondary_button("Back", lambda: ui.navigate.to("/tracker")).mark("preview-back")
                self.write_button = primary_button("", self._write).mark("preview-write")
            self._update_write()

    def _changes(self) -> None:
        changes = self.result.plan.changes
        if not changes:
            with ui.column().classes("as-panel-pad"):
                ok_line("Nothing to write: the sheet already has every status the jobs give.").mark("preview-none")
            return
        hint("Statuses the sheet does not have yet: runs that started or finished since it was last written.").classes(
            "as-panel-pad")
        cells = [html_th(t) for t in ("Run", "Mach", "Alt (km)", "AoA", "δe", "In the sheet", "Will be", "From")]
        for change in changes[:ROWS_AT_MOST]:
            mach, alt, aoa, elev, _beta = change.row.key
            cells += [html_td(change.row.run_id, classes="as-mono"),
                      *(html_td(format_value(v)) for v in (mach, alt, aoa, elev)),
                      html_td(inner=pill_html(change.row.status)), html_td(inner=pill_html(change.status)),
                      html_td(f"{change.source.project} / {change.source.case} · job {change.source.job_id}",
                              classes="as-muted")]
        with ui.element("div").classes("as-table-scroll w-full"):
            html_table("auto auto auto auto auto auto auto minmax(240px, 1fr)", cells).classes(
                "as-preview-table").mark("preview-change-table")
        self._more(len(changes))

    def _kept(self) -> None:
        kept = self.result.plan.kept
        self.kept_box.clear()
        with self.kept_box:
            if not kept:
                with ui.column().classes("as-panel-pad"):
                    ok_line("No verdict of yours differs from the jobs'.").mark("preview-no-kept")
                return
            with ui.row().classes("as-kept-head w-full"):
                ui.label("You marked these yourself, and the job's convergence check says otherwise. Yours stay unless "
                         "you take the job's.").classes("grow min-w-0")
                every = len(self.accepted) == len(kept)
                secondary_button("Keep all yours" if every else f"Use the job's for all {len(kept)}",
                                 lambda: self._accept_all(not every)).mark("preview-accept-all")
            with ui.element("div").classes("as-table-scroll w-full"):
                with table("auto auto auto auto auto auto auto minmax(200px, 1fr) auto").classes("as-preview-table"):
                    for title in ("Run", "Mach", "Alt (km)", "AoA", "δe", "Yours", "The job says", "Why", ""):
                        th(title)
                    for change in kept[:ROWS_AT_MOST]:
                        row = change.row.row
                        mark = f"preview-kept-{change.row.run_id}"
                        td(change.row.run_id, mono=True)
                        for value in change.row.key[:4]:
                            td(format_value(value))
                        with td_box():
                            status_pill(change.row.status)
                        with td_box():
                            status_pill(change.status)
                        reason = self.result.reasons.get(row, "")
                        td(reason or "—").classes("as-muted as-wrap")
                        with td_box():
                            on = row in self.accepted
                            chip_button("Using the job's" if on else "Use the job's",
                                        lambda r=row: self._accept(r)).classes("as-chip-on" if on else "").mark(mark)
            self._more(len(kept))

    def _outside(self) -> None:
        outside = self.result.plan.outside
        if not outside:
            with ui.column().classes("as-panel-pad"):
                ok_line("Every case of the chosen jobs has a row in the sheet.").mark("preview-no-outside")
            return
        hint("Cases the chosen jobs ran that no row of the sheet is for: nothing is written for them.").classes(
            "as-panel-pad")
        cells = [html_th(t) for t in ("Project / case", "Status", "Not in the sheet because")]
        for entry in outside[:ROWS_AT_MOST]:
            cells += [html_td(f"{entry.project} / {entry.case}", classes="as-mono"),
                      html_td(inner=pill_html(entry.status)),
                      html_td(outside_reason(self.result.matrix, entry.key) if entry.key else "", classes="as-muted")]
        with ui.element("div").classes("as-table-scroll w-full"):
            html_table("minmax(260px, 1fr) auto minmax(220px, 1fr)", cells).classes("as-preview-table").mark(
                "preview-outside-table")
        self._more(len(outside))

    @staticmethod
    def _more(count: int) -> None:
        if count > ROWS_AT_MOST:
            hint(f"Showing the first {ROWS_AT_MOST} of {count}.").classes("as-panel-pad")

    def _accept(self, row: int) -> None:
        (self.accepted.discard if row in self.accepted else self.accepted.add)(row)
        self._kept()
        self._update_write()

    def _accept_all(self, on: bool) -> None:
        self.accepted = {change.row.row for change in self.result.plan.kept} if on else set()
        self._kept()
        self._update_write()

    def _count(self) -> int:
        return len(self.result.plan.changes) + len(self.accepted)

    def _update_write(self) -> None:
        count = self._count()
        completed = self.result.completed_on is not None
        self.write_button.text = (f"Write {count} status{'' if count == 1 else 'es'}" if count
                                  else "Write the completion date" if completed else "Nothing to write")
        self.write_button.set_enabled(bool(count) or completed)

    async def _write(self) -> None:
        accepted = [change for change in self.result.plan.kept if change.row.row in self.accepted]
        self.write_button.set_enabled(False)
        try:
            written = await run.io_bound(write_link, self.link, accepted)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            self.write_button.set_enabled(True)
            return
        ui.notify(f"Wrote {written} status{'' if written == 1 else 'es'} to {Path(self.link.workbook).name}",
                  type="positive")
        self.accepted.clear()
        await self.load()

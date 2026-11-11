"""Run matrix: run-matrix workbooks whose Status column follows the projects' jobs (engine/tracker_links.py).

/tracker lists the linked sheets; /tracker/link links a sheet (?link=<id> changes a link); /tracker/preview?link=<id>
shows what a write would change, and the verdicts entered by hand that a job disagrees with, before writing;
/tracker/new adds a sheet to a workbook from its template sheet, and links it."""
from collections import Counter
from pathlib import Path

from nicegui import run, ui

from ...engine.errors import AeroSuiteError, TrackerError
from ...engine.naming import format_value
from ...engine.tracker import (
    BACKUPS_KEPT,
    ORDERS,
    daily_backups,
)
from ...engine.tracker_links import (
    Link,
    LinkReport,
    find_link,
    last_write,
    load_tracker,
    remove_link,
    report,
    saved_links,
    set_auto,
    set_completed,
    write_link,
)
from ..layout import header
from ..tracker_view import bar_html, bar_text
from ..ui_kit import (
    banner,
    card,
    danger_button,
    hint,
    primary_button,
    secondary_button,
    summary_tile,
    table,
    td_box,
    th,
    titled,
)
from .tracker_coverage import Coverage, coverage_url, sheet_chips
from .tracker_link import LinkForm
from .tracker_new import NewSheetForm
from .tracker_parts import GROUPS, NEW_URL, _crumbs, _log_text, edit_url, legend, preview_url, stack_cell, when_text
from .tracker_preview import Preview


def register() -> None:
    @ui.page("/tracker")
    def tracker_page() -> None:
        header("tracker")
        with ui.column().classes("as-page w-full").mark("tracker-page"):
            with ui.row().classes("w-full items-center no-wrap"):
                _crumbs(("Run matrix", ""))
                secondary_button("Coverage", lambda: ui.navigate.to(coverage_url("")), icon="grid_view").mark(
                    "tracker-coverage")
                secondary_button("New sheet from template", lambda: ui.navigate.to(NEW_URL), icon="note_add").mark(
                    "tracker-new")
                primary_button("Link a sheet", lambda: ui.navigate.to(edit_url()), icon="add").mark("tracker-add")
            Overview(ui.column().classes("w-full gap-4"))

    @ui.page("/tracker/link")
    def link_page(link: str = "") -> None:
        header("tracker")
        existing = find_link(link) if link else None
        with ui.column().classes("as-page w-full").mark("tracker-link-page"):
            _crumbs(("Run matrix", "/tracker"), ("Change a link" if existing else "Link a sheet", ""))
            if link and existing is None:
                banner("error", "This link no longer exists.").mark("tracker-missing")
                return
            LinkForm(existing)

    @ui.page(NEW_URL)
    def new_page() -> None:
        header("tracker")
        with ui.column().classes("as-page w-full").mark("tracker-new-page"):
            _crumbs(("Run matrix", "/tracker"), ("New sheet from template", ""))
            NewSheetForm()

    @ui.page("/tracker/coverage")
    def coverage_page(link: str = "", view: str = "") -> None:
        header("tracker")
        links = saved_links()
        ongoing = [item for item in links if item.completed is not True]
        found = find_link(link) if link else next(iter(ongoing or links), None)
        with ui.column().classes("as-page w-full").mark("tracker-coverage-page"):
            _crumbs(("Run matrix", "/tracker"), (f"{found.sheet} · coverage" if found else "Coverage", ""))
            if found is None:
                banner("error", "This link no longer exists.").mark("tracker-missing")
                return
            sheet_chips(found, view)
            Coverage(found, view)

    @ui.page("/tracker/preview")
    def preview_page(link: str = "") -> None:
        header("tracker")
        found = find_link(link)
        with ui.column().classes("as-page w-full").mark("tracker-preview-page"):
            _crumbs(("Run matrix", "/tracker"), (found.sheet if found else "Preview", ""))
            if found is None:
                banner("error", "This link no longer exists.").mark("tracker-missing")
                return
            Preview(found)


# --- the linked sheets ---------------------------------------------------------------------------------------------

class Overview:
    def __init__(self, holder: ui.column) -> None:
        self.holder = holder
        self.group = "ongoing"
        with holder:
            hint("Reading the workbooks…").mark("tracker-loading")
        ui.timer(0, self.load, once=True)

    async def load(self) -> None:
        try:
            data = load_tracker()
        except TrackerError as exc:  # never shown as "no sheets linked": a save then would lose the links
            self.holder.clear()
            with self.holder:
                banner("error", str(exc)).mark("tracker-unreadable")
            return
        reports = await run.io_bound(lambda: [report(link) for link in data.links])
        if self.holder.is_deleted:
            return
        self.holder.clear()
        with self.holder:
            self.render(data, reports)

    def render(self, data, reports: list[LinkReport]) -> None:
        if not reports:
            with card("No sheets linked yet") as box:
                box.mark("tracker-empty")
                hint("Link a sheet of a run-matrix workbook (the CFD run-matrix template: Mach, altitude, AoA, elevator"
                     " and sideslip in columns A–E, a Status column) to the projects that run its cases. AeroSuite "
                     "then fills in Status as cases run and finish; Notes and every other cell are left alone.")
                with ui.row().classes("gap-2"):
                    primary_button("Link a sheet", lambda: ui.navigate.to(edit_url()), icon="add").mark(
                        "tracker-add-empty")
                    secondary_button("New sheet from template", lambda: ui.navigate.to(NEW_URL),
                                     icon="note_add").mark("tracker-new-empty")
            return
        self._tiles(reports)
        grouped = {"ongoing": [item for item in reports if not item.done],
                   "completed": [item for item in reports if item.done]}
        if not grouped[self.group]:
            self.group = next((key for key in GROUPS if grouped[key]), "ongoing")
        with ui.tabs(value=self.group, on_change=lambda e: setattr(self, "group", e.value)).props(
                "dense no-caps align=left inline-label").classes("as-tabs w-full").mark("tracker-groups") as tabs:
            for key, label in GROUPS.items():
                with ui.tab(key, label).mark(f"tracker-group-{key}"):
                    ui.label(str(len(grouped[key]))).classes("as-tab-count").mark(f"tracker-group-{key}-count")
        with ui.tab_panels(tabs, value=self.group).classes("as-tab-panels w-full"):
            for key in GROUPS:
                with ui.tab_panel(key).classes("gap-4 p-0"):
                    if not grouped[key]:
                        hint("No completed sheets yet: a sheet moves here once every run has a verdict, or when "
                             "you mark it completed." if key == "completed" else "Every sheet is completed.")
                    workbooks: dict[str, list[LinkReport]] = {}
                    for item in grouped[key]:
                        workbooks.setdefault(item.link.workbook, []).append(item)
                    for workbook, items in workbooks.items():
                        self._workbook(workbook, items, data.log)
        self._log(data.log)

    def _tiles(self, reports: list[LinkReport]) -> None:
        counts = sum((item.sheet_counts for item in reports), start=Counter())
        runs = sum(len(item.matrix.rows) for item in reports if item.matrix)
        kept = [item for item in reports if item.plan and item.plan.kept]
        with ui.element("div").classes("as-tiles"):
            summary_tile("Runs in the matrices", f"{runs:,}").mark("tracker-runs")
            summary_tile("Converged", counts["Converged"]).mark("tracker-converged")
            summary_tile("Not converged", counts["Not Converged"]).mark("tracker-not-converged")
            with ui.column().classes("as-tile" + (" as-tile-attention" if kept else "")) as tile:
                tile.mark("tracker-kept-tile")
                ui.label("Your verdicts the jobs disagree with").classes("as-tile-label")
                ui.label(str(sum(len(item.plan.kept) for item in kept))).classes("as-tile-value").mark("tracker-kept")
            if kept:
                tile.on("click", lambda: ui.navigate.to(preview_url(kept[0].link.id)))
                titled(tile, "Review them")

    def _workbook(self, workbook: str, items: list[LinkReport], log) -> None:
        path = Path(workbook)
        with card(flush=True) as box:
            box.mark(f"tracker-workbook-{path.name}")
            with ui.row().classes("as-workbook-head w-full"):
                ui.icon("table_view").classes("as-workbook-icon")
                with ui.column().classes("gap-0 min-w-0 grow"):
                    ui.label(path.name).classes("as-card-title as-truncate")
                    ui.label(workbook).classes("as-mono as-muted as-hint")
                written = last_write(log, workbook)
                with ui.column().classes("gap-0"):
                    ui.label("Last written").classes("as-label")
                    ui.label(f"{when_text(written.at)} · {'automatically' if written.trigger == 'auto' else 'by hand'}"
                             if written else "Not yet").mark("tracker-last-write")
                ids = [item.link.id for item in items]
                ui.switch("Write automatically", value=all(item.link.auto for item in items),
                          on_change=lambda e, ids=ids: self._set_auto(ids, e.value)).mark("tracker-auto")
                secondary_button("Download", lambda: ui.download.file(path), icon="download").mark(
                    "tracker-download").set_enabled(path.is_file())
                self._backups(path)
            with ui.element("div").classes("as-table-scroll w-full"):
                with table("minmax(190px, 1.2fr) minmax(170px, 1fr) minmax(240px, 1.7fr) minmax(130px, .8fr) "
                           "auto").classes("as-matrix-table"):
                    for title in ("Sheet", "Projects", "Progress", "Waiting to write", ""):
                        th(title)
                    for item in items:
                        self._sheet_row(item)
            legend()

    def _backups(self, workbook: Path) -> None:
        """The workbook's daily copies (each from before that day's first write), to download."""
        copies = daily_backups(workbook)
        if not copies:
            return
        with ui.button(icon="history").props("flat round dense").mark("tracker-backups") as button:
            titled(button, f"Backups: the workbook before each day's first write, {BACKUPS_KEPT} kept")
            with ui.menu():
                ui.label("Before the first write of…").classes("as-menu-title")
                for day, copy in copies:
                    ui.menu_item(f"{day:%a %d %b %Y}", lambda copy=copy: ui.download.file(copy)).mark(
                        f"tracker-backup-{day:%Y-%m-%d}")

    def _sheet_row(self, item: LinkReport) -> None:
        link = item.link
        mark = f"tracker-sheet-{link.id}"
        with stack_cell():
            ui.label(link.sheet).classes("as-strong").mark(mark)
            runs = f"{len(item.matrix.rows)} runs" if item.matrix else ""
            if item.done:
                runs += " · " + ("marked completed" if link.completed else "every run has a verdict")
            hint(runs).mark(f"{mark}-runs")
        with stack_cell():
            elevators = ", ".join(format_value(p.elevator) for p in link.projects)
            ui.label(f"{len(link.projects)} project{'' if len(link.projects) == 1 else 's'}")
            hint(f"δe {elevators}" if elevators else "")
            with ui.row().classes("gap-1"):
                if link.order:
                    ui.label(f"{ORDERS.get(link.order, link.order)} only").classes("as-tag as-tag-accent").mark(
                        f"{mark}-order")
                for tag in link.tags:
                    ui.label(f"#{tag.lstrip('#')} only").classes("as-tag as-tag-accent")
                for tag in link.skip_tags:
                    ui.label(f"not #{tag.lstrip('#')}").classes("as-tag")
        with stack_cell():
            if item.error:
                ui.label(item.error).classes("as-error-text").mark(f"{mark}-error")
            else:
                total = len(item.matrix.rows)
                ui.html(bar_html(item.sheet_counts, total), sanitize=False).classes("w-full")
                hint(bar_text(item.sheet_counts, total)).mark(f"{mark}-progress")
        with stack_cell():
            if item.plan is not None:
                pending = len(item.plan.changes)
                ui.label(f"{pending} to write" if pending else "Up to date").classes(
                    "as-strong" if pending else "as-ok-text").mark(f"{mark}-pending")
                if item.plan.kept:
                    ui.label(f"{len(item.plan.kept)} verdicts kept").classes("as-hint as-hint-warning")
            if item.queued:
                count = len(item.queued)
                titled(ui.label(f"{count} edit{'' if count == 1 else 's'} of yours queued").classes(
                    "as-hint as-hint-warning").mark(f"{mark}-queued"),
                    "Set on the coverage page while the workbook was open; written when it is closed")
        with td_box():
            secondary_button("Preview", lambda: ui.navigate.to(preview_url(link.id))).mark(f"{mark}-preview")
            write = primary_button("Write", lambda: self._write(link)).mark(f"{mark}-write")
            write.set_enabled(bool(item.plan and item.plan.changes))
            with ui.button(icon="more_vert", color=None).props(
                    'flat round dense aria-label="More for this sheet"').tooltip("More").mark(f"{mark}-more"):
                with ui.menu():
                    if item.done:
                        ui.menu_item("Move to ongoing", lambda: self._set_completed(link, False)).mark(
                            f"{mark}-ongoing")
                    else:
                        ui.menu_item("Mark as completed", lambda: self._set_completed(link, True)).mark(
                            f"{mark}-complete")
                    ui.menu_item("Coverage", lambda: ui.navigate.to(coverage_url(link.id))).mark(f"{mark}-coverage")
                    ui.menu_item("Change the link", lambda: ui.navigate.to(edit_url(link.id))).mark(f"{mark}-edit")
                    ui.separator()
                    ui.menu_item("Remove from the run matrix", lambda: self._confirm_remove(link)).classes(
                        "as-error-text").mark(f"{mark}-remove")

    def _log(self, log) -> None:
        if not log:
            return
        with card("Recent writes", fold="tracker-log") as box:
            box.mark("tracker-log")
            for entry in log[:8]:
                with ui.row().classes("as-log-line w-full"):
                    ui.label(when_text(entry.at)).classes("as-log-when" + (" as-error-text" if entry.error else ""))
                    ui.label(f"{entry.sheet} · " + _log_text(entry)).classes("grow min-w-0")
                    hint("automatically" if entry.trigger == "auto" else "by hand")

    async def _set_completed(self, link: Link, completed: bool) -> None:
        set_completed(link.id, completed)
        ui.notify(f"{link.sheet} is {'completed' if completed else 'ongoing'}")
        self.group = "completed" if completed else "ongoing"
        await self.load()

    def _confirm_remove(self, link: Link) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[28rem] max-w-full gap-3").mark("tracker-remove-dialog"):
            ui.label(f"Remove {link.sheet} from the run matrix?").classes("as-dialog-title")
            hint("AeroSuite stops writing its Status. The workbook and the sheet stay as they are; you can link it "
                 "again later.")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", dialog.close).mark("tracker-remove-cancel")
                danger_button("Remove", lambda: self._remove(link, dialog)).mark("tracker-remove-confirm")
        dialog.open()

    async def _remove(self, link: Link, dialog) -> None:
        dialog.close()
        remove_link(link.id)
        ui.notify(f"{link.sheet} is no longer in the run matrix; the workbook is unchanged")
        await self.load()

    def _set_auto(self, ids: list[str], value: bool) -> None:
        set_auto(ids, value)
        ui.notify("Writes automatically as cases start and finish" if value else "Written only when you press Write")

    async def _write(self, link: Link) -> None:
        try:
            written = await run.io_bound(write_link, link)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
        else:
            ui.notify(f"Wrote {written} status{'' if written == 1 else 'es'} to {Path(link.workbook).name}",
                      type="positive")
        await self.load()

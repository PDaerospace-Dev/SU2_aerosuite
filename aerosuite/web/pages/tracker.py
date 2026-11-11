"""Run matrix: run-matrix workbooks whose Status column follows the projects' jobs (engine/tracker_links.py).

/tracker lists the linked sheets; /tracker/link links a sheet (?link=<id> changes a link); /tracker/preview?link=<id>
shows what a write would change, and the verdicts entered by hand that a job disagrees with, before writing;
/tracker/new adds a sheet to a workbook from its template sheet, and links it."""
from collections import Counter
from datetime import date, datetime
from html import escape
from math import prod
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from nicegui import run, ui

from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.tracker import (ORDERS, Template, detail_value, elevator_of, outside_reason, parse_values,
                               project_levels, read_template, sheet_name_problem, sheet_names, template_sheets)
from ...engine.tracker_links import (Link, LinkedProject, LinkReport, candidate_projects, create_sheet, find_link,
                                     last_write, load_tracker, remove_link, report, save_link, set_auto,
                                     set_completed, write_link)
from ..layout import header
from ..picker import pick_path
from .tracker_coverage import Coverage, coverage_url, sheet_chips
from ..ui_kit import (banner, card, chip_button, danger_button, field, flat_button, hint, html_table, html_td, html_th,
                      fold_at_start, ok_line, path_field, primary_button, secondary_button, summary_tile, table, td,
                      td_box, th, titled, warning_group)

ROWS_AT_MOST = 300  # rows a preview table draws
# the sheet's Status values -> pill tone, and the bar segment they count in
TONES = {"Converged": "done", "Not Converged": "unconverged", "Failed": "failed", "Diverged": "failed",
         "Running": "running", "Pending": "pending", "Hold": "cancelled"}
SEGMENTS = [("converged", "Converged", ("Converged",)), ("not", "Not converged / failed",
                                                        ("Not Converged", "Failed", "Diverged")),
            ("live", "Running / queued", ("Running", "Pending")), ("hold", "Hold", ("Hold",))]
AXES = ["Mach", "altitudes", "AoA", "elevator", "sideslip"]
SWEEP_FIELDS = [("Mach", ""), ("Altitude", "km"), ("AoA", "deg"), ("Elevator δe", "deg"), ("Sideslip β", "deg")]
NEW_URL = "/tracker/new"
GROUPS = {"ongoing": "Ongoing", "completed": "Completed"}
fold_at_start("tracker-log")  # Recent writes: one click away


def preview_url(link_id: str) -> str:
    return f"/tracker/preview?link={quote(link_id)}"


def edit_url(link_id: str = "") -> str:
    return f"/tracker/link?link={quote(link_id)}" if link_id else "/tracker/link"


def _crumbs(*parts: tuple[str, str]) -> None:
    """Projects › Run matrix › ...: (text, url) pairs, the last one the current page."""
    with ui.row().classes("as-crumbs w-full"):
        ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
        for text, url in parts[:-1]:
            ui.label("›").classes("as-crumb-sep")
            ui.link(text, url).classes("as-crumb-link").mark("crumb-tracker")
        ui.label("›").classes("as-crumb-sep")
        ui.label(parts[-1][0]).classes("as-crumb-current as-truncate").mark("crumb-page")


def pill_html(status: str) -> str:
    return (f'<span class="as-pill as-pill-{TONES.get(status, "pending")}">{escape(status or "blank")}</span>'
            if status else '<span class="as-muted">blank</span>')


def status_pill(status: str) -> ui.label:
    if not status:
        return ui.label("blank").classes("as-muted")
    return ui.label(status).classes(f"as-pill as-pill-{TONES.get(status, 'pending')}")


def bar_html(counts, total: int) -> str:
    """The sheet's statuses as one bar: converged, not converged, running, hold; the rest (no job) is the track."""
    spans = []
    for key, _label, statuses in SEGMENTS:
        share = sum(counts.get(status, 0) for status in statuses) / total * 100 if total else 0
        if share:
            spans.append(f'<span class="as-mseg-{key}" style="width: {share:.2f}%"></span>')
    return f'<div class="as-mbar">{"".join(spans)}</div>'


def bar_text(counts, total: int) -> str:
    parts = [(sum(counts.get(s, 0) for s in statuses), label.split(" /")[0].lower())
             for _key, label, statuses in SEGMENTS]
    blank = total - sum(number for number, _ in parts)
    words = [f"{number} {label}" for number, label in parts if number]
    return " · ".join(words + ([f"{blank} no status"] if blank else [])) or "no runs"


def legend() -> None:
    with ui.row().classes("as-legend w-full"):
        for key, label, _statuses in SEGMENTS:
            with ui.row().classes("as-legend-item"):
                ui.element("span").classes(f"as-swatch as-mseg-{key}")
                ui.label(label)
        with ui.row().classes("as-legend-item"):
            ui.element("span").classes("as-swatch as-mseg-none")
            ui.label("No status yet")


def order_choice(value: str, on_change=None) -> ui.toggle:
    """Which solver order a sheet takes: any, or only the cases a job ran at 1st or 2nd order."""
    with ui.column().classes("w-full gap-1"):
        ui.label("Solver order").classes("as-strong")
        toggle = ui.toggle({"": "Any", **ORDERS}, value=value if value in ORDERS else "", on_change=on_change).props(
            "dense no-caps unelevated toggle-color=primary").classes("as-toggle")
        hint("Read from the config each job ran with (MUSCL_FLOW on is 2nd order), so it does not depend on the "
             "note. A job that kept no config counts as 2nd order only with #2nd_order in its note.")
    return toggle


def stack_cell() -> ui.column:
    """A table cell whose lines stack (a name over its hint)."""
    return ui.column().classes("as-td as-td-stack")


def when_text(moment: datetime) -> str:
    today = datetime.now().date()
    return moment.strftime("Today %H:%M" if moment.date() == today else "%d %b %H:%M")


def sweep_text(report_: LinkReport) -> str:
    levels = report_.matrix.levels
    counts = " × ".join(f"{max(1, len(level))} {axis}" for level, axis in zip(levels, AXES))
    return f"{counts} = {len(report_.matrix.rows)} runs"


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
        links = load_tracker().links
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


def _log_text(entry) -> str:
    if entry.error:
        return f"not written: {entry.error}"
    if entry.trigger == "new-sheet":
        return "added from the template"
    if entry.trigger == "edit":
        return f"{entry.written} run{'' if entry.written == 1 else 's'} edited"
    text = f"{entry.written} status{'' if entry.written == 1 else 'es'} written"
    return text + (f", completed on {entry.completed_on:%Y-%m-%d}" if entry.completed_on else "")


# --- the linked sheets ---------------------------------------------------------------------------------------------

class Overview:
    def __init__(self, holder: ui.column) -> None:
        self.holder = holder
        self.group = "ongoing"
        with holder:
            hint("Reading the workbooks…").mark("tracker-loading")
        ui.timer(0, self.load, once=True)

    async def load(self) -> None:
        data = load_tracker()
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
            with ui.element("div").classes("as-table-scroll w-full"):
                with table("minmax(190px, 1.2fr) minmax(170px, 1fr) minmax(240px, 1.7fr) minmax(130px, .8fr) "
                           "auto").classes("as-matrix-table"):
                    for title in ("Sheet", "Projects", "Progress", "Waiting to write", ""):
                        th(title)
                    for item in items:
                        self._sheet_row(item)
            legend()

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


# --- link a sheet ---------------------------------------------------------------------------------------------------

class LinkForm:
    def __init__(self, existing: Optional[Link]) -> None:
        self.existing = existing
        self.link = existing.model_copy(deep=True) if existing else Link(workbook=self._last_workbook(), sheet="")
        self.rows: dict[str, dict] = {}  # project folder -> {"on", "elevator" input, "jobs", "matched" labels}
        self.extra: list[str] = [p.path for p in self.link.projects]
        self.seen = 0  # the newest recompute; an older one's result is dropped
        with ui.row().classes("as-link-layout w-full"):
            with ui.column().classes("as-card as-link-main"):
                self._form()
            with ui.column().classes("as-link-side"):
                with card("What would be written"):
                    self.summary = ui.column().classes("w-full gap-2").mark("link-summary")
                with card("Sweep in the sheet"):
                    self.sweep = ui.column().classes("w-full gap-1").mark("link-sweep")
        ui.timer(0, self._load_workbook, once=True)

    @staticmethod
    def _last_workbook() -> str:
        links = load_tracker().links
        return links[-1].workbook if links else ""

    def _form(self) -> None:
        self.workbook = path_field("Workbook", mark="link-workbook", browse_mark="link-browse",
                                   title="Choose the run-matrix workbook", mode="file", suffixes=(".xlsx",),
                                   help="A path on this server. To keep a SharePoint copy current, upload this file "
                                        "after a write.")
        self.workbook.value = self.link.workbook
        self.workbook.on("blur", self._load_workbook)
        self.workbook.on("keydown.enter", self._load_workbook)
        self.workbook.on_value_change(lambda e: self._load_workbook() if not e.sender.is_deleted and
                                      e.value.endswith(".xlsx") else None)
        self.sheet = field(ui.select([], label="Sheet", on_change=lambda: self.recompute())).props(
            "stack-label").classes("as-link-sheet").mark("link-sheet")
        self.found = ui.column().classes("w-full gap-0").mark("link-found")
        with ui.column().classes("w-full gap-1"):
            ui.label("Projects").classes("as-strong")
            hint("One project per elevator deflection; it is read from the folder name (del0, del20p, del30m). "
                 "Change it where the name does not say.")
            self.projects = ui.element("div").classes("as-table-scroll as-link-projects w-full")
            flat_button("Add a project folder", self._add_project, icon="add").mark("link-add-project")
        self.order = order_choice(self.link.order, lambda: self.recompute()).mark("link-order")
        with ui.row().classes("w-full gap-4"):
            self.tags = field(ui.input_chips("Only jobs tagged", value=list(self.link.tags),
                                             on_change=lambda: self.recompute()),
                              help="Only jobs whose note has one of these #tags count").classes(
                "grow").mark("link-tags")
            self.skip_tags = field(ui.input_chips("Leave out jobs tagged", value=list(self.link.skip_tags),
                                                  on_change=lambda: self.recompute()),
                                   help="Jobs whose note has one of these #tags never count").classes("grow").mark(
                "link-skip-tags")
        with ui.column().classes("w-full gap-1"):
            ui.label("When a job and your sheet disagree on a verdict").classes("as-strong")
            self.overwrite = ui.radio({False: "Keep yours: a Converged, Not Converged, Diverged or Failed you entered "
                                              "stays, and is listed for review",
                                       True: "Use the job's: AeroSuite's convergence check (CL, CD, CMy steady over "
                                             "the last 10%) decides"},
                                      value=self.link.overwrite, on_change=lambda: self.recompute()).mark(
                "link-overwrite")
        self.auto = ui.checkbox("Write automatically as cases start and finish (skipped while the workbook is open "
                                "in Excel)", value=self.link.auto).mark("link-auto")
        self.error = ui.label("").classes("as-error-text").mark("link-error")
        with ui.row().classes("w-full justify-end gap-2 as-link-footer"):
            if self.existing is not None:
                danger_button("Remove link", self._remove).mark("link-remove")
                ui.space()
            secondary_button("Cancel", lambda: ui.navigate.to("/tracker")).mark("link-cancel")
            primary_button("Save and preview", self._save).mark("link-save")

    # -- the workbook and its projects --

    async def _load_workbook(self) -> None:
        workbook = (self.workbook.value or "").strip()
        try:
            names = await run.io_bound(sheet_names, Path(workbook)) if workbook else []
            problem = ""
        except (AeroSuiteError, OSError) as exc:
            names, problem = [], str(exc)
        if self.sheet.is_deleted:
            return
        current = self.sheet.value if self.sheet.value in names else (
            self.link.sheet if self.link.sheet in names else (names[0] if names else None))
        self.sheet.set_options(names, value=current)
        self._draw_projects(workbook)
        if problem:
            self._show_found(problem, ok=False)
        await self.recompute()

    def _draw_projects(self, workbook: str) -> None:
        linked = {p.path: p.elevator for p in self.link.projects}
        before = {path: (row["on"].value, row["elevator"].value) for path, row in self.rows.items()}
        self.rows.clear()
        self.projects.clear()
        with self.projects:
            with table("36px minmax(160px, 1.4fr) minmax(130px, 1fr) minmax(70px, .6fr) minmax(70px, .6fr)"):
                for title in ("", "Folder", "Elevator δe (deg)", "Jobs", "Matched runs"):
                    th(title)
                for path in candidate_projects(workbook, self.extra):
                    key = str(path)
                    on, elevator = before.get(key, (key in linked, None))
                    if elevator is None:
                        elevator = format_value(linked[key]) if key in linked else self._from_name(path)
                    mark = f"link-project-{path.name}"
                    with td_box():
                        checkbox = ui.checkbox(value=on, on_change=lambda: self.recompute()).props("dense").mark(
                            f"{mark}-on")
                    titled(td(path.name, mono=True), key)
                    with td_box():
                        box = field(ui.input(value=elevator, on_change=lambda: self.recompute())).props(
                            "dense").classes("as-link-elevator").mark(f"{mark}-elevator")
                    jobs, matched = td("").mark(f"{mark}-jobs"), td("").mark(f"{mark}-matched")
                    self.rows[key] = {"on": checkbox, "elevator": box, "jobs": jobs, "matched": matched}

    @staticmethod
    def _from_name(path: Path) -> str:
        try:
            return format_value(elevator_of(path))
        except AeroSuiteError:
            return ""

    async def _add_project(self) -> None:
        chosen = await pick_path("Choose a project folder", mode="folder")
        if chosen is None:
            return
        if not (chosen / "project.json").is_file():
            ui.notify(f"{chosen} is not a project folder (no project.json)", type="warning")
            return
        if str(chosen) not in self.extra:
            self.extra.append(str(chosen))
        self._draw_projects((self.workbook.value or "").strip())
        self.rows[str(chosen)]["on"].value = True

    # -- the draft and what it would write --

    def _draft(self) -> tuple[Optional[Link], str]:
        """The link as the form has it, or None and why it cannot be saved."""
        workbook = (self.workbook.value or "").strip()
        if not workbook:
            return None, "Choose the workbook."
        if not self.sheet.value:
            return None, "Choose a sheet."
        projects = []
        for path, row in self.rows.items():
            if not row["on"].value:
                continue
            text = (row["elevator"].value or "").strip()
            try:
                projects.append(LinkedProject(path=path, elevator=float(text)))
            except ValueError:
                return None, f"Give the elevator deflection of {Path(path).name} in degrees."
        if not projects:
            return None, "Tick at least one project."
        return self.link.model_copy(update={
            "workbook": workbook, "sheet": self.sheet.value, "projects": projects,
            "tags": [t.lstrip("#") for t in self.tags.value or []],
            "skip_tags": [t.lstrip("#") for t in self.skip_tags.value or []],
            "order": self.order.value or "",
            "overwrite": bool(self.overwrite.value), "auto": bool(self.auto.value)}), ""

    async def recompute(self) -> None:
        self.seen += 1
        seen = self.seen
        draft, problem = self._draft()
        if draft is None and self.sheet.value:  # no project ticked yet: the sheet can still be read
            draft = self.link.model_copy(update={"workbook": (self.workbook.value or "").strip(),
                                                 "sheet": self.sheet.value, "projects": []})
        if draft is None:
            self.summary.clear()
            self.sweep.clear()
            if (self.workbook.value or "").strip() and not self.sheet.options:
                return
            self._show_found("", ok=True)
            return
        result = await run.io_bound(report, draft)
        if seen != self.seen or self.summary.is_deleted:
            return
        self._show(result, problem)

    def _show_found(self, text: str, ok: bool) -> None:
        self.found.clear()
        if text:
            with self.found:
                (ok_line(text) if ok else banner("error", text)).mark("link-found-text")

    def _show(self, result: LinkReport, problem: str) -> None:
        self.error.text = ""
        if result.error:
            self._show_found(result.error, ok=False)
            self.summary.clear()
            self.sweep.clear()
            return
        column = result.matrix.status_column
        self._show_found(f"Run matrix found: {sweep_text(result)}. Status is column {column}; Notes and every other "
                         f"cell are never written.", ok=True)
        by_path = {project.path: project for project in result.projects}
        for path, row in self.rows.items():
            project = by_path.get(path)
            row["jobs"].text = f"{project.jobs_chosen} of {project.jobs}" if project else ""
            row["matched"].text = str(project.matched) if project else ""
        self.summary.clear()
        with self.summary:
            if result.plan is None or not result.link.projects:
                hint(problem or "Tick the projects that run this sheet's cases.")
            else:
                total = len(result.matrix.rows)
                ui.html(bar_html(result.sheet_counts, total), sanitize=False).classes("w-full")
                with ui.element("div").classes("as-link-numbers"):
                    for label, value, mark in (("To write", len(result.plan.changes), "link-changes"),
                                               ("Unchanged", result.plan.unchanged, "link-unchanged"),
                                               ("Verdicts kept", len(result.plan.kept), "link-kept"),
                                               ("No job yet", result.no_job, "link-no-job")):
                        with ui.column().classes("gap-0"):
                            ui.label(label).classes("as-label")
                            ui.label(str(value)).classes("as-link-number").mark(mark)
                outside = len(result.plan.outside)
                if outside:
                    ui.label(f"{outside} case(s) of the chosen jobs have no row in the sheet.").classes(
                        "as-hint as-hint-warning").mark("link-outside")
                else:
                    ui.label("Every case of the chosen jobs has a row in the sheet.").classes("as-ok-text")
        self.sweep.clear()
        with self.sweep:
            with ui.element("div").classes("as-link-sweep-grid"):
                for name, level, unit in zip(("Mach", "Altitude", "AoA", "Elevator δe", "Sideslip β"),
                                             result.matrix.levels, ("", " km", "°", "°", "°")):
                    ui.label(name).classes("as-label")
                    ui.label((", ".join(format_value(v) for v in level) or "0") + unit)
            hint("Read from columns A–E. Change the sweep in Excel; the next write follows it.")

    async def _save(self) -> None:
        draft, problem = self._draft()
        if draft is None:
            self.error.text = problem
            return
        try:
            save_link(draft)
        except AeroSuiteError as exc:
            self.error.text = str(exc)
            return
        ui.navigate.to(preview_url(draft.id))

    def _remove(self) -> None:
        remove_link(self.link.id)
        ui.notify(f"{self.link.sheet} is no longer linked; the workbook is unchanged")
        ui.navigate.to("/tracker")


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
                     f"{workbook.stem}.bak{workbook.suffix}.").classes("grow")
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


# --- a new sheet from the template ------------------------------------------------------------------------------------

class NewSheetForm:
    """The workbook and its template sheet, the new sheet's name, its projects, sweep and case details, and the link."""

    def __init__(self) -> None:
        self.template: Optional[Template] = None
        self.rows: dict[str, dict] = {}  # project folder -> {"on", "elevator"}
        self.extra: list[str] = []
        self.details: dict[int, ui.input] = {}
        self.sweep: list[ui.input] = []
        with ui.row().classes("as-link-layout w-full"):
            with ui.column().classes("as-card as-link-main"):
                self._form()
            with ui.column().classes("as-link-side"):
                with card("The new sheet"):
                    self.summary = ui.column().classes("w-full gap-2").mark("new-summary")
                with card("What Create does"):
                    hint("Copies the template sheet inside the workbook, as its last sheet, with the details and the "
                         "sweep below filled in and Status empty. Its formulas lay out the run matrix as usual. Every "
                         "other sheet, and the rest of the file, is left as it is; the previous file is kept as "
                         "<name>.bak.xlsx.")
                    hint("Linked, its Status is then written from the projects' jobs like any linked sheet.")
        ui.timer(0, self._load_workbook, once=True)

    def _form(self) -> None:
        self.workbook = path_field("Workbook", mark="new-workbook", browse_mark="new-browse",
                                   title="Choose the run-matrix workbook", mode="file", suffixes=(".xlsx",),
                                   help="A path on this server: the workbook that has the template sheet.")
        self.workbook.value = LinkForm._last_workbook()
        self.workbook.on("blur", self._load_workbook)
        self.workbook.on("keydown.enter", self._load_workbook)
        self.workbook.on_value_change(lambda e: self._load_workbook() if not e.sender.is_deleted and
                                      e.value.endswith(".xlsx") else None)
        with ui.row().classes("w-full gap-4"):
            self.template_select = field(ui.select([], label="Template sheet", on_change=self._load_template)).props(
                "stack-label").classes("as-link-sheet").mark("new-template")
            self.name = field(ui.input("New sheet name", on_change=self._update),
                              help="At most 31 characters, none of : \\ / ? * [ ]").classes("as-link-sheet").mark(
                "new-name")
        self.found = ui.column().classes("w-full gap-0").mark("new-found")
        with ui.column().classes("w-full gap-1"):
            ui.label("Projects").classes("as-strong")
            hint("The projects whose cases the sheet tracks, one per elevator deflection (read from the folder name; "
                 "change it where the name does not say). Ticking one fills the sweep from their cases.")
            self.projects = ui.element("div").classes("as-table-scroll as-link-projects w-full")
            flat_button("Add a project folder", self._add_project, icon="add").mark("new-add-project")
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-center"):
                ui.label("Sweep").classes("as-strong grow")
                flat_button("Fill from the projects", self._fill_sweep, icon="refresh").mark("new-fill")
            hint("The values of each parameter, separated by commas. The sheet runs every combination: Mach slowest, "
                 "then altitude, AoA, elevator and sideslip.")
            with ui.element("div").classes("as-new-sweep w-full"):
                for (name, unit), mark in zip(SWEEP_FIELDS, ("mach", "altitude", "aoa", "elevator", "beta")):
                    self.sweep.append(field(ui.input(f"{name} ({unit})" if unit else name, on_change=self._update),
                                            mono=True).props("stack-label").mark(f"new-sweep-{mark}"))
        with ui.column().classes("w-full gap-1"):
            ui.label("Case details").classes("as-strong")
            hint("Column D of the template's first section; empty ones stay empty.")
            self.details_box = ui.element("div").classes("as-new-details w-full").mark("new-details")
        with ui.column().classes("w-full gap-1"):
            self.link = ui.checkbox("Link it to these projects, so its Status follows their jobs", value=True,
                                    on_change=lambda e: self.link_box.set_visibility(e.value)).mark("new-link")
            with ui.column().classes("w-full gap-3") as self.link_box:
                self.order = order_choice("").mark("new-order")
                with ui.row().classes("w-full gap-4"):
                    self.tags = field(ui.input_chips("Only jobs tagged"),
                                      help="Only jobs whose note has one of these #tags count").classes(
                        "grow").mark("new-tags")
                    self.skip_tags = field(ui.input_chips("Leave out jobs tagged"),
                                           help="Jobs whose note has one of these #tags never count").classes(
                        "grow").mark("new-skip-tags")
        self.error = ui.label("").classes("as-error-text").mark("new-error")
        with ui.row().classes("w-full justify-end gap-2 as-link-footer"):
            secondary_button("Cancel", lambda: ui.navigate.to("/tracker")).mark("new-cancel")
            self.create = primary_button("Create sheet", self._create, icon="note_add").mark("new-create")

    # -- the workbook, its template and the projects --

    def _book(self) -> str:
        return (self.workbook.value or "").strip()

    async def _load_workbook(self) -> None:
        workbook = self._book()
        try:
            names, templates = await run.io_bound(lambda: (sheet_names(Path(workbook)),
                                                           template_sheets(Path(workbook)))) if workbook else ([], [])
            problem = ""
        except (AeroSuiteError, OSError) as exc:
            names, templates, problem = [], [], str(exc)
        if self.template_select.is_deleted:
            return
        for linked in load_tracker().links:  # the projects that already track this workbook's other sheets
            if linked.workbook == workbook:
                self.extra += [p.path for p in linked.projects if p.path not in self.extra]
        options = templates + [name for name in names if name not in templates]
        current = self.template_select.value if self.template_select.value in options else (
            options[0] if options else None)
        self.template_select.set_options(options, value=current)
        self._draw_projects(workbook)
        self.found.clear()
        if problem:
            with self.found:
                banner("error", problem).mark("new-found-text")
        await self._load_template()

    async def _load_template(self) -> None:
        sheet = self.template_select.value
        try:
            template = await run.io_bound(read_template, Path(self._book()), sheet) if sheet else None
            problem = ""
        except (AeroSuiteError, OSError) as exc:
            template, problem = None, str(exc)
        if self.details_box.is_deleted:
            return
        self.template = template
        self.found.clear()
        if problem:
            with self.found:
                banner("error", problem).mark("new-found-text")
        self._draw_details()
        self._update()

    def _draw_details(self) -> None:
        self.details.clear()
        self.details_box.clear()
        if self.template is None:
            return
        with self.details_box:
            for detail in self.template.details:
                mark = f"new-detail-{detail.row}"
                if isinstance(detail.value, datetime):
                    start = "start" in detail.label.lower()
                    box = ui.input(detail.label, value=date.today().isoformat() if start else "")
                    box.props("type=date stack-label")
                else:
                    shown = format_value(detail.value) if isinstance(detail.value, (int, float)) else (
                        detail.value or "")
                    box = ui.input(detail.label, value=shown).props("stack-label")
                self.details[detail.row] = field(box).mark(mark)

    def _draw_projects(self, workbook: str) -> None:
        before = {path: (row["on"].value, row["elevator"].value) for path, row in self.rows.items()}
        self.rows.clear()
        self.projects.clear()
        with self.projects:
            with table("36px minmax(160px, 1.4fr) minmax(130px, 1fr)"):
                for title in ("", "Folder", "Elevator δe (deg)"):
                    th(title)
                for path in candidate_projects(workbook, self.extra):
                    key = str(path)
                    on, elevator = before.get(key, (False, LinkForm._from_name(path)))
                    mark = f"new-project-{path.name}"
                    with td_box():
                        checkbox = ui.checkbox(value=on, on_change=self._fill_sweep).props("dense").mark(f"{mark}-on")
                    titled(td(path.name, mono=True), key)
                    with td_box():
                        box = field(ui.input(value=elevator, on_change=self._fill_sweep)).props("dense").classes(
                            "as-link-elevator").mark(f"{mark}-elevator")
                    self.rows[key] = {"on": checkbox, "elevator": box}

    async def _add_project(self) -> None:
        chosen = await pick_path("Choose a project folder", mode="folder")
        if chosen is None:
            return
        if not (chosen / "project.json").is_file():
            ui.notify(f"{chosen} is not a project folder (no project.json)", type="warning")
            return
        if str(chosen) not in self.extra:
            self.extra.append(str(chosen))
        self._draw_projects(self._book())
        self.rows[str(chosen)]["on"].value = True

    def _projects(self) -> tuple[list[LinkedProject], str]:
        """The ticked projects, or why one cannot be used."""
        projects = []
        for path, row in self.rows.items():
            if not row["on"].value:
                continue
            try:
                projects.append(LinkedProject(path=path, elevator=float((row["elevator"].value or "").strip())))
            except ValueError:
                return [], f"Give the elevator deflection of {Path(path).name} in degrees."
        return projects, ""

    async def _fill_sweep(self) -> None:
        projects, _ = self._projects()
        if not projects:
            return
        levels = await run.io_bound(project_levels, [(Path(p.path), p.elevator) for p in projects])
        if self.summary.is_deleted:
            return
        for box, values in zip(self.sweep, levels):
            box.value = ", ".join(format_value(v) for v in values)
        self._update()

    # -- what it would make --

    def _levels(self) -> tuple[list[list[float]], list[str]]:
        levels, problems = [], []
        for (name, _unit), box in zip(SWEEP_FIELDS, self.sweep):
            try:
                levels.append(parse_values(box.value or "", name))
            except AeroSuiteError as exc:
                levels.append([])
                problems.append(str(exc))
        return levels, problems

    def _problems(self, levels: list[list[float]]) -> list[str]:
        problems = []
        name = self.name.value or ""
        if name:
            try:
                problem = sheet_name_problem(Path(self._book()), name)
            except (AeroSuiteError, OSError):
                problem = ""
            if problem:
                problems.append(problem)
        if self.template is not None:
            runs = prod(max(1, len(values)) for values in levels)
            if runs > self.template.runs:
                problems.append(f"The sweep makes {runs:,} runs; {self.template.sheet} has rows for "
                                f"{self.template.runs:,}.")
        return problems

    def _update(self) -> None:
        if self.summary.is_deleted:
            return
        levels, problems = self._levels()
        problems += self._problems(levels)
        self.summary.clear()
        with self.summary:
            if self.template is None:
                hint("Choose the workbook and its template sheet.")
                return
            runs = prod(max(1, len(values)) for values in levels) if levels[0] else 0
            with ui.column().classes("gap-0"):
                ui.label("Runs").classes("as-label")
                ui.label(f"{runs:,}").classes("as-link-number").mark("new-runs")
                hint(f"{self.template.sheet} has rows for {self.template.runs:,}")
            with ui.element("div").classes("as-link-sweep-grid"):
                for (name, unit), values in zip(SWEEP_FIELDS, levels):
                    ui.label(name).classes("as-label")
                    ui.label(f"{len(values)} value{'' if len(values) == 1 else 's'}" if values else "none (0)")
            for problem in problems:
                ui.label(problem).classes("as-hint as-hint-warning").mark("new-problem")

    async def _create(self) -> None:
        self.error.text = ""
        if self.template is None:
            self.error.text = "Choose the workbook and its template sheet."
            return
        name = (self.name.value or "").strip()
        projects, problem = self._projects()
        levels, problems = self._levels()
        problems = ([problem] if problem else []) + problems + self._problems(levels)
        if not name:
            problems.insert(0, "Give the new sheet a name.")
        if self.link.value and not projects and not problem:
            problems.append("Tick the projects to link it to, or untick Link it.")
        if not levels[0]:
            problems.append("Give at least one Mach number.")
        try:
            details = {row: detail_value(detail, self.details[row].value or "")
                       for row, detail in ((d.row, d) for d in self.template.details)}
        except AeroSuiteError as exc:
            problems.append(str(exc))
        if problems:
            self.error.text = problems[0]
            return
        link = Link(workbook=self._book(), sheet=name, projects=projects,
                    tags=[t.lstrip("#") for t in self.tags.value or []],
                    skip_tags=[t.lstrip("#") for t in self.skip_tags.value or []], order=self.order.value or "")
        self.create.set_enabled(False)
        try:
            await run.io_bound(create_sheet, link, self.template.sheet, details, levels, bool(self.link.value))
        except (AeroSuiteError, OSError) as exc:
            self.error.text = str(exc)
            self.create.set_enabled(True)
            return
        ui.notify(f"Added {name} to {Path(link.workbook).name}", type="positive")
        ui.navigate.to(preview_url(link.id) if self.link.value else "/tracker")

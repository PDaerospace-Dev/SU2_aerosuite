"""Run matrix › New sheet from template: a copy of the workbook's template sheet for a new case, with its
projects, sweep and details."""
from datetime import date, datetime
from math import prod
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.tracker import (
    Template,
    detail_value,
    parse_values,
    project_levels,
    read_template,
    sheet_name_problem,
    sheet_names,
    template_sheets,
)
from ...engine.tracker_links import Link, LinkedProject, candidate_projects, create_sheet, saved_links
from ..picker import pick_path
from ..ui_kit import (
    banner,
    card,
    field,
    flat_button,
    hint,
    path_field,
    primary_button,
    secondary_button,
    table,
    td,
    td_box,
    th,
    titled,
)
from .tracker_link import LinkForm
from .tracker_parts import SWEEP_FIELDS, order_choice, preview_url

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
        for linked in saved_links():  # the projects that already track this workbook's other sheets
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

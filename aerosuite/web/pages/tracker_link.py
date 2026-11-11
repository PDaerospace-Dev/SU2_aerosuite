"""Run matrix › Link a sheet: the workbook and sheet, the projects with their elevator deflection, the solver order
and tag filters, and what would be written."""
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.tracker import elevator_of, sheet_names
from ...engine.tracker_links import (
    Link,
    LinkedProject,
    LinkReport,
    candidate_projects,
    remove_link,
    report,
    save_link,
    saved_links,
)
from ..picker import pick_path
from ..tracker_view import bar_html
from ..ui_kit import (
    banner,
    card,
    danger_button,
    field,
    flat_button,
    hint,
    ok_line,
    path_field,
    primary_button,
    secondary_button,
    table,
    td,
    td_box,
    th,
    titled,
)
from .tracker_parts import order_choice, preview_url, sweep_text

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
        links = saved_links()
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

"""Results: the chosen history parameters of this study (and of other designs drawn over it), averaged per case,
with derived and characteristic values, plots and packages (spec docs/superpowers/specs/2026-09-29-results-design.md).
"""
from __future__ import annotations

import math
import re
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.parse import quote

import pandas as pd
from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.formula import FormulaError, Missing, parse
from ...engine.models import DerivedValue, PlotSpec, ResultsSettings
from ...engine.naming import format_value
from ...engine.packages import (Package, availability, disable_package, effective, enable_package, list_packages,
                                load_package, save_package)
from ...engine.study_results import CONSTANT_NAMES, SWEEP_NAMES
from ...engine.project import PROJECT_FILE
from ...engine.results import history_columns
from ...engine.study_results import study_results, write_results
from ..fields import text_field
from ..jobs import WATCHER
from ..layout import ProjectFrame, open_session, project_url
from ..param_picker import ParamPicker
from ..picker import pick_path
from ..results_charts import ChartDesign, along, chart_options, describe_lines, split_keys
from ..results_view import (SWEEP_LABELS, SWEEP_UNITS, add_parameter, filter_rows, pin, remove_parameter,
                            shown_values, status_counts, sweep_values, table_text, toggle_filter, varying)
from ..theme import SERIES_COLORS
from ..ui_kit import (banner, card, card_head, chip_button, field, hint, pill, primary_button, secondary_button,
                      summary_tile, table, td, td_box, th)

POLL_SECONDS = 5.0  # how often the page checks whether a job started or ended
FILTERED = ("Altitude", "Mach", "Beta")  # sweep variables with filter chips (α is the usual X axis)


def register() -> None:
    @ui.page("/results")
    def results_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "results", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            pages.append(ResultsPage(frame))


def number_text(value) -> str:
    return f"{value:.5g}" if isinstance(value, (int, float)) and math.isfinite(value) else "—"


def _value_text(value) -> str:
    return "—" if value is None or isinstance(value, Missing) else number_text(value)


def _blank(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


@contextmanager
def section(title: str, subtitle: str, *, opened: bool, on_fold: Callable[[bool], None], mark: str,
            flush: bool = False) -> Iterator[ui.expansion]:
    """A card that folds: its head stays; `on_fold(opened)` saves the state."""
    with ui.expansion(value=opened, on_value_change=lambda e: on_fold(bool(e.value))).classes(
            "as-section w-full" + (" as-section-flush" if flush else "")).mark(mark) as box:
        with box.add_slot("header"):
            with ui.row().classes("items-center gap-2 w-full no-wrap") as head:
                ui.label(title).classes("as-card-title")
                if subtitle:
                    ui.label(subtitle).classes("as-card-subtitle")
                ui.space()
        box.head = head
        yield box


class ResultsPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.columns: list[str] = []
        self.definitions = None
        self.designs: list = []  # StudyResults: this study first, then the compared ones
        self.problems: list[tuple[str, str]] = []  # compared studies that cannot be read: (folder, why)
        self.picker = ParamPicker(self)
        self._shown: tuple = ([], [])  # (rows per design, varying sweep variables) as last drawn
        with frame.actions:
            secondary_button("Copy table", icon="content_copy", on_click=self.copy_table).mark("results-copy")
            secondary_button("Export CSV", icon="download", on_click=self.export_csv).mark("results-export")
            secondary_button("Save as package…", icon="inventory_2", on_click=self.open_save_package).mark(
                "package-save")
        self.body = ui.column().classes("w-full gap-4").mark("results-body")
        self._job = self._job_key()
        ui.timer(POLL_SECONDS, self._poll)
        self.render()

    # -- state ----------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self.frame.session.directory

    @property
    def settings(self) -> ResultsSettings:
        return self.frame.session.project.results

    def load(self) -> None:
        self.columns = history_columns(self.directory)
        self.definitions = effective(self.settings, self.columns)
        self.designs, self.problems = [], []
        for folder in [self.directory, *(Path(p) for p in self.settings.compare)]:
            try:
                self.designs.append(study_results(folder, self.definitions, self.settings.average_last))
            except AeroSuiteError as exc:
                self.problems.append((str(folder), str(exc)))

    def change(self, edit: Callable[[ResultsSettings], None], *, render: bool = True) -> None:
        message = self.frame.save(lambda p: edit(p.results), then=self.render if render else None)
        if message:
            ui.notify(message, type="negative")

    def _job_key(self):
        latest = WATCHER.state(self.directory, self.frame.session.project).latest
        return (latest.id, latest.state) if latest else None

    def _poll(self) -> None:
        key = self._job_key()
        if key != self._job:  # a job started or ended: its cases' results changed
            self._job = key
            self.render()

    # -- actions --------------------------------------------------------------

    def choose(self, name: str, on: bool) -> None:
        self.change(lambda s: (add_parameter if on else remove_parameter)(s, self.definitions, name))

    def choose_group(self, names: list, on: bool) -> None:
        def edit(s: ResultsSettings) -> None:
            for name in names:
                (add_parameter if on else remove_parameter)(s, self.definitions, name)
        self.change(edit)

    def clear_parameters(self) -> None:
        def edit(s: ResultsSettings) -> None:
            pin(s, self.definitions)
            s.parameters = []
        self.change(edit)

    def names_in_use(self) -> set:
        definitions = self.definitions
        return (set(self.columns) | set(SWEEP_NAMES) | set(CONSTANT_NAMES) | definitions.derived_names
                | {c.name for c in definitions.characteristics})

    def preview(self, kind: str, formula: str) -> tuple[list[tuple[str, str]], str]:
        """The first values of a formula on this study, or the error: ([(label, value text)], error)."""
        definitions = self.definitions
        curve = kind == "curve"
        known = set(self.columns) | set(SWEEP_NAMES) | definitions.derived_names | (
            set() if curve else set(CONSTANT_NAMES))
        try:
            parse(formula, curve=curve, known=known)
        except FormulaError as exc:
            return [], str(exc)
        trial = DerivedValue(name="\u2063preview", formula=formula)  # a name no user can type
        extended = replace(definitions, characteristics=[*definitions.characteristics, trial]) if curve else \
            replace(definitions, derived=[*definitions.derived, trial])
        result = study_results(self.directory, extended, self.settings.average_last)
        if curve:
            return [(" · ".join(f"{SWEEP_LABELS[k]} {format_value(v)}" for k, v in row.curve.items()),
                     _value_text(row.values.get(trial.name))) for row in result.characteristics[:3]], ""
        rows = []
        for _, row in result.table.head(3).iterrows():
            reason = result.reason(row["Case"], trial.name)
            rows.append((row["Case"], reason or number_text(row.get(trial.name))))
        return rows, ""

    def open_derived_dialog(self) -> None:
        """A derived value per case, or a characteristic value per curve, with a live preview."""
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
            ui.label("Derived parameter").classes("as-dialog-title")
            kind = ui.toggle({"case": "Per case", "curve": "Characteristic value (per curve)"}, value="case").props(
                "no-caps unelevated dense toggle-color=primary").classes("as-toggle").mark("derived-kind")
            explain = hint("")
            with ui.element("div").classes("as-grid-2"):
                name = field(ui.input("Name")).classes("w-full").mark("derived-name")
                unit = field(ui.input("Unit (optional)")).classes("w-full").mark("derived-unit")
            formula = field(ui.textarea("Formula"), mono=True).props("rows=2 autogrow").classes("w-full").mark(
                "derived-formula")

            def insert(text: str) -> None:
                formula.value = (formula.value or "").rstrip() + (" " if formula.value else "") + text

            def braced(n: str) -> str:
                return n if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) else "{" + n + "}"

            parameters = list(dict.fromkeys([*self.definitions.parameters, *self.columns]))
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label("Insert").classes("as-label w-20")
                field(ui.select(parameters + sorted(self.definitions.derived_names), label="a parameter",
                                with_input=True, on_change=lambda e: e.value and (insert(braced(e.value)),
                                                                                  e.sender.set_value(None)))
                      ).classes("grow").mark("derived-insert")
            with ui.row().classes("items-center gap-1 w-full"):
                ui.label("Sweep").classes("as-label w-20")
                for n in SWEEP_NAMES:
                    chip_button(n, on_click=lambda n=n: insert(n))
            constants_row = ui.row().classes("items-center gap-1 w-full")
            with constants_row:
                ui.label("Study").classes("as-label w-20")
                for n in CONSTANT_NAMES:
                    chip_button(n, on_click=lambda n=n: insert(n))
            functions = hint("")
            with ui.column().classes("as-strip w-full gap-1"):
                ui.label("Preview").classes("as-stat-label")
                preview_box = ui.column().classes("gap-0 w-full")
            error = ui.label("").classes("as-error-text").mark("derived-error")

            def refresh(_=None) -> None:
                curve = kind.value == "curve"
                explain.text = ("One number per curve (per Mach, …), read off the curve along α."
                                if curve else "A formula of each case's averaged values.")
                functions.text = ("slope(Y, X, from, to) · at(Y, X, value) · max(Y) · min(Y) · argmax(Y, X) · "
                                  "argmin(Y, X), with + − × ÷ ^" if curve else
                                  "+ − × ÷ ^ ( ) · sqrt abs log exp sin cos tan (degrees) min max")
                constants_row.set_visibility(not curve)
                preview_box.clear()
                error.text = ""
                text = (formula.value or "").strip()
                if not text:
                    return
                rows, problem = self.preview(kind.value, text)
                error.text = problem
                with preview_box:
                    for index, (label, value) in enumerate(rows):
                        ui.label(f"{label}   {value}").classes("as-mono").mark(f"derived-preview-{index}")

            def save() -> None:
                text = (formula.value or "").strip()
                title = (name.value or "").strip()
                if not title:
                    error.text = "Give the parameter a name"
                    return
                if title in self.names_in_use():
                    error.text = f"{title} is already a parameter; choose another name"
                    return
                rows, problem = self.preview(kind.value, text) if text else ([], "Give a formula")
                if problem:
                    error.text = problem
                    return
                value = DerivedValue(name=title, formula=text, unit=(unit.value or "").strip())
                dialog.submit(True)
                dialog.clear()

                def edit(s: ResultsSettings) -> None:
                    if kind.value == "curve":
                        s.characteristics.append(value)
                    else:
                        s.derived.append(value)
                        add_parameter(s, self.definitions, title)
                self.change(edit)

            kind.on_value_change(refresh)
            formula.on_value_change(refresh)
            refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: (dialog.submit(False), dialog.clear())).mark(
                    "derived-cancel")
                primary_button("Add parameter", on_click=save).mark("derived-save")
        dialog.open()

    def copy_table(self) -> None:
        rows, sweep = self._shown
        text = table_text([(d.name, part) for d, part in zip(self.designs, rows)], sweep, self.definitions.parameters)
        ui.clipboard.write(text)
        ui.notify("Table copied: paste it into a spreadsheet", type="positive")

    def export_csv(self) -> None:
        """This study's results/summary.csv (and characteristics.csv), and the summary downloaded to the browser."""
        if not self.designs:
            return
        try:
            paths = write_results(self.directory, self.designs[0], self.definitions.parameters)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.download.content(paths[0].read_bytes(), f"{self.frame.session.project.name}-summary.csv", "text/csv")
        ui.notify("Saved " + " and ".join(str(p.relative_to(self.directory)) for p in paths), type="positive")

    def open_save_package(self) -> None:
        """Save this study's own parameters, derived and characteristic values and plots as a package."""
        with ui.dialog() as dialog, ui.card().classes("w-[30rem] max-w-full"):
            ui.label("Save as package").classes("as-dialog-title")
            hint("The chosen parameters, this study's own derived and characteristic values and its own plots. "
                 "Any study can then switch the package on.")
            package_id = field(ui.input("Id", placeholder="e.g. duct-performance")).classes("w-full").mark(
                "package-id")
            name = field(ui.input("Name")).classes("w-full").mark("package-name")
            description = field(ui.input("Description (optional)")).classes("w-full").mark("package-description")
            error = ui.label("").classes("as-error-text").mark("package-error")

            def save() -> None:
                key = (package_id.value or "").strip()
                try:
                    load_package(key)
                    error.text = f"A package called {key} exists; choose another id"
                    return
                except AeroSuiteError:
                    pass
                settings = self.settings
                package = Package(id=key, name=(name.value or "").strip(), description=(description.value or "").strip(),
                                  parameters=list(self.definitions.parameters), derived=list(settings.derived),
                                  characteristics=list(settings.characteristics), plots=list(settings.plots))
                try:
                    save_package(package)
                except AeroSuiteError as exc:
                    error.text = str(exc)
                    return
                dialog.submit(True)
                dialog.clear()
                ui.notify(f"Saved package {package.name}", type="positive")
                self.render()

            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: (dialog.submit(False), dialog.clear()))
                primary_button("Save package", on_click=save).mark("package-save-confirm")
        dialog.open()

    def toggle_package(self, package: Package) -> None:
        on = package.id in self.definitions.packages

        def edit(s: ResultsSettings) -> None:
            pin(s, self.definitions)
            (disable_package if on else enable_package)(s, package)
        self.change(edit)

    def add_plot(self, x: str, y: list, split: Optional[str]) -> None:
        def edit(s: ResultsSettings) -> None:
            for name in [x, *y]:
                if name not in SWEEP_NAMES:
                    add_parameter(s, self.definitions, name)
            s.plots.append(PlotSpec(x=x, y=list(y), split=split or None))
        self.change(edit)

    def remove_plot(self, index: int) -> None:
        self.change(lambda s: s.plots.pop(index))

    def open_case(self, owners: list, event) -> None:
        """A clicked point: that case in Monitor (of the study the point belongs to)."""
        if 0 <= event.series_index < len(owners) and event.name:
            ui.navigate.to(project_url("monitor", owners[event.series_index]) + f"&case={quote(event.name)}")

    def fold(self, key: str, opened: bool) -> None:
        def edit(s: ResultsSettings) -> None:
            s.folded = [k for k in s.folded if k != key] + ([] if opened else [key])
        self.change(edit, render=False)

    async def add_design(self) -> None:
        chosen = await pick_path("Choose a study to compare", mode="folder", start=self.directory.parent)
        if chosen is None:
            return
        folder = Path(chosen).resolve()
        if not (folder / PROJECT_FILE).is_file():
            ui.notify(f"{folder} is not an AeroSuite study (no {PROJECT_FILE})", type="negative")
            return
        if folder == self.directory.resolve() or str(folder) in self.settings.compare:
            ui.notify("That study is already shown", type="warning")
            return
        self.change(lambda s: s.compare.append(str(folder)))

    def remove_design(self, folder: str) -> None:
        self.change(lambda s: setattr(s, "compare", [p for p in s.compare if p != folder]))

    def set_average(self, text: str) -> Optional[str]:
        try:
            value = int(text)
        except ValueError:
            return "Give a whole number of iterations"
        if value < 1:
            return "Average over at least 1 iteration"
        self.change(lambda s: setattr(s, "average_last", value))
        return None

    # -- drawing --------------------------------------------------------------

    def render(self) -> None:
        """Plain synchronous rebuild: tests read the page right after a change."""
        self.load()
        values = sweep_values(d.table for d in self.designs)
        shown = shown_values(self.settings, values, comparing=len(self.designs) > 1)
        rows = [filter_rows(d.table, shown) for d in self.designs]
        self._shown = (rows, varying(values))
        self.body.clear()
        with self.body:
            self._designs_card(values, shown)
            self._parameters_card()
            if not any(len(r) for r in rows):
                banner("info", "No results yet: run the sweep on the Run page; results appear here as cases "
                               "finish.").mark("results-empty")
            else:
                self._tiles(rows)
                self._plots_section(rows, values)
                self._characteristics_section()
                self._results_section(rows, values)
        if self.picker.panel.visible:
            self.picker.render()

    def _designs_card(self, values: dict, shown: dict) -> None:
        with card():
            with ui.row().classes("items-center gap-2 w-full"):
                ui.label("Designs").classes("as-label w-24")
                for i, design in enumerate(self.designs):
                    with ui.row().classes("as-design-chip items-center gap-2 no-wrap").mark(f"design-{i}"):
                        ui.element("span").classes("as-swatch").style(f"background: {SERIES_COLORS[i % 8]}")
                        ui.label(design.name)
                        if i == 0:
                            ui.label("this study").classes("as-muted")
                        else:
                            ui.button(icon="close", color=None,
                                      on_click=lambda f=str(design.folder): self.remove_design(f)).props(
                                "flat round dense size=xs").mark(f"design-remove-{i}")
                for folder, why in self.problems:
                    with ui.row().classes("as-design-chip as-design-chip-error items-center gap-2 no-wrap").props(
                            f'title="{why}"').mark("design-problem"):
                        ui.icon("error_outline")
                        ui.label(Path(folder).name)
                        ui.button(icon="close", color=None, on_click=lambda f=folder: self.remove_design(f)).props(
                            "flat round dense size=xs")
                chip_button("+ Add design…", on_click=self.add_design).mark("design-add")
            with ui.row().classes("items-center gap-2 w-full"):
                for name in FILTERED:
                    if len(values.get(name, [])) < 2:
                        continue
                    ui.label(SWEEP_LABELS[name]).classes("as-label")
                    for value in values[name]:
                        chip = chip_button(format_value(value),
                                           on_click=lambda n=name, v=value: self.change(
                                               lambda s: toggle_filter(s, n, v, shown[n])))
                        chip.mark(f"filter-{name}-{format_value(value)}")
                        if value in shown[name]:
                            chip.classes("as-chip-on")
                    ui.element("span").classes("w-4")
                ui.space()
                ui.label("Average last").classes("as-label")
                with ui.element("div").classes("w-24"):
                    text_field("", self.settings.average_last, self.set_average, mark="results-average")
                ui.label("iterations").classes("as-label")

    def _parameters_card(self) -> None:
        definitions = self.definitions
        derived = definitions.derived_names
        total = len(self.columns) + len(derived)
        with card():
            with card_head("Parameters", f"{len(definitions.parameters)} of {total} chosen · averaged, tabulated "
                                         "and ready to plot"):
                ui.space()
                secondary_button("+ Derived…", on_click=self.open_derived_dialog).mark("derived-add")
                secondary_button("Choose parameters…", icon="checklist", on_click=self.picker.open).mark(
                    "results-choose")
            if definitions.parameters:
                with ui.row().classes("items-center gap-2 w-full"):
                    for name in definitions.parameters:
                        with ui.row().classes("as-design-chip items-center gap-1 no-wrap"):
                            ui.label(("ƒ " if name in derived else "") + name).mark(f"param-{name}")
                            ui.button(icon="close", color=None, on_click=lambda n=name: self.choose(n, False)).props(
                                "flat round dense size=xs").mark(f"param-remove-{name}")
            else:
                hint("Nothing chosen: pick the parameters to average, tabulate and plot.").mark("results-none")
            for design in self.designs:
                for note in design.notes:
                    hint(note).classes("as-hint-warning").mark("results-note")

    def _tiles(self, rows: list) -> None:
        counts = status_counts(rows)
        with ui.element("div").classes("as-tiles"):
            summary_tile("Cases shown", counts["shown"]).mark("tile-shown")
            summary_tile("Converged", counts["converged"]).mark("tile-converged")
            summary_tile("Unconverged", counts["unconverged"],
                         "danger" if counts["unconverged"] else None).mark("tile-unconverged")
            summary_tile("Designs", len(self.designs)).mark("tile-designs")

    def _plots_section(self, rows: list, values: dict) -> None:
        definitions = self.definitions
        own = self.settings.plots
        packages = [p for p in list_packages() if p.id in definitions.packages and p.plots]
        count = sum(len(p.plots) for p in packages) + len(own)
        with section("Plots", f"{count} plot{'' if count == 1 else 's'}", opened="plots" not in self.settings.folded,
                     on_fold=lambda o: self.fold("plots", o), mark="section-plots") as box:
            with box.head:
                for package in list_packages():
                    on = package.id in definitions.packages
                    missing = availability(package, self.columns)
                    chip = chip_button(("✓ " if on else "") + package.name,
                                       on_click=lambda p=package: self.toggle_package(p)).mark(f"package-{package.id}")
                    chip.on("click.stop", lambda: None)
                    if on:
                        chip.classes("as-chip-on")
                    elif missing:
                        chip.props(f'disable title="Needs {", ".join(missing)} in the history files"')
                primary_button("+ Add plot", on_click=lambda: self.open_add_plot(values)).on(
                    "click.stop", lambda: None).mark("plot-add")
            designs = [ChartDesign(d.name, SERIES_COLORS[i % 8], part, str(d.folder))
                       for i, (d, part) in enumerate(zip(self.designs, rows))]
            units = {d.name: d.unit for d in definitions.derived}
            for package in packages:
                ui.label(package.name).classes("as-strong")
                with ui.element("div").classes("as-grid-2"):
                    for index, plot in enumerate(package.plots):
                        self._chart(plot, designs, units, mark=f"chart-{package.id}-{index}")
            if own:
                ui.label("My plots").classes("as-strong")
                with ui.element("div").classes("as-grid-2"):
                    for index, plot in enumerate(own):
                        with ui.column().classes("w-full gap-0"):
                            with ui.row().classes("w-full justify-end"):
                                ui.button(icon="close", color=None,
                                          on_click=lambda i=index: self.remove_plot(i)).props(
                                    "flat round dense size=sm").props('title="Remove this plot"').mark(
                                    f"plot-remove-{index}")
                            self._chart(plot, designs, units, mark=f"chart-own-{index}")
            if not count:
                hint("No plots yet: switch on a package above, or add a plot of any parameters.").mark("plots-none")

    def _chart(self, plot: PlotSpec, designs: list, units: dict, mark: str) -> None:
        title = f"{', '.join(plot.y)} vs {SWEEP_LABELS.get(plot.x, plot.x)}"
        options, owners = chart_options(plot, designs, units, title)
        ui.echart(options, on_point_click=lambda e, o=owners: self.open_case(o, e)).classes("w-full").style(
            "height: 320px").mark(mark)

    def open_add_plot(self, values: dict) -> None:
        """Any X (a sweep variable that varies, or a parameter) against one or more Y parameters."""
        definitions = self.definitions
        sweep = [name for name in SWEEP_NAMES if len(values.get(name, [])) > 1] or ["Alpha"]
        parameters = list(dict.fromkeys([*definitions.parameters, *sorted(definitions.derived_names),
                                         *self.columns]))
        x_options = {name: SWEEP_LABELS[name] for name in sweep} | {name: name for name in parameters}
        combined = pd.concat([d.table for d in self.designs])
        with ui.dialog() as dialog, ui.card().classes("w-[34rem] max-w-full"):
            ui.label("Add a plot").classes("as-dialog-title")
            hint("X is a sweep variable or any parameter; Y is one or more parameters.")
            x_select = field(ui.select(x_options, value=sweep[0], label="X axis", with_input=True)).classes(
                "w-full").mark("plot-x")
            y_select = field(ui.select(parameters, value=[], label="Y axis (one or more)", multiple=True,
                                       with_input=True)).props("use-chips").classes("w-full").mark("plot-y")
            split_select = field(ui.select({"": "Automatic"}, value="", label="Lines")).classes("w-full").mark(
                "plot-split")
            lines = hint("").mark("plot-lines")
            error = ui.label("").classes("as-error-text").mark("plot-error")

            def update(_=None) -> None:
                x = x_select.value or sweep[0]
                choices = {"": "Automatic"} | {n: f"One line per {SWEEP_LABELS[n]}" for n in SWEEP_NAMES
                                               if len(values.get(n, [])) > 1 and n != along(x)}
                split_select.set_options(choices, value=split_select.value if split_select.value in choices else "")
                lines.text = describe_lines(x, split_keys(x, combined, split_select.value or None))

            x_select.on_value_change(update)
            split_select.on_value_change(update)
            update()

            def add() -> None:
                if not y_select.value:
                    error.text = "Choose at least one Y parameter"
                    return
                dialog.submit(True)
                dialog.clear()
                self.add_plot(x_select.value, list(y_select.value), split_select.value or None)

            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: (dialog.submit(False), dialog.clear())).mark(
                    "plot-dialog-cancel")
                primary_button("Add plot", on_click=add).mark("plot-dialog-add")
        dialog.open()

    def _characteristics_section(self) -> None:
        characteristics = self.definitions.characteristics
        if not characteristics:
            return
        several = len(self.designs) > 1
        keys = list(dict.fromkeys(k for d in self.designs for row in d.characteristics for k in row.curve))
        with section("Characteristic values", "read off each curve along α", opened="characteristics" not in
                     self.settings.folded, on_fold=lambda o: self.fold("characteristics", o),
                     mark="section-characteristics", flush=True):
            columns = (["minmax(8rem, 1fr)"] if several else []) + ["minmax(5rem, .6fr)"] * len(keys)
            columns += ["minmax(6rem, .8fr)"] * len(characteristics)
            with ui.element("div").classes("as-table-scroll w-full"):
                with table(" ".join(columns)).mark("characteristics-table"):
                    if several:
                        th("Design")
                    for key in keys:
                        th(SWEEP_LABELS[key])
                    for c in characteristics:
                        th(c.name + (f" ({c.unit})" if c.unit else "")).props(f'title="{c.name} = {c.formula}"')
                    for i, design in enumerate(self.designs):
                        for j, row in enumerate(design.characteristics):
                            if several:
                                with td_box():
                                    ui.element("span").classes("as-swatch").style(
                                        f"background: {SERIES_COLORS[i % 8]}")
                                    ui.label(design.name)
                            for key in keys:
                                td(format_value(row.curve[key]) if key in row.curve else "—")
                            for c in characteristics:
                                value = row.values.get(c.name)
                                cell = td(_value_text(value)).mark(f"char-{i}-{j}-{c.name}")
                                if isinstance(value, Missing):
                                    cell.props(f'title="{value.reason}"')

    def _results_section(self, rows: list, values: dict) -> None:
        sweep = varying(values)
        params = self.definitions.parameters
        several = len(self.designs) > 1
        count = sum(len(r) for r in rows)
        with section("Results", f"averaged over the last {self.settings.average_last} iterations · {count} cases",
                     opened="results" not in self.settings.folded, on_fold=lambda o: self.fold("results", o),
                     mark="section-results", flush=True):
            columns = ["minmax(11rem, 1.3fr)"] + (["minmax(8rem, 1fr)"] if several else [])
            columns += ["minmax(4rem, .5fr)"] * len(sweep) + ["minmax(6rem, .7fr)"] * len(params)
            columns += ["minmax(7rem, .6fr)"]
            with ui.element("div").classes("as-table-scroll w-full"):
                with table(" ".join(columns)).mark("results-table"):
                    th("Case").classes("as-sticky")
                    if several:
                        th("Design")
                    for name in sweep:
                        th(SWEEP_LABELS[name] + (f" ({SWEEP_UNITS[name]})" if name in SWEEP_UNITS else ""))
                    for name in params:
                        th(("ƒ " if name in self.definitions.derived_names else "") + name)
                    th("Status")
                    for i, (design, part) in enumerate(zip(self.designs, rows)):
                        for _, row in part.iterrows():
                            self._row(i, design, row, sweep, params, several)

    def _row(self, i: int, design, row, sweep: list, params: list, several: bool) -> None:
        case = row["Case"]
        with td_box() as box:
            box.classes("as-sticky").mark(f"row-{i}-{case}")
            ui.element("span").classes("as-swatch").style(f"background: {SERIES_COLORS[i % 8]}")
            ui.label(case).classes("as-mono")
        if several:
            td(design.name)
        for name in sweep:
            td(format_value(row[name]) if name in row and not _blank(row[name]) else "—")
        for name in params:
            value = row.get(name)
            cell = td(number_text(value)).mark(f"cell-{i}-{case}-{name}")
            reason = design.reason(case, name)
            if reason:
                cell.props(f'title="{reason}"')
        with td_box():
            converged = row.get("Converged")
            pill("NOT JUDGED" if _blank(converged) else "CONVERGED" if converged else "UNCONVERGED").mark(
                f"status-{i}-{case}")

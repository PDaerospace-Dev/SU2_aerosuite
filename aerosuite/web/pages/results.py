"""Results: the chosen history parameters of this study (and of other designs drawn over it), averaged per case,
with derived and characteristic values, plots and packages (spec docs/superpowers/specs/2026-09-29-results-design.md).
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.models import ResultsSettings
from ...engine.naming import format_value
from ...engine.packages import effective
from ...engine.project import PROJECT_FILE
from ...engine.results import history_columns
from ...engine.study_results import study_results
from ..fields import text_field
from ..jobs import WATCHER
from ..layout import ProjectFrame, open_session
from ..param_picker import ParamPicker
from ..picker import pick_path
from ..results_view import (SWEEP_LABELS, SWEEP_UNITS, add_parameter, filter_rows, pin, remove_parameter,
                            shown_values, status_counts, sweep_values, toggle_filter, varying)
from ..theme import SERIES_COLORS
from ..ui_kit import (banner, card, card_head, chip_button, hint, pill, secondary_button, summary_tile, table, td,
                      td_box, th)

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

    def open_derived_dialog(self) -> None:
        """The Derived parameter dialog (Task 7)."""

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
        self.body.clear()
        with self.body:
            self._designs_card(values, shown)
            self._parameters_card()
            if not any(len(r) for r in rows):
                banner("info", "No results yet: run the sweep on the Run page; results appear here as cases "
                               "finish.").mark("results-empty")
            else:
                self._tiles(rows)
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

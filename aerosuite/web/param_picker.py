"""The Results page's Choose parameters panel: every history parameter, searchable and grouped, from the right."""
from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from ..engine.results import GROUP_RESIDUALS, GROUP_TOTALS, group_of, ordered_groups

if TYPE_CHECKING:
    from .pages.results import ResultsPage

DERIVED_GROUP = "Derived (ƒ)"


class ParamPicker:
    def __init__(self, page: "ResultsPage") -> None:
        self.page = page
        self.query = ""
        with ui.column().classes("as-calc-panel").mark("picker-panel") as self.panel:
            with ui.row().classes("as-calc-panel-head w-full no-wrap"):
                ui.icon("checklist", size="20px")
                ui.label("Choose parameters").classes("as-card-title")
                ui.space()
                ui.button(icon="close", on_click=self.close, color=None).props("flat round dense").mark(
                    "picker-close")
            with ui.column().classes("as-calc-panel-body w-full gap-3"):
                self.search = ui.input(placeholder="Search parameters, e.g. wing or CM",
                                       on_change=lambda e: self._search(e.value or "")).props(
                    'outlined dense clearable prepend-icon="search"').classes("as-field w-full").mark("picker-search")
                self.body = ui.column().classes("w-full gap-2")
        self.panel.set_visibility(False)

    def open(self) -> None:
        self.render()
        self.panel.set_visibility(True)

    def close(self) -> None:
        self.panel.set_visibility(False)

    def _search(self, text: str) -> None:
        self.query = text.strip().lower()
        self.render()

    def render(self) -> None:
        """Rebuild the list (plain synchronous rebuild: tests read it right after a change)."""
        page = self.page
        columns, definitions = page.columns, page.definitions
        chosen = set(definitions.parameters)
        self.search.props(f'placeholder="Search {len(columns)} parameters, e.g. wing or CM"')
        self.body.clear()
        with self.body:
            with ui.row().classes("items-center w-full"):
                ui.label(f"{len(definitions.parameters)} chosen").classes("as-label").mark("picker-count")
                ui.space()
                ui.button("Clear all", on_click=page.clear_parameters, color=None).props(
                    "flat dense no-caps").classes("as-hint").mark("picker-clear")
            derived = [d.name for d in definitions.derived]
            groups = [(DERIVED_GROUP, derived)] + [(g, [c for c in columns if group_of(c) == g])
                                                   for g in ordered_groups(columns)]
            for group, members in groups:
                shown = [m for m in members if self.query in m.lower()] if self.query else members
                if not shown and not (group == DERIVED_GROUP and not self.query):
                    continue
                picked = [m for m in members if m in chosen]
                opened = bool(self.query) or group == GROUP_TOTALS or (bool(picked) and group != GROUP_RESIDUALS)
                self._group(group, members, shown, picked, opened, derived=group == DERIVED_GROUP)

    def _group(self, group: str, members: list, shown: list, picked: list, opened: bool, derived: bool) -> None:
        page = self.page
        with ui.expansion(value=opened).classes("as-pick-group w-full").mark(f"picker-group-{group}") as box:
            with box.add_slot("header"):
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    if members:  # ticked when the whole group is chosen; a click chooses or clears it all
                        ui.checkbox(value=len(picked) == len(members),
                                    on_change=lambda e, m=members: page.choose_group(m, e.value)).props(
                            "dense").on("click.stop", lambda: None).mark(f"picker-tick-{group}")
                    ui.label(group).classes("as-strong")
                    ui.label(str(len(members))).classes("as-muted")
                    ui.space()
                    if picked:
                        ui.label(f"{len(picked)} chosen").classes("as-hint")
                    if derived:
                        ui.button("+ Derived…", on_click=page.open_derived_dialog, color=None).props(
                            "flat dense no-caps").classes("as-hint").mark("picker-add-derived")
            with ui.element("div").classes("as-pick-grid"):
                for name in shown:
                    ui.checkbox(("ƒ " if derived else "") + name, value=name in picked,
                                on_change=lambda e, n=name: page.choose(n, e.value)).props("dense").mark(
                        f"pick-{name}")

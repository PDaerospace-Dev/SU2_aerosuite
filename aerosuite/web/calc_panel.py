"""Calculators as a panel that slides in from the right over any page (the top bar's Calculators button)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from nicegui import ui

if TYPE_CHECKING:
    from .layout import ProjectFrame


class CalcPanel:
    def __init__(self, frame: Optional["ProjectFrame"]) -> None:
        self.frame = frame  # inside a project, ISA's Apply writes to it
        self.view = None  # built on first open: most page views never use it
        with ui.column().classes("as-calc-panel").mark("calc-panel") as self.panel:
            with ui.row().classes("as-calc-panel-head w-full no-wrap"):
                ui.icon("calculate", size="20px")
                ui.label("Calculators").classes("as-card-title")
                ui.space()
                ui.button(icon="close", on_click=self.close, color=None).props("flat round dense").mark(
                    "calc-panel-close")
            self.body = ui.column().classes("as-calc-panel-body w-full")
        self.panel.set_visibility(False)

    def toggle(self) -> None:
        if self.panel.visible:
            self.close()
        else:
            self.open()

    def open(self) -> None:
        if self.view is None:
            from .pages.calculators import CalculatorsView  # the page module imports layout, which imports this

            with self.body:
                self.view = CalculatorsView(self.frame, "", compact=True)
        self.panel.set_visibility(True)

    def close(self) -> None:
        self.panel.set_visibility(False)

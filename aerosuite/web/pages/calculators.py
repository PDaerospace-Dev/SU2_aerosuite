"""Calculators: a list of calculators on the left, the open one on the right; Apply appears inside a project."""
from typing import Optional

from nicegui import ui

from ..calculators import CalcContext, calculators
from ..layout import ProjectFrame, header, open_session


def register() -> None:
    @ui.page("/calculators")
    def calculators_page(project: str = "", calc: str = "") -> None:
        views: list = []
        frame: Optional[ProjectFrame] = None
        if project:
            session = open_session(project)
            if session is None:
                return
            frame = ProjectFrame(session, "calculators",
                                 on_reload=lambda: views[0].show(views[0].key, {}) if views else None)
            holder = frame.content
        else:
            header()
            holder = ui.column().classes("as-page w-full")
            with holder:
                with ui.row().classes("as-crumbs w-full"):
                    ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                    ui.label("›").classes("as-crumb-sep")
                    ui.label("Calculators").classes("as-crumb-current").mark("crumb-page")
        with holder:
            views.append(CalculatorsView(frame, calc))


class CalculatorsView:
    def __init__(self, frame: Optional[ProjectFrame], key: str) -> None:
        self.frame = frame
        keys = [c.key for c in calculators()]
        self.key = key if key in keys else keys[0]
        with ui.element("div").classes("as-calc"):
            self.list = ui.column().classes("gap-1")
            self.card = ui.column().classes("w-full")
        self.show(self.key, {})

    def show(self, key: str, handoff: dict) -> None:
        self.key = key
        items = calculators()
        self.list.clear()
        with self.list:
            for calc in items:
                item = ui.column().classes("as-calc-item" + (" as-calc-item-on" if calc.key == key else "")).mark(
                    f"calc-item-{calc.key}")
                item.on("click", lambda _, k=calc.key: self.show(k, {}))
                with item:
                    ui.label(calc.title).classes("as-strong")
                    ui.label(calc.description).classes("as-muted")
        self.card.clear()
        with self.card:
            next(c for c in items if c.key == key).build(CalcContext(self.frame, handoff, self.show))

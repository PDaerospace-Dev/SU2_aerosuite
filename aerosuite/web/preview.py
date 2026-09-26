"""A 'Preview' switch and the rendered config of a chosen case (Config and Aircraft pages)."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import read_template, render_case
from ..engine.errors import AeroSuiteError
from .layout import ProjectFrame
from .ui_kit import banner, field


def preview_section(frame: ProjectFrame) -> Callable[[], None]:
    """Build the switch and box; returns a function that redraws the preview (synchronously)."""
    state = {"on": False, "case": None}

    def toggle(value: bool) -> None:
        state["on"] = value
        render()

    ui.switch("Preview", value=False, on_change=lambda e: toggle(e.value)).mark("preview-toggle")
    box = ui.column().classes("w-full gap-2")

    def choose(name: str) -> None:
        state["case"] = name
        render()

    def render() -> None:
        box.clear()
        if not state["on"]:
            return
        project = frame.session.project
        with box:
            if not project.cases:
                ui.label("No case to preview yet.").mark("preview-empty")
                return
            names = [case.name for case in project.cases]
            if state["case"] not in names:
                state["case"] = names[0]
            if len(names) > 1:
                field(ui.select(names, value=state["case"], label="Case",
                                on_change=lambda e: choose(e.value))).mark("preview-case")
            try:
                template = read_template(frame.session.directory, project)
            except AeroSuiteError as exc:
                banner("error", f"Error: {exc}").mark("preview-error")
                return
            case = next(case for case in project.cases if case.name == state["case"])
            ui.code(render_case(template, project, case), language="ini").classes("w-full as-mono").mark("preview")

    render()
    return render

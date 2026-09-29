"""The rendered config of a chosen case (the Preview tab of Config and Aircraft; see side_panel.py)."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import read_template, render_case
from ..engine.errors import AeroSuiteError
from .layout import ProjectFrame
from .ui_kit import banner, field


def preview_section(frame: ProjectFrame) -> Callable[[], None]:
    """Build the box; returns a function that redraws the preview (synchronously)."""
    state = {"case": None}
    box = ui.column().classes("w-full gap-2")

    def choose(name: str) -> None:
        state["case"] = name
        render()

    def render() -> None:
        box.clear()
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
                case = next(case for case in project.cases if case.name == state["case"])
                text = render_case(template, project, case)
            except AeroSuiteError as exc:
                banner("error", f"Error: {exc}").mark("preview-error")
                return
            ui.code(text, language="ini").classes("w-full as-mono").mark("preview")

    render()
    return render

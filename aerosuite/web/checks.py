"""Checks and the Generate button: shared by the Config page (sweep off) and the Sweep page."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import generate_configs
from ..engine.errors import AeroSuiteError
from ..engine.preflight import has_errors, preflight
from .layout import ProjectFrame


def render_checks(frame: ProjectFrame, refresh: Callable[[], None]) -> None:
    found = preflight(frame.session.directory, frame.session.project, "generate")
    if not found:
        ui.label("No problems found.").classes("text-positive").mark("problems-none")
    for problem in found:
        style = "text-negative" if problem.severity == "error" else "text-warning"
        prefix = "Error" if problem.severity == "error" else "Warning"
        ui.label(f"{prefix}: {problem.message}").classes(style).mark(f"problem-{problem.severity}")

    def generate() -> None:
        stale = frame.ensure_current(notify=False)  # one toast, worded for Generate, not two
        if stale is not None:
            if frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; generate again", type="warning")
            return
        # Check again: files may have gone (e.g. the mesh deleted) since these checks were drawn.
        errors = [p for p in preflight(frame.session.directory, frame.session.project, "generate")
                  if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            refresh()
            return
        try:
            written = generate_configs(frame.session.directory, frame.session.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        plural = "" if len(written) == 1 else "s"
        ui.notify(f"Wrote {len(written)} config{plural}", type="positive")
        frame.refresh()
        refresh()

    button = ui.button("Generate configs", on_click=generate).mark("generate")
    button.set_enabled(not has_errors(found))

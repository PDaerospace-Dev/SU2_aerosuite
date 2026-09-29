"""Checks and the Generate button: shared by the CFG setup page (sweep off) and the Sweep page."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import generate_configs
from ..engine.errors import AeroSuiteError
from ..engine.preflight import has_errors, preflight
from .layout import ProjectFrame
from .ui_kit import banner, ok_line, primary_button, warning_group


def render_checks(frame: ProjectFrame, button: Optional[ui.button] = None) -> None:
    """The generate checks as banners (or one green line); `button` is enabled only when none is an error."""
    found = preflight(frame.session.directory, frame.session.project, "generate")
    if not found:
        ok_line("No problems found.").mark("problems-none")
    for problem in found:
        if problem.severity == "error":
            banner("error", f"Error: {problem.message}").mark("problem-error")
    warnings = [problem.message for problem in found if problem.severity != "error"]
    if warnings:
        warning_group(warnings, mark="problem-warning")
    if button is not None:
        button.set_enabled(not has_errors(found))


def generate_button(frame: ProjectFrame, refresh: Callable[[], None]) -> ui.button:
    """The page's primary "Generate configs" button; `refresh` redraws the checks afterwards."""

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

    return primary_button("Generate configs", on_click=generate).mark("generate")

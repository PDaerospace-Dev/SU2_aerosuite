"""Sweep on or off: a grid of Mach/α/β cases, or the template as one case (Setup and Config)."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import build_cases
from .layout import ProjectFrame

LONG = {True: "Sweep · a grid of Mach, α and β cases", False: "Single case · the template as it is"}
SHORT = {True: "Sweep", False: "Single case"}


def set_sweep(frame: ProjectFrame, on: bool, then: Optional[Callable[[], None]] = None) -> None:
    def change(p) -> None:
        p.sweep.enabled = on
        p.cases = build_cases(p)

    message = frame.save(change, then=then)
    if message:
        ui.notify(message, type="negative")


def sweep_radio(frame: ProjectFrame, *, mark: str) -> ui.radio:
    """Setup's two large choices."""
    return ui.radio(LONG, value=frame.session.project.sweep.enabled,
                    on_change=lambda e: set_sweep(frame, e.value)).props("inline").classes("as-choice").mark(mark)


def sweep_toggle(frame: ProjectFrame, *, mark: str, then: Callable[[], None]) -> ui.toggle:
    """A compact switch for a page's action bar; `then` redraws the page."""
    return ui.toggle(SHORT, value=frame.session.project.sweep.enabled,
                     on_change=lambda e: set_sweep(frame, e.value, then)).props(
        "no-caps unelevated dense toggle-color=primary").classes("as-toggle").mark(mark)

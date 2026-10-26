"""How cases are named: the base name and which parts go into a name. The Sweep page's, and an aircraft single
case's on the Aircraft page; both edit the same sweep.naming."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import build_cases
from ..engine.editing import update_sweep
from ..engine.models import Project
from .fields import text_field
from .layout import ProjectFrame

NAMING = [
    ("include_mach", "Mach"),
    ("include_altitude", "Altitude"),
    ("include_alpha", "α"),
    ("include_beta", "β"),
    ("include_base", "Base name"),
]


def base_name_field(frame: ProjectFrame, after: Callable[[], None]) -> None:
    text_field("Base name", frame.session.project.sweep.naming.base_name,
               lambda text: frame.save(lambda p: update_sweep(p, base_name=text.strip()), then=after),
               mark="sweep-base-name", side_label=True)


def naming_checkboxes(frame: ProjectFrame, after: Callable[[], None]) -> None:
    naming = frame.session.project.sweep.naming
    with ui.row().classes("items-center gap-4"):
        ui.label("Name cases with").classes("as-label")
        for flag, label in NAMING:
            ui.checkbox(label, value=getattr(naming, flag),
                        on_change=lambda e, f=flag: _set_naming(frame, f, e.value, after)).mark(f"naming-{flag}")


def _set_naming(frame: ProjectFrame, flag: str, value: bool, after: Callable[[], None]) -> None:
    def change(p: Project) -> None:
        setattr(p.sweep.naming, flag, value)
        p.cases = build_cases(p)

    message = frame.save(change, then=after)
    if message:
        ui.notify(message, type="negative")

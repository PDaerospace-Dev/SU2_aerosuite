"""The Aircraft page's Boundaries tab: the MARKER_ lines. The four usual ones (heat flux wall, far field, plotted,
monitored) and any other the project sets: tick one to write it, untick it to remove the line from every config,
leave the value empty for the template's line."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.editing import set_parameter, unset_parameter
from ..engine.models import Project
from .fields import text_field
from .layout import ProjectFrame
from .ui_kit import hint

MARKER_ROWS = ["MARKER_HEATFLUX", "MARKER_FAR", "MARKER_PLOTTING", "MARKER_MONITORING"]


def boundaries_tab(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    """Build the tab; returns its redraw."""
    mesh = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    hint(f"Mesh markers: {mesh}").mark("boundaries-mesh")
    box = ui.column().classes("w-full gap-2")

    def both() -> None:
        render()
        after()

    def include(key: str, on: bool) -> None:
        def change(p: Project) -> None:
            if not on:
                p.settings.markers[key] = None  # the line is removed from every config
            elif key in p.settings.markers and p.settings.markers[key] is None:
                del p.settings.markers[key]  # back to the template's line

        message = frame.save(change, then=both)
        if message:
            ui.notify(message, type="negative")

    def set_value(key: str, text: str) -> Optional[str]:
        if text.strip():
            return frame.save(lambda p: set_parameter(p.settings, key, text), then=both)
        if frame.session.project.settings.markers.get(key) is not None:
            return frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        return None

    def render() -> None:
        # Plain synchronous rebuild: tests read these rows right after a change.
        box.clear()
        markers = frame.session.project.settings.markers
        keys = MARKER_ROWS + sorted(k for k in markers if k not in MARKER_ROWS)
        with box:
            with ui.element("div").classes("as-grid-form"):
                for key in keys:
                    value = markers.get(key, "")
                    ui.checkbox(key, value=value is not None,
                                on_change=lambda e, k=key: include(k, e.value)).mark(f"marker-{key}-include")
                    with ui.column().classes("gap-0"):
                        text_field("Value", value or "", lambda text, k=key: set_value(k, text),
                                   mark=f"marker-{key}-value", placeholder=hints.get(key, "template value"),
                                   mono=True)

    render()
    return render

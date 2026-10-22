"""The right-hand column of Aircraft and Config: the rendered config and SU2's reference, as tabs."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.reference import RefOption
from .layout import ProjectFrame
from .preview import preview_section
from .reference_panel import reference_panel
from .ui_kit import card


def side_panel(
    frame: ProjectFrame,
    on_insert: Callable[[RefOption], Optional[str]],
    in_config: Callable[[], set[str]],
    config: Optional[Callable[[], Callable[[], None]]] = None,
) -> tuple[Callable[[], None], Callable[[], None]]:
    """Build the sticky tabbed card; returns (redraw the preview, redraw the reference results).

    `config`, when given, draws an editable Config tab in place of the read-only Preview (Aircraft); it returns
    its own redraw.
    """
    first = "config" if config is not None else "preview"
    with card() as box:
        box.classes("as-side").mark("side-panel")
        with ui.tabs(value=first).props("dense no-caps align=left inline-label").classes(
                "as-tabs w-full").mark("side-tabs") as tabs:
            if config is not None:
                ui.tab("config", "Config", icon="edit_note").mark("side-tab-config")
            else:
                ui.tab("preview", "Preview", icon="visibility").mark("side-tab-preview")
            ui.tab("reference", "SU2 reference", icon="menu_book").mark("side-tab-reference")
        with ui.tab_panels(tabs, value=first).props("keep-alive").classes("as-tab-panels w-full"):
            with ui.tab_panel(first).classes("gap-2"):
                preview = config() if config is not None else preview_section(frame)
            with ui.tab_panel("reference").classes("gap-2"):
                reference = reference_panel(on_insert=on_insert, in_config=in_config)
    return preview, reference

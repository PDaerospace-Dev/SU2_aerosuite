"""CFG setup: the project's template as text, with a live preview and SU2's reference beside it (as tabs).

Aircraft studies edit their template on the Aircraft page's Template tab instead (see status.visible_steps).
"""
from typing import Callable

from nicegui import ui

from ...engine.project import template_file_name, template_warnings
from ..checks import generate_button, render_checks
from ..layout import ProjectFrame, open_session
from ..side_panel import side_panel
from ..sweep_choice import sweep_toggle
from ..template_editor import TemplateEditor, carry_unsaved
from ..ui_kit import card, warning_group


def register() -> None:
    @ui.page("/config")
    def config_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        state: dict = {}  # survives body.refresh(): see carry_unsaved

        def reload_body() -> None:
            carry_unsaved(state)
            body.refresh()

        frame = ProjectFrame(session, "config", on_reload=reload_body)

        @ui.refreshable
        def body() -> None:
            _build(frame, state, reload_body)

        with frame.content:
            body()


def _build(frame: ProjectFrame, state: dict, redraw: Callable[[], None]) -> None:
    holders: dict = {}

    def show_warnings(warnings: list[str]) -> None:
        box = holders["warnings"]
        box.clear()
        if "checks" in holders:  # sweep off: the checks above Generate already list these
            return
        with box:
            if warnings:
                warning_group(warnings, mark="config-warning")

    def render_checks_box() -> None:
        box = holders.get("checks")
        if box is None:
            return
        box.clear()
        with box:
            render_checks(frame, holders.get("generate"))

    def saved(warnings: list[str]) -> None:
        show_warnings(warnings)
        holders["preview"]()
        render_checks_box()
        holders["reference"]()

    frame.actions.clear()
    with frame.actions:
        # The same choice as on Setup; with the sweep off, this page generates the one config.
        sweep_toggle(frame, mark="config-sweep", then=redraw)
        if not frame.session.project.sweep.enabled:
            holders["generate"] = generate_button(frame, render_checks_box)
    if not frame.session.project.sweep.enabled:
        holders["checks"] = ui.column().classes("w-full gap-2").mark("config-checks")
    holders["warnings"] = ui.column().classes("w-full gap-2")
    with ui.element("div").classes("as-columns"):
        with card("Template", f"Saved automatically · {template_file_name(frame.session.project)}"):
            editor = TemplateEditor(frame, state, on_saved=saved)
        holders["preview"], holders["reference"] = side_panel(frame, on_insert=editor.insert, in_config=editor.keys)
    show_warnings(template_warnings(editor.initial))
    render_checks_box()

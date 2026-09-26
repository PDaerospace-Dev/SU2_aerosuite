"""Config: the project's template as text, with a live preview and SU2's reference beside it."""
import re
from typing import Optional

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.project import TEMPLATE_FILE, read_template_text, set_template_text, template_warnings
from ...engine.reference import RefOption, keys_in
from ..checks import generate_button, render_checks
from ..layout import ProjectFrame, open_session
from ..preview import preview_section
from ..reference_panel import reference_panel

ADDED_HEADING = "% --- added from reference ---"


def register() -> None:
    @ui.page("/config")
    def config_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        # Survives body.refresh(): lets a reload triggered by an unrelated project.json change
        # (e.g. the disk watcher, or frame.save's own stale check) carry forward text the user
        # typed but has not blurred yet, instead of overwriting it with what is on disk.
        state: dict = {"editor": None, "saved_text": None}

        def reload_body() -> None:
            editor = state["editor"]
            if editor is not None and state["saved_text"] is not None:
                current = editor.value or ""
                if current != state["saved_text"]:
                    state["pending"] = current
            body.refresh()

        frame = ProjectFrame(session, "config", on_reload=reload_body)

        @ui.refreshable
        def body() -> None:
            _build(frame, state)

        with frame.content:
            body()


def _initial_text(frame: ProjectFrame) -> tuple[str, Optional[str]]:
    """The template text, and — when it exists but cannot be read — the engine's error message."""
    path = frame.session.directory / frame.session.project.template
    if not path.is_file():
        return "", None
    try:
        return read_template_text(frame.session.directory, frame.session.project), None
    except AeroSuiteError as exc:
        return "", str(exc)


def _build(frame: ProjectFrame, state: dict) -> None:
    disk_text, load_error = _initial_text(frame)
    pending = state.pop("pending", None)
    initial = pending if (pending is not None and not load_error) else disk_text
    state["saved_text"] = disk_text
    holders: dict = {}

    def show_warnings(warnings: list[str]) -> None:
        box = holders["warnings"]
        box.clear()
        with box:
            for warning in warnings:
                ui.label(warning).classes("text-warning text-xs").mark("config-warning")

    def render_checks_box() -> None:
        box = holders.get("checks")
        if box is None:
            return
        box.clear()
        with box:
            render_checks(frame, holders.get("generate"))

    def after_save() -> None:
        holders["preview"]()
        render_checks_box()
        holders["reference"]()

    def save_text(text: str) -> Optional[str]:
        # template.cfg is independent of project.json: write it directly (an engine function,
        # not a raw filesystem write) instead of through frame.save, so an unrelated outside
        # change to project.json cannot refuse this save or force a reload that drops the text.
        needs_field_update = frame.session.project.template != TEMPLATE_FILE
        try:
            warnings = set_template_text(frame.session.directory, frame.session.project, text)
        except AeroSuiteError as exc:
            return str(exc)
        if needs_field_update:
            message = frame.save(lambda p: setattr(p, "template", TEMPLATE_FILE))
            if message is not None:
                return message
        else:
            frame.refresh()
        state["saved_text"] = text
        show_warnings(warnings)
        after_save()
        return None

    def commit() -> None:
        if load_error:
            return
        text = holders["editor"].value or ""
        if text == state["saved_text"] and not holders["error"].text:
            return
        holders["error"].text = save_text(text) or ""

    def insert(option: RefOption) -> Optional[str]:
        if load_error:
            return "The template cannot be read; fix it on disk first (see the error above)"
        text = holders["editor"].value or ""
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(rf"^\s*{re.escape(option.key)}\s*=", line):
                return f"{option.key} is already set on line {number}"
        addition = "" if (not text or text.endswith("\n")) else "\n"
        if ADDED_HEADING not in text:
            addition += ADDED_HEADING + "\n"
        new_text = text + addition + option.line + "\n"
        holders["editor"].value = new_text
        message = save_text(new_text)
        holders["error"].text = message or ""
        return message

    frame.actions.clear()
    if not frame.session.project.sweep.enabled:
        with frame.actions:
            holders["generate"] = generate_button(frame, render_checks_box)
    with ui.row().classes("w-full no-wrap items-start gap-6"):
        with ui.column().classes("w-1/2 gap-2"):
            editor = ui.textarea("Template (template.cfg)", value=initial).props(
                'outlined input-class=font-mono input-style="height: 70vh"').classes("w-full").mark("config-text")
            if load_error:
                editor.props("readonly")
            holders["editor"] = editor
            state["editor"] = editor
            holders["error"] = ui.label(load_error or "").classes("text-negative text-xs").mark(
                "config-text-error")
            holders["warnings"] = ui.column().classes("gap-0")
            editor.on("blur", commit)
            holders["preview"] = preview_section(frame)
            if not frame.session.project.sweep.enabled:
                ui.label("Checks").classes("text-lg")
                holders["checks"] = ui.column().classes("w-full gap-2").mark("config-checks")
        with ui.column().classes("w-1/2 gap-2"):
            holders["reference"] = reference_panel(
                on_insert=insert, in_config=lambda: keys_in(holders["editor"].value or ""))
    show_warnings(template_warnings(initial))
    render_checks_box()

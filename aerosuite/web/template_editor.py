"""The template as text (CFG setup's editor, Aircraft's Template tab): autosaves on blur; Insert appends a line."""
import re
from typing import Callable, Optional

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.project import read_template_text, set_template_text, template_file_name
from ..engine.reference import RefOption, keys_in
from .layout import ProjectFrame
from .ui_kit import field

ADDED_HEADING = "% --- added from reference ---"


def carry_unsaved(state: dict) -> None:
    """Before a page rebuild: keep text typed but not yet saved, so the rebuilt editor shows it again.

    `state` outlives the rebuild (a reload triggered by an unrelated project.json change, e.g. the
    disk watcher or frame.save's own stale check, must not overwrite unsaved typing with the disk).
    """
    editor = state.get("editor")
    if editor is not None and state.get("saved_text") is not None:
        current = editor.value or ""
        if current != state["saved_text"]:
            state["pending"] = current


def _disk_text(frame: ProjectFrame) -> tuple[str, Optional[str]]:
    """The template text, and — when it exists but cannot be read — the engine's error message."""
    path = frame.session.directory / frame.session.project.template
    if not path.is_file():
        return "", None
    try:
        return read_template_text(frame.session.directory, frame.session.project), None
    except AeroSuiteError as exc:
        return "", str(exc)


class TemplateEditor:
    def __init__(self, frame: ProjectFrame, state: dict, on_saved: Callable[[list[str]], None],
                 height: str = "70vh") -> None:
        """`on_saved(warnings)` runs after each successful save; `state` must survive page rebuilds."""
        self.frame = frame
        self.state = state
        self.on_saved = on_saved
        disk_text, self.load_error = _disk_text(frame)
        pending = state.pop("pending", None)
        self.initial = pending if (pending is not None and not self.load_error) else disk_text
        state["saved_text"] = disk_text
        self.editor = field(ui.textarea(value=self.initial), mono=True).props(
            f'input-style="height: {height}"').classes("w-full").mark("config-text")
        if self.load_error:
            self.editor.props("readonly")
        state["editor"] = self.editor
        self.error = ui.label(self.load_error or "").classes("as-error-text").mark("config-text-error")
        self.editor.on("blur", self.commit)

    def keys(self) -> set[str]:
        """The options set in the text as typed (for the reference's "In config" marks)."""
        return keys_in(self.editor.value or "")

    def save_text(self, text: str) -> Optional[str]:
        # The template file is independent of project.json: write it directly (an engine function,
        # not a raw filesystem write) instead of through frame.save, so an unrelated outside
        # change to project.json cannot refuse this save or force a reload that drops the text.
        frame = self.frame
        name = template_file_name(frame.session.project)
        needs_field_update = frame.session.project.template != name
        try:
            warnings = set_template_text(frame.session.directory, frame.session.project, text)
        except AeroSuiteError as exc:
            return str(exc)
        if needs_field_update:
            message = frame.save(lambda p: setattr(p, "template", name))
            if message is not None:
                return message
        else:
            frame.refresh()
        self.state["saved_text"] = text
        self.on_saved(warnings)
        return None

    def commit(self) -> None:
        if self.load_error:
            return
        text = self.editor.value or ""
        if text == self.state["saved_text"] and not self.error.text:
            return
        self.error.text = self.save_text(text) or ""

    def insert(self, option: RefOption) -> Optional[str]:
        """Append the reference's line for `option` (under a heading) and save; returns an error, if any."""
        if self.load_error:
            return "The template cannot be read; fix it on disk first (see the error above)"
        text = self.editor.value or ""
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(rf"^\s*{re.escape(option.key)}\s*=", line):
                return f"{option.key} is already set on line {number}"
        addition = "" if (not text or text.endswith("\n")) else "\n"
        if ADDED_HEADING not in text:
            addition += ADDED_HEADING + "\n"
        new_text = text + addition + option.line + "\n"
        self.editor.value = new_text
        message = self.save_text(new_text)
        self.error.text = message or ""
        return message

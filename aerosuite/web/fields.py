"""An input that autosaves: commit on blur or Enter, show the engine's error under the field."""
from typing import Callable, Optional

from nicegui import ui

Commit = Callable[[str], Optional[str]]  # returns an error message, or None when saved


def text_field(label: str, value: object, on_commit: Commit, *, mark: str, placeholder: str = "") -> ui.input:
    field = ui.input(label, value="" if value is None else str(value), placeholder=placeholder)
    field.classes("w-full").mark(mark)
    if placeholder:
        field.props("stack-label")
    error = ui.label("").classes("text-negative text-xs").mark(f"{mark}-error")
    last = {"text": field.value or ""}

    def commit() -> None:
        text = field.value or ""
        if text == last["text"] and not error.text:
            return
        message = on_commit(text)
        error.text = message or ""
        if message is None:
            last["text"] = text

    field.on("blur", commit)
    field.on("keydown.enter", commit)
    return field

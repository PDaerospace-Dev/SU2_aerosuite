"""An input that autosaves: commit on blur or Enter, show the engine's error under the field."""
from typing import Callable, Optional

from nicegui import ui

from .ui_kit import field

Commit = Callable[[str], Optional[str]]  # returns an error message, or None when saved


def text_field(label: str, value: object, on_commit: Commit, *, mark: str, placeholder: str = "",
               mono: bool = False) -> ui.input:
    box = field(ui.input(label, value="" if value is None else str(value), placeholder=placeholder), mono=mono)
    box.classes("w-full").mark(mark)
    if placeholder:
        box.props("stack-label")  # keep the label floated so the placeholder hint stays visible
    error = ui.label("").classes("as-error-text").mark(f"{mark}-error")
    last = {"text": box.value or ""}

    def commit() -> None:
        text = box.value or ""
        if text == last["text"] and not error.text:
            return
        message = on_commit(text)
        error.text = message or ""
        if message is None:
            last["text"] = text

    box.on("blur", commit)
    box.on("keydown.enter", commit)
    return box

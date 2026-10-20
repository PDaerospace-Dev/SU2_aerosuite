"""An input that autosaves: commit on blur or Enter, show the engine's error under the field."""
from typing import Callable, Optional

from nicegui import ui

from .ui_kit import field

Commit = Callable[[str], Optional[str]]  # returns an error message, or None when saved


def text_field(label: str, value: object, on_commit: Commit, *, mark: str, placeholder: str = "",
               mono: bool = False, side_label: bool = False) -> ui.input:
    """`side_label`: the label to the left of the box (the label then marked `<mark>-label`), not inside it."""
    text = "" if value is None else str(value)
    if side_label:
        with ui.row().classes("as-side-field w-full items-center no-wrap"):
            ui.label(label).classes("as-side-label").mark(f"{mark}-label")
            box = field(ui.input(value=text, placeholder=placeholder), mono=mono)
            box.classes("grow min-w-0").mark(mark)
    else:
        box = field(ui.input(label, value=text, placeholder=placeholder), mono=mono)
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

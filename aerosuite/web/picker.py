"""Workstation file/folder picker: browse from the server's root folder, or paste a path."""
from pathlib import Path
from typing import Literal, Optional, Sequence

from nicegui import ui

from ..engine.errors import AeroSuiteError
from . import config
from .files import list_entries, parent_of
from .ui_kit import field, flat_button, primary_button, secondary_button


async def pick_path(
    title: str,
    *,
    mode: Literal["file", "folder", "any"],
    suffixes: Sequence[str] = (),
    start: Optional[Path] = None,
) -> Optional[Path]:
    """Show the picker dialog; returns the chosen path, or None if cancelled."""
    wanted = tuple(suffix.lower() for suffix in suffixes)
    here = {"dir": Path(start) if start is not None and Path(start).is_dir() else config.root()}

    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label(title).classes("as-dialog-title")
        location = ui.label("").classes("as-mono as-muted").mark("picker-location")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            pasted = field(ui.input("Paste a path"), mono=True).classes("grow").mark("picker-path")
            secondary_button("Use", on_click=lambda: use_pasted()).mark("picker-use")
        error = ui.label("").classes("as-error-text").mark("picker-error")
        listing = ui.column().classes("w-full gap-0 max-h-80 overflow-auto")
        with ui.row().classes("w-full items-center gap-2"):
            flat_button("Up", on_click=lambda: go_up(), icon="arrow_upward").mark("picker-up")
            ui.space()
            secondary_button("Cancel", on_click=lambda: dialog.submit(None)).mark("picker-cancel")
            if mode in ("folder", "any"):
                primary_button("Choose this folder", on_click=lambda: dialog.submit(here["dir"])).mark(
                    "picker-choose-folder")

    def show(directory: Path) -> None:
        try:
            entries = list_entries(directory, wanted if mode == "file" else ())
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        here["dir"] = directory
        error.text = ""
        location.text = str(directory)
        listing.clear()
        with listing:
            for entry in entries:
                if entry.is_dir:
                    icon = "folder_special" if entry.is_project else "folder"
                    ui.button(entry.name, icon=icon, on_click=lambda e=entry: show(e.path)).props(
                        "flat no-caps align=left").classes("w-full").mark(f"picker-entry-{entry.name}")
                elif mode in ("file", "any"):
                    ui.button(entry.name, icon="description", on_click=lambda e=entry: dialog.submit(e.path)).props(
                        "flat no-caps align=left").classes("w-full").mark(f"picker-entry-{entry.name}")

    def go_up() -> None:
        parent = parent_of(here["dir"])
        if parent is not None:
            show(parent)

    def use_pasted() -> None:
        raw = (pasted.value or "").strip()
        if not raw:
            error.text = "Type or paste a path first"
            return
        path = Path(raw).expanduser()
        if path.is_dir():
            if mode in ("folder", "any"):
                dialog.submit(path)
            else:
                show(path)
        elif path.is_file() and (
                mode == "any" or (mode == "file" and (not wanted or path.name.lower().endswith(wanted)))):
            dialog.submit(path)
        else:
            what = {"folder": "folder", "file": "matching file", "any": "file or folder"}[mode]
            error.text = f"Not a {what}: {path}"

    show(here["dir"])
    result = await dialog
    dialog.delete()
    return result

"""Workstation file/folder picker: browse from the server's root folder, or paste a path."""
from pathlib import Path
from typing import Literal, Optional, Sequence

from nicegui import ui

from ..engine.errors import AeroSuiteError
from . import config
from .files import list_entries, parent_of


async def pick_path(
    title: str,
    *,
    mode: Literal["file", "folder"],
    suffixes: Sequence[str] = (),
    start: Optional[Path] = None,
) -> Optional[Path]:
    """Show the picker dialog; returns the chosen path, or None if cancelled."""
    wanted = tuple(suffix.lower() for suffix in suffixes)
    here = {"dir": Path(start) if start is not None and Path(start).is_dir() else config.root()}

    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label(title).classes("text-lg")
        location = ui.label("").classes("text-xs text-grey-7").mark("picker-location")
        with ui.row().classes("w-full items-center no-wrap"):
            pasted = ui.input("Paste a path").classes("grow").mark("picker-path")
            ui.button("Use", on_click=lambda: use_pasted()).mark("picker-use")
        error = ui.label("").classes("text-negative text-xs").mark("picker-error")
        listing = ui.column().classes("w-full gap-0 max-h-80 overflow-auto")
        with ui.row():
            ui.button("Up", icon="arrow_upward", on_click=lambda: go_up()).props("flat").mark("picker-up")
            if mode == "folder":
                ui.button("Choose this folder", on_click=lambda: dialog.submit(here["dir"])).mark(
                    "picker-choose-folder")
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat").mark("picker-cancel")

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
                elif mode == "file":
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
            if mode == "folder":
                dialog.submit(path)
            else:
                show(path)
        elif mode == "file" and path.is_file() and (not wanted or path.name.lower().endswith(wanted)):
            dialog.submit(path)
        else:
            error.text = f"Not a {'folder' if mode == 'folder' else 'matching file'}: {path}"

    show(here["dir"])
    result = await dialog
    dialog.delete()
    return result

"""The top bar's ParaView button: a menu of the project's cases that have flow files, newest first.

ParaView starts on the workstation's own display, so only a browser on the workstation starts it;
from another PC a case copies its folder path instead.
"""
import ipaddress
from pathlib import Path
from typing import Sequence

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.paraview import CaseOutput, case_outputs, open_in_paraview
from ..engine.restarts import RUNS_DIR

MENU_CASES = 10  # cases listed by name; "All cases" covers the rest
REMOTE_NOTE = "ParaView opens on the workstation only: a case copies its folder path"


def is_local(ip: str) -> bool:
    """Whether a browser at this address is on the workstation itself."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return ip == "localhost"


class ParaViewMenu:
    def __init__(self, frame) -> None:
        self.frame = frame
        with ui.button("ParaView", icon="view_in_ar", color=None).props("flat dense no-caps").classes(
                "as-topbar-icon as-topbar-labelled").mark("paraview"):
            # Filled each time it opens: flow files appear as cases finish.
            self.menu = ui.menu().mark("paraview-menu")
        self.menu.on_value_change(lambda e: self._fill() if e.value else None)

    def _runs_folder(self) -> Path:
        project = self.frame.session.project
        if project.imported is not None:
            return Path(project.imported.source)
        return Path(self.frame.session.directory) / RUNS_DIR

    def _fill(self) -> None:
        session = self.frame.session
        outputs = case_outputs(session.directory, session.project)
        local = is_local(ui.context.client.ip)
        self.menu.clear()
        with self.menu:
            if not outputs:
                ui.menu_item("No flow files yet").props("disable").mark("paraview-none")
            elif not local:
                ui.menu_item(REMOTE_NOTE).props("disable").mark("paraview-remote")
            for index, output in enumerate(outputs[:MENU_CASES]):
                with ui.menu_item(on_click=lambda o=output: self._choose(o, local)).mark(f"paraview-case-{output.name}"):
                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                        ui.label(output.name).classes("as-mono grow")
                        if index == 0:
                            ui.label("latest").classes("as-label")
            if len(outputs) > 1 and local:
                ui.separator()
                ui.menu_item(f"All {len(outputs)} cases (surfaces)", on_click=lambda: self._open(
                    [path for output in outputs for path in output.surface_files],
                    f"{len(outputs)} cases")).mark("paraview-all")
            if outputs:
                ui.separator()
            ui.menu_item("Copy runs folder path", on_click=lambda: self._copy(self._runs_folder())).mark(
                "paraview-copy")

    def _choose(self, output: CaseOutput, local: bool) -> None:
        if local:
            self._open(output.files, output.name)
        else:
            self._copy(output.folder)

    def _open(self, files: Sequence[Path], what: str) -> None:
        try:
            open_in_paraview(files)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Opening {what} in ParaView", type="positive")

    def _copy(self, folder: Path) -> None:
        ui.clipboard.write(str(folder))
        ui.notify(f"Path copied: {folder}", type="positive")

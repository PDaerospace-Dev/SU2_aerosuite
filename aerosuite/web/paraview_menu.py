"""The top bar's ParaView button: a menu of the project's cases that have flow files, newest first, and
"Write ASCII from restart…" (a case's flow.vtk and surface_flow.vtk rebuilt by SU2_SOL from its restart file).

ParaView starts on the workstation's own display, so only a browser on the workstation starts it;
from another PC a case copies its folder path instead.
"""
import ipaddress
from pathlib import Path
from typing import Sequence

from nicegui import run, ui

from ..engine.ascii_export import TIME_LIMIT_TEXT, write_ascii
from ..engine.errors import AeroSuiteError
from ..engine.jobs.executors import backend_of, slurm_options
from ..engine.jobs.overview import run_solutions
from ..engine.paraview import CaseOutput, case_outputs, open_in_paraview
from ..engine.restarts import RUNS_DIR
from ..engine.settings import load_settings
from .ui_kit import hint, primary_button, secondary_button

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
        self._ascii_dialog()

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
            if self.frame.session.project.imported is None:
                ui.menu_item("Write ASCII from restart…", on_click=self._ask_ascii).mark("paraview-ascii")
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

    # -- ASCII files from a restart ----------------------------------------------------------------------------

    def _ascii_dialog(self) -> None:
        """Built once, outside the menu: a dialog made inside a menu item would close with the menu."""
        with ui.dialog() as self.ascii_dialog, ui.card().classes("w-[30rem] max-w-full"):
            ui.label("Write ASCII ParaView files").classes("as-dialog-title")
            hint("SU2_SOL rebuilds a case's flow.vtk and surface_flow.vtk from its restart file, into its folder "
                 "(written on the node's own disk first, then moved).")
            self.ascii_case = ui.select({}, label="Case", with_input=True).props("outlined dense").classes(
                "as-field w-full").mark("ascii-case")
            self.ascii_where = hint().mark("ascii-where")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=self.ascii_dialog.close).mark("ascii-cancel")
                self.ascii_button = primary_button("Write", icon="description", on_click=self._write_ascii).mark(
                    "ascii-write")

    def _ask_ascii(self) -> None:
        session = self.frame.session
        solutions = run_solutions(session.directory)  # every run folder with a restart file, newest first
        if not solutions:
            ui.notify("No case has a restart file yet", type="warning")
            return
        self.ascii_case.set_options({s.name: s.name + (f" · {s.status.lower()}" if s.status else "")
                                     for s in solutions}, value=solutions[0].name)
        settings = load_settings()[0]
        if backend_of(session.project, settings) == "slurm":
            options = slurm_options(session.project, settings)
            where = f"Runs on Slurm {options.partition}, {options.ntasks} tasks, for at most {TIME_LIMIT_TEXT}."
        else:
            where = f"Runs on this machine with {session.project.run.partitions} MPI processes."
        self.ascii_where.set_text(where)
        self.ascii_button.set_enabled(True)
        self.ascii_dialog.open()

    async def _write_ascii(self) -> None:
        case = self.ascii_case.value
        if not case:
            return
        session = self.frame.session
        self.ascii_button.set_enabled(False)  # sbatch takes a moment: no second job by a double click
        try:
            message = await run.io_bound(write_ascii, session.directory, session.project, case, load_settings()[0])
        except AeroSuiteError as exc:
            self.ascii_button.set_enabled(True)
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        self.ascii_dialog.close()
        ui.notify(message, type="positive", multi_line=True)

    def _copy(self, folder: Path) -> None:
        ui.clipboard.write(str(folder))
        ui.notify(f"Path copied: {folder}", type="positive")

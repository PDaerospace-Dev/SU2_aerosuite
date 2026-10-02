"""The flow files SU2 wrote for each case, and ParaView started on them (on this machine's display)."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .errors import AeroSuiteError
from .models import Project
from .restarts import RUNS_DIR

PARAVIEW = "paraview"
PARAVIEW_ENV = "AEROSUITE_PARAVIEW"  # another executable (name or path) to start instead
FLOW_SUFFIXES = (".vtu", ".vtk", ".vtm")
SURFACE_PREFIX = "surface"  # SU2's SURFACE_FILENAME default is surface_flow
DISPLAY_VARIABLES = ("DISPLAY", "WAYLAND_DISPLAY")


@dataclass(frozen=True)
class CaseOutput:
    name: str
    folder: Path
    files: tuple[Path, ...]  # surface files first
    written: float  # the newest file's modification time

    @property
    def surface_files(self) -> tuple[Path, ...]:
        """The surface files alone (much smaller than the volume); every file if there is none."""
        surface = tuple(path for path in self.files if _is_surface(path))
        return surface or self.files


def _is_surface(path: Path) -> bool:
    return path.name.lower().startswith(SURFACE_PREFIX)


def flow_files(folder: Path) -> list[Path]:
    """The ParaView files directly in a case folder, surface files first, then by name."""
    try:
        found = [path for path in Path(folder).iterdir()
                 if path.suffix.lower() in FLOW_SUFFIXES and path.is_file()]
    except OSError:
        return []
    return sorted(found, key=lambda path: (not _is_surface(path), path.name))


def _case_folders(project_dir: Path, project: Project) -> list[tuple[str, Path]]:
    if project.imported is not None:
        return [(case.name, Path(case.folder)) for case in project.imported.cases]
    return [(case.name, Path(project_dir) / RUNS_DIR / case.name) for case in project.cases]


def case_outputs(project_dir: Path, project: Project) -> list[CaseOutput]:
    """Every case that has flow files, the most recently written first."""
    outputs = []
    for name, folder in _case_folders(project_dir, project):
        files = flow_files(folder)
        if not files:
            continue
        try:
            written = max(path.stat().st_mtime for path in files)
        except OSError:
            continue  # removed while being listed
        outputs.append(CaseOutput(name, folder, tuple(files), written))
    return sorted(outputs, key=lambda output: output.written, reverse=True)


def paraview_command() -> str:
    return os.environ.get(PARAVIEW_ENV) or PARAVIEW


def open_in_paraview(files: Sequence[Path]) -> None:
    """Start ParaView on `files`, detached: it outlives AeroSuite. Raises AeroSuiteError if it cannot start."""
    if not files:
        raise AeroSuiteError("No flow files to open")
    command = paraview_command()
    executable = shutil.which(command)
    if executable is None:
        raise AeroSuiteError(f"ParaView not found: '{command}' is not on the PATH (set {PARAVIEW_ENV} to its path)")
    if os.name != "nt" and not any(os.environ.get(name) for name in DISPLAY_VARIABLES):
        raise AeroSuiteError("No display to open ParaView on: AeroSuite was started without a desktop session")
    try:
        subprocess.Popen([executable, *(str(path) for path in files)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise AeroSuiteError(f"Could not start ParaView: {exc}") from exc

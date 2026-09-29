"""Restart files: where a case's solution is, and whether a path points into this project's runs."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

RUNS_DIR = "runs"
DEFAULT_RESTART_NAME = "restart_flow"  # SU2's default RESTART_FILENAME
_RESTART_RE = re.compile(r"^\s*RESTART_FILENAME\s*=\s*(\S+)", re.MULTILINE)


def _restart_name(folder: Path) -> str:
    """RESTART_FILENAME from the case's .cfg (the sweep script copies it into the case folder)."""
    configs = sorted(folder.glob("*.cfg"), key=lambda path: path.stem != folder.name)  # own cfg first
    for cfg in configs:
        try:
            match = _RESTART_RE.search(cfg.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if match:
            return Path(match.group(1)).name
    return DEFAULT_RESTART_NAME


def find_restart_file(folder: Path) -> Optional[Path]:
    """The restart file SU2 wrote in a case folder: the name as written, then with .dat, then .csv."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    name = _restart_name(folder)
    for candidate in (name, f"{name}.dat", f"{name}.csv"):
        path = folder / candidate
        if path.is_file():
            return path
    return None


def restart_file(project_dir: Path, case_name: str) -> Optional[Path]:
    """The restart file from the case's last run in this project, or None."""
    return find_restart_file(Path(project_dir) / RUNS_DIR / case_name)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def own_case_of(project_dir: Path, ref: str, case_names: Iterable[str]) -> Optional[str]:
    """X when `ref` is this project's runs/X folder or a file directly inside it (X a case name)."""
    runs = (Path(project_dir) / RUNS_DIR).resolve()
    path = Path(ref).resolve()
    names = set(case_names)
    for candidate in (path, path.parent):
        if candidate.name in names and _same(candidate.parent, runs):
            return candidate.name
    return None

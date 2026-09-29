"""Directory listings for the file picker (workstation side)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ..engine.errors import ProjectError
from ..engine.project import PROJECT_FILE


@dataclass(frozen=True)
class Entry:
    name: str
    path: Path
    is_dir: bool
    is_project: bool


def _is_dir(path: Path) -> Optional[bool]:
    try:
        return path.is_dir()
    except OSError:
        return None


def _is_project(path: Path) -> bool:
    try:
        return (path / PROJECT_FILE).is_file()
    except OSError:
        return False


def list_entries(directory: Path, suffixes: Sequence[str] = ()) -> list[Entry]:
    """Sub-folders first, then files (only those ending in `suffixes`, if given); hidden entries skipped."""
    directory = Path(directory)
    wanted = tuple(suffix.lower() for suffix in suffixes)
    try:
        children = list(directory.iterdir())
    except OSError as exc:
        raise ProjectError(f"Cannot open {directory}: {exc}") from exc
    folders: list[Entry] = []
    files: list[Entry] = []
    for child in children:
        if child.name.startswith("."):
            continue
        is_dir = _is_dir(child)
        if is_dir is None:
            continue
        if is_dir:
            folders.append(Entry(child.name, child, True, _is_project(child)))
        elif not wanted or child.name.lower().endswith(wanted):
            files.append(Entry(child.name, child, False, False))

    def by_name(entry: Entry) -> str:
        return entry.name.lower()

    return sorted(folders, key=by_name) + sorted(files, key=by_name)


def parent_of(directory: Path) -> Optional[Path]:
    directory = Path(directory)
    parent = directory.parent
    return None if parent == directory else parent

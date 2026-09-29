"""Recently opened projects, most recent first ($AEROSUITE_HOME/recent.json, default ~/.aerosuite)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..engine.errors import AeroSuiteError
from ..engine.jobs.store import scan_jobs
from ..engine.project import PROJECT_FILE, open_project
from .status import project_kind

MAX_RECENT = 15


def store_path() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return (Path(home) if home else Path.home() / ".aerosuite") / "recent.json"


def load_recent() -> list[Path]:
    """Recent project folders that still contain a project."""
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [Path(item) for item in data if isinstance(item, str) and (Path(item) / PROJECT_FILE).is_file()]


def add_recent(directory: Path) -> None:
    """Move `directory` to the top of the list. A failure to save is ignored: this is a convenience."""
    entry = str(Path(directory).resolve())
    items = [entry] + [str(path) for path in load_recent() if str(path) != entry]
    path = store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[:MAX_RECENT], indent=2), encoding="utf-8")
    except OSError:
        pass


@dataclass(frozen=True)
class RecentProject:
    directory: Path
    name: str
    kind: str  # "sweep · 3 cases" / "single case"; "" when project.json cannot be read
    latest: Optional[str]  # the newest job's state, None without jobs or when unreadable


def recent_projects() -> list[RecentProject]:
    """The recent list with each project's name, kind and latest run; unreadable projects still listed."""
    items = []
    for directory in load_recent():
        try:
            project = open_project(directory)
        except (AeroSuiteError, OSError, ValueError):
            items.append(RecentProject(directory, directory.name, "", None))
            continue
        try:
            jobs, _ = scan_jobs(directory)
        except (AeroSuiteError, OSError):
            jobs = []
        items.append(RecentProject(directory, project.name, project_kind(project),
                                   jobs[0].state.value if jobs else None))
    return items

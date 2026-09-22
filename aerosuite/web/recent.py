"""Recently opened projects, most recent first ($AEROSUITE_HOME/recent.json, default ~/.aerosuite)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..engine.project import PROJECT_FILE

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

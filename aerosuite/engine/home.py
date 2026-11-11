"""The folder AeroSuite keeps its own files in ($AEROSUITE_HOME, default ~/.aerosuite) and the recent projects list."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .project import PROJECT_FILE


def aerosuite_home() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return Path(home) if home else Path.home() / ".aerosuite"


def recent_file() -> Path:
    return aerosuite_home() / "recent.json"


def load_recent() -> list[Path]:
    """Recent project folders that still contain a project."""
    try:
        data = json.loads(recent_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [Path(item) for item in data if isinstance(item, str) and (Path(item) / PROJECT_FILE).is_file()]

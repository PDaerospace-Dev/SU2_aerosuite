"""Sidebar badges: which workflow steps look done, need attention, are not started, or come later."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR
from ..engine.errors import ProjectError
from ..engine.models import Project
from ..engine.preflight import sweep_problems
from ..engine.results import load_case_index

Badge = Literal["done", "attention", "todo", "later"]

STEPS: list[tuple[str, str]] = [
    ("setup", "Setup"),
    ("settings", "Settings"),
    ("sweep", "Sweep"),
    ("configs", "Configs"),
    ("run", "Run"),
    ("monitor", "Monitor"),
    ("results", "Results"),
]


def _configs_badge(project_dir: Path, project: Project) -> Badge:
    if not (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).is_file():
        return "todo"
    try:
        generated = set(load_case_index(project_dir / CONFIGS_DIR))
    except ProjectError:
        return "attention"
    return "done" if generated and generated == {case.name for case in project.cases} else "attention"


def step_badges(project_dir: Path, project: Project) -> dict[str, Badge]:
    project_dir = Path(project_dir)
    template_ok = (project_dir / project.template).is_file()
    mesh_ok = bool(project.mesh.path) and Path(project.mesh.path).is_file()
    if template_ok and mesh_ok:
        setup: Badge = "done"
    elif not template_ok and not project.mesh.path:
        setup = "todo"
    else:
        setup = "attention"
    if not project.sweep.mach and not project.cases:
        sweep: Badge = "todo"
    elif any(problem.severity == "error" for problem in sweep_problems(project)):
        sweep = "attention"
    else:
        sweep = "done"
    return {
        "setup": setup,
        "settings": "done" if template_ok else "todo",
        "sweep": sweep,
        "configs": _configs_badge(project_dir, project),
        "run": "later",
        "monitor": "later",
        "results": "later",
    }

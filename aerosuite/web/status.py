"""Sidebar badges: which workflow steps look done, need attention, are not started, or come later."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, read_template
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.jobs.overview import NOT_RUN, case_overview
from ..engine.jobs.store import active_lock
from ..engine.models import Project
from ..engine.preflight import sweep_problems
from ..engine.project import template_warnings
from ..engine.results import load_case_index

Badge = Literal["done", "attention", "todo", "later", "running", "plain"]

STEPS: list[tuple[str, str]] = [
    ("setup", "Setup"),
    ("config", "Config"),
    ("aircraft", "Aircraft"),
    ("sweep", "Sweep"),
    ("configs", "Configs"),
    ("run", "Run"),
    ("monitor", "Monitor"),
    ("results", "Results"),
]


def visible_steps(project: Project) -> list[tuple[str, str]]:
    """Aircraft only with a profile; Sweep only when the sweep is on."""
    return [
        (key, label) for key, label in STEPS
        if not (key == "aircraft" and not project.profile)
        and not (key == "sweep" and not project.sweep.enabled)
    ]


def _configs_badge(project_dir: Path, project: Project) -> Badge:
    if not (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).is_file():
        return "todo"
    try:
        generated = set(load_case_index(project_dir / CONFIGS_DIR))
    except ProjectError:
        return "attention"
    return "done" if generated and generated == {case.name for case in project.cases} else "attention"


def _config_badge(project_dir: Path, project: Project, template_ok: bool) -> Badge:
    if not template_ok:
        return "todo"
    try:
        warnings = template_warnings(read_template(project_dir, project))
    except AeroSuiteError:
        return "attention"
    return "attention" if warnings else "done"


def _run_badge(project_dir: Path, project: Project) -> Badge:
    if active_lock(project_dir):
        return "running"
    statuses = [row.status for row in case_overview(project_dir, project).rows]
    if not statuses or all(status == NOT_RUN for status in statuses):
        return "todo"
    if all(status == "CONVERGED" for status in statuses):
        return "done"
    return "attention"


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
    elif any(problem.severity == "error" for problem in sweep_problems(project, project_dir)):
        sweep = "attention"
    else:
        sweep = "done"
    return {
        "setup": setup,
        "config": _config_badge(project_dir, project, template_ok),
        "aircraft": "done" if template_ok else "todo",
        "sweep": sweep,
        "configs": _configs_badge(project_dir, project),
        "run": _run_badge(project_dir, project),
        "monitor": "plain",
        "results": "later",
    }

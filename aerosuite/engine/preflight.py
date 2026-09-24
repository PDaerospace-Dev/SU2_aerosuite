"""Checks run before generating configs or starting a job. Returns every problem at once."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .cfg import CASE_INDEX_FILE, CONFIGS_DIR, RUN_CONTROL_FILE
from .jobs.runner import (
    is_aerosuite_python,
    resolve_sweep_python,
    sweep_environment,
    sweep_script_path,
)
from .jobs.store import active_lock
from .models import Project
from .naming import find_collisions
from .project import template_warnings


@dataclass(frozen=True)
class Problem:
    severity: Literal["error", "warning"]
    message: str


def has_errors(problems: Iterable[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _not_absolute(what: str, value: str) -> Problem:
    return Problem("error", f"{what} must be an absolute path (the sweep runs from the runs/ folder): {value}")


def _marker_problems(project: Project) -> list[Problem]:
    known = set(project.mesh.markers)
    if not known:
        return []
    problems = []
    for key, value in project.settings.markers.items():
        if not value:
            continue
        names = [part.strip() for part in value.strip().strip("()").split(",") if part.strip()]
        for name in names:
            if not _is_number(name) and name not in known:
                problems.append(Problem(
                    "warning", f"{key} refers to '{name}', which is not a marker in the mesh"
                ))
    return problems


def _restart_problems(project: Project) -> list[Problem]:
    problems = []
    earlier: set[str] = set()
    for index, case in enumerate(project.cases):
        if case.restart == "previous" and index == 0:
            problems.append(Problem(
                "warning", f"{case.name}: 'previous' restart on the first case will start from scratch"
            ))
        elif case.restart == "custom":
            if not case.restart_ref:
                problems.append(Problem("error", f"{case.name}: 'custom' restart needs a restart file"))
            elif not Path(case.restart_ref).is_absolute():
                problems.append(_not_absolute(f"{case.name}: restart file", case.restart_ref))
            elif not Path(case.restart_ref).is_file():
                problems.append(Problem("error", f"{case.name}: restart file not found: {case.restart_ref}"))
        elif case.restart == "from_case" and case.restart_ref not in earlier:
            problems.append(Problem(
                "error",
                f"{case.name}: 'from_case' must reference an earlier case (got {case.restart_ref!r})",
            ))
        elif case.restart == "initial":
            initial = project.run.initial_restart
            if not initial:
                problems.append(Problem(
                    "error", f"{case.name}: 'initial' restart needs run.initial_restart to be set"
                ))
            elif not Path(initial).is_absolute():
                problems.append(_not_absolute(f"{case.name}: initial restart file", initial))
            elif not Path(initial).is_file():
                problems.append(Problem("error", f"{case.name}: initial restart file not found: {initial}"))
        earlier.add(case.name)
    return problems


def sweep_problems(project: Project) -> list[Problem]:
    """Problems with the sweep and its cases (the Sweep page shows these beside the case table)."""
    problems: list[Problem] = []
    if project.sweep.enabled and not project.sweep.mach:  # build_cases would silently fall back to Mach 0
        problems.append(Problem("error", "No Mach numbers in the sweep"))
    if not project.cases:
        problems.append(Problem("error", "The sweep has no cases"))
    duplicates = find_collisions(case.name for case in project.cases)
    if duplicates:
        problems.append(Problem(
            "error", "Duplicate case names (files would overwrite each other): " + ", ".join(duplicates)
        ))
    problems += _restart_problems(project)
    return problems


def _run_problems(project_dir: Path, project: Project) -> list[Problem]:
    problems = []
    if not (project_dir / CONFIGS_DIR / RUN_CONTROL_FILE).is_file():
        problems.append(Problem("error", "Configs have not been generated (configs/run_control.txt is missing)"))
    index = project_dir / CONFIGS_DIR / CASE_INDEX_FILE
    if index.is_file():
        try:
            generated = set(json.loads(index.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            generated = None
        if generated != {case.name for case in project.cases}:
            problems.append(Problem(
                "warning", "Generated configs are out of date with the sweep; regenerate before running"
            ))
    if not os.environ.get("SU2_RUN"):
        problems.append(Problem("error", "SU2_RUN is not set; the sweep script needs it to import SU2"))
    script = sweep_script_path(project.run)
    if not script.is_file():
        problems.append(Problem("error", f"Sweep script not found: {script}"))
    python = project.run.sweep_python
    resolved = resolve_sweep_python(python)
    search_path = sweep_environment().get("PATH", "")
    if shutil.which(resolved, path=search_path) is None and not Path(resolved).is_file():
        problems.append(Problem("error", f"Python for the sweep script not found: {python}"))
    elif is_aerosuite_python(resolved):
        problems.append(Problem(
            "warning",
            f"The sweep script would run under AeroSuite's own Python ({resolved}); "
            "SU2 is normally importable only from the system Python "
            "— set run.sweep_python to that interpreter",
        ))
    return problems


def preflight(project_dir: Path, project: Project, action: Literal["generate", "run"]) -> list[Problem]:
    project_dir = Path(project_dir)
    problems: list[Problem] = []
    template = project_dir / project.template
    if not template.is_file():
        problems.append(Problem("error", f"Template not found: {template}"))
    else:
        try:
            text = template.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(Problem("error", f"Cannot read template {template}: {exc}"))
        else:
            problems += [Problem("warning", warning) for warning in template_warnings(text)]
    if not project.mesh.path:
        problems.append(Problem("error", "No mesh selected"))
    elif not Path(project.mesh.path).is_absolute():
        problems.append(_not_absolute("Mesh", project.mesh.path))
    elif not Path(project.mesh.path).is_file():
        problems.append(Problem("error", f"Mesh not found: {project.mesh.path}"))
    problems += sweep_problems(project)
    problems += _marker_problems(project)
    lock = active_lock(project_dir)
    if lock:
        problems.append(Problem("error", f"Job {lock['job_id']} is still running for this project"))
    if action == "run":
        problems += _run_problems(project_dir, project)
    return problems

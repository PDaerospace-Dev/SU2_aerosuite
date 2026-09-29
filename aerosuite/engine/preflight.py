"""Checks run before generating configs or starting a job. Returns every problem at once."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from .cfg import CASE_INDEX_FILE, CONFIGS_DIR, RUN_CONTROL_FILE, case_freestream
from .freestream import FREESTREAM_KEYS, freestream_setup_errors
from .jobs.runner import (
    is_aerosuite_python,
    resolve_sweep_python,
    sweep_environment,
    sweep_script_path,
)
from .jobs.store import active_lock
from .models import Case, Project
from .naming import find_collisions
from .project import template_warnings
from .restarts import find_restart_file, own_case_of


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


def _custom_problems(case: Case, names: list[str], project_dir: Optional[Path]) -> list[Problem]:
    ref = case.restart_ref
    if not ref:
        return [Problem("error", f"{case.name}: 'custom' restart needs a restart file or case folder")]
    if "," in ref:
        return [Problem("error", f"{case.name}: restart path must not contain a comma "
                                 f"(run_control.txt separates fields with commas): {ref}")]
    path = Path(ref)
    if not path.is_absolute():
        return [_not_absolute(f"{case.name}: restart path", ref)]
    if project_dir is not None and own_case_of(project_dir, ref, names) is not None:
        return []  # a case of this project: its solution may come from the same job
    if path.is_dir():
        if find_restart_file(path) is None:
            return [Problem("error", f"{case.name}: no restart file found in folder {ref}")]
        return []
    if not path.is_file():
        return [Problem("error", f"{case.name}: restart path not found: {ref}")]
    return []


def _restart_problems(project: Project, project_dir: Optional[Path]) -> list[Problem]:
    problems = []
    names = [case.name for case in project.cases]
    for index, case in enumerate(project.cases):
        if case.restart == "previous" and index == 0:
            problems.append(Problem(
                "warning", f"{case.name}: 'previous' restart on the first case will start from scratch"
            ))
        elif case.restart == "custom":
            problems += _custom_problems(case, names, project_dir)
    return problems


def _template_text(project: Project, project_dir: Optional[Path]) -> Optional[str]:
    """The template text for per-case checks; None when there is no folder or it cannot be read
    (preflight reports that itself)."""
    if project_dir is None:
        return None
    try:
        return (Path(project_dir) / project.template).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _freestream_problems(project: Project, project_dir: Optional[Path]) -> list[Problem]:
    fs = project.settings.freestream
    if fs.mode != "altitude":
        return []
    problems = [Problem("error", message) for message in freestream_setup_errors(project)]
    template = _template_text(project, project_dir)
    # A single case runs at the template's Mach: with no readable template there is nothing to check yet.
    if not problems and (project.sweep.enabled or template is not None):
        for row in case_freestream(project, template or ""):
            if row.values is None:
                reason = ("the template's MACH_NUMBER is missing or 0, so no Reynolds number can be computed"
                          if not project.sweep.enabled and row.mach <= 0 else row.error)
                problems.append(Problem("error", f"{row.name}: {reason}"))
    for key in FREESTREAM_KEYS:
        if key in project.settings.overrides:
            problems.append(Problem("warning", f"{key} ignored: freestream comes from the altitude"))
    problems += _unused_reynolds_problems(project, template or "")
    return problems


def _option(project: Project, template: str, key: str) -> Optional[str]:
    """An SU2 option's value as the configs will have it: a project override, else the template's line."""
    if key in project.settings.overrides:
        return project.settings.overrides[key].strip()
    match = re.search(rf"^\s*{key}\s*=\s*([^\s%]+)", template, re.MULTILINE)
    return match.group(1) if match else None


def _unused_reynolds_problems(project: Project, template: str) -> list[Problem]:
    """Altitude mode writes REYNOLDS_NUMBER; say so when SU2 will not use it."""
    problems = []
    init = _option(project, template, "INIT_OPTION")
    if init is not None and init.upper() != "REYNOLDS":
        problems.append(Problem("warning", f"INIT_OPTION= {init}: SU2 won't use the Reynolds number from the "
                                           "altitude; set INIT_OPTION= REYNOLDS"))
    solver = _option(project, template, "SOLVER")
    if solver is not None and solver.upper().startswith("INC_"):
        problems.append(Problem("warning", f"SOLVER= {solver}: the incompressible solver ignores the Reynolds "
                                           "number and temperature from the altitude"))
    return problems


def sweep_problems(project: Project, project_dir: Optional[Path] = None) -> list[Problem]:
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
    problems += _freestream_problems(project, project_dir)
    problems += _restart_problems(project, project_dir)
    return problems


def _config_state_problems(project_dir: Path, project: Project) -> list[Problem]:
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
    return problems


def _environment_problems(project: Project) -> list[Problem]:
    problems = []
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


def preflight(project_dir: Path, project: Project, action: Literal["generate", "run", "submit"]) -> list[Problem]:
    project_dir = Path(project_dir)
    problems: list[Problem] = []
    template = project_dir / project.template
    if not template.is_file():
        problems.append(Problem("error", f"Template not found: {template}"))
    else:
        try:
            text = template.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            problems.append(Problem("error", f"{template} is not UTF-8 text: {exc}"))
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
    problems += sweep_problems(project, project_dir)
    problems += _marker_problems(project)
    lock = active_lock(project_dir)
    if lock:
        problems.append(Problem("error", f"Job {lock['job_id']} is still running for this project"))
    if action == "run":
        problems += _config_state_problems(project_dir, project)
    if action in ("run", "submit"):
        problems += _environment_problems(project)
    return problems

"""Checks run before generating configs or starting a job. Returns every problem at once."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal, Optional, Sequence

from .cfg import CASE_INDEX_FILE, CONFIGS_DIR, RUN_CONTROL_FILE, STALE_NAME, case_freestream, stale_case_name
from .config_rules import config_problems
from .su2_check import check_cases
from .freestream import FREESTREAM_KEYS, freestream_setup_errors
from .jobs.runner import (
    resolve_sweep_python,
    sweep_environment,
    sweep_script_path,
)
from .jobs.store import active_lock
from .models import Case, Project
from .naming import NAME_CHARACTERS, find_collisions, unsafe_names
from .project import template_warnings
from .restarts import find_restart_file, own_case_of

if TYPE_CHECKING:
    from .jobs.executors import SlurmOptions
    from .settings import AppSettings


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
    """Altitude mode writes the compressible freestream; say so when SU2 will not use it. Either INIT_OPTION
    is fine: REYNOLDS uses the Reynolds number, TD_CONDITIONS the pressure."""
    problems = []
    solver = _option(project, template, "SOLVER")
    if solver is not None and solver.upper().startswith("INC_"):
        problems.append(Problem("warning", f"SOLVER= {solver}: the incompressible solver ignores the Reynolds "
                                           "number, temperature and pressure from the altitude"))
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
    unsafe = unsafe_names(case.name for case in project.cases)
    if unsafe:
        problems.append(Problem(
            "error", f"Case names can only use {NAME_CHARACTERS} (they are file names): {unsafe[0]!r}"
            + (f" and {len(unsafe) - 1} more" if len(unsafe) > 1 else "")
            + "; change the base name or the altitude label"
        ))
    problems += _freestream_problems(project, project_dir)
    problems += _case_name_problems(project, project_dir)
    problems += _restart_problems(project, project_dir)
    return problems


def _case_name_problems(project: Project, project_dir: Optional[Path]) -> list[Problem]:
    """An aircraft single case whose name no longer follows the template (edited outside AeroSuite)."""
    template = _template_text(project, project_dir)
    renamed = stale_case_name(project, template) if template is not None else None
    if renamed is None:
        return []
    return [Problem("error", STALE_NAME.format(old=project.cases[0].name, new=renamed))]


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
    elif os.environ.get("SU2_RUN") and not project.run.sweep_script:  # a custom script may import SU2 its own way
        error = su2_import_error(resolved)
        if error:
            problems.append(Problem("error", f"The sweep's Python ({resolved}) cannot import SU2: {error}"))
    return problems


IMPORT_CHECK_SECONDS = 60.0  # the Run page draws its checks often: one try per interpreter per minute
_IMPORT_CODE = "import os, sys; sys.path.append(os.environ['SU2_RUN']); import SU2"
_import_checks: dict[tuple, tuple[float, Optional[str]]] = {}


def su2_import_error(python: str) -> Optional[str]:
    """Why `python` cannot import SU2 the way the sweep script does (SU2_RUN on sys.path), or None when it can.

    The last line of the error, e.g. "ModuleNotFoundError: No module named 'numpy'". Cached for a minute."""
    env = sweep_environment()
    key = (python, env.get("SU2_RUN"), env.get("PYTHONPATH"))
    now = time.monotonic()
    cached = _import_checks.get(key)
    if cached is not None and now - cached[0] < IMPORT_CHECK_SECONDS:
        return cached[1]
    try:
        done = subprocess.run([python, "-c", _IMPORT_CODE], env=env, capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
        lines = [line.strip() for line in (done.stderr or done.stdout).splitlines() if line.strip()]
        error = None if done.returncode == 0 else (lines[-1] if lines else f"exit code {done.returncode}")
    except subprocess.TimeoutExpired:
        error = "importing SU2 took longer than 30 s"
    except OSError as exc:
        error = str(exc)
    _import_checks[key] = (now, error)
    return error


def preflight(project_dir: Path, project: Project, action: Literal["generate", "run", "submit"],
              cases: Optional[Sequence[str]] = None, options: Optional["SlurmOptions"] = None,
              settings: Optional["AppSettings"] = None, check_su2: bool = False) -> list[Problem]:
    """Every problem for `action`. For a run or submit, the backend's own checks: the local sweep's environment, or
    (Slurm) shared storage, configs, mesh, partition, tasks and memory for `cases` (default all) with `options`
    (default the project's and the settings'). `check_su2` runs SU2's dry run on each case's config (a few
    seconds; Generate and Submit do); without it, only verdicts SU2 already gave are reported."""
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
    problems += config_problems(project_dir, project)
    if settings is None:
        from .settings import load_settings

        su2_settings = load_settings()[0]
    else:
        su2_settings = settings
    problems += check_cases(project_dir, project, cases, su2_settings, run=check_su2)
    lock = active_lock(project_dir)
    if lock and not (action == "generate" and lock.get("backend") == "slurm"):  # Slurm cases run from copies
        problems.append(Problem("error", f"Job {lock['job_id']} is still running for this project"))
    if action == "run":
        problems += _config_state_problems(project_dir, project)
    if action in ("run", "submit"):
        problems += _backend_problems(project_dir, project, action, cases, options, settings)
    return problems


def _backend_problems(project_dir: Path, project: Project, action: str, cases: Optional[Sequence[str]],
                      options: Optional["SlurmOptions"], settings: Optional["AppSettings"]) -> list[Problem]:
    from .jobs.executors import backend_of, slurm_options
    from .settings import load_settings

    if settings is None:
        settings, warnings = load_settings()
    else:
        warnings = []
    if backend_of(project, settings) != "slurm":
        return _environment_problems(project)
    from .slurm_checks import slurm_problems

    options = options or slurm_options(project, settings)
    problems = [Problem("warning", warning) for warning in warnings]
    return problems + slurm_problems(project_dir, project, cases, options.partition, options.ntasks,
                                     options.time_limit, settings, read_configs=action == "run")

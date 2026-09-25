"""A job's own inputs: the selected cases' configs and a run_control.txt that restarts correctly.

Every submit runs from jobs/<id>/configs/, so rerunning some cases never touches configs/, and a
restart never silently refers to a different case than the one the user chose:
- `previous` means the case before it in the project's case list;
- a reference to a case of this project that runs earlier in the job uses its fresh solution
  (`previous` when it runs just before, else `from_case`);
- otherwise that case's current solution is copied to jobs/<id>/restart/<case>/ before anything
  runs (the sweep script deletes runs/<case>/ when that case starts) and passed as `custom`.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE, apply_parameters
from ..errors import JobError
from ..models import Case, Project
from ..restarts import find_restart_file, own_case_of, restart_file
from .store import JOBS_DIR

RESTART_DIR = "restart"


@dataclass(frozen=True)
class ControlLine:
    case: str
    option: str  # "none" | "previous" | "from_case" | "custom"
    ref: Optional[str] = None  # from_case: "<case>.cfg"; custom: a restart file outside this project's runs/
    copy_from: Optional[Path] = None  # custom: a solution in this project's runs/, copied aside first


@dataclass(frozen=True)
class RestartPlan:
    lines: list[ControlLine]
    warnings: list[str] = field(default_factory=list)
    missing_continue: list[str] = field(default_factory=list)  # continued cases with no solution


def plan_restarts(project_dir: Path, project: Project, cases: Sequence[str],
                  continue_cases: Iterable[str] = ()) -> RestartPlan:
    """How each selected case restarts in a job running `cases` (in the project's case order)."""
    names = [case.name for case in project.cases]
    unknown = [name for name in cases if name not in names]
    if unknown:
        raise JobError("Unknown cases: " + ", ".join(unknown))
    wanted = set(cases)
    selected = [name for name in names if name in wanted]
    if not selected:
        raise JobError("No cases selected")
    by_name = {case.name: case for case in project.cases}
    continued = set(continue_cases)
    lines: list[ControlLine] = []
    warnings: list[str] = []
    missing: list[str] = []
    for position, name in enumerate(selected):
        if name in continued:
            solution = restart_file(project_dir, name)
            if solution is None:
                missing.append(name)
                lines.append(ControlLine(name, "none"))
            else:
                lines.append(ControlLine(name, "custom", copy_from=solution))
            continue
        case = by_name[name]
        target = _referenced_case(project_dir, case, names)
        if target is not None:
            lines.append(_case_reference(project_dir, name, target, selected[:position], warnings))
        elif case.restart == "custom":
            lines.append(_custom_path(name, case.restart_ref or ""))
        else:
            lines.append(ControlLine(name, "none"))
    return RestartPlan(lines, warnings, missing)


def _referenced_case(project_dir: Path, case: Case, names: list[str]) -> Optional[str]:
    """The case of this project whose solution `case` restarts from, if any."""
    if case.restart == "previous":
        index = names.index(case.name)
        return names[index - 1] if index > 0 else None
    if case.restart == "custom" and case.restart_ref:
        return own_case_of(project_dir, case.restart_ref, names)
    return None


def _case_reference(project_dir: Path, name: str, target: str, earlier: list[str],
                    warnings: list[str]) -> ControlLine:
    if target in earlier:  # runs earlier in this job: restart from its fresh solution
        if earlier[-1] == target:
            return ControlLine(name, "previous")
        return ControlLine(name, "from_case", ref=f"{target}.cfg")
    solution = restart_file(project_dir, target)
    if solution is None:
        warnings.append(f"{name}: {target} has no restart file, so {name} starts from scratch")
        return ControlLine(name, "none")
    return ControlLine(name, "custom", copy_from=solution)


def _custom_path(name: str, ref: str) -> ControlLine:
    path = Path(ref)
    if path.is_dir():
        solution = find_restart_file(path)
        if solution is None:
            raise JobError(f"{name}: no restart file found in folder {ref}")
        return ControlLine(name, "custom", ref=str(solution))
    return ControlLine(name, "custom", ref=ref)


def prepare_job(project_dir: Path, project: Project, job_id: str, cases: Sequence[str],
                continue_cases: Iterable[str] = ()) -> Path:
    """Write jobs/<id>/configs/ (cfgs + run_control.txt) and copy restart solutions aside.

    Returns the configs folder. On any error nothing of this job is left behind.
    """
    project_dir = Path(project_dir).resolve()
    continued = set(continue_cases)
    plan = plan_restarts(project_dir, project, cases, continued)
    if plan.missing_continue:
        raise JobError("These cases have no solution to continue from: " + ", ".join(plan.missing_continue))
    source = project_dir / CONFIGS_DIR
    missing = [line.case for line in plan.lines if not (source / f"{line.case}.cfg").is_file()]
    if missing:
        raise JobError("Configs are missing for " + ", ".join(missing) + "; generate configs first")
    job_dir = project_dir / JOBS_DIR / job_id
    if job_dir.exists():
        raise JobError(f"{job_dir} already exists")
    configs = job_dir / CONFIGS_DIR
    try:
        configs.mkdir(parents=True)
        control = []
        for line in plan.lines:
            text = (source / f"{line.case}.cfg").read_text(encoding="utf-8")
            if line.case in continued:
                text = apply_parameters(text, {"RESTART_SOL": "YES"})
            (configs / f"{line.case}.cfg").write_text(text, encoding="utf-8", newline="\n")
            control.append(_control_line(job_dir, line))
        (configs / RUN_CONTROL_FILE).write_text("\n".join(control) + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise JobError(f"Cannot prepare job {job_id} in {job_dir}: {exc}") from exc
    return configs


def _control_line(job_dir: Path, line: ControlLine) -> str:
    fields = [f"{line.case}.cfg", line.option]
    if line.copy_from is not None:
        copy = job_dir / RESTART_DIR / line.copy_from.parent.name / line.copy_from.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(line.copy_from, copy)
        fields.append(str(copy))
    elif line.ref is not None:
        fields.append(line.ref)
    return ", ".join(fields)

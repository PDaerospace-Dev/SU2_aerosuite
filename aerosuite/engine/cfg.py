"""SU2 config rendering: template + project settings + case values -> .cfg text."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .errors import GenerationError, ProjectError, TemplateError
from .jobs.store import active_lock
from .models import Case, Project, Settings
from .naming import case_name, find_collisions, format_value

CONFIGS_DIR = "configs"
RUN_CONTROL_FILE = "run_control.txt"
CASE_INDEX_FILE = "cases.json"

_MARKER_TAG_RE = re.compile(r"^\s*MARKER_TAG\s*=\s*(\S+)")


def extract_markers(mesh_path: Path) -> list[str]:
    """Boundary marker names from the MARKER_TAG= lines of an .su2 mesh."""
    try:
        with open(mesh_path, "r", encoding="utf-8", errors="replace") as fh:
            return [m.group(1) for line in fh if (m := _MARKER_TAG_RE.match(line))]
    except OSError as exc:
        raise ProjectError(f"Cannot read mesh file {mesh_path}: {exc}") from exc


def apply_parameters(content: str, parameters: Mapping[str, Optional[str]]) -> str:
    """Set KEY= value lines in cfg text.

    Existing key -> line replaced; missing key -> appended at the end;
    value None -> line removed.
    """
    appended = []
    for key, value in parameters.items():
        line_re = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if value is None:
            content = re.sub(rf"^{re.escape(key)}\s*=.*(?:\n)?", "", content, flags=re.MULTILINE)
            continue
        line = f"{key}= {value}"
        if line_re.search(content):
            content = line_re.sub(lambda _match: line, content)
        else:
            appended.append(line)
    if appended:
        content = content.rstrip("\n") + "\n\n" + "\n".join(appended) + "\n"
    return content


def _number(value) -> Optional[str]:
    return None if value is None else format_value(value)


def single_case_name(project: Project) -> str:
    """The one case of a sweep-off project: the project name as a safe file stem."""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", project.name).strip("._")
    return stem or "case"


def template_case_values(template: str) -> tuple[float, float, float]:
    """MACH_NUMBER, AOA and SIDESLIP_ANGLE as written in a template (0.0 if missing or not a number)."""
    values = []
    for key in ("MACH_NUMBER", "AOA", "SIDESLIP_ANGLE"):
        match = re.search(rf"^{key}\s*=\s*([^\s%]+)", template, re.MULTILINE)
        try:
            values.append(float(match.group(1)) if match else 0.0)
        except ValueError:
            values.append(0.0)
    return values[0], values[1], values[2]


def settings_parameters(settings: Settings) -> dict[str, Optional[str]]:
    """Project-wide parameters; unset fields are omitted so the template value stands."""
    fs, ref, num = settings.freestream, settings.reference, settings.numerics
    candidates = {
        "FREESTREAM_TEMPERATURE": _number(fs.temperature_K),
        "REYNOLDS_NUMBER": _number(fs.reynolds),
        "REYNOLDS_LENGTH": _number(fs.reynolds_length),
        "REF_ORIGIN_MOMENT_X": _number(ref.origin_x),
        "REF_ORIGIN_MOMENT_Y": _number(ref.origin_y),
        "REF_ORIGIN_MOMENT_Z": _number(ref.origin_z),
        "REF_LENGTH": _number(ref.ref_length),
        "REF_AREA": _number(ref.ref_area),
        "KIND_TURB_MODEL": num.turb_model,
        "CFL_NUMBER": _number(num.cfl),
        "ITER": None if num.iter is None else str(num.iter),
        "CONV_NUM_METHOD_FLOW": num.conv_method,
        "MUSCL_FLOW": num.muscl,
    }
    params: dict[str, Optional[str]] = {k: v for k, v in candidates.items() if v is not None}
    params.update(settings.markers)
    params.update(settings.overrides)
    return params


def case_parameters(project: Project, case: Case) -> dict[str, str]:
    params: dict[str, str] = {}
    if project.sweep.enabled:
        params.update({
            "MACH_NUMBER": format_value(case.mach),
            "AOA": format_value(case.alpha),
            "SIDESLIP_ANGLE": format_value(case.beta),
            "BREAKDOWN_FILENAME": f"{case.name}_FB.dat",
        })
    if project.mesh.path:
        # Absolute, because the sweep runs from runs/ rather than from the cfg folder.
        params["MESH_FILENAME"] = str(Path(project.mesh.path).resolve())
    return params


def read_template(project_dir: Path, project: Project) -> str:
    path = Path(project_dir) / project.template
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError(f"{path} is not UTF-8 text: {exc}") from exc
    except OSError as exc:
        raise TemplateError(f"Cannot read template {path}: {exc}") from exc


def render_case(template: str, project: Project, case: Case) -> str:
    """Template -> settings -> overrides -> case values; later layers win."""
    params = settings_parameters(project.settings)
    params.update(case_parameters(project, case))
    return apply_parameters(template, params)


def build_cases(project: Project) -> list[Case]:
    """Expand the sweep into cases, keeping restart choices of cases that still exist."""
    sweep, naming = project.sweep, project.sweep.naming
    previous = {case.name: case for case in project.cases}
    if not sweep.enabled:
        name = single_case_name(project)
        old = previous.get(name)
        return [Case(
            name=name, mach=0.0, alpha=0.0, beta=0.0,
            restart=old.restart if old else "none",
            restart_ref=old.restart_ref if old else None,
        )]
    cases = []
    for mach in sweep.mach or [0.0]:
        for alpha in sweep.alpha or [0.0]:
            for beta in sweep.beta or [0.0]:
                name = case_name(
                    mach, alpha, beta,
                    altitude=sweep.altitude,
                    base_name=naming.base_name,
                    include_mach=naming.include_mach,
                    include_alpha=naming.include_alpha,
                    include_beta=naming.include_beta,
                    include_altitude=naming.include_altitude,
                    include_base=naming.include_base,
                )
                old = previous.get(name)
                cases.append(Case(
                    name=name, mach=mach, alpha=alpha, beta=beta,
                    restart=old.restart if old else "none",
                    restart_ref=old.restart_ref if old else None,
                ))
    return cases


def run_control_text(cases: Sequence[Case]) -> str:
    """run_control.txt in the format aoa_sweep_v8.py reads (a job writes its own; see jobs/plan.py)."""
    lines = []
    for case in cases:
        fields = [f"{case.name}.cfg", case.restart]
        if case.restart == "custom":
            fields.append(case.restart_ref or "")
        lines.append(", ".join(fields))
    return "\n".join(lines) + "\n"


def generate_configs(project_dir: Path, project: Project) -> list[Path]:
    """Write configs/<case>.cfg for every case, plus run_control.txt and cases.json."""
    lock = active_lock(project_dir)
    if lock:
        # The running sweep reads each cfg only when its case starts.
        raise GenerationError(
            f"Job {lock['job_id']} is still running for this project; "
            "wait for it or cancel it before regenerating configs"
        )
    if not project.cases:
        raise GenerationError("The sweep has no cases; build the cases first")
    duplicates = find_collisions(case.name for case in project.cases)
    if duplicates:
        raise GenerationError(
            "These case names occur more than once and would overwrite each other: "
            + ", ".join(duplicates)
        )
    no_ref = [c.name for c in project.cases if c.restart == "custom" and not c.restart_ref]
    if no_ref:
        raise GenerationError(
            "These cases need a restart reference for their restart option: "
            + ", ".join(no_ref)
        )
    template = read_template(project_dir, project)
    out_dir = Path(project_dir) / CONFIGS_DIR
    if project.sweep.enabled:
        index = {c.name: {"mach": c.mach, "alpha": c.alpha, "beta": c.beta} for c in project.cases}
    else:
        mach, alpha, beta = template_case_values(template)
        index = {c.name: {"mach": mach, "alpha": alpha, "beta": beta} for c in project.cases}
    written = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*.cfg"):
            stale.unlink()
        for case in project.cases:
            path = out_dir / f"{case.name}.cfg"
            path.write_text(render_case(template, project, case), encoding="utf-8", newline="\n")
            written.append(path)
        (out_dir / RUN_CONTROL_FILE).write_text(
            run_control_text(project.cases), encoding="utf-8", newline="\n"
        )
        (out_dir / CASE_INDEX_FILE).write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError as exc:
        raise GenerationError(f"Cannot write configs to {out_dir}: {exc}") from exc
    return written

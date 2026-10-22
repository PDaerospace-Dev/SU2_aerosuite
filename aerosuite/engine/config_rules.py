"""AeroSuite's own checks of the config a case runs with, for what SU2's dry run cannot see (it uses a dummy
geometry) or accepts although it is rarely meant. Instant: no SU2 is run.

- error: a marker of the mesh with no boundary condition (SU2 stops on it once it reads the mesh);
- warnings: an adaptive CFL whose minimum is above CFL_NUMBER, REF_AREA / REF_LENGTH left at SU2's 1 in an
  aircraft study, a history without the coefficients Results judges convergence on.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .cfg import read_template, render_case
from .errors import AeroSuiteError
from .models import Project

if TYPE_CHECKING:
    from .preflight import Problem

_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*(?:%.*)?$")
# MARKER_ options that name markers without giving them a boundary condition
NOT_CONDITIONS = {
    "MARKER_PLOTTING", "MARKER_MONITORING", "MARKER_DESIGNING", "MARKER_GEO_EVAL", "MARKER_ANALYZE",
    "MARKER_ANALYZE_AVERAGE", "MARKER_DEFORM_MESH", "MARKER_DEFORM_MESH_SYM_PLANE", "MARKER_FLUID_LOAD",
    "MARKER_MOVING", "MARKER_WALL_FUNCTIONS", "MARKER_ZONE_INTERFACE", "MARKER_FLUID_INTERFACE",
    "MARKER_CHT_INTERFACE", "MARKER_PYTHON_CUSTOM", "MARKER_SOBOLEVBC", "MARKER_TURBOMACHINERY",
    "MARKER_MIXINGPLANE_INTERFACE", "MARKER_SHROUD", "MARKER_TURBO_PERFORMANCE", "MARKER_GILES_PERFORMANCE",
    "MARKER_NORMAL_DISPL", "MARKER_DISPL", "MARKER_SLIDING", "MARKER_ACTDISK_CG",
}
CONVERGENCE_FIELDS = {"AERO_COEFF", "LIFT", "DRAG", "MOMENT_Y"}  # history fields that give CL, CD, CMy


def _options(text: str) -> dict[str, str]:
    options = {}
    for line in text.splitlines():
        match = _LINE_RE.match(line)
        if match:
            options[match.group(1)] = match.group(2)
    return options


def _items(value: str) -> list[str]:
    return [part.strip() for part in value.strip().strip("()").split(",") if part.strip()]


def _number(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:
        return None


def config_problems(project_dir: Path, project: Project) -> list["Problem"]:
    """Problems with the config the cases run with (the first case's; the rules do not depend on the case)."""
    from .preflight import Problem

    if not project.cases:
        return []
    try:
        text = render_case(read_template(project_dir, project), project, project.cases[0])
    except AeroSuiteError:
        return []  # preflight reports the template or the freestream
    options = _options(text)
    problems = []

    known = project.mesh.markers
    if known:
        named = {item for key, value in options.items() if key.startswith("MARKER_") and key not in NOT_CONDITIONS
                 for item in _items(value)}
        missing = [marker for marker in known if marker not in named]
        if missing:
            problems.append(Problem("error", f"The mesh's marker{'s' if len(missing) > 1 else ''} "
                                             f"{', '.join(missing)} {'have' if len(missing) > 1 else 'has'} no "
                                             "boundary condition in the config (e.g. MARKER_HEATFLUX, MARKER_FAR): "
                                             "SU2 stops when it reads the mesh"))

    if options.get("CFL_ADAPT", "").upper() == "YES":
        params = [_number(item) for item in _items(options.get("CFL_ADAPT_PARAM", ""))]
        cfl = _number(options.get("CFL_NUMBER", ""))
        if len(params) >= 3 and params[2] is not None and cfl is not None and params[2] > cfl:
            problems.append(Problem("warning", f"CFL_ADAPT_PARAM's minimum CFL {params[2]:g} is above CFL_NUMBER "
                                               f"{cfl:g}: the CFL jumps to {params[2]:g} at the first adaptation"))

    if project.profile:
        for key in ("REF_AREA", "REF_LENGTH"):
            value = _number(options[key]) if key in options else 1.0
            if value == 1.0:
                problems.append(Problem("warning", f"{key} is 1 (SU2's default): the coefficients are per "
                                                   f"{'1 m²' if key == 'REF_AREA' else '1 m'}; set it on the "
                                                   "Aircraft page"))
        fields = {item.upper() for item in _items(options.get("HISTORY_OUTPUT", ""))}
        if not fields & CONVERGENCE_FIELDS:
            problems.append(Problem("warning", "HISTORY_OUTPUT has no AERO_COEFF (or LIFT, DRAG): Results cannot "
                                               "judge convergence, which it reads from CL, CD and CMy"))

    return problems

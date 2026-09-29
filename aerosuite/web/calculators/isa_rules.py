"""ISA calculator rules without NiceGUI: what it pre-fills from a project, and what Apply would change."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, NamedTuple, Optional

from ...engine.cfg import settings_parameters, template_case_values
from ...engine.editing import set_altitudes, set_freestream
from ...engine.errors import ProjectError
from ...engine.freestream import freestream_for, naming_altitude, sweeps_altitude
from ...engine.models import Freestream, Project, Settings
from ...engine.naming import format_value

SWEEP_REASON = "Per-case freestream is set on the Aircraft page, which needs an aircraft profile (Setup)"
NO_MACH_REASON = "The template has no MACH_NUMBER; the Reynolds number needs the Mach that runs"
MODE_TEXT = {"manual": "Set by hand", "altitude": "From altitude"}


class Prefill(NamedTuple):
    altitude_km: float
    mach: float
    length_m: float
    note: str


@dataclass(frozen=True)
class ApplyPlan:
    kind: Literal["settings", "template", "blocked"]  # settings: the project's freestream (Aircraft page)
    changes: list[tuple[str, str, str]] = field(default_factory=list)  # (what, old, new)
    note: str = ""
    reason: str = ""  # why Apply is not possible (kind "blocked")
    template_params: dict[str, str] = field(default_factory=dict)


def _num(value: Optional[float], unit: str) -> str:
    return "—" if value is None else f"{format_value(value)} {unit}"


def isa_prefill(project: Optional[Project], template: str) -> Prefill:
    if project is None:
        return Prefill(0.0, 0.8, 1.0, "")
    fs, notes = project.settings.freestream, []
    altitude, length, mach = 0.0, 1.0, 0.8
    if sweeps_altitude(project) and project.sweep.altitudes_km:
        altitude = project.sweep.altitudes_km[0]
        notes.append(f"altitude {format_value(altitude)} km (the sweep's first)")
    elif fs.mode == "altitude" and not project.sweep.enabled and fs.altitude_km is not None:
        altitude = fs.altitude_km
        notes.append("altitude from the Aircraft page")
    if fs.reynolds_length:
        length = fs.reynolds_length
        notes.append("length from the project's Reynolds length")
    if project.sweep.enabled and project.sweep.mach:
        mach = max(project.sweep.mach)
        notes.append(f"Mach {format_value(mach)} (the sweep's highest)")
    elif template_case_values(template)[0] > 0:
        mach = template_case_values(template)[0]
        notes.append(f"Mach {format_value(mach)} (the template's)")
    note = f"Filled from {project.name}: " + ", ".join(notes) if notes else ""
    return Prefill(altitude, mach, length, note)


def _template_value(template: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.*?)\s*$", template, re.MULTILINE)
    return match.group(1) if match else "—"


def apply_isa_settings(project: Project, altitude_km: float, length_m: float) -> None:
    """Apply to a project's settings: altitude mode at this one altitude (it replaces a sweep's list)."""
    set_freestream(project, mode="altitude", reynolds_length=length_m)
    set_altitudes(project, [altitude_km])


def plan_isa_apply(project: Project, template: Optional[str], altitude_km: float, mach: float,
                   length_m: float) -> ApplyPlan:
    if project.profile or project.settings.freestream.mode == "altitude":
        # With a profile, or already in altitude mode (e.g. set with the CLI), the per-case values come from
        # the project's freestream settings, which also win over any template line.
        fs = project.settings.freestream
        new = project.model_copy(deep=True)
        try:
            apply_isa_settings(new, altitude_km, length_m)
        except ProjectError as exc:
            return ApplyPlan("blocked", reason=str(exc))
        if project.sweep.enabled:
            old_altitude = ("Altitudes", ", ".join(format_value(a) for a in project.sweep.altitudes_km) + " km"
                            if project.sweep.altitudes_km else "—")
        else:
            old_altitude = ("Altitude", _num(fs.altitude_km, "km"))
        changes = [("Freestream", MODE_TEXT[fs.mode], "From altitude"),
                   (*old_altitude, _num(altitude_km, "km")),
                   ("Reynolds length", _num(fs.reynolds_length, "m"), _num(length_m, "m"))]
        old_label, new_label = naming_altitude(project), naming_altitude(new)
        if old_label != new_label and project.sweep.enabled and project.sweep.naming.include_altitude:
            changes.append(("Altitude label (case names)", old_label, new_label))
        if len(new.cases) != len(project.cases):
            note = f"{len(project.cases)} cases become {len(new.cases)}"
        else:
            renamed = sum(1 for old, now in zip(project.cases, new.cases) if old.name != now.name)
            note = f"Renames {renamed} case{'' if renamed == 1 else 's'}" if renamed else ""
        return ApplyPlan("settings", changes, note)
    if project.sweep.enabled:
        return ApplyPlan("blocked", reason=SWEEP_REASON)
    if template is None:
        return ApplyPlan("blocked", reason="The template cannot be read")
    run_mach = template_case_values(template)[0]
    if run_mach <= 0:
        return ApplyPlan("blocked", reason=NO_MACH_REASON)
    settings = Settings(freestream=Freestream(mode="altitude", altitude_km=altitude_km, reynolds_length=length_m))
    try:
        params = freestream_for(settings, run_mach)
    except ProjectError as exc:
        return ApplyPlan("blocked", reason=str(exc))
    changes = [(key, _template_value(template, key), value) for key, value in params.items()]
    notes = []
    if run_mach != mach:
        notes.append(f"The Reynolds number is computed for Mach {format_value(run_mach)} (the template's), "
                     f"not {format_value(mach)}")
    # Project-wide values (Placeholders, by-hand freestream) are written over the template in every config.
    winning = [key for key in params if key in settings_parameters(project.settings)]
    if winning:
        notes.append(f"This project also sets {', '.join(winning)}, which win over the template; "
                     "remove them for these values to take effect")
    return ApplyPlan("template", changes, ". ".join(notes), template_params=params)

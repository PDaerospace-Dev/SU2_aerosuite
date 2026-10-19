"""Turn user input into project changes. Shared by the CLI and (later) the web UI."""
from __future__ import annotations

import math
import re
from typing import Any, Optional

from .cfg import build_cases
from .errors import ProjectError
from .models import Project, Settings
from .naming import name_part_problem

MARKER_PREFIX = "MARKER_"
REMOVE_WORD = "none"
# Written per case from the sweep and the mesh; a project-wide value would be overwritten.
CASE_KEYS = frozenset({"MACH_NUMBER", "AOA", "SIDESLIP_ANGLE", "MESH_FILENAME", "BREAKDOWN_FILENAME"})

MAX_LIST_VALUES = 1000  # in one sweep list; a mistyped step must not build millions of values

_SPLIT_RE = re.compile(r"[,\s]+")
_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*")


def _number(token: str, context: str) -> float:
    try:
        value = float(token)
    except ValueError:
        raise ProjectError(f"{token!r} in {context!r} is not a number") from None
    if not math.isfinite(value):
        raise ProjectError(f"{token!r} in {context!r} is not a number")
    return value


def _expand_range(token: str) -> list[float]:
    parts = token.split(":")
    if len(parts) != 3:
        raise ProjectError(f"Range {token!r} must be start:stop:step")
    start, stop, step = (_number(part, token) for part in parts)
    if step <= 0:
        raise ProjectError(f"Range {token!r} needs a positive step")
    if stop < start:
        raise ProjectError(f"Range {token!r} has its stop below its start")
    if (stop - start) / step >= MAX_LIST_VALUES:  # checked before anything is built
        raise ProjectError(f"Range {token!r} makes more than {MAX_LIST_VALUES} values; use a larger step")
    count = math.floor(round((stop - start) / step, 9)) + 1
    # round() removes float noise (0.30000000000000004); + 0.0 turns -0.0 into 0.0
    return [round(start + i * step, 10) + 0.0 for i in range(count)]


def parse_value_list(text: str) -> list[float]:
    """'0.6, 0.8 0.85' -> [0.6, 0.8, 0.85]; 'start:stop:step' expands inclusively."""
    values: list[float] = []
    for token in _SPLIT_RE.split(text.strip()):
        if not token:
            continue
        if ":" in token:
            values.extend(_expand_range(token))
        else:
            values.append(_number(token, text))
    if not values:
        raise ProjectError(f"No values given in {text!r}")
    if len(values) > MAX_LIST_VALUES:
        raise ProjectError(f"{len(values)} values given; a list takes at most {MAX_LIST_VALUES}")
    return values


def _back_to_template(key: str) -> str:
    """How to return to the template's value; worded for the web UI and the CLI alike."""
    return f"remove the setting to go back to the template value (CLI: --unset {key})"


def parse_key_value(text: str) -> tuple[str, str]:
    """'cfl_number=5' -> ('CFL_NUMBER', '5')."""
    key, sep, value = text.partition("=")
    key = key.strip().upper()
    if not sep or not key:
        raise ProjectError(f"{text!r} must look like KEY=VALUE")
    value = value.strip()
    if not value:
        raise ProjectError(f"{text!r} has no value; {_back_to_template(key)}")
    return key, value


def _check_key(key: str) -> str:
    key = key.strip().upper()
    if not _KEY_RE.fullmatch(key):
        raise ProjectError(f"{key!r} is not a valid SU2 option name")
    if key in CASE_KEYS:
        raise ProjectError(f"{key} is set per case by the sweep and the mesh; change the sweep or mesh instead")
    return key


def set_parameter(settings: Settings, key: str, value: str) -> None:
    """MARKER_* keys set (or with value 'none' remove) a marker line; other keys become overrides."""
    key = _check_key(key)
    value = value.strip()
    if not value:
        raise ProjectError(f"{key} needs a value; {_back_to_template(key)}")
    if key.startswith(MARKER_PREFIX):
        settings.markers[key] = None if value.lower() == REMOVE_WORD else value
    elif value.lower() == REMOVE_WORD:
        raise ProjectError(f"Only MARKER_ lines can be removed; {_back_to_template(key)}")
    else:
        settings.overrides[key] = value


def unset_parameter(settings: Settings, key: str) -> None:
    """Forget a marker or override so the template's line applies again."""
    key = key.strip().upper()
    found = key in settings.markers or key in settings.overrides
    settings.markers.pop(key, None)
    settings.overrides.pop(key, None)
    if not found:
        raise ProjectError(f"{key} is not set in this project")


KEEP: Any = object()  # set_freestream: leave this field as it is


def rebuild_if_changed(project: Project) -> bool:
    """Rebuild the cases when their names or altitudes would change (an empty Mach sweep stays empty);
    returns whether they were rebuilt."""
    if not project.cases and project.sweep.enabled and not project.sweep.mach:
        return False
    rebuilt = build_cases(project)
    if [(c.name, c.altitude_km) for c in rebuilt] == [(c.name, c.altitude_km) for c in project.cases]:
        return False
    project.cases = rebuilt
    return True


def set_freestream(project: Project, *, mode: Any = KEEP, altitude_km: Any = KEEP,
                   reynolds_length: Any = KEEP) -> bool:
    """Change how configs get their freestream (None clears a number); `altitude_km` is the single case's
    altitude (a sweep's are its altitudes_km). Rebuilds the cases when their names or altitudes change.
    Returns whether anything changed."""
    fs = project.settings.freestream
    if mode is not KEEP and mode not in ("manual", "altitude"):
        raise ProjectError(f"Freestream mode must be 'manual' or 'altitude', not {mode!r}")
    for what, value in (("Altitude", altitude_km), ("Reynolds length", reynolds_length)):
        if value is not KEEP and value is not None and not math.isfinite(value):
            raise ProjectError(f"{what} must be a number")
    before = (fs.mode, fs.altitude_km, fs.reynolds_length)
    if mode is not KEEP:
        fs.mode = mode
    if altitude_km is not KEEP:
        fs.altitude_km = altitude_km
    if reynolds_length is not KEEP:
        fs.reynolds_length = reynolds_length
    rebuild_if_changed(project)
    return (fs.mode, fs.altitude_km, fs.reynolds_length) != before


def update_sweep(
    project: Project,
    *,
    mach: Optional[list[float]] = None,
    alpha: Optional[list[float]] = None,
    beta: Optional[list[float]] = None,
    altitude: Optional[str] = None,
    base_name: Optional[str] = None,
    altitudes_km: Optional[list[float]] = None,
) -> bool:
    """Apply the given sweep fields; rebuild the cases when anything changed."""
    if mach is not None and any(m <= 0 for m in mach):
        raise ProjectError("Mach numbers must be greater than 0")
    if altitudes_km is not None and not all(math.isfinite(a) for a in altitudes_km):
        raise ProjectError("Altitudes must be numbers")
    if altitude is not None and project.settings.freestream.mode == "altitude":
        raise ProjectError("The altitude label follows the altitudes in altitude mode "
                           "(set them on the Sweep page, or with --altitude-km)")
    for text, what in ((altitude, "The altitude label"), (base_name, "The base name")):
        problem = name_part_problem(text, what) if text else None  # empty: left out of the names
        if problem:
            raise ProjectError(problem)
    sweep = project.sweep
    changed = False
    for field, value in (("mach", mach), ("alpha", alpha), ("beta", beta), ("altitudes_km", altitudes_km)):
        if value is not None:
            setattr(sweep, field, list(value))
            changed = True
    if altitude is not None:
        sweep.altitude = altitude
        changed = True
    if base_name is not None:
        sweep.naming.base_name = base_name
        changed = True
    if changed:
        project.cases = build_cases(project)
    return changed


def set_altitudes(project: Project, altitudes_km: list[float]) -> bool:
    """The altitudes the cases run at: the sweep's list with the sweep on, else the single case's one."""
    if project.sweep.enabled:
        return update_sweep(project, altitudes_km=altitudes_km)
    if len(altitudes_km) != 1:
        raise ProjectError("A single case has one altitude; switch the sweep on to run several")
    return set_freestream(project, altitude_km=altitudes_km[0])

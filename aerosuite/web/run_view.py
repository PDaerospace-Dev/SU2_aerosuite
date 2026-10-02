"""The Run page's rules without NiceGUI: its layout by study size, groups, status counts, durations, time left."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ..engine.jobs.overview import NOT_RUN
from ..engine.naming import format_value

GROUPS_FROM = 13  # fewer cases are listed plainly
STATUS_ORDER = ("CONVERGED", "RUNNING", "PENDING", NOT_RUN, "UNCONVERGED", "FAILED", "CANCELLED")
ATTENTION = {"RUNNING", "UNCONVERGED", "FAILED"}  # a group holding one of these starts open


@dataclass(frozen=True)
class Group:
    label: str  # "Mach 1.5 · 10 km"
    names: list  # its cases, in case order


def case_groups(cases: Sequence) -> list[Group]:
    """The cases by Mach and altitude, groups in the order their first case comes."""
    found: dict[tuple, list] = {}
    for case in cases:
        found.setdefault((case.mach, case.altitude_km), []).append(case.name)
    return [Group(f"Mach {format_value(mach)}" + ("" if altitude is None else f" · {format_value(altitude)} km"), names)
            for (mach, altitude), names in found.items()]


def layout(cases: Sequence) -> str:
    """"none", "single" (a case card), "list" (a plain table) or "groups" (the table folded by Mach and altitude)."""
    if not cases:
        return "none"
    if len(cases) == 1:
        return "single"
    return "groups" if len(cases) >= GROUPS_FROM and len(case_groups(cases)) > 1 else "list"


def status_counts(rows: Sequence) -> list[tuple[str, int]]:
    """(status, how many) for the statuses present, in STATUS_ORDER."""
    statuses = [row.status for row in rows]
    return [(status, statuses.count(status)) for status in STATUS_ORDER if status in statuses]


def duration_text(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    return f"{minutes} min" + (f" {secs} s" if secs else "")


def time_left(elapsed: float, finished: int, total: int) -> Optional[float]:
    """A rough guess: the cases still to go at the average time of those finished; None before the first ends."""
    if finished <= 0:
        return None
    return elapsed / finished * max(0, total - finished)


def _option(text: str, key: str) -> Optional[str]:
    match = re.search(rf"^\s*{key}\s*=\s*([^\s%]+)", text, re.MULTILINE)
    return match.group(1) if match else None


def case_conditions(config: str, mesh: Optional[str]) -> list[tuple[str, str]]:
    """What a single case will run, read from its rendered config: (label, value), missing ones left out."""
    solver, turbulence = _option(config, "SOLVER"), _option(config, "KIND_TURB_MODEL")
    if solver and turbulence and turbulence.upper() != "NONE":
        solver = f"{solver} · {turbulence}"
    items = [("Solver", solver), ("Mach", _option(config, "MACH_NUMBER")), ("α (deg)", _option(config, "AOA")),
             ("β (deg)", _option(config, "SIDESLIP_ANGLE")), ("Iterations (max)", _option(config, "ITER")),
             ("Mesh", Path(mesh).name if mesh else None)]
    return [(label, value) for label, value in items if value]

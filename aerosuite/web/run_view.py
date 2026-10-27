"""The Run page's rules without NiceGUI: its layout by study size, groups, status counts, durations, time left."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ..engine.jobs.overview import NOT_RUN
from ..engine.naming import format_value

GROUPS_FROM = 13  # fewer cases are listed plainly
STATUS_ORDER = ("CONVERGED", "RUNNING", "PENDING", NOT_RUN, "UNCONVERGED", "FAILED", "BLOCKED", "CANCELLED")
ATTENTION = {"RUNNING", "UNCONVERGED", "FAILED", "BLOCKED"}  # a group holding one of these starts open


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


# -- the board and the list by state ---------------------------------------------------------------------------

_ALTITUDE_RE = re.compile(r"^(\d+)(?:p(\d+))?km$", re.IGNORECASE)


@dataclass(frozen=True)
class NamedCase:
    """A case known only by its name (still in a running job, no longer in the sweep): what the name says."""
    name: str
    mach: float
    alpha: float
    beta: float
    altitude_km: Optional[float]


def case_from_name(name: str) -> Optional[NamedCase]:
    """Mach, α, β and altitude read back from a case name; None without a Mach and an α."""
    from ..engine.naming import parse_case_name
    parsed = parse_case_name(name)
    if parsed.mach is None or parsed.alpha is None:
        return None
    altitude = None
    for token in name.split("_"):
        match = _ALTITUDE_RE.match(token)
        if match:
            altitude = float(match[1] + ("." + match[2] if match[2] else ""))
    return NamedCase(name, parsed.mach, parsed.alpha, parsed.beta or 0.0, altitude)

COMPACT_FROM = 40  # more cases show as compact tiles


@dataclass(frozen=True)
class BoardSection:
    key: str  # "10|0": altitude and β, for folding
    label: str  # "10 km", "10 km · β 2°", or "" for a sweep at one altitude and β
    machs: list  # the rows, ascending
    alphas: list  # the columns, ascending
    cells: dict  # (mach, alpha) -> case name


def board_sections(cases: Sequence) -> list[BoardSection]:
    """The cases as grids, one per altitude (and β, when β is swept): Mach down, α across."""
    betas = sorted({case.beta for case in cases})
    found: dict[tuple, dict] = {}
    for case in cases:
        found.setdefault((case.altitude_km, case.beta), {})[(case.mach, case.alpha)] = case.name
    sections = []
    for (altitude, beta), cells in sorted(found.items(), key=lambda item: (item[0][0] or 0, item[0][1])):
        parts = [f"{format_value(altitude)} km"] if altitude is not None else []
        if len(betas) > 1:
            parts.append(f"β {format_value(beta)}°")
        sections.append(BoardSection(
            f"{'' if altitude is None else format_value(altitude)}|{format_value(beta)}", " · ".join(parts),
            sorted({mach for mach, _ in cells}), sorted({alpha for _, alpha in cells}), cells))
    return sections


def has_board(cases: Sequence) -> bool:
    """Whether the cases make a grid worth drawing as one: some altitude has at least two Machs and two αs."""
    return any(len(section.machs) > 1 and len(section.alphas) > 1 for section in board_sections(cases))


TILE_WORDS = {"CONVERGED": "Converged", "UNCONVERGED": "Unconverged", "RUNNING": "Running", "PENDING": "Queued",
              "FAILED": "Failed", "BLOCKED": "Blocked", "CANCELLED": "Cancelled", NOT_RUN: "Not run"}


def tile_text(status: str, iterations: Optional[int] = None, place: Optional[int] = None) -> str:
    """A tile's small line: ✓ and the iterations, the iterations so far, the place in the queue, or the outcome."""
    if status == "CONVERGED":
        return f"✓ {iterations} it" if iterations else "✓"
    if status in ("UNCONVERGED", "RUNNING", "CANCELLED") and iterations:
        return f"{iterations} it"
    if status == "PENDING" and place:
        return f"#{place}"
    if status in ("FAILED", "BLOCKED"):
        return "! " + TILE_WORDS[status].lower()
    return "—" if status == NOT_RUN else TILE_WORDS.get(status, status).lower()


# (key, title, the statuses it holds); the list shows them in this order
STATE_SECTIONS = [
    ("running", "Running now", {"RUNNING"}),
    ("queued", "Queued", {"PENDING"}),
    ("attention", "Needs a look", {"FAILED", "BLOCKED", "UNCONVERGED", "CANCELLED"}),
    ("not-run", "Not run yet", {NOT_RUN}),
    ("done", "Done", {"CONVERGED"}),
]


def state_sections(rows: Sequence) -> list[tuple[str, str, list]]:
    """(key, title, its rows) for the sections that have rows, failed ones first within Needs a look."""
    order = {"FAILED": 0, "BLOCKED": 1, "UNCONVERGED": 2, "CANCELLED": 3}
    out = []
    for key, title, statuses in STATE_SECTIONS:
        members = [row for row in rows if row.status in statuses]
        if key == "attention":
            members.sort(key=lambda row: order.get(row.status, 9))
        if members:
            out.append((key, title, members))
    return out

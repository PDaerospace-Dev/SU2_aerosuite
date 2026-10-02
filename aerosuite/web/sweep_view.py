"""The Sweep page's rules without NiceGUI: short value text, the restart rule and the cases set differently."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

from ..engine.naming import format_value

RANGE_FROM = 4  # evenly spaced values read as start:stop:step from this many
RULES = ("none", "previous", "custom")  # ties go to the earlier one


def values_text(values: Sequence[float]) -> str:
    """A sweep list as its field shows it: "-10:20:2" when evenly spaced (it reads back the same), else the
    values."""
    if len(values) >= RANGE_FROM:
        step = round(values[1] - values[0], 10)
        if step > 0 and all(abs(values[i + 1] - values[i] - step) < 1e-9 for i in range(len(values) - 1)):
            return f"{format_value(values[0])}:{format_value(values[-1])}:{format_value(step)}"
    return ", ".join(format_value(v) for v in values)


def rule_restarts(cases: Sequence, rule: str, folder: Optional[str] = None) -> list[tuple[str, Optional[str]]]:
    """Each case's (restart, restart_ref) under a rule for the whole sweep.

    "previous" leaves the first case, and the first case of each altitude, at "none" (each altitude starts
    fresh); "custom" points each case at `folder / <case name>`, e.g. another study's runs/ folder.
    """
    out = []
    for index, case in enumerate(cases):
        first_of_altitude = index == 0 or case.altitude_km != cases[index - 1].altitude_km
        if rule == "previous" and first_of_altitude:
            out.append(("none", None))
        elif rule == "custom":
            out.append(("custom", str(Path(folder) / case.name) if folder else None))
        else:
            out.append((rule, None))
    return out


def _custom_folder(cases: Sequence) -> Optional[str]:
    """The folder most custom restarts sit in as `folder / <case name>`."""
    parents = Counter(str(Path(case.restart_ref).parent) for case in cases
                      if case.restart == "custom" and case.restart_ref and Path(case.restart_ref).name == case.name)
    return parents.most_common(1)[0][0] if parents else None


def detect_rule(cases: Sequence) -> tuple[str, Optional[str], list[str]]:
    """(rule, its folder for "custom", the cases set differently): the rule the most cases follow."""
    best: tuple = ("none", None, [])
    if not cases:
        return best
    folder = _custom_folder(cases)
    fewest = None
    for rule in RULES:
        if rule == "custom" and folder is None:
            continue
        expected = rule_restarts(cases, rule, folder)
        differing = [case.name for case, wanted in zip(cases, expected)
                     if (case.restart, case.restart_ref if case.restart == "custom" else None) != wanted]
        if fewest is None or len(differing) < fewest:
            fewest, best = len(differing), (rule, folder if rule == "custom" else None, differing)
    return best


def restart_text(cases: Sequence, index: int) -> str:
    case = cases[index]
    if case.restart == "previous":
        return f"continues from {cases[index - 1].name}" if index else "from scratch (no case before it)"
    if case.restart == "custom":
        return f"from {case.restart_ref}" if case.restart_ref else "from a file (not chosen)"
    return "from scratch"


def case_formula(machs: int, alphas: int, betas: int, altitudes: int) -> str:
    parts = [f"{machs} Mach"] + ([f"{altitudes} altitude{'' if altitudes == 1 else 's'}"] if altitudes else [])
    return " × ".join(parts + [f"{alphas} α", f"{betas} β"])

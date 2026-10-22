"""Rerun with changes: config settings for one job only (a lower CFL, a first-order start, more iterations), written
into that job's own copy of the case's config (jobs/plan.py), so the template and the other cases stay as they
are. The job record keeps them, so the Run page can show what a case last ran with and keep it."""
from __future__ import annotations

from typing import Mapping, Optional

from ..naming import format_value

FIRST_ORDER = {"MUSCL_FLOW": "NO", "MUSCL_TURB": "NO"}


def rerun_changes(cfl: Optional[float] = None, first_order: bool = False,
                  iterations: Optional[int] = None) -> dict[str, str]:
    """The config lines for a rerun: a CFL (fixed: adaptation off), a first-order start, a number of iterations."""
    changes: dict[str, str] = {}
    if cfl is not None:
        changes.update({"CFL_NUMBER": format_value(cfl), "CFL_ADAPT": "NO"})
    if first_order:
        changes.update(FIRST_ORDER)
    if iterations is not None:
        changes["ITER"] = str(iterations)
    return changes


def describe(changes: Mapping[str, str]) -> str:
    """'CFL 0.5 (fixed), first order, 3000 iterations'; other lines as KEY= value."""
    parts, rest = [], dict(changes)
    if "CFL_NUMBER" in rest:
        parts.append(f"CFL {rest.pop('CFL_NUMBER')}" + (" (fixed)" if rest.pop("CFL_ADAPT", None) == "NO" else ""))
    if rest.get("MUSCL_FLOW") == "NO":
        rest.pop("MUSCL_FLOW")
        rest.pop("MUSCL_TURB", None)
        parts.append("first order")
    if "ITER" in rest:
        parts.append(f"{rest.pop('ITER')} iterations")
    parts += [f"{key}= {value}" for key, value in rest.items()]
    return ", ".join(parts)

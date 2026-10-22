"""Why a case failed, in plain words, with what to try next: read from the end of its output (the job record's
failure tail), Slurm's verdict and, for a divergence, its history. Worked out when shown, so jobs recorded before
this read the same way."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..results import read_history
from ..su2_check import su2_message

_ITERATION_RE = re.compile(r"^\|\s*(\d+)\|")  # a row of SU2's screen table
_EXIT_RE = re.compile(r"(?:AEROSUITE_EXIT|SU2 exited with code)\s+(-?\d+)")
_LAUNCH_RE = re.compile(r"(srun: error.*|.*PMIX ERROR.*|.*command not found.*|.*cannot open shared object.*)")


@dataclass(frozen=True)
class Diagnosis:
    kind: str  # diverged, config, mesh, restart, su2, launch, time_limit, memory, node, cancelled, blocked, failed
    summary: str  # what happened, one line
    advice: str = ""  # what to try, one line


def last_iteration(text: str) -> Optional[int]:
    found = [int(match.group(1)) for match in map(_ITERATION_RE.match, text.splitlines()) if match]
    return found[-1] if found else None


def _at(text: str) -> str:
    iteration = last_iteration(text)
    return f" at iteration {iteration}" if iteration is not None else ""


def diagnose(tail: str, state: Optional[str] = None, time_limit: str = "") -> Diagnosis:
    """The failure in `tail` (a job record's failure tail: a first line from AeroSuite, then the output's end)."""
    state = (state or "").upper()
    first = next((line.strip() for line in tail.splitlines() if line.strip()), "")
    message = su2_message(tail) if "Error in " in tail else ""
    lowered = message.lower()
    if first.startswith("Not run:"):
        return Diagnosis("blocked", first.removeprefix("Not run: "), "Run it again: it starts from scratch now")
    if state == "CANCELLED" or first.startswith("Cancelled"):
        return Diagnosis("cancelled", first if first.startswith("Cancelled") else "Cancelled")
    if state == "TIMEOUT" or "DUE TO TIME LIMIT" in tail:
        limit = f" ({time_limit})" if time_limit else ""
        return Diagnosis("time_limit", f"Stopped at the time limit{limit}{_at(tail)}",
                         "Continue from its last solution, with a longer time limit")
    if state == "OUT_OF_MEMORY" or "oom-kill" in tail.lower() or "out of memory" in tail.lower():
        return Diagnosis("memory", "Ran out of memory", "Resubmit on a node with more memory, or with fewer tasks")
    if state in ("NODE_FAIL", "BOOT_FAIL"):
        return Diagnosis("node", "The node failed", "Resubmit: the case itself was fine")
    if "diverged" in lowered or "nan detected" in lowered:
        return Diagnosis("diverged", f"Diverged{_at(tail)} (SU2 found NaN)",
                         "Rerun with a lower CFL or a first-order start, from its last solution")
    if message and ("mesh file" in lowered or "grid file" in lowered) and ("not found" in lowered
                                                                           or "could not" in lowered):
        return Diagnosis("mesh", f"SU2 couldn't read the mesh: {message}", "Check the mesh on Setup")
    if message and ("restart" in lowered or "solution file" in lowered):
        return Diagnosis("restart", f"The restart solution didn't fit: {message}",
                         "Start from scratch, or choose another solution")
    if message and ("CConfig" in tail or "invalid option" in lowered):
        return Diagnosis("config", f"SU2 rejected the config: {message}", "Change it in the config, then submit again")
    if message:
        return Diagnosis("su2", f"SU2 stopped: {message}")
    if "SU2 Project Website" not in tail and "Release" not in tail:
        launch = next((match.group(1).strip() for match in map(_LAUNCH_RE.match, tail.splitlines()) if match), None)
        if launch:
            return Diagnosis("launch", f"SU2 didn't start: {launch}",
                             "Check the module line and the launch command in Settings")
    codes = _EXIT_RE.findall(tail)
    if codes:
        return Diagnosis("failed", f"SU2 exited with code {codes[-1]}{_at(tail)}")
    return Diagnosis("failed", first or "Failed")


@lru_cache(maxsize=64)
def _trend(path: str, modified: float) -> str:
    try:
        df = read_history(Path(path))
    except Exception:  # a history being written, or not one: no trend
        return ""
    column = next((c for c in df.columns if str(c).startswith("rms[")), None)
    if column is None or len(df) < 20:
        return ""
    values = df[column].astype(float)
    best = int(values.idxmin())
    last, lowest = values.iloc[-1], values.iloc[best]
    iteration = df.iloc[best, 0] if len(df.columns) else best
    if last > lowest + 0.5:
        return (f"the residuals were rising ({column} from 1e{lowest:.1f} at iteration {int(iteration)} to "
                f"1e{last:.1f})")
    quarter = values.iloc[-max(5, len(values) // 4):]
    if quarter.max() - quarter.min() < 0.3:
        return f"the residuals had stopped falling ({column} around 1e{last:.1f})"
    return ""


def residual_trend(history: Path) -> str:
    """How the residuals went before a divergence, in words ("" when nothing stands out)."""
    try:
        modified = history.stat().st_mtime
    except OSError:
        return ""
    return _trend(str(history), modified)

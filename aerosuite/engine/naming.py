"""Case naming: sweep values <-> case names, in one place.

Names are tokens joined by "_":
    Mach   M<int>p<frac>        0.85 -> M0p85, 1.0 -> M1p0
    alpha  a[n]<int>[p<frac>]   5 -> a5, -5 -> an5, 2.5 -> a2p5
    beta   b[n]<int>[p<frac>]   same rules as alpha
Whole numbers give the same names as AeroSuite v7, so old run folders still parse.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, NamedTuple, Optional

from .errors import GenerationError


_NAME_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_CASE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
NAME_CHARACTERS = "letters, digits, '.', '-' and '_'"


def name_part_problem(text: str, what: str) -> Optional[str]:
    """Why `text` cannot be part of a case name (a file and folder name), or None."""
    if _NAME_PART_RE.fullmatch(text):
        return None
    return f"{what} {text!r} can only use {NAME_CHARACTERS}, starting with a letter or digit"


def unsafe_names(names: Iterable[str]) -> list[str]:
    """The case names that cannot be file and folder names."""
    return [name for name in names if not _CASE_NAME_RE.fullmatch(name) or name in (".", "..")]


def format_value(value: float) -> str:
    """Shortest exact decimal text: 0.85 -> '0.85', 5.0 -> '5', -0.5 -> '-0.5'."""
    value = float(value)
    if value == 0:
        return "0"
    text = repr(value)
    if "e" in text:
        text = format(value, ".15f").rstrip("0").rstrip(".")
    if text.endswith(".0"):
        text = text[:-2]
    return text


def mach_token(mach: float) -> str:
    text = format_value(mach)
    if "." not in text:
        text += ".0"
    return "M" + text.replace(".", "p")


def angle_token(angle: float) -> str:
    """Angle token without its a/b prefix: 5 -> '5', -5 -> 'n5', 2.5 -> '2p5'."""
    text = format_value(abs(float(angle))).replace(".", "p")
    return "n" + text if float(angle) < 0 else text


def case_name(
    mach: float,
    alpha: float,
    beta: float,
    *,
    altitude: str = "",
    base_name: str = "",
    include_mach: bool = True,
    include_alpha: bool = True,
    include_beta: bool = True,
    include_altitude: bool = True,
    include_base: bool = True,
) -> str:
    parts = []
    if include_mach:
        parts.append(mach_token(mach))
    if include_altitude and altitude:
        parts.append(altitude.lower())
    if include_alpha:
        parts.append("a" + angle_token(alpha))
    if include_beta:
        parts.append("b" + angle_token(beta))
    if include_base and base_name:
        parts.append(base_name.lower())
    if not parts:
        raise GenerationError("At least one naming component must be included in case names")
    return "_".join(parts)


class ParsedName(NamedTuple):
    mach: Optional[float]
    alpha: Optional[float]
    beta: Optional[float]


_MACH_RE = re.compile(r"^m(\d+)(?:[p.](\d+))?$", re.IGNORECASE)
# Accepts a2p5 / an5 / a-5 (current) and legacy a5m / a5p sign suffixes.
_ANGLE_RE = re.compile(
    r"^(?P<neg>n|-)?(?P<int>\d+)(?:[p.](?P<frac>\d+))?(?P<sfx>[mp])?$", re.IGNORECASE
)


def parse_angle(body: str) -> Optional[float]:
    match = _ANGLE_RE.match(body)
    if not match:
        return None
    value = float(match["int"] + ("." + match["frac"] if match["frac"] else ""))
    negative = bool(match["neg"]) or (match["sfx"] or "").lower() == "m"
    return -value if negative else value


def parse_case_name(name: str) -> ParsedName:
    """Recover Mach/alpha/beta from a case name; missing parts are None."""
    if name.lower().endswith(".cfg"):
        name = name[:-4]
    mach = alpha = beta = None
    for token in name.split("_"):
        if mach is None and (match := _MACH_RE.match(token)):
            mach = float(match[1] + ("." + match[2] if match[2] else ""))
            continue
        head, body = token[:1].lower(), token[1:]
        if alpha is None and head == "a":
            alpha = parse_angle(body)
        elif beta is None and head == "b":
            beta = parse_angle(body)
    return ParsedName(mach, alpha, beta)


def find_collisions(names: Iterable[str]) -> list[str]:
    """Names that occur more than once, sorted."""
    counts = Counter(names)
    return sorted(name for name, count in counts.items() if count > 1)

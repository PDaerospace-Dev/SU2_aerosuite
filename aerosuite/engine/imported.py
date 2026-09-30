"""Existing SU2 runs, one folder per case (its .cfg and history), read into a read-only study.

A case's values come from its .cfg (what SU2 ran) and from its folder name; where both give one, the cfg wins and
the difference is reported. Names are read part by part (split at "_"), in any order:
    M2p5 Mach · 30km / 11000m / sl altitude · a50, an4, a2p5, a5m α · b6 β · T200K temperature · the rest: base name
Nothing in the source folders is ever written.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .errors import ProjectError
from .naming import parse_angle, format_value

HISTORY_SUFFIXES = (".csv", ".dat")
_NUMBER = r"(\d+)(?:[p.](\d+))?"
_MACH_RE = re.compile(rf"^m{_NUMBER}$", re.IGNORECASE)
_ALTITUDE_RE = re.compile(rf"^{_NUMBER}(km|m)$", re.IGNORECASE)
_TEMPERATURE_RE = re.compile(rf"^t{_NUMBER}k$", re.IGNORECASE)
# cfg option -> the value it gives
CFG_VALUES = {"MACH_NUMBER": "mach", "AOA": "alpha", "SIDESLIP_ANGLE": "beta", "FREESTREAM_TEMPERATURE": "temperature_K"}
_RELATIVE = 1e-6  # name and cfg agree within this


def _number(match: re.Match) -> float:
    return float(match.group(1) + ("." + match.group(2) if match.group(2) else ""))


@dataclass(frozen=True)
class NameValues:
    mach: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    altitude_km: Optional[float] = None
    temperature_K: Optional[float] = None
    base: str = ""


def read_name(name: str) -> NameValues:
    """The values a folder name carries; each kind is read once, unrecognised parts form the base name."""
    values: dict[str, float] = {}
    base = []
    for part in name.split("_"):
        head, body = part[:1].lower(), part[1:]
        if "mach" not in values and (match := _MACH_RE.match(part)):
            values["mach"] = _number(match)
        elif "altitude_km" not in values and part.lower() == "sl":
            values["altitude_km"] = 0.0
        elif "altitude_km" not in values and (match := _ALTITUDE_RE.match(part)):
            metres = match.group(3).lower() == "m"
            values["altitude_km"] = _number(match) / 1000 if metres else _number(match)
        elif "temperature_K" not in values and (match := _TEMPERATURE_RE.match(part)):
            values["temperature_K"] = _number(match)
        elif head in ("a", "b") and ("alpha" if head == "a" else "beta") not in values and body \
                and (angle := parse_angle(body)) is not None:
            values["alpha" if head == "a" else "beta"] = angle
        else:
            base.append(part)
    return NameValues(base="_".join(base), **values)


@dataclass(frozen=True)
class Disagreement:
    option: str  # the cfg option, e.g. MACH_NUMBER
    cfg_value: float  # used
    name_value: float  # what the folder name said


@dataclass(frozen=True)
class FoundCase:
    name: str
    folder: Path
    cfg: Optional[Path]
    history: Path
    mach: float
    alpha: float
    beta: float
    altitude_km: Optional[float]
    temperature_K: Optional[float]
    base: str
    disagreements: tuple = ()


@dataclass(frozen=True)
class Skipped:
    name: str
    reason: str


def _cfg_values(text: str) -> dict[str, Union[float, str]]:
    values: dict = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Z_]+)\s*=\s*([^%]*?)\s*(?:%.*)?$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _float(text) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _choose_cfg(folder: Path) -> Union[Path, None, Skipped]:
    cfgs = sorted(folder.glob("*.cfg"))
    if not cfgs:
        return None
    own = folder / f"{folder.name}.cfg"
    if own in cfgs:
        return own
    if len(cfgs) == 1:
        return cfgs[0]
    with_mach = [c for c in cfgs if re.search(r"^\s*MACH_NUMBER\s*=", _read(c), re.MULTILINE)]
    if len(with_mach) == 1:
        return with_mach[0]
    return Skipped(folder.name, "several .cfg files, none named like the folder")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _history(folder: Path, cfg: dict) -> Optional[Path]:
    stem = Path(str(cfg.get("CONV_FILENAME") or "history")).name
    stem = stem[: -len(Path(stem).suffix)] if Path(stem).suffix in HISTORY_SUFFIXES else stem
    for suffix in HISTORY_SUFFIXES:
        if (folder / f"{stem}{suffix}").is_file():
            return folder / f"{stem}{suffix}"
    others = sorted(p for suffix in HISTORY_SUFFIXES for p in folder.glob(f"history*{suffix}") if p.is_file())
    return others[0] if others else None


def read_case(folder: Path) -> Union[FoundCase, Skipped]:
    folder = Path(folder)
    cfg_path = _choose_cfg(folder)
    if isinstance(cfg_path, Skipped):
        return cfg_path
    cfg = _cfg_values(_read(cfg_path)) if cfg_path else {}
    history = _history(folder, cfg)
    if history is None:
        return Skipped(folder.name, "no history file")
    from_name = read_name(folder.name)
    values = {"altitude_km": from_name.altitude_km}
    disagreements = []
    for option, key in CFG_VALUES.items():
        named = getattr(from_name, key)
        given = _float(cfg.get(option))
        if given is None:
            values[key] = named
            continue
        values[key] = given
        if named is not None and abs(given - named) > _RELATIVE * max(1.0, abs(given)):
            disagreements.append(Disagreement(option, given, named))
    if values["mach"] is None:
        return Skipped(folder.name, "no Mach (MACH_NUMBER in the .cfg or M… in the name)")
    if values["alpha"] is None:
        return Skipped(folder.name, "no α (AOA in the .cfg or a… in the name)")
    return FoundCase(name=folder.name, folder=folder.resolve(), cfg=cfg_path.resolve() if cfg_path else None,
                     history=history.resolve(), mach=values["mach"], alpha=values["alpha"],
                     beta=values["beta"] if values["beta"] is not None else 0.0,
                     altitude_km=values["altitude_km"], temperature_K=values["temperature_K"],
                     base=from_name.base, disagreements=tuple(disagreements))


@dataclass
class Scan:
    cases: list = field(default_factory=list)  # FoundCase, by folder name
    warnings: list = field(default_factory=list)  # grouped messages
    skipped: list = field(default_factory=list)  # Skipped


def scan(source: Path) -> Scan:
    """Every case folder directly inside `source` (hidden ones left out); identical warnings grouped."""
    source = Path(source)
    if not source.is_dir():
        raise ProjectError(f"{source} is not a folder")
    result = Scan()
    grouped: dict[tuple, list[str]] = {}
    for folder in sorted(p for p in source.iterdir() if p.is_dir() and not p.name.startswith(".")):
        found = read_case(folder)
        if isinstance(found, Skipped):
            result.skipped.append(found)
            continue
        result.cases.append(found)
        for d in found.disagreements:
            grouped.setdefault((d.option, d.cfg_value, d.name_value), []).append(found.name)
    for (option, cfg_value, name_value), names in grouped.items():
        who = names[0] if len(names) == 1 else f"{len(names)} cases ({names[0]}, …)"
        used = format_value(cfg_value)
        result.warnings.append(f"{who}: the cfg's {option} is {used}, the name says {format_value(name_value)} — "
                               f"{used} used")
    return result

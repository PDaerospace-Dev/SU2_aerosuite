"""Freestream from an ISA altitude: each case's temperature and Reynolds number from its own Mach."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .atmosphere import ISACalculator
from .errors import ProjectError
from .models import Freestream, Project, Settings
from .naming import format_value

FREESTREAM_KEYS = ("FREESTREAM_TEMPERATURE", "REYNOLDS_NUMBER", "REYNOLDS_LENGTH")
ALTITUDE_MIN_KM, ALTITUDE_MAX_KM = 0.0, 100.0


@dataclass(frozen=True)
class FreestreamValues:
    temperature_K: float
    reynolds: float
    reynolds_length: float


@dataclass(frozen=True)
class CaseFreestream:
    name: str
    mach: float  # the Mach the case runs at
    values: Optional[FreestreamValues]  # None when they cannot be computed
    error: str  # why not; "" when values is set


def altitude_label(altitude_km: float) -> str:
    """The case-name label for an altitude, written like Mach: 11 -> '11km', 10.5 -> '10p5km'."""
    return format_value(altitude_km).replace(".", "p") + "km"


def naming_altitude(project: Project) -> str:
    """The altitude label case names use: derived in altitude mode once an altitude is set, else typed."""
    fs = project.settings.freestream
    if fs.mode == "altitude" and fs.altitude_km is not None:
        return altitude_label(fs.altitude_km)
    return project.sweep.altitude


def freestream_setup_errors(fs: Freestream) -> list[str]:
    """What stops altitude mode from computing anything (the same for every case)."""
    errors = []
    if fs.altitude_km is None:
        errors.append("Freestream from altitude needs an altitude (0–100 km)")
    elif not math.isfinite(fs.altitude_km) or not ALTITUDE_MIN_KM <= fs.altitude_km <= ALTITUDE_MAX_KM:
        errors.append(f"Altitude {format_value(fs.altitude_km)} km is outside the standard atmosphere (0–100 km)")
    if fs.reynolds_length is None or not fs.reynolds_length > 0:
        errors.append("Freestream from altitude needs a Reynolds length greater than 0")
    return errors


def freestream_values(fs: Freestream, mach: float) -> FreestreamValues:
    """ISA temperature and the Reynolds number at `mach`; ProjectError when they cannot be computed."""
    errors = freestream_setup_errors(fs)
    if errors:
        raise ProjectError(errors[0])
    if not mach > 0:
        raise ProjectError(f"Mach {format_value(mach)} gives no Reynolds number; the Mach must be greater than 0")
    isa = ISACalculator.calculate(fs.altitude_km, mach, fs.reynolds_length)
    return FreestreamValues(isa["temperature"], isa["reynolds_number"], fs.reynolds_length)


def freestream_for(settings: Settings, mach: float) -> Optional[dict[str, str]]:
    """The per-case config lines in altitude mode (None in manual mode)."""
    if settings.freestream.mode != "altitude":
        return None
    values = freestream_values(settings.freestream, mach)
    return {
        "FREESTREAM_TEMPERATURE": format_value(round(values.temperature_K, 3)),
        "REYNOLDS_NUMBER": format_value(round(values.reynolds)),
        "REYNOLDS_LENGTH": format_value(values.reynolds_length),
    }

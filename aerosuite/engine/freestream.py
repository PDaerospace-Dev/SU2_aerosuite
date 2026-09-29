"""Freestream from an ISA altitude: each case's temperature and Reynolds number from its own altitude and Mach."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .atmosphere import ISACalculator
from .errors import ProjectError
from .models import Case, Freestream, Project, Settings
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
    altitude_km: Optional[float] = None  # the altitude the case runs at


_FROM_SETTINGS = object()  # freestream_values: use the freestream's own (single-case) altitude


def altitude_label(altitude_km: float) -> str:
    """The case-name label for an altitude, written like Mach: 11 -> '11km', 10.5 -> '10p5km'."""
    return format_value(altitude_km).replace(".", "p") + "km"


def sweeps_altitude(project: Project) -> bool:
    """Whether the cases take their altitudes from the sweep's list (altitude mode with the sweep on)."""
    return project.sweep.enabled and project.settings.freestream.mode == "altitude"


def case_altitude(project: Project, case: Case) -> Optional[float]:
    """The altitude a case runs at: its own in an altitude sweep, else the freestream's single altitude."""
    return case.altitude_km if project.sweep.enabled else project.settings.freestream.altitude_km


def label_for(project: Project, altitude_km: Optional[float]) -> str:
    """The altitude label a case name uses: derived in altitude mode from an altitude, else typed."""
    if project.settings.freestream.mode == "altitude" and altitude_km is not None:
        return altitude_label(altitude_km)
    return project.sweep.altitude


def naming_altitude(project: Project) -> str:
    """The altitude label(s) the case names use, for display: '0km, 11km' for an altitude sweep."""
    if sweeps_altitude(project) and project.sweep.altitudes_km:
        return ", ".join(altitude_label(a) for a in project.sweep.altitudes_km)
    if project.sweep.enabled:
        return project.sweep.altitude
    return label_for(project, project.settings.freestream.altitude_km)


def _altitude_error(altitude_km: Optional[float]) -> Optional[str]:
    if altitude_km is None:
        return "Freestream from altitude needs an altitude (0–100 km)"
    if not math.isfinite(altitude_km) or not ALTITUDE_MIN_KM <= altitude_km <= ALTITUDE_MAX_KM:
        return f"Altitude {format_value(altitude_km)} km is outside the standard atmosphere (0–100 km)"
    return None


def _length_error(fs: Freestream) -> Optional[str]:
    if fs.reynolds_length is None or not fs.reynolds_length > 0:
        return "Freestream from altitude needs a Reynolds length greater than 0"
    return None


def freestream_setup_errors(source) -> list[str]:
    """What stops altitude mode from computing values, each once: for a Project (every altitude it runs at),
    or for a Freestream alone (its single altitude)."""
    if isinstance(source, Project):
        fs = source.settings.freestream
        if sweeps_altitude(source):
            altitudes = list(dict.fromkeys(source.sweep.altitudes_km))
            errors = [] if altitudes else ["No altitudes in the sweep"]
        else:
            altitudes = [fs.altitude_km]
            errors = []
        errors += [e for e in map(_altitude_error, altitudes) if e]
    else:
        fs = source
        errors = [e for e in (_altitude_error(fs.altitude_km),) if e]
    length = _length_error(fs)
    return errors + ([length] if length else [])


def freestream_values(fs: Freestream, mach: float, altitude_km=_FROM_SETTINGS) -> FreestreamValues:
    """ISA temperature at the altitude (the freestream's own unless given) and the Reynolds number at `mach`;
    ProjectError when they cannot be computed."""
    if altitude_km is _FROM_SETTINGS:
        altitude_km = fs.altitude_km
    error = _altitude_error(altitude_km) or _length_error(fs)
    if error:
        raise ProjectError(error)
    if not mach > 0:
        raise ProjectError(f"Mach {format_value(mach)} gives no Reynolds number; the Mach must be greater than 0")
    isa = ISACalculator.calculate(altitude_km, mach, fs.reynolds_length)
    if round(isa["reynolds_number"]) < 1:  # the config writes it as a whole number
        raise ProjectError(f"The Reynolds number at {format_value(altitude_km)} km, Mach {format_value(mach)} and "
                           f"length {format_value(fs.reynolds_length)} m is below 1; check the altitude and length")
    return FreestreamValues(isa["temperature"], isa["reynolds_number"], fs.reynolds_length)


def freestream_for(settings: Settings, mach: float, altitude_km=_FROM_SETTINGS) -> Optional[dict[str, str]]:
    """The per-case config lines in altitude mode (None in manual mode)."""
    if settings.freestream.mode != "altitude":
        return None
    values = freestream_values(settings.freestream, mach, altitude_km)
    return {
        "FREESTREAM_TEMPERATURE": format_value(round(values.temperature_K, 3)),
        "REYNOLDS_NUMBER": format_value(round(values.reynolds)),
        "REYNOLDS_LENGTH": format_value(values.reynolds_length),
    }

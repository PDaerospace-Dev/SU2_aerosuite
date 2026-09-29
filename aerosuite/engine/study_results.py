"""A study's results for the Results page: averaged parameters, derived values and characteristic values."""
from __future__ import annotations

import re
from typing import Optional, Union

from .atmosphere import ISACalculator
from .cfg import case_mach
from .formula import Missing
from .freestream import altitude_error, case_altitude
from .models import Case, Project

ISA_NAMES = ("rho_inf", "p_inf", "T_inf", "V_inf", "q_inf")
CONSTANT_NAMES = ("S_ref", "L_ref") + ISA_NAMES
_ISA_KEYS = {"rho_inf": "density", "p_inf": "pressure", "T_inf": "temperature", "V_inf": "true_airspeed",
             "q_inf": "dynamic_pressure"}


def _template_number(template: str, key: str) -> Optional[float]:
    match = re.search(rf"^\s*{key}\s*=\s*([^\s%]+)", template, re.MULTILINE)
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None


def study_constants(project: Project, case: Case, template: str) -> dict[str, Union[float, Missing]]:
    """S_ref and L_ref (the reference settings, else the template), and with the freestream from altitude the
    ISA density, pressure, temperature, airspeed and dynamic pressure at the case's altitude and Mach."""
    ref = project.settings.reference
    values: dict[str, Union[float, Missing]] = {}
    for name, setting, key, what in (("S_ref", ref.ref_area, "REF_AREA", "area"),
                                     ("L_ref", ref.ref_length, "REF_LENGTH", "length")):
        value = setting if setting is not None else _template_number(template, key)
        values[name] = value if value is not None else Missing(f"no reference {what} ({key})")
    if project.settings.freestream.mode != "altitude":
        values.update({name: Missing(f"{name} needs the freestream from altitude") for name in ISA_NAMES})
        return values
    altitude = case_altitude(project, case)
    error = altitude_error(altitude)
    if error:
        values.update({name: Missing(error) for name in ISA_NAMES})
        return values
    isa = ISACalculator.calculate(altitude, case_mach(project, case, template), 1.0)
    values.update({name: isa[key] for name, key in _ISA_KEYS.items()})
    return values

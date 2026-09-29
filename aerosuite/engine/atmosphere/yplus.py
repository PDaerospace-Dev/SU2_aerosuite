"""
y+ First Cell Height Calculator — core physics.

All correlations and logic ported directly from cfd_yplus_calculator.py.
"""

import math
from typing import Dict, Tuple


# ── Skin-friction correlations ────────────────────────────────────────────────

def _cf_laminar_external(Re: float) -> float:
    """Blasius flat-plate (laminar external): Cf = 0.664 / Re^0.5"""
    return 0.664 / math.sqrt(Re)


def _cf_turbulent_external(Re: float) -> float:
    """Schlichting power-law (turbulent external): Cf = 0.027 / Re^(1/7)"""
    return 0.027 / (Re ** (1.0 / 7.0))


def _cf_laminar_internal(Re: float) -> float:
    """Hagen-Poiseuille (laminar pipe): Cf = 16 / Re"""
    return 16.0 / Re


def _cf_turbulent_internal(Re: float) -> float:
    """Petukhov correlation (turbulent pipe): Cf = (0.790·ln(Re) - 1.64)^-2"""
    return (0.790 * math.log(Re) - 1.64) ** -2


FORMULAS: Dict[Tuple[str, str], dict] = {
    ("Laminar", "External"): {
        "name":   "Blasius Flat-Plate (Laminar)",
        "latex":  "Cf = 0.664 / Re^(1/2)",
        "detail": "Valid for Re < 5×10⁵  |  Flat plate boundary layer",
        "fn":     _cf_laminar_external,
        "re_min": None,  # exclusive bounds of the formula's valid Reynolds range
        "re_max": 5e5,
    },
    ("Turbulent", "External"): {
        "name":   "Schlichting Power-Law (Turbulent)",
        "latex":  "Cf = 0.027 / Re^(1/7)",
        "detail": "Valid for 5×10⁵ < Re < 10⁷  |  Turbulent flat plate",
        "fn":     _cf_turbulent_external,
        "re_min": 5e5,
        "re_max": 1e7,
    },
    ("Laminar", "Internal"): {
        "name":   "Hagen-Poiseuille (Laminar Pipe)",
        "latex":  "Cf = 16 / Re",
        "detail": "Valid for Re < 2300  |  Fully-developed pipe/channel flow",
        "fn":     _cf_laminar_internal,
        "re_min": None,
        "re_max": 2300.0,
    },
    ("Turbulent", "Internal"): {
        "name":   "Petukhov Correlation (Turbulent Pipe)",
        "latex":  "Cf = (0.790·ln(Re) - 1.64)^-2",
        "detail": "Valid for 3000 < Re < 5×10⁶  |  Smooth pipe, Darcy-Weisbach",
        "fn":     _cf_turbulent_internal,
        "re_min": 3000.0,
        "re_max": 5e6,
    },
}


def detect_flow_regime(Re: float, domain_type: str) -> Tuple[str, str]:
    """
    Auto-detect Laminar or Turbulent from Re and domain type.

    Returns (flow_type, regime_label).
    """
    if domain_type == "External":
        if Re < 5e5:
            return "Laminar",   f"Laminar  (Re = {Re:,.0f} < 5×10⁵)"
        else:
            return "Turbulent", f"Turbulent  (Re = {Re:,.0f} ≥ 5×10⁵)"
    else:  # Internal
        if Re < 2300:
            return "Laminar",   f"Laminar  (Re = {Re:,.0f} < 2300)"
        elif Re < 4000:
            return "Turbulent", f"Transitional → Turbulent  (Re = {Re:,.0f}, 2300–4000)"
        else:
            return "Turbulent", f"Turbulent  (Re = {Re:,.0f} ≥ 4000)"


def compute_layers(y1: float, delta99: float) -> int:
    """Estimate number of prism layers to span delta99 with growth ratio 1.2."""
    growth = 1.2
    if y1 <= 0 or delta99 <= 0:
        return 10
    n = math.log(1 - (delta99 / y1) * (1 - growth)) / math.log(growth)
    return max(5, min(50, round(abs(n))))


def calculate(
    velocity:    float,
    density:     float,
    viscosity:   float,   # dynamic viscosity  [kg/(m·s)]
    length:      float,
    y_plus:      float,
    domain_type: str,     # "External" or "Internal"
) -> dict:
    """
    Compute first-cell height and related quantities for a target y+.

    Parameters
    ----------
    velocity    : free-stream / bulk velocity   [m/s]
    density     : fluid density                 [kg/m³]
    viscosity   : dynamic viscosity             [kg/(m·s)]
    length      : characteristic length         [m]
    y_plus      : target y+ value
    domain_type : "External" or "Internal"

    Returns
    -------
    dict with keys: Re, Cf, tau_w, u_tau, y1, y1_mm,
                    n_layers, formula, flow_type, regime_label,
                    in_range (Re inside the formula's valid range)
    """
    nu = viscosity / density
    Re = velocity * length / nu

    flow_type, regime_label = detect_flow_regime(Re, domain_type)
    formula = FORMULAS[(flow_type, domain_type)]

    Cf    = formula["fn"](Re)
    tau_w = 0.5 * Cf * density * velocity ** 2
    u_tau = math.sqrt(tau_w / density)
    y1    = y_plus * nu / u_tau

    # Boundary-layer thickness estimate for layer count
    if domain_type == "External":
        delta = (5.0 * length / math.sqrt(Re)) if flow_type == "Laminar" \
                else (0.37 * length / Re ** 0.2)
    else:
        delta = length / 2.0

    re_min, re_max = formula["re_min"], formula["re_max"]
    in_range = (re_min is None or Re > re_min) and (re_max is None or Re < re_max)

    return {
        "Re":           Re,
        "Cf":           Cf,
        "tau_w":        tau_w,
        "u_tau":        u_tau,
        "y1":           y1,
        "y1_mm":        y1 * 1000.0,
        "n_layers":     compute_layers(y1, delta * 0.3),
        "formula":      formula,
        "flow_type":    flow_type,
        "regime_label": regime_label,
        "in_range":     in_range,
    }

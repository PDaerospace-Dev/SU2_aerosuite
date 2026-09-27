"""y+ first cell height: a flat-plate estimate of the wall spacing for a target y+ (engine: atmosphere.yplus)."""
from __future__ import annotations

import math

from nicegui import ui

from ...engine.atmosphere import yplus as calculate
from ...engine.naming import format_value
from ..ui_kit import card, field, hint, result, sci
from . import CalcContext, Calculator

INPUTS = [  # (key, label, default)
    ("velocity", "Velocity (m/s)", 50.0),
    ("density", "Density (kg/m³)", 1.225),
    ("viscosity", "Dynamic viscosity (Pa·s)", 1.789e-5),
    ("length", "Characteristic length (m)", 1.0),
    ("y_plus", "Target y+", 1.0),
]


def first_cell_text(y1_m: float) -> str:
    return f"{y1_m * 1e6:.3g} µm" if y1_m < 1e-3 else f"{y1_m * 1e3:.3g} mm"


def _read(boxes: dict, label: dict) -> dict:
    """The inputs as positive numbers; ValueError with the message to show."""
    values = {}
    for key, box in boxes.items():
        text = (box.value or "").strip()
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{label[key]}: {text!r} is not a number") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label[key]} must be greater than 0")
        values[key] = value
    return values


def build(ctx: CalcContext) -> None:
    label = {key: text for key, text, _ in INPUTS}
    start = {key: ctx.handoff.get(key, default) for key, _, default in INPUTS}
    with card("y+ first cell height", "flat-plate estimate of the wall spacing for a target y+"):
        if ctx.handoff.get("source"):
            ui.label(ctx.handoff["source"]).classes("as-strip as-muted").mark("yplus-from")
        with ui.row().classes("items-center gap-3"):
            domain = ui.toggle(["External", "Internal"], value="External",
                               on_change=lambda _: recompute()).props("no-caps unelevated").mark("yplus-domain")
            hint("external: flow over a body · internal: duct or pipe")
        boxes = {}
        with ui.element("div").classes("as-grid-3"):
            for key, text, _ in INPUTS:
                boxes[key] = field(ui.input(text, value=f"{start[key]:.6g}", on_change=lambda _: recompute())).mark(
                    f"yplus-{key}")
        error = ui.label("").classes("as-error-text").mark("yplus-error")
        with ui.element("div").classes("as-grid-3"):
            out = {
                "first": result("First cell height", highlight=True).mark("yplus-first-cell"),
                "layers": result("Prism layers (to 0.3 δ)").mark("yplus-layers"),
                "re": result("Reynolds number").mark("yplus-re"),
                "cf": result("Skin friction Cf").mark("yplus-cf"),
                "tau": result("Wall shear τw (Pa)").mark("yplus-tau"),
                "utau": result("Friction velocity uτ (m/s)").mark("yplus-utau"),
            }
        with ui.column().classes("as-formula w-full"):
            formula = ui.label("").classes("as-strong").mark("yplus-formula")
            equation = ui.label("").classes("as-mono")
            detail = hint("")
            note = hint("").classes("as-hint-warning").mark("yplus-range-note")

    def recompute() -> None:
        try:
            v = _read(boxes, label)
            r = calculate(v["velocity"], v["density"], v["viscosity"], v["length"], v["y_plus"], domain.value)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            error.text = str(exc)
            for tile in out.values():
                tile.text = "—"
            note.set_visibility(False)
            return
        error.text = ""
        out["first"].text = first_cell_text(r["y1"])
        out["layers"].text = str(r["n_layers"])
        out["re"].text = sci(r["Re"])
        out["cf"].text = sci(r["Cf"])
        out["tau"].text = format_value(round(r["tau_w"], 3))
        out["utau"].text = format_value(round(r["u_tau"], 3))
        formula.text = r["formula"]["name"]  # the engine's name already says laminar or turbulent
        equation.text = r["formula"]["latex"]
        detail.text = r["formula"]["detail"]
        note.text = f"Re = {sci(r['Re'])} is outside this formula's valid range; treat the height as an estimate"
        note.set_visibility(not r["in_range"])

    recompute()


CALCULATOR = Calculator("yplus", "y+ first cell height", "wall spacing for a target y+", build)

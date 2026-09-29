"""ISA atmosphere: properties at an altitude, Apply to the project, and Send to y+."""
from __future__ import annotations

import math
from typing import Optional

from nicegui import ui

from ...engine.atmosphere import ISACalculator
from ...engine.cfg import read_template
from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ..template_edit import write_template_params
from ..ui_kit import card, field, primary_button, result, sci, secondary_button, table, td, th
from . import CalcContext, Calculator
from .isa_rules import ApplyPlan, apply_isa_settings, isa_prefill, plan_isa_apply

INPUTS = [("altitude", "Altitude (km)"), ("mach", "Mach"), ("length", "Characteristic length (m)")]
RESULTS = [  # (marker, label, engine key, format, highlight)
    ("isa-temperature", "Temperature", "temperature", lambda v: f"{format_value(round(v, 2))} K", True),
    ("isa-pressure", "Pressure", "pressure", lambda v: f"{format_value(round(v))} Pa", False),
    ("isa-density", "Density", "density", lambda v: f"{v:.4g} kg/m³", False),
    ("isa-sound", "Speed of sound", "speed_of_sound", lambda v: f"{format_value(round(v, 2))} m/s", False),
    ("isa-tas", "True airspeed", "true_airspeed", lambda v: f"{format_value(round(v, 2))} m/s", False),
    ("isa-q", "Dynamic pressure", "dynamic_pressure", lambda v: f"{format_value(round(v))} Pa", False),
    ("isa-mu", "Dynamic viscosity", "dynamic_viscosity", lambda v: f"{sci(v)} Pa·s", False),
    ("isa-re", "Reynolds number", "reynolds_number", sci, True),
]


def _short(name: str, limit: int = 24) -> str:
    """A project name short enough for a button; the full name is in the top bar and the dialog."""
    return name if len(name) <= limit else name[:limit - 1].rstrip("-_ ")


def _template(ctx: CalcContext) -> Optional[str]:
    if ctx.frame is None:
        return None
    try:
        return read_template(ctx.frame.session.directory, ctx.frame.session.project)
    except AeroSuiteError:
        return None


def build(ctx: CalcContext) -> None:
    project = ctx.frame.session.project if ctx.frame else None
    prefill = isa_prefill(project, _template(ctx) or "")
    start = {"altitude": prefill.altitude_km, "mach": prefill.mach, "length": prefill.length_m}
    state: dict = {"isa": None, "inputs": None}
    with card("ISA atmosphere", "International Standard Atmosphere, 0–100 km"):
        if prefill.note:
            ui.label(prefill.note).classes("as-strip as-muted").mark("isa-from")
        boxes = {}
        with ui.element("div").classes("as-grid-3"):
            for key, text in INPUTS:
                boxes[key] = field(ui.input(text, value=format_value(start[key]),
                                            on_change=lambda _: recompute())).mark(f"isa-{key}")
        error = ui.label("").classes("as-error-text").mark("isa-error")
        with ui.element("div").classes("as-grid-4"):
            tiles = {marker: result(text, highlight).mark(marker) for marker, text, _, _, highlight in RESULTS}
        with ui.row().classes("w-full justify-end items-center gap-2"):
            reason = ui.label("").classes("as-hint").mark("isa-apply-reason")
            secondary_button("Send to y+ →", on_click=lambda: send()).mark("isa-send-yplus")
            apply_button = None
            if ctx.frame is not None:
                apply_button = primary_button(f"Apply to {_short(project.name)}…", on_click=lambda: confirm()).mark(
                    "isa-apply")

    def read() -> tuple[float, float, float]:
        values = []
        for key, text in INPUTS:
            raw = (boxes[key].value or "").strip()
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(f"{text}: {raw!r} is not a number") from None
            if not math.isfinite(value):
                raise ValueError(f"{text}: {raw!r} is not a finite number")
            values.append(value)
        return values[0], values[1], values[2]

    def plan() -> Optional[ApplyPlan]:
        if ctx.frame is None or state["inputs"] is None:
            return None
        return plan_isa_apply(ctx.frame.session.project, _template(ctx), *state["inputs"])

    def recompute() -> None:
        try:
            altitude, mach, length = read()
            state["isa"] = ISACalculator.calculate(altitude, mach, length)
            state["inputs"] = (altitude, mach, length)
            error.text = ""
        except ValueError as exc:
            state["isa"], state["inputs"] = None, None
            error.text = str(exc)
        for marker, _, key, fmt, _ in RESULTS:
            tiles[marker].text = fmt(state["isa"][key]) if state["isa"] else "—"
        current = plan()
        blocked = current is None or current.kind == "blocked"
        if apply_button is not None:
            apply_button.set_enabled(not blocked)
        reason.text = current.reason if current is not None and current.kind == "blocked" else ""
        reason.set_visibility(bool(reason.text))

    def send() -> None:
        isa, inputs = state["isa"], state["inputs"]
        handoff = {} if isa is None else {
            "velocity": isa["true_airspeed"], "density": isa["density"], "viscosity": isa["dynamic_viscosity"],
            "length": inputs[2],
            "source": f"From ISA: {format_value(inputs[0])} km, Mach {format_value(inputs[1])}",
        }
        ctx.open("yplus", handoff)

    async def confirm() -> None:
        current = plan()
        if current is None or current.kind == "blocked":
            return
        with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
            ui.label(f"Apply ISA to {ctx.frame.session.project.name}?").classes("as-dialog-title")
            with table("minmax(10rem, 1.2fr) minmax(6rem, 1fr) minmax(6rem, 1fr)"):
                for heading in ("", "Now", "After"):
                    th(heading)
                for index, (what, old, new) in enumerate(current.changes):
                    td(what).mark(f"apply-change-{index}")
                    td(old).classes("as-muted")
                    td(new)
            if current.note:
                ui.label(current.note).classes("as-hint").mark("apply-note")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(False)).mark("apply-cancel")
                primary_button("Apply", on_click=lambda: dialog.submit(True)).mark("apply-confirm")
        confirmed = await dialog
        dialog.delete()
        if confirmed:
            _apply(ctx, current, state["inputs"])
            recompute()

    recompute()


def _apply(ctx: CalcContext, plan: ApplyPlan, inputs: tuple[float, float, float]) -> None:
    frame = ctx.frame
    altitude, _, length = inputs
    if plan.kind == "settings":
        message = frame.save(lambda p: apply_isa_settings(p, altitude, length))
    else:
        message = write_template_params(frame, plan.template_params)
    if message:
        ui.notify(message, type="negative")
    else:
        ui.notify(f"Applied ISA to {frame.session.project.name}", type="positive")


CALCULATOR = Calculator("isa", "ISA atmosphere", "T, p, ρ, μ, Re from altitude and Mach", build)

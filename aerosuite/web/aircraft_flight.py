"""The Aircraft page's Flight & air tab: Mach, AoA and β (a single case's from the template, a sweep's lists), and
the air they fly in: set by hand (one temperature and Reynolds number) or from altitude (ISA, per case)."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import case_freestream, read_template, settings_parameters, template_case_values
from ..engine.editing import parse_value_list, set_freestream, update_sweep
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.naming import format_value
from .aircraft_form import number_field
from .fields import text_field
from .layout import ProjectFrame, project_url
from .pages.sweep import sweep_summary
from .session import parse_optional_number
from .sweep_view import values_text
from .template_edit import write_template_params
from .ui_kit import hint, pascals, sci, stat

MODE_CHOICES = {"manual": "Set by hand", "altitude": "From altitude"}
MODE_HINTS = {
    "manual": "One temperature and Reynolds number for every case",
    "altitude": "Each case gets the ISA temperature and pressure of its altitude and its own Reynolds number",
}
# (template key, label, the sweep's list and the field's marker name)
CONDITIONS = (("MACH_NUMBER", "Mach", "mach"), ("AOA", "AoA α (deg)", "alpha"),
              ("SIDESLIP_ANGLE", "Sideslip β (deg)", "beta"))
LIST_PLACEHOLDER = "e.g. 0.6, 0.8  or  -4:12:2 (from:to:step)"


def flight_tab(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    """Build the tab; returns its redraw."""
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        ui.label("Air").classes("as-label")
        ui.toggle(MODE_CHOICES, value=frame.session.project.settings.freestream.mode,
                  on_change=lambda e: choose(e.value)).props(
            "no-caps unelevated dense toggle-color=primary").classes("as-toggle").style("flex: none").mark(
            "freestream-mode")
        mode_hint = hint("").mark("freestream-mode-hint")
    box = ui.column().classes("w-full gap-3")

    def both() -> None:
        render()
        after()

    def choose(mode: str) -> None:
        message = frame.save(lambda p: set_freestream(p, mode=mode), then=both)
        if message:
            ui.notify(message, type="negative")

    def number(label: str, name: str, value, placeholder: str) -> None:
        text_field(label, "" if value is None else format_value(value),
                   lambda text: frame.save(
                       lambda p: set_freestream(p, **{name: parse_optional_number(text, label)}), then=both),
                   mark=f"freestream-{name}", placeholder=placeholder)

    def render() -> None:
        # Plain synchronous rebuild: tests read these fields right after a change.
        box.clear()
        project = frame.session.project
        fs, sweep_on = project.settings.freestream, project.sweep.enabled
        mode_hint.text = MODE_HINTS[fs.mode]
        with box:
            with ui.element("div").classes("as-grid-3"):  # the flight condition, then the air it flies in
                if sweep_on:
                    _sweep_lists(frame, both)
                else:
                    _conditions(frame, both)
            with ui.element("div").classes("as-grid-3"):
                if fs.mode == "manual":
                    if sweep_on:
                        with ui.column().classes("gap-1"):
                            text_field("Altitude label", project.sweep.altitude,
                                       lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()),
                                                               then=both),
                                       mark="sweep-altitude", placeholder="in the case names, e.g. sl")
                    for label, name in (("Temperature (K)", "temperature_K"), ("Reynolds number", "reynolds"),
                                        ("Reynolds length", "reynolds_length")):
                        with ui.column().classes("gap-1"):
                            number_field(frame, hints, label, "freestream", name, "float", both)
                else:
                    with ui.column().classes("gap-1"):
                        if sweep_on:
                            text_field("Altitudes (km)", values_text(project.sweep.altitudes_km),
                                       lambda text: frame.save(lambda p: update_sweep(
                                           p, altitudes_km=parse_value_list(text) if text.strip() else []),
                                           then=both),
                                       mark="sweep-altitudes", placeholder="e.g. 0, 5, 11  or  0:12:3")
                        else:
                            number("Altitude (km)", "altitude_km", fs.altitude_km, "ISA, 0–100 km")
                    with ui.column().classes("gap-1"):
                        number("Reynolds length (m)", "reynolds_length", fs.reynolds_length,
                               "for the Reynolds number")
            if sweep_on:
                with ui.column().classes("w-full gap-2").mark("flight-sweep-summary"):
                    sweep_summary(frame)
                ui.link("Every case and its restart: Sweep page →",
                        project_url("sweep", frame.session.directory)).classes("as-hint").mark("flight-sweep-link")
            elif fs.mode == "altitude":
                _summary(frame)
            if fs.mode == "altitude":
                kept = [f"temperature {format_value(fs.temperature_K)} K" if fs.temperature_K is not None else "",
                        f"Reynolds number {sci(fs.reynolds)}" if fs.reynolds is not None else ""]
                kept = [part for part in kept if part]
                if kept:
                    hint("Kept for Set by hand: " + ", ".join(kept)).mark("freestream-kept")

    render()
    return render


def _sweep_lists(frame: ProjectFrame, after: Callable[[], None]) -> None:
    """The sweep's Mach, α and β lists, as the Sweep page sets them."""
    sweep = frame.session.project.sweep
    for _key, label, name in CONDITIONS:
        with ui.column().classes("gap-1"):
            text_field(label, values_text(getattr(sweep, name)),
                       lambda text, n=name: frame.save(
                           lambda p: update_sweep(p, **{n: parse_value_list(text)}), then=after),
                       mark=f"sweep-{name}", placeholder=LIST_PLACEHOLDER)


def _conditions(frame: ProjectFrame, after: Callable[[], None]) -> None:
    """A single case's Mach, AoA and β: the template's MACH_NUMBER, AOA and SIDESLIP_ANGLE (editable)."""
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        template = ""
    values = template_case_values(template) if template else (None, None, None)
    winning = settings_parameters(project.settings)
    for (key, label, name), value in zip(CONDITIONS, values):
        with ui.column().classes("gap-1"):
            _template_number(frame, after, key, label, name, value, winning.get(key))


def _template_number(frame: ProjectFrame, after: Callable[[], None], key: str, label: str, name: str,
                     value: Optional[float], winning: Optional[str]) -> None:
    """One of the single case's MACH_NUMBER, AOA and SIDESLIP_ANGLE, written into the template."""
    def commit(text: str) -> Optional[str]:
        try:
            number = parse_optional_number(text, label)
        except ProjectError as exc:
            return str(exc)
        if key == "MACH_NUMBER" and (number is None or number <= 0):
            return "Mach must be greater than 0"
        if number is None:
            return f"{label} needs a value"
        message = write_template_params(frame, {key: format_value(number)})
        if message is None:
            after()
        return message

    text_field(label, "" if value is None else format_value(value), commit, mark=f"freestream-{name}",
               placeholder=f"{key} in the template")
    if winning is not None:
        hint(f"A {key} placeholder ({winning}) wins over this in the config; "
             "remove it under Extra options for this value to take effect").classes(
            "as-hint-warning").mark(f"freestream-{name}-wins")


def _summary(frame: ProjectFrame) -> None:
    """A single case's temperature, pressure and Reynolds number from its altitude, or why they can't be computed."""
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        template = ""
    rows = case_freestream(project, template)
    with ui.row().classes("as-strip as-strip-result").mark("freestream-summary"):
        if not rows:
            ui.label("No case yet").classes("as-muted")
            return
        row = rows[0]
        if row.values is None:
            ui.label(row.error).classes("as-error-text").mark("freestream-summary-error")
            return
        stat("Temperature", f"{format_value(round(row.values.temperature_K, 2))} K")
        stat("Pressure", pascals(row.values.pressure_Pa))
        stat("Reynolds number", sci(row.values.reynolds))
        ui.label(f"at the template's Mach {format_value(row.mach)}").classes("as-muted ml-auto")

"""Aircraft: the Aircraft Aero form (profile defaults as hints), placeholders, preview and the reference."""
from typing import Callable, Optional

from nicegui import ui

from ...engine.cfg import case_freestream, read_template, render_case, settings_parameters, template_case_values
from ...engine.editing import MARKER_PREFIX, set_freestream, set_parameter, unset_parameter
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import format_value
from ...engine.profiles import load_profile
from ...engine.reference import RefOption, keys_in
from ..fields import text_field
from ...engine.project import template_file_name, template_warnings
from ..checks import generate_button, render_checks
from ..layout import ProjectFrame, open_session, project_url
from ..session import parse_optional_int, parse_optional_number
from ..side_panel import side_panel
from ..sweep_choice import sweep_toggle
from ..template_editor import TemplateEditor, carry_unsaved
from ..template_edit import write_template_params
from ..ui_kit import banner, card, field, hint, readonly, sci, secondary_button, stat, table, td, td_box, th

# (label, settings group, field, kind) — kind: "float" | "int"
NUMBER_FIELDS = {
    "Physical and reference": [
        ("Reference length", "reference", "ref_length", "float"),
        ("Reference area", "reference", "ref_area", "float"),
        ("Moment origin x", "reference", "origin_x", "float"),
        ("Moment origin y", "reference", "origin_y", "float"),
        ("Moment origin z", "reference", "origin_z", "float"),
    ],
}
NUMERIC_TEXT = [("CFL number", "cfl", "float"), ("Iterations", "iter", "int")]
DROPDOWNS = [
    ("Convective", "conv_method", ["ROE", "JST", "AUSM"]),
    ("MUSCL", "muscl", ["YES", "NO"]),
    ("Turbulence", "turb_model", ["SST", "SA"]),
]
MARKER_ROWS = ["MARKER_HEATFLUX", "MARKER_FAR", "MARKER_PLOTTING", "MARKER_MONITORING"]


def register() -> None:
    @ui.page("/aircraft")
    def aircraft_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        state: dict = {}  # the Template tab's editor state; survives body.refresh() (see carry_unsaved)

        def reload_body() -> None:
            carry_unsaved(state)
            body.refresh()

        frame = ProjectFrame(session, "aircraft", on_reload=reload_body)

        @ui.refreshable
        def body() -> None:
            if not frame.session.project.profile:
                frame.actions.clear()
                banner("info", "This project has no aircraft profile. Choose one in Setup "
                       "to use the Aircraft Aero form.").mark("aircraft-none")
                return
            _build(frame, state, reload_body)

        with frame.content:
            body()


def _hints(project: Project) -> dict[str, str]:
    try:
        profile = load_profile(project.profile)
    except ProjectError:
        return {}
    return {**profile.setting_hints, **profile.hints}


def _rendered_keys(frame: ProjectFrame) -> set[str]:
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        return set()
    if not project.cases:
        return keys_in(template)
    try:
        return keys_in(render_case(template, project, project.cases[0]))
    except AeroSuiteError:  # e.g. altitude mode without an altitude yet
        return keys_in(template)


def _build(frame: ProjectFrame, state: dict, redraw: Callable[[], None]) -> None:
    """The form on the left; Preview | Template | SU2 reference on the right. An aircraft study has no
    CFG setup step, so the sweep switch and (sweep off) Generate are here."""
    hints = _hints(frame.session.project)
    holders: dict = {}
    sweep_on = frame.session.project.sweep.enabled

    def render_checks_box() -> None:
        box = holders.get("checks")
        if box is None:
            return
        box.clear()
        with box:
            render_checks(frame, holders.get("generate"))

    def after() -> None:
        holders["preview"]()
        holders["reference"]()
        render_checks_box()

    def template_saved(warnings: list[str]) -> None:
        box = holders["template-warnings"]
        box.clear()
        if sweep_on:  # sweep off: the checks above Generate already list these
            with box:
                for warning in warnings:
                    banner("warning", warning).mark("config-warning")
        holders["freestream"]()  # a single case's Mach is the template's
        after()

    def template_tab() -> None:
        hint(f"Saved automatically · {template_file_name(frame.session.project)} · the form's values and "
             "Placeholders are written over it in every config").mark("template-note")
        holders["template-warnings"] = ui.column().classes("w-full gap-2")
        editor = TemplateEditor(frame, state, on_saved=template_saved, height="55vh")
        if sweep_on:
            with holders["template-warnings"]:
                for warning in template_warnings(editor.initial):
                    banner("warning", warning).mark("config-warning")

    frame.actions.clear()
    with frame.actions:
        sweep_toggle(frame, mark="aircraft-sweep", then=redraw)
        if not sweep_on:
            holders["generate"] = generate_button(frame, render_checks_box)
    if not sweep_on:
        holders["checks"] = ui.column().classes("w-full gap-2").mark("aircraft-checks")
        render_checks_box()

    with ui.element("div").classes("as-columns"):
        with ui.column().classes("gap-4 w-full"):
            holders["freestream"] = _freestream(frame, hints, after)
            for title, rows in NUMBER_FIELDS.items():
                with card(title):
                    with ui.element("div").classes("as-grid-3"):
                        for label, group, name, kind in rows:
                            with ui.column().classes("gap-1"):
                                _number_field(frame, hints, label, group, name, kind, after)
            with card("Numerics"):
                with ui.element("div").classes("as-grid-3"):
                    for label, name, options in DROPDOWNS:
                        with ui.column().classes("gap-1"):
                            _dropdown(frame, label, name, options, after)
                    for label, name, kind in NUMERIC_TEXT:
                        with ui.column().classes("gap-1"):
                            _number_field(frame, hints, label, "numerics", name, kind, after)
            holders["markers"] = _markers(frame, hints, after)
            holders["overrides"] = _placeholders(frame, after)
        holders["preview"], holders["reference"] = side_panel(
            frame, on_insert=lambda option: _insert(frame, option, holders, after),
            in_config=lambda: _rendered_keys(frame), template=template_tab)


MODE_CHOICES = {
    "manual": "Set by hand · one temperature and Reynolds number for every case",
    "altitude": "From altitude · each case gets ISA temperature and its own Reynolds number",
}


def _freestream(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    with card("Freestream"):
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
        fs = frame.session.project.settings.freestream
        with box:
            _mach(frame, both)
            ui.radio(MODE_CHOICES, value=fs.mode, on_change=lambda e: choose(e.value)).props("inline").classes(
                "as-choice").mark("freestream-mode")
            if fs.mode == "manual":
                with ui.element("div").classes("as-grid-3"):
                    for label, name in (("Temperature (K)", "temperature_K"), ("Reynolds number", "reynolds"),
                                        ("Reynolds length", "reynolds_length")):
                        with ui.column().classes("gap-1"):
                            _number_field(frame, hints, label, "freestream", name, "float", both)
                return
            with ui.element("div").classes("as-grid-2"):
                with ui.column().classes("gap-1"):
                    number("Altitude (km)", "altitude_km", fs.altitude_km, "ISA, 0–100 km")
                with ui.column().classes("gap-1"):
                    number("Reynolds length (m)", "reynolds_length", fs.reynolds_length,
                           "characteristic length for the Reynolds number")
            _summary(frame)
            kept = [f"temperature {format_value(fs.temperature_K)} K" if fs.temperature_K is not None else "",
                    f"Reynolds number {sci(fs.reynolds)}" if fs.reynolds is not None else ""]
            kept = [part for part in kept if part]
            if kept:
                hint("Kept for Set by hand: " + ", ".join(kept)).mark("freestream-kept")

    render()
    return render


def _mach(frame: ProjectFrame, after: Callable[[], None]) -> None:
    """The Mach number(s): the Sweep page's with the sweep on, else the template's MACH_NUMBER (editable)."""
    project = frame.session.project
    with ui.element("div").classes("as-grid-3"):
        with ui.column().classes("gap-1"):
            if project.sweep.enabled:
                ui.label("Mach").classes("as-label")
                readonly(", ".join(format_value(m) for m in project.sweep.mach) or "—").mark("freestream-mach-sweep")
                ui.link("Set on the Sweep page", project_url("sweep", frame.session.directory)).classes(
                    "as-hint").mark("freestream-mach-link")
                return
            try:
                template = read_template(frame.session.directory, project)
            except AeroSuiteError:
                template = ""
            mach = template_case_values(template)[0] if template else None

            def commit(text: str) -> Optional[str]:
                try:
                    value = parse_optional_number(text, "Mach")
                except ProjectError as exc:
                    return str(exc)
                if value is None or value <= 0:
                    return "Mach must be greater than 0"
                message = write_template_params(frame, {"MACH_NUMBER": format_value(value)})
                if message is None:
                    after()
                return message

            text_field("Mach", "" if mach is None else format_value(mach), commit, mark="freestream-mach",
                       placeholder="MACH_NUMBER in the template")
            winning = settings_parameters(project.settings).get("MACH_NUMBER")
            if winning is not None:
                hint(f"A MACH_NUMBER placeholder ({winning}) wins over this in the config; "
                     "remove it under Placeholders for this value to take effect").classes(
                    "as-hint-warning").mark("freestream-mach-wins")


def _summary(frame: ProjectFrame) -> None:
    """Temperature and the Reynolds range the cases get, or why they can't be computed."""
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        template = ""
    rows = case_freestream(project, template)
    with ui.row().classes("as-strip").mark("freestream-summary"):
        if not rows:
            ui.label("No cases yet").classes("as-muted")
            return
        failed = next((row for row in rows if row.values is None), None)
        if failed is not None:
            ui.label(failed.error).classes("as-error-text").mark("freestream-summary-error")
            return
        reynolds = sorted(row.values.reynolds for row in rows)
        machs = sorted(row.mach for row in rows)
        stat("Temperature", f"{format_value(round(rows[0].values.temperature_K, 2))} K")
        span = sci(reynolds[0]) if sci(reynolds[0]) == sci(reynolds[-1]) else f"{sci(reynolds[0])} … {sci(reynolds[-1])}"
        stat("Reynolds number", span)
        if project.sweep.enabled:
            where = (f"per case, from each case's Mach ({format_value(machs[0])} – {format_value(machs[-1])})"
                     if machs[0] != machs[-1] else f"at Mach {format_value(machs[0])}")
            ui.label(where + " · see the Sweep page").classes("as-muted")
        else:
            ui.label(f"at the template's Mach {format_value(machs[0])}").classes("as-muted")


def _number_field(frame, hints, label, group, name, kind, after) -> None:
    current = getattr(getattr(frame.session.project.settings, group), name)
    shown = "" if current is None else (format_value(current) if kind == "float" else str(current))
    parse = parse_optional_number if kind == "float" else parse_optional_int

    def change(p: Project, text: str) -> None:
        setattr(getattr(p.settings, group), name, parse(text, label))

    text_field(label, shown, lambda text: frame.save(lambda p: change(p, text), then=after),
               mark=f"{group}-{name}", placeholder=hints.get(f"{group}.{name}", "template value"))


def _dropdown(frame, label, name, choices, after) -> None:
    current = getattr(frame.session.project.settings.numerics, name)
    options = {"": "(template value)", **{c: c for c in choices}}
    if current and current not in options:
        options[current] = current  # keep a template value that is not in the fixed list

    def change(value) -> None:
        message = frame.save(lambda p: setattr(p.settings.numerics, name, value or None), then=after)
        if message:
            ui.notify(message, type="negative")

    field(ui.select(options, value=current or "", label=label,
                    on_change=lambda e: change(e.value))).classes("w-full").mark(f"numerics-{name}")


def _markers(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    mesh = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    with card("Markers", f"Mesh markers: {mesh}"):
        box = ui.column().classes("w-full gap-2")

    def render() -> None:
        # Plain synchronous rebuild: tests read these rows right after a change.
        box.clear()
        markers = frame.session.project.settings.markers
        keys = MARKER_ROWS + sorted(k for k in markers if k not in MARKER_ROWS)
        with box:
            with ui.element("div").classes("as-grid-form"):
                for key in keys:
                    value = markers.get(key, "")
                    ui.checkbox(key, value=value is not None,
                                on_change=lambda e, k=key: include(k, e.value)).mark(f"marker-{key}-include")
                    with ui.column().classes("gap-0"):
                        text_field("Value", value or "", lambda text, k=key: set_value(k, text),
                                   mark=f"marker-{key}-value", placeholder=hints.get(key, "template value"),
                                   mono=True)

    def both() -> None:
        render()
        after()

    def include(key: str, on: bool) -> None:
        def change(p: Project) -> None:
            if not on:
                p.settings.markers[key] = None  # the line is removed from every config
            elif key in p.settings.markers and p.settings.markers[key] is None:
                del p.settings.markers[key]  # back to the template's line

        message = frame.save(change, then=both)
        if message:
            ui.notify(message, type="negative")

    def set_value(key: str, text: str) -> Optional[str]:
        if text.strip():
            return frame.save(lambda p: set_parameter(p.settings, key, text), then=both)
        if frame.session.project.settings.markers.get(key) is not None:
            return frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        return None

    render()
    return render


def _placeholders(frame: ProjectFrame, after: Callable[[], None]) -> Callable[[], None]:
    with card("Placeholders", "Any other SU2 option, written into every config.", flush=True):
        box = ui.column().classes("w-full gap-0")
        with ui.row().classes("w-full items-start no-wrap gap-2 px-4 pt-3 pb-2"):
            key_box = field(ui.input("Option"), mono=True).classes("w-48").mark("override-new-key")
            value_box = field(ui.input("Value")).classes("grow").mark("override-new-value")
            secondary_button("Add", on_click=lambda: add()).mark("override-add")
        error = ui.label("").classes("as-error-text px-4 pb-3").mark("override-add-error")

    def render() -> None:
        box.clear()
        items = sorted(frame.session.project.settings.overrides.items())
        if not items:
            return
        with box:
            with table("minmax(10rem, 14rem) minmax(0, 1fr) 56px"):
                for heading in ("Option", "Value", ""):
                    th(heading)
                for key, value in items:
                    td(key, mono=True)
                    with td_box():
                        with ui.column().classes("grow gap-0"):
                            text_field("Value", value,
                                       lambda text, k=key: frame.save(
                                           lambda p: set_parameter(p.settings, k, text), then=after),
                                       mark=f"override-{key}-value", mono=True)
                    with td_box():
                        ui.button(icon="delete", on_click=lambda k=key: forget(k), color=None).props(
                            "flat round dense").mark(f"override-{key}-delete")

    def both() -> None:
        render()
        after()

    def forget(key: str) -> None:
        message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    def add() -> None:
        name = (key_box.value or "").strip().upper()

        def change(p: Project) -> None:
            if name.startswith(MARKER_PREFIX):
                raise ProjectError("Use the Markers section for MARKER_ options")
            set_parameter(p.settings, name, value_box.value or "")

        message = frame.save(change, then=both)
        error.text = message or ""
        if message is None:
            key_box.value = ""
            value_box.value = ""

    render()
    return render


def _insert(frame: ProjectFrame, option: RefOption, holders: dict, after: Callable[[], None]) -> Optional[str]:
    settings = frame.session.project.settings
    if option.key.startswith(MARKER_PREFIX):
        if settings.markers.get(option.key):
            return f"{option.key} is already in Markers"
        target, place = holders["markers"], "Markers"
    else:
        if option.key in settings.overrides:
            return f"{option.key} is already in Placeholders"
        target, place = holders["overrides"], "Placeholders"

    def both() -> None:
        target()
        after()

    message = frame.save(lambda p: set_parameter(p.settings, option.key, option.default_value), then=both)
    return message or f"Added {option.key} to {place}"

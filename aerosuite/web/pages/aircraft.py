"""Aircraft: the Aircraft Aero form (profile defaults as hints), placeholders and the reference."""
from typing import Callable, Optional

from nicegui import ui

from ...engine.cfg import read_template, render_case
from ...engine.editing import MARKER_PREFIX, set_parameter, unset_parameter
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import format_value
from ...engine.profiles import load_profile
from ...engine.reference import RefOption, keys_in
from ..fields import text_field
from ..layout import ProjectFrame, open_session
from ..preview import preview_section
from ..reference_panel import reference_panel
from ..session import parse_optional_int, parse_optional_number

# (label, settings group, field, kind) — kind: "float" | "int"
NUMBER_FIELDS = {
    "Freestream": [
        ("Temperature (K)", "freestream", "temperature_K", "float"),
        ("Reynolds number", "freestream", "reynolds", "float"),
        ("Reynolds length", "freestream", "reynolds_length", "float"),
    ],
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
        frame = ProjectFrame(session, "aircraft", on_reload=lambda: body.refresh())

        @ui.refreshable
        def body() -> None:
            if not frame.session.project.profile:
                ui.label("This project has no aircraft profile. Choose one in Setup "
                         "to use the Aircraft Aero form.").mark("aircraft-none")
                return
            _build(frame)

        with frame.content:
            ui.label("Aircraft").classes("text-2xl")
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
    return keys_in(render_case(template, project, project.cases[0]))


def _build(frame: ProjectFrame) -> None:
    hints = _hints(frame.session.project)
    holders: dict = {}

    def after() -> None:
        holders["preview"]()
        holders["reference"]()

    with ui.row().classes("w-full no-wrap items-start gap-6"):
        with ui.column().classes("w-1/2 gap-2"):
            for title, rows in NUMBER_FIELDS.items():
                ui.label(title).classes("text-lg")
                for label, group, name, kind in rows:
                    _number_field(frame, hints, label, group, name, kind, after)
            ui.label("Numerics").classes("text-lg")
            for label, name, options in DROPDOWNS:
                _dropdown(frame, label, name, options, after)
            for label, name, kind in NUMERIC_TEXT:
                _number_field(frame, hints, label, "numerics", name, kind, after)
            holders["markers"] = _markers(frame, hints, after)
            holders["overrides"] = _placeholders(frame, after)
            holders["preview"] = preview_section(frame)
        with ui.column().classes("w-1/2 gap-2"):
            holders["reference"] = reference_panel(
                on_insert=lambda option: _insert(frame, option, holders, after),
                in_config=lambda: _rendered_keys(frame))


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

    ui.select(options, value=current or "", label=label,
              on_change=lambda e: change(e.value)).classes("w-full").mark(f"numerics-{name}")


def _markers(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    ui.label("Markers").classes("text-lg")
    mesh = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    ui.label(f"Mesh markers: {mesh}").classes("text-xs text-grey-8")
    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        # Plain synchronous rebuild: tests read these rows right after a change.
        box.clear()
        markers = frame.session.project.settings.markers
        keys = MARKER_ROWS + sorted(k for k in markers if k not in MARKER_ROWS)
        with box:
            for key in keys:
                value = markers.get(key, "")
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.checkbox(key, value=value is not None,
                                on_change=lambda e, k=key: include(k, e.value)).classes("w-56").mark(
                        f"marker-{key}-include")
                    text_field("Value", value or "", lambda text, k=key: set_value(k, text),
                               mark=f"marker-{key}-value", placeholder=hints.get(key, "template value"))

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
    ui.label("Placeholders").classes("text-lg")
    ui.label("Any other SU2 option, written into every config.").classes("text-xs text-grey-8")
    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        box.clear()
        with box:
            for key, value in sorted(frame.session.project.settings.overrides.items()):
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label(key).classes("w-48")
                    text_field("Value", value,
                               lambda text, k=key: frame.save(
                                   lambda p: set_parameter(p.settings, k, text), then=after),
                               mark=f"override-{key}-value")
                    ui.button(icon="delete", on_click=lambda k=key: forget(k)).props("flat").mark(
                        f"override-{key}-delete")

    def both() -> None:
        render()
        after()

    def forget(key: str) -> None:
        message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    with ui.row().classes("w-full items-center no-wrap"):
        key_box = ui.input("Option").classes("w-48").mark("override-new-key")
        value_box = ui.input("Value").classes("grow").mark("override-new-value")
        ui.button("Add", on_click=lambda: add()).mark("override-add")
    error = ui.label("").classes("text-negative text-xs").mark("override-add-error")

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

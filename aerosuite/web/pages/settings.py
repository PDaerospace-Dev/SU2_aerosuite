"""Settings: freestream, reference, numerics, markers and overrides, beside a live .cfg preview."""
from typing import Callable

from nicegui import ui

from ...engine.cfg import read_template, render_case
from ...engine.editing import MARKER_PREFIX, set_parameter, unset_parameter
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import format_value
from ..fields import text_field
from ..layout import ProjectFrame, open_session
from ..session import parse_optional_int, parse_optional_number

# (label, settings group, field, kind) — kind: "float" | "int" | "text"
FIELDS = {
    "Freestream": [
        ("Temperature (K)", "freestream", "temperature_K", "float"),
        ("Reynolds number", "freestream", "reynolds", "float"),
        ("Reynolds length", "freestream", "reynolds_length", "float"),
    ],
    "Reference": [
        ("Moment origin x", "reference", "origin_x", "float"),
        ("Moment origin y", "reference", "origin_y", "float"),
        ("Moment origin z", "reference", "origin_z", "float"),
        ("Reference length", "reference", "ref_length", "float"),
        ("Reference area", "reference", "ref_area", "float"),
    ],
    "Numerics": [
        ("Turbulence model", "numerics", "turb_model", "text"),
        ("CFL number", "numerics", "cfl", "float"),
        ("Iterations", "numerics", "iter", "int"),
        ("Convective scheme", "numerics", "conv_method", "text"),
        ("MUSCL", "numerics", "muscl", "text"),
    ],
}


def register() -> None:
    @ui.page("/settings")
    def settings_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "settings", on_reload=lambda: body.refresh())

        state = {"case": None}
        preview_holder: dict = {}

        def render_preview() -> None:
            # A plain synchronous rebuild, not `@ui.refreshable`: autosave callers need the
            # preview to reflect a change the instant `frame.save` returns (the tests check it
            # with no `await` in between), but a refreshable's `.refresh()` only *schedules* its
            # rebuild as a background task for the next event-loop tick, which is too late.
            box = preview_holder.get("box")
            if box is None:
                return
            box.clear()
            with box:
                _preview(frame, state, render_preview)

        @ui.refreshable
        def body() -> None:
            with ui.row().classes("w-full no-wrap items-start gap-6"):
                with ui.column().classes("w-1/2 gap-2"):
                    for title, rows in FIELDS.items():
                        ui.label(title).classes("text-lg")
                        for label, group, name, kind in rows:
                            _settings_field(frame, label, group, name, kind, render_preview)
                    _markers_table(frame, render_preview)
                    _overrides_table(frame, render_preview)
                with ui.column().classes("w-1/2 gap-2"):
                    ui.label("Preview").classes("text-lg")
                    preview_holder["box"] = ui.column().classes("w-full gap-2")
            render_preview()

        with frame.content:
            ui.label("Settings").classes("text-2xl")
            body()


def _parse(kind: str, text: str, label: str):
    if kind == "float":
        return parse_optional_number(text, label)
    if kind == "int":
        return parse_optional_int(text, label)
    return text.strip() or None


def _settings_field(frame: ProjectFrame, label: str, group: str, name: str, kind: str,
                    after: Callable[[], None]) -> None:
    current = getattr(getattr(frame.session.project.settings, group), name)
    shown = "" if current is None else (format_value(current) if kind == "float" else str(current))

    def change(p: Project, text: str) -> None:
        setattr(getattr(p.settings, group), name, _parse(kind, text, label))

    text_field(label, shown, lambda text: frame.save(lambda p: change(p, text), then=after),
               mark=f"{group}-{name}", placeholder="template value")


def _add_row(frame: ProjectFrame, prefix: str, check: Callable[[str], None], then: Callable[[], None]) -> None:
    with ui.row().classes("w-full items-center no-wrap"):
        key = ui.input("Option").classes("w-48").mark(f"{prefix}-new-key")
        value = ui.input("Value").classes("grow").mark(f"{prefix}-new-value")
        ui.button("Add", on_click=lambda: add()).mark(f"{prefix}-add")
    error = ui.label("").classes("text-negative text-xs").mark(f"{prefix}-add-error")

    def add() -> None:
        name = (key.value or "").strip().upper()

        def change(p: Project) -> None:
            check(name)
            set_parameter(p.settings, name, value.value or "")

        message = frame.save(change, then=then)
        error.text = message or ""
        if message is None:
            # Clear the row so a second Add starts fresh instead of `.type()` appending
            # onto the name/value this Add just consumed.
            key.value = ""
            value.value = ""


def _markers_table(frame: ProjectFrame, after: Callable[[], None]) -> None:
    ui.label("Markers").classes("text-lg")
    markers = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    ui.label(f"Mesh markers: {markers}").classes("text-xs text-grey-8").mark("mesh-marker-list")

    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        # Plain synchronous rebuild — see the comment on `render_preview` in `register()`.
        box.clear()
        with box:
            for key, value in sorted(frame.session.project.settings.markers.items()):
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label(key).classes("w-48")
                    if value is not None:
                        text_field("Value", value,
                                   lambda text, k=key: frame.save(
                                       lambda p: set_parameter(p.settings, k, text), then=after),
                                   mark=f"marker-{key}-value")
                    ui.switch("Remove line", value=value is None,
                              on_change=lambda e, k=key: toggle(k, e.value)).mark(f"marker-{key}-remove")
                    ui.button(icon="delete", on_click=lambda k=key: forget(k)).props("flat").mark(
                        f"marker-{key}-delete")

    def toggle(key: str, remove: bool) -> None:
        if remove:
            message = frame.save(lambda p: p.settings.markers.__setitem__(key, None), then=both)
        else:  # switching removal off returns to the template's line
            message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    def forget(key: str) -> None:
        message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    def both() -> None:
        render()
        after()

    def must_be_marker(name: str) -> None:
        if not name.startswith(MARKER_PREFIX):
            raise ProjectError("Marker keys start with MARKER_ (use Overrides for other options)")

    render()
    _add_row(frame, "marker", must_be_marker, both)


def _overrides_table(frame: ProjectFrame, after: Callable[[], None]) -> None:
    ui.label("Overrides").classes("text-lg")

    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        # Plain synchronous rebuild — see the comment on `render_preview` in `register()`.
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

    def forget(key: str) -> None:
        message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    def both() -> None:
        render()
        after()

    def not_a_marker(name: str) -> None:
        if name.startswith(MARKER_PREFIX):
            raise ProjectError("Use the Markers table for MARKER_ options")

    render()
    _add_row(frame, "override", not_a_marker, both)


def _preview(frame: ProjectFrame, state: dict, refresh: Callable[[], None]) -> None:
    project = frame.session.project
    if not project.cases:
        ui.label("Set up the sweep to preview a case's config.").mark("preview-empty")
        return
    names = [case.name for case in project.cases]
    if state["case"] not in names:
        state["case"] = names[0]

    def choose(name: str) -> None:
        state["case"] = name
        refresh()

    ui.select(names, value=state["case"], label="Case", on_change=lambda e: choose(e.value)).mark("preview-case")
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError as exc:
        ui.label(f"Error: {exc}").classes("text-negative").mark("preview-error")
        return
    case = next(case for case in project.cases if case.name == state["case"])
    ui.code(render_case(template, project, case), language="ini").classes("w-full").mark("preview")

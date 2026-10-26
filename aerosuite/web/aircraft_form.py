"""The Aircraft page's Solver, Reference and Extra options tabs, and the number and dropdown fields every tab
uses. A field left empty keeps the template's value; the profile's default is its placeholder."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import read_template
from ..engine.config_rules import _items, _options
from ..engine.editing import MARKER_PREFIX, parse_cfl_adapt_param, set_parameter, unset_parameter
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.models import Project
from ..engine.naming import format_value
from .fields import text_field
from .layout import ProjectFrame
from .session import parse_optional_int, parse_optional_number
from .ui_kit import field, hint, secondary_button, table, td, td_box, th

REFERENCE_FIELDS = [  # (label, field)
    ("Reference length", "ref_length"),
    ("Reference area", "ref_area"),
    ("Moment origin x", "origin_x"),
    ("Moment origin y", "origin_y"),
    ("Moment origin z", "origin_z"),
]
SCHEME = [
    ("Convective", "conv_method", ["ROE", "JST", "AUSM"]),
    ("MUSCL", "muscl", ["YES", "NO"]),
    ("Turbulence", "turb_model", ["SST", "SA"]),
]
# CFL_ADAPT_PARAM's numbers, in SU2's order: (label, marker); the last two may be left out
CFL_PARAMS = [("Factor down", "cfl-factor-down"), ("Factor up", "cfl-factor-up"), ("Min CFL", "cfl-min"),
              ("Max CFL", "cfl-max"), ("Linear solver tolerance", "cfl-tolerance"), ("Start iteration", "cfl-start")]
SU2_CFL_PARAMS = ["0.1", "2.0", "10.0", "1e10", "0.001", "0"]  # SU2's own default, when the template has none


def number_field(frame: ProjectFrame, hints: dict[str, str], label: str, group: str, name: str, kind: str,
                 after: Callable[[], None]) -> None:
    current = getattr(getattr(frame.session.project.settings, group), name)
    shown = "" if current is None else (format_value(current) if kind == "float" else str(current))
    parse = parse_optional_number if kind == "float" else parse_optional_int

    def change(p: Project, text: str) -> None:
        setattr(getattr(p.settings, group), name, parse(text, label))

    text_field(label, shown, lambda text: frame.save(lambda p: change(p, text), then=after),
               mark=f"{group}-{name}", placeholder=hints.get(f"{group}.{name}", "template value"))


def dropdown(frame: ProjectFrame, label: str, name: str, choices: list[str], after: Callable[[], None]) -> None:
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


def _template_options(frame: ProjectFrame) -> dict[str, str]:
    try:
        return _options(read_template(frame.session.directory, frame.session.project))
    except AeroSuiteError:
        return {}


def solver_tab(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    """Scheme, iterations and CFL; with Adaptive CFL on, CFL_ADAPT_PARAM's numbers. Returns its redraw."""
    box = ui.column().classes("w-full gap-3")

    def both() -> None:
        render()
        after()

    def render() -> None:
        box.clear()
        numerics = frame.session.project.settings.numerics
        template = _template_options(frame)
        adaptive = (numerics.cfl_adapt or template.get("CFL_ADAPT", "NO")).upper() == "YES"
        with box:
            ui.label("Scheme").classes("as-subhead")
            with ui.element("div").classes("as-grid-3"):
                for label, name, options in SCHEME:
                    with ui.column().classes("gap-1"):
                        dropdown(frame, label, name, options, after)
            ui.label("Iterations and CFL").classes("as-subhead")
            with ui.element("div").classes("as-grid-3"):
                with ui.column().classes("gap-1"):
                    number_field(frame, hints, "Iterations", "numerics", "iter", "int", after)
                with ui.column().classes("gap-1"):
                    number_field(frame, hints, "CFL number" + (" (start)" if adaptive else ""), "numerics", "cfl",
                                 "float", after)
                with ui.column().classes("gap-0 justify-center"):
                    ui.switch("Adaptive CFL", value=adaptive,
                              on_change=lambda e: set_adaptive(e.value)).mark("numerics-cfl_adapt")
                    if numerics.cfl_adapt is None:
                        hint("as in the template").mark("numerics-cfl_adapt-template")
            if adaptive:
                _cfl_params(frame, numerics.cfl_adapt_param, template.get("CFL_ADAPT_PARAM"), both)

    def set_adaptive(on: bool) -> None:
        message = frame.save(lambda p: setattr(p.settings.numerics, "cfl_adapt", "YES" if on else "NO"), then=both)
        if message:
            ui.notify(message, type="negative")

    render()
    return render


def _cfl_params(frame: ProjectFrame, own: Optional[str], template: Optional[str],
                after: Callable[[], None]) -> None:
    """CFL_ADAPT_PARAM as one box per number; the template's numbers are the placeholders while it is not set."""
    fallback = [item for item in _items(template or "") if item.upper() != "NONE"] or SU2_CFL_PARAMS
    values = _items(own) if own else []

    def commit(index: int, label: str, text: str) -> Optional[str]:
        numbers = list(values or fallback)
        numbers += [""] * (len(CFL_PARAMS) - len(numbers))
        numbers[index] = text.strip()
        if index < 4 and not numbers[index]:
            return f"{label} needs a number"
        while len(numbers) > 4 and not numbers[-1]:
            numbers.pop()  # the tolerance and start iteration may be left out, from the end
        if "" in numbers:
            return "The start iteration needs the linear solver tolerance before it"

        def change(p: Project) -> None:
            try:
                p.settings.numerics.cfl_adapt_param = parse_cfl_adapt_param(", ".join(numbers))
            except ValueError as exc:
                raise ProjectError(str(exc)) from None

        return frame.save(change, then=after)

    def reset() -> None:
        message = frame.save(lambda p: setattr(p.settings.numerics, "cfl_adapt_param", None), then=after)
        if message:
            ui.notify(message, type="negative")

    with ui.column().classes("as-cfl-adapt w-full gap-2").mark("cfl-adapt-box"):
        def boxes(indexes: range) -> None:
            with ui.element("div").classes("as-grid-4" if len(indexes) == 4 else "as-grid-2"):
                for index in indexes:
                    label, mark = CFL_PARAMS[index]
                    shown = values[index] if index < len(values) else ""
                    placeholder = fallback[index] if index < len(fallback) else "SU2 default"
                    with ui.column().classes("gap-1"):
                        text_field(label, shown, lambda text, i=index, n=label: commit(i, n, text), mark=mark,
                                   placeholder=placeholder)

        boxes(range(4))
        more = len(values) > 4
        with ui.expansion("More: linear solver tolerance, start iteration", value=more).classes(
                "w-full as-hint").mark("cfl-more"):
            boxes(range(4, 6))
        with ui.row().classes("items-center gap-2"):
            if own:
                hint(f"writes CFL_ADAPT_PARAM= {own}").classes("as-mono").mark("cfl-param-line")
                ui.button("Use the template's", on_click=reset, color=None).props("flat dense no-caps size=sm").mark(
                    "cfl-param-reset")
            else:
                hint("the template's CFL_ADAPT_PARAM" + ("" if template else " (none: SU2's default)")).mark(
                    "cfl-param-line")


def reference_tab(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    """Build the tab; returns its redraw."""
    box = ui.column().classes("w-full gap-3")

    def render() -> None:
        box.clear()
        with box:
            with ui.element("div").classes("as-grid-2"):
                for label, name in REFERENCE_FIELDS[:2]:
                    with ui.column().classes("gap-1"):
                        number_field(frame, hints, label, "reference", name, "float", after)
            with ui.element("div").classes("as-grid-3"):
                for label, name in REFERENCE_FIELDS[2:]:
                    with ui.column().classes("gap-1"):
                        number_field(frame, hints, label, "reference", name, "float", after)

    render()
    return render


def extra_tab(frame: ProjectFrame, after: Callable[[], None]) -> Callable[[], None]:
    """Any other SU2 option, written into every config (settings.overrides). Returns its redraw."""
    hint("Any other SU2 option, written into every config. Insert one from the SU2 reference, or type it.")
    with ui.row().classes("w-full items-start no-wrap gap-2"):
        key_box = field(ui.input("Option"), mono=True).classes("w-48").mark("override-new-key")
        value_box = field(ui.input("Value")).classes("grow").mark("override-new-value")
        secondary_button("Add", on_click=lambda: add()).mark("override-add")
    error = ui.label("").classes("as-error-text").mark("override-add-error")
    box = ui.column().classes("w-full gap-0")

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
                raise ProjectError("Use the Boundaries tab for MARKER_ options")
            set_parameter(p.settings, name, value_box.value or "")

        message = frame.save(change, then=both)
        error.text = message or ""
        if message is None:
            key_box.value = ""
            value_box.value = ""

    render()
    return render

"""The Aircraft page's Convergence tab: how many iterations a case may take, and when SU2 stops it before that.

SU2 stops a case at ITER, or earlier once CONV_FIELD is met: a residual down to CONV_RESIDUAL_MINVAL, or coefficients
that settle (each changes on average by less than CONV_CAUCHY_EPS over CONV_CAUCHY_ELEMS iterations), checked from
CONV_STARTITER. AeroSuite's own verdict (Converged / Not Converged) is a separate check of CL, CD and CMy."""
from typing import Callable, Optional

from nicegui import run, ui

from ..engine.cfg import read_template
from ..engine.config_rules import _options
from ..engine.editing import COEFFICIENT_FIELDS, RESIDUAL_FIELDS, conv_fields, parse_conv_field
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.models import Numerics, Project
from ..engine.results import CONVERGENCE_THRESHOLD
from .aircraft_form import number_field
from .fields import text_field
from .layout import ProjectFrame
from .session import parse_optional_int, parse_optional_number
from .ui_kit import banner, chip_button, hint, secondary_button

_WORDS = {"CONVERGED": "Converged", "UNCONVERGED": "Not converged"}
MODES = {"template": "As in the template", "residual": "The residual drops", "forces": "The forces settle"}
KEYS = {"CONV_FIELD": "conv_field", "CONV_RESIDUAL_MINVAL": "conv_residual_minval",
        "CONV_CAUCHY_ELEMS": "conv_cauchy_elems", "CONV_CAUCHY_EPS": "conv_cauchy_eps",
        "CONV_STARTITER": "conv_startiter"}
FORCES = ["LIFT", "DRAG", "MOMENT_Y"]  # the chips, as CL, CD, CMy
# "The forces settle" starts from these: a drift of at most 100 x 1e-5 = 0.1% over the window, AeroSuite's own limit
FORCE_DEFAULTS = {"conv_field": "( LIFT, DRAG )", "conv_cauchy_elems": 100, "conv_cauchy_eps": 1e-5,
                  "conv_startiter": 200}
SU2_DEFAULTS = {"CONV_FIELD": "RMS_DENSITY", "CONV_RESIDUAL_MINVAL": "-8", "CONV_CAUCHY_ELEMS": "100",
                "CONV_CAUCHY_EPS": "1e-10", "CONV_STARTITER": "5"}


def mode_of(numerics: Numerics) -> str:
    fields = conv_fields(numerics.conv_field or "")
    if not fields:
        return "template"
    return "forces" if all(field in COEFFICIENT_FIELDS for field in fields) else "residual"


def set_mode(numerics: Numerics, mode: str) -> None:
    """Switch what stops SU2 early, keeping what still applies (the start iteration, the residual's level)."""
    if mode == "template":
        for name in KEYS.values():
            setattr(numerics, name, None)
    elif mode == "residual":
        if mode_of(numerics) != "residual":
            numerics.conv_field = "RMS_DENSITY"
        numerics.conv_cauchy_elems = numerics.conv_cauchy_eps = None
    else:
        if mode_of(numerics) != "forces":
            numerics.conv_field = FORCE_DEFAULTS["conv_field"]
        for name in ("conv_cauchy_elems", "conv_cauchy_eps", "conv_startiter"):
            if getattr(numerics, name) is None:
                setattr(numerics, name, FORCE_DEFAULTS[name])
        numerics.conv_residual_minval = None


def toggle_force(numerics: Numerics, field: str) -> None:
    fields = conv_fields(numerics.conv_field or "")
    fields = [f for f in fields if f != field] if field in fields else fields + [field]
    fields = [f for f in FORCES if f in fields] + [f for f in fields if f not in FORCES]
    if not fields:
        raise ProjectError("Keep at least one coefficient: SU2 needs something to watch")
    numerics.conv_field = parse_conv_field(", ".join(fields))


def take_overrides(project: Project) -> None:
    """Move CONV_* lines from Extra options into this tab's fields (they would replace them otherwise)."""
    numerics, overrides = project.settings.numerics, project.settings.overrides
    parse = {"conv_field": parse_conv_field, "conv_residual_minval": float, "conv_cauchy_elems": int,
             "conv_cauchy_eps": float, "conv_startiter": int}
    for key, name in KEYS.items():
        if key in overrides:
            try:
                setattr(numerics, name, parse[name](overrides[key]))
            except ValueError as exc:
                raise ProjectError(f"{key}= {overrides[key]}: {exc}") from None
            del overrides[key]


def convergence_tab(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    """Returns its redraw."""
    box = ui.column().classes("w-full gap-3")

    def both() -> None:
        render()
        after()

    def save(change: Callable[[Project], None]) -> Optional[str]:
        """Save a change and redraw; a field shows the message itself, a switch or a chip as a notice."""
        return frame.save(change, then=both)

    def press(change: Callable[[Project], None]) -> None:
        message = save(change)
        if message:
            ui.notify(message, type="negative")

    def render() -> None:
        box.clear()
        settings = frame.session.project.settings
        numerics = settings.numerics
        mode = mode_of(numerics)
        try:
            template = _options(read_template(frame.session.directory, frame.session.project))
        except AeroSuiteError:
            template = {}
        with box:
            moved = [key for key in KEYS if key in settings.overrides]
            if moved:
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    banner("warning", f"Extra options also set {', '.join(moved)}, and win.").classes("grow").mark(
                        "conv-overrides")
                    secondary_button("Move here", lambda: press(take_overrides)).mark("conv-take-overrides")
            with ui.element("div").classes("as-grid-3"):
                with ui.column().classes("gap-1"):
                    number_field(frame, hints, "Iterations (max)", "numerics", "iter", "int", after)
            ui.label("Stop early when").classes("as-subhead")
            ui.toggle(MODES, value=mode, on_change=lambda e: press(lambda p: set_mode(p.settings.numerics, e.value))
                      ).props("dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark("conv-mode")
            if mode == "template":
                _template_line(template)
            elif mode == "residual":
                _residual(numerics, template, save, press)
            else:
                _forces(numerics, save, press)
            _verdicts(frame)

    render()
    return render


def _verdicts(frame: ProjectFrame) -> None:
    """AeroSuite's check, and judging the finished runs again with it as it is now."""
    from ..engine.results import COEFFICIENT_TOLERANCES

    ui.label("AeroSuite's verdict").classes("as-subhead")
    floors = ", ".join(f"{column} {value:g}" for column, value in COEFFICIENT_TOLERANCES.items())
    with ui.row().classes("items-center gap-1"):
        hint(f"Converged: CL, CD and CMy within {CONVERGENCE_THRESHOLD:.1%} over the last 10% of iterations.")
        ui.icon("info_outline").classes("as-help-icon").tooltip(
            f"Or, near zero, varying by less than {floors}. A run keeps the verdict it got when it ended; "
            "judging again applies the check as it is now.")
    result = ui.column().classes("w-full gap-1")

    async def again() -> None:
        from ..engine.jobs.rejudge import rejudge

        button.set_enabled(False)
        changed = await run.io_bound(rejudge, frame.session.directory)
        button.set_enabled(True)
        result.clear()
        with result:
            if not changed:
                hint("No verdict changed.").mark("conv-rejudged")
                return
            hint(f"{len(changed)} verdict{'' if len(changed) == 1 else 's'} changed:").mark("conv-rejudged")
            for item in changed[:20]:
                hint(f"{item.case}: {_WORDS[item.old]} → {_WORDS[item.new]}").classes("as-mono")

    button = secondary_button("Judge finished runs again", again, icon="rule").mark("conv-rejudge")


def _template_line(template: dict[str, str]) -> None:
    field = template.get("CONV_FIELD")
    if not field:
        text = "Template: none, so SU2's default (RMS_DENSITY down to -8)"
    elif all(f in COEFFICIENT_FIELDS for f in conv_fields(field)):
        text = (f"Template: {_coefficients(field)} settle, "
                f"{template.get('CONV_CAUCHY_EPS', SU2_DEFAULTS['CONV_CAUCHY_EPS'])} over "
                f"{template.get('CONV_CAUCHY_ELEMS', SU2_DEFAULTS['CONV_CAUCHY_ELEMS'])} iterations")
    else:
        text = (f"Template: {field} down to "
                f"{template.get('CONV_RESIDUAL_MINVAL', SU2_DEFAULTS['CONV_RESIDUAL_MINVAL'])}")
    hint(text).mark("conv-template")


def _coefficients(field: str) -> str:
    return ", ".join(COEFFICIENT_FIELDS.get(f, f) for f in conv_fields(field))


def _number_box(label: str, value: Optional[float], placeholder: str, mark: str,
                setter: Callable[[Numerics, str], None], save, as_int: bool = False) -> None:
    shown = "" if value is None else (str(value) if as_int else f"{value:g}")
    text_field(label, shown, lambda text: save(lambda p: setter(p.settings.numerics, text)), mark=mark,
               placeholder=placeholder)


def _residual(numerics: Numerics, template: dict[str, str], save, press) -> None:
    current = conv_fields(numerics.conv_field or "")[0]
    with ui.element("div").classes("as-grid-3"):
        with ui.column().classes("gap-1"):
            ui.select(list(RESIDUAL_FIELDS), value=current, label="Residual",
                      on_change=lambda e: press(lambda p: setattr(p.settings.numerics, "conv_field", e.value))
                      ).props("dense outlined").classes("w-full").mark("conv-residual")
        with ui.column().classes("gap-1"):
            _number_box("Down to (log10)", numerics.conv_residual_minval,
                        template.get("CONV_RESIDUAL_MINVAL", "-8 (SU2's default)"), "conv-minval",
                        lambda n, t: setattr(n, "conv_residual_minval", parse_optional_number(t, "Down to")), save)
        with ui.column().classes("gap-1"):
            _number_box("Check from iteration", numerics.conv_startiter,
                        template.get("CONV_STARTITER", "5 (SU2's default)"), "conv-startiter",
                        lambda n, t: setattr(n, "conv_startiter", parse_optional_int(t, "Check from")), save,
                        as_int=True)


def _forces(numerics: Numerics, save, press) -> None:
    fields = conv_fields(numerics.conv_field or "")
    with ui.row().classes("items-center gap-2"):
        ui.label("Coefficients").classes("as-label")
        for field in FORCES:
            on = field in fields
            chip_button(COEFFICIENT_FIELDS[field], lambda _, f=field: press(
                lambda p: toggle_force(p.settings.numerics, f))).classes("as-chip-on" if on else "").mark(
                f"conv-force-{COEFFICIENT_FIELDS[field]}")
        others = [f for f in fields if f not in FORCES]
        if others:
            hint(f"and {', '.join(others)}")
    with ui.element("div").classes("as-grid-3"):
        with ui.column().classes("gap-1"):
            _number_box("Window (iterations)", numerics.conv_cauchy_elems, "100", "conv-elems",
                        lambda n, t: setattr(n, "conv_cauchy_elems", parse_optional_int(t, "Window")), save,
                        as_int=True)
        with ui.column().classes("gap-1"):
            _number_box("Tolerance", numerics.conv_cauchy_eps, "1e-5", "conv-eps",
                        lambda n, t: setattr(n, "conv_cauchy_eps", parse_optional_number(t, "Tolerance")), save)
        with ui.column().classes("gap-1"):
            _number_box("Check from iteration", numerics.conv_startiter, "200", "conv-startiter",
                        lambda n, t: setattr(n, "conv_startiter", parse_optional_int(t, "Check from")), save,
                        as_int=True)
    window, eps = numerics.conv_cauchy_elems or 100, numerics.conv_cauchy_eps or 1e-5
    drift = window * eps
    text = f"Stops when each drifts less than {drift:.2%} over {window} iterations"
    if drift > 2 * CONVERGENCE_THRESHOLD:
        text += f": looser than AeroSuite's {CONVERGENCE_THRESHOLD:.1%}"
    hint(text).mark("conv-forces-hint")

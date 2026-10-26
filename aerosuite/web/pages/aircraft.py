"""Aircraft: an aircraft study's whole setup on one page. On top, the case strip: the case's name (or the sweep's
count) with its naming, and what it runs at. Under it the form, as tabs: Flight & air, Solver, Boundaries,
Reference, Start (Restarts with the sweep on) and Extra options. On the right the config (the lines AeroSuite writes,
or the whole of it, editable) and SU2's reference. The problems and Generate sit with the Sweep | Single switch."""
from pathlib import Path
from typing import Callable

from nicegui import ui

from ...engine.cfg import (case_freestream, read_template, render_case, stale_case_name, template_case_values,
                           template_or_none)
from ...engine.editing import MARKER_PREFIX, set_parameter, update_sweep
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import format_value
from ...engine.preflight import has_errors, preflight
from ...engine.profiles import load_profile
from ...engine.project import follow_template
from ...engine.reference import RefOption, keys_in
from ..aircraft_boundaries import boundaries_tab
from ..aircraft_flight import flight_tab
from ..aircraft_form import extra_tab, reference_tab, solver_tab
from ..checks import generate_button
from ..config_tab import ConfigTab, carry_unsaved_config
from ..fields import text_field
from ..layout import ProjectFrame, open_session, project_url
from ..naming_fields import base_name_field, naming_checkboxes
from ..restart_card import restart_card
from ..side_panel import side_panel
from ..sweep_choice import sweep_toggle
from ..sweep_view import detect_rule
from ..template_editor import carry_unsaved
from ..ui_kit import banner, card, hint, sci, stat
from .sweep import restart_rule

TABS = [("flight", "Flight & air"), ("solver", "Solver"), ("boundaries", "Boundaries"), ("reference", "Reference"),
        ("start", "Start"), ("extra", "Extra options")]
RULE_WORDS = {"none": "from scratch", "previous": "from the previous case", "custom": "from a folder"}


def register() -> None:
    @ui.page("/aircraft")
    def aircraft_page(project: str = "", tab: str = "") -> None:
        """`tab`: the form tab to open (flight, solver, boundaries, reference, start, extra)."""
        session = open_session(project)
        if session is None:
            return
        state: dict = {}  # the Config tab's editor state and the open tab; survives body.refresh()
        if tab in dict(TABS):
            state["form_tab"] = tab

        def reload_body() -> None:
            carry_unsaved(state)
            carry_unsaved_config(state)
            body.refresh()

        frame = ProjectFrame(session, "aircraft", on_reload=reload_body)

        @ui.refreshable
        def body() -> None:
            if not frame.session.project.profile:
                frame.actions.clear()
                banner("info", "This project has no aircraft profile. Choose one in Setup "
                       "to use the Aircraft Aero form.").mark("aircraft-none")
                return
            _follow_template(frame)
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


def _follow_template(frame: ProjectFrame) -> None:
    """Rename the single case when the template's Mach, AoA or β changed outside AeroSuite."""
    project = frame.session.project
    template = template_or_none(frame.session.directory, project)
    if template is None or stale_case_name(project, template) is None:
        return
    message = frame.save(lambda p: follow_template(frame.session.directory, p))
    if message:
        ui.notify(message, type="negative")


def _build(frame: ProjectFrame, state: dict, redraw: Callable[[], None]) -> None:
    hints = _hints(frame.session.project)
    holders: dict = {}

    def after() -> None:
        """Everything that shows what a change made: the strip, the problems, the counts, the config."""
        for name in ("strip", "problems", "counts", "preview", "reference", "start"):
            if name in holders:
                holders[name]()

    def template_saved(_warnings: list[str]) -> None:
        holders["flight"]()  # a single case's Mach is the template's
        after()

    def layers_saved() -> None:
        """A form line edited in the config: the form's fields show the new values (the config keeps its place)."""
        for name in ("flight", "solver", "boundaries", "reference-tab", "extra"):
            holders[name]()
        after()

    def config_tab() -> Callable[[], None]:
        return ConfigTab(frame, state, on_template_saved=template_saved, on_layers_saved=layers_saved,
                         on_pick=lambda tab: holders["tabs"].set_value(tab)).render

    frame.actions.clear()
    with frame.actions:
        holders["badges"] = ui.row().classes("items-center gap-1 no-wrap").mark("problem-badges")
        sweep_toggle(frame, mark="aircraft-sweep", then=redraw)
        holders["generate"] = generate_button(frame, lambda: holders["problems"]())
    holders["problems"] = _problems(frame, holders)
    open_names = _names_dialog(frame, after)

    with ui.element("div").classes("as-columns as-columns-aircraft"):
        with ui.column().classes("gap-4 w-full"):
            holders["strip"] = _case_strip(frame, open_names)
            with card() as tabs_card:
                tabs_card.mark("form-card")
                _tabs(frame, state, hints, holders, after)
        holders["preview"], holders["reference"] = side_panel(
            frame, on_insert=lambda option: _insert(frame, option, holders),
            in_config=lambda: _rendered_keys(frame), config=config_tab)
    holders["problems"]()
    holders["counts"]()


def _tabs(frame: ProjectFrame, state: dict, hints: dict[str, str], holders: dict, after: Callable[[], None]) -> None:
    sweep_on = frame.session.project.sweep.enabled
    counts: dict = {}
    with ui.tabs(value=state.get("form_tab", "flight"),
                 on_change=lambda e: state.update(form_tab=e.value)).props(
            "dense no-caps align=left inline-label").classes("as-tabs as-form-tabs w-full").mark("form-tabs") as tabs:
        for key, label in TABS:
            with ui.tab(key, "Restarts" if key == "start" and sweep_on else label).mark(f"form-tab-{key}"):
                if key == "extra":
                    counts[key] = ui.label("").classes("as-tab-count").mark(f"form-tab-{key}-count")
    holders["tabs"] = tabs
    with ui.tab_panels(tabs, value=tabs.value).props("keep-alive").classes("as-tab-panels w-full"):
        with ui.tab_panel("flight").classes("gap-3"):
            holders["flight"] = flight_tab(frame, hints, after)
        with ui.tab_panel("solver").classes("gap-3"):
            holders["solver"] = solver_tab(frame, hints, after)
        with ui.tab_panel("boundaries").classes("gap-3"):
            holders["boundaries"] = boundaries_tab(frame, hints, after)
        with ui.tab_panel("reference").classes("gap-3"):
            holders["reference-tab"] = reference_tab(frame, hints, after)
        with ui.tab_panel("start").classes("gap-3"):
            _start_tab(frame, holders, after)
        with ui.tab_panel("extra").classes("gap-3"):
            holders["extra"] = extra_tab(frame, after)

    def render_counts() -> None:
        extra = len(frame.session.project.settings.overrides)
        counts["extra"].text = str(extra)

    holders["counts"] = render_counts


def _start_tab(frame: ProjectFrame, holders: dict, after: Callable[[], None]) -> None:
    """A single case's restart; with the sweep on, the rule every case follows (each case on the Sweep page)."""
    if not frame.session.project.sweep.enabled:
        holders["start"] = restart_card(frame, after, framed=False)
        return
    box = ui.column().classes("w-full gap-2").mark("restart-rules")

    def render() -> None:
        box.clear()
        with box:
            restart_rule(frame, both)
            ui.link("Set a case differently: the Sweep page's Cases →",
                    project_url("sweep", frame.session.directory)).classes("as-hint").mark("restart-sweep-link")

    def both() -> None:
        render()
        after()

    render()
    holders["start"] = render


# -- the case strip --------------------------------------------------------------------------------------------

def _span(values: list[float], unit: str = "") -> str:
    if not values:
        return "—"
    if len(values) > 3:
        return f"{format_value(values[0])} … {format_value(values[-1])}{unit} ({len(values)})"
    return ", ".join(format_value(v) for v in values) + unit


def _case_strip(frame: ProjectFrame, open_names: Callable[[], None]) -> Callable[[], None]:
    """The case's name (a sweep's count) and what it runs at; the name opens the naming. Returns its redraw."""
    with card() as box:
        box.mark("case-strip")
        row = ui.row().classes("as-case-strip w-full")

    def render() -> None:
        row.clear()
        project = frame.session.project
        fs, cases = project.settings.freestream, project.cases
        with row:
            with ui.column().classes("gap-1"):
                ui.label("Cases" if project.sweep.enabled else "Case").classes("as-stat-label")
                text = (f"{len(cases)} case{'' if len(cases) == 1 else 's'}" if project.sweep.enabled
                        else cases[0].name if cases else "—")
                with ui.button(on_click=open_names, color=None).props("flat no-caps dense").classes(
                        "as-case-chip").mark("case-name"):
                    ui.label(text).mark("case-name-text")
                    ui.icon("edit")
            if project.sweep.enabled:
                sweep = project.sweep
                stat("Mach", _span(sweep.mach)).mark("strip-mach")
                stat("α", _span(sweep.alpha, "°")).mark("strip-alpha")
                stat("β", _span(sweep.beta, "°")).mark("strip-beta")
                if fs.mode == "altitude":
                    stat("Altitudes", _span(sweep.altitudes_km, " km")).mark("strip-altitude")
                rule, _folder, differing = detect_rule(cases)
                stat("Restarts", RULE_WORDS[rule] + (f" ({len(differing)} differ)" if differing else "")).mark(
                    "strip-restart")
                return
            try:
                template = read_template(frame.session.directory, project)
            except AeroSuiteError:
                template = ""
            mach, alpha, beta = template_case_values(template) if template else (0.0, 0.0, 0.0)
            stat("Mach", format_value(mach)).mark("strip-mach")
            stat("α", f"{format_value(alpha)}°").mark("strip-alpha")
            stat("β", f"{format_value(beta)}°").mark("strip-beta")
            if fs.mode == "altitude":
                stat("Altitude", "—" if fs.altitude_km is None else f"{format_value(fs.altitude_km)} km").mark(
                    "strip-altitude")
                rows = case_freestream(project, template) if template else []
                values = rows[0].values if rows else None
                stat("Reynolds", sci(values.reynolds) if values else "—").mark("strip-reynolds")
            else:
                stat("Temperature", "template" if fs.temperature_K is None
                     else f"{format_value(fs.temperature_K)} K").mark("strip-temperature")
                stat("Reynolds", "template" if fs.reynolds is None else sci(fs.reynolds)).mark("strip-reynolds")
            if cases:
                case = cases[0]
                start = ("fresh" if case.restart != "custom" else
                         f"from {Path(case.restart_ref).name}" if case.restart_ref else "from a solution")
                stat("Start", start).mark("strip-start")

    render()
    return render


def _names_dialog(frame: ProjectFrame, after: Callable[[], None]) -> Callable[[], None]:
    """What goes into a case name, as on the Sweep page (the same naming); returns what opens it."""
    with ui.dialog() as dialog, ui.card().classes("w-[34rem] max-w-full"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Case names").classes("as-dialog-title grow")
            ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark("names-close")
        box = ui.column().classes("w-full gap-3").mark("names-dialog")

    def both() -> None:
        render()
        after()

    def render() -> None:
        box.clear()
        project = frame.session.project
        with box:
            base_name_field(frame, both)
            if project.settings.freestream.mode == "manual":  # from altitude, the label is the altitude's
                text_field("Altitude label", project.sweep.altitude,
                           lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=both),
                           mark="names-altitude-label", side_label=True)
            naming_checkboxes(frame, both)
            names = [case.name for case in project.cases]
            shown = names[0] if len(names) == 1 else f"{names[0]} … {names[-1]}" if names else "—"
            with ui.row().classes("as-strip items-center gap-2"):
                ui.label("Names" if len(names) > 1 else "Name").classes("as-muted")
                ui.label(shown).classes("as-mono as-strong").mark("names-preview")
            hint("The same naming as the Sweep page. Each case keeps its restart when its name changes.")

    def open_names() -> None:
        render()
        dialog.open()

    return open_names


def _problems(frame: ProjectFrame, holders: dict) -> Callable[[], None]:
    """The checks as badges by Generate (a click lists them); Generate waits for the errors. Returns the redraw."""
    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Problems").classes("as-dialog-title grow")
            ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark(
                "problems-close")
        listing = ui.column().classes("w-full gap-2").mark("problems-list")

    def render() -> None:
        project = frame.session.project
        found = preflight(frame.session.directory, project, "generate")
        errors = [p.message for p in found if p.severity == "error"]
        warnings = [p.message for p in found if p.severity != "error"]
        generate = holders["generate"]
        generate.set_enabled(not has_errors(found))
        count = len(project.cases)
        generate.text = (f"Generate {count} config{'' if count == 1 else 's'}" if project.sweep.enabled
                         else "Generate configs")
        badges = holders["badges"]
        badges.clear()
        with badges:
            if not found:
                ui.label("No problems").classes("as-pill as-pill-done").mark("problems-none")
            if errors:
                ui.label(f"{len(errors)} error{'' if len(errors) == 1 else 's'}").classes(
                    "as-pill as-pill-failed as-problem-badge").mark("problems-errors").on("click", dialog.open)
            if warnings:
                ui.label(f"{len(warnings)} warning{'' if len(warnings) == 1 else 's'}").classes(
                    "as-pill as-pill-unconverged as-problem-badge").mark("problems-warnings").on(
                    "click", dialog.open)
        listing.clear()
        with listing:
            for message in errors:
                banner("error", f"Error: {message}").mark("problem-error")
            for message in warnings:
                banner("warning", message).mark("problem-warning")

    return render


def _insert(frame: ProjectFrame, option: RefOption, holders: dict):
    """An option from SU2's reference: a MARKER_ line into Boundaries, anything else into Extra options."""
    settings = frame.session.project.settings
    if option.key.startswith(MARKER_PREFIX):
        if settings.markers.get(option.key):
            return f"{option.key} is already in Boundaries"
        target, place = "boundaries", "Boundaries"
    else:
        if option.key in settings.overrides:
            return f"{option.key} is already in Extra options"
        target, place = "extra", "Extra options"

    def both() -> None:
        holders[target]()
        holders["tabs"].set_value(target)
        for name in ("strip", "problems", "counts", "preview", "reference"):
            holders[name]()

    message = frame.save(lambda p: set_parameter(p.settings, option.key, option.default_value), then=both)
    return message or f"Added {option.key} to {place}"

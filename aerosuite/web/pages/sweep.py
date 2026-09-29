"""Sweep: Mach/alpha/beta (and, from altitude, altitude) lists, naming, per-case restarts, problems and Generate."""
from pathlib import Path
from typing import Callable, Optional

from nicegui import ui

from ...engine.cfg import build_cases, case_freestream, read_template
from ...engine.editing import parse_value_list, update_sweep
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import find_collisions, format_value
from ..checks import generate_button, render_checks
from ..fields import text_field
from ..layout import ProjectFrame, open_session
from ..picker import pick_path
from ..ui_kit import banner, card, card_head, chip_button, field, hint, sci, secondary_button, table, td, td_box, th

RESTART_OPTIONS = ["none", "previous", "custom"]
NAMING = [
    ("include_mach", "Mach"),
    ("include_altitude", "Altitude"),
    ("include_alpha", "α"),
    ("include_beta", "β"),
    ("include_base", "Base name"),
]


def register() -> None:
    @ui.page("/sweep")
    def sweep_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "sweep", on_reload=lambda: body.refresh())

        holders: dict = {}

        def render_cases() -> None:
            # A plain synchronous rebuild, not `@ui.refreshable`: a select's `on_change` (e.g.
            # picking a restart choice) must leave the case table showing the right ref column
            # the instant `frame.save` returns, but a refreshable's `.refresh()` only
            # *schedules* its rebuild as a background task for the next event-loop tick — the
            # same reasoning settings.py records for its markers/overrides tables and preview.
            box = holders.get("cases")
            if box is None:
                return
            box.clear()
            with box:
                _case_table(frame, after)

        def render_problems() -> None:
            # Same reasoning as `render_cases`: tests read the Generate button's `.enabled`
            # (and the problem markers) right after a change, with no `await` in between.
            box = holders.get("problems")
            if box is None:
                return
            box.clear()
            with box:
                render_checks(frame, holders.get("generate"))

        def after() -> None:
            render_cases()
            render_problems()

        @ui.refreshable
        def body() -> None:
            frame.actions.clear()
            if not frame.session.project.sweep.enabled:
                holders.clear()  # render_cases / render_problems then do nothing
                banner("info", "The sweep is off for this project: it is a single case. "
                       "Switch the sweep on in Setup to run Mach/alpha/beta cases.").mark("sweep-off")
                return
            with frame.actions:
                holders["generate"] = generate_button(frame, render_problems)
            holders["problems"] = ui.column().classes("w-full gap-2")
            _sweep_fields(frame, after)
            with card(flush=True) as cases_card:
                holders["cases"] = cases_card
            render_cases()
            render_problems()

        with frame.content:
            body()


def _values(values: list[float]) -> str:
    return ", ".join(format_value(v) for v in values)


def _sweep_fields(frame: ProjectFrame, after: Callable[[], None]) -> None:
    sweep = frame.session.project.sweep
    with card("Flight conditions"):
        with ui.element("div").classes("as-grid-3"):
            for label, name in (("Mach", "mach"), ("Angle of attack α (deg)", "alpha"), ("Sideslip β (deg)", "beta")):
                with ui.column().classes("gap-1"):
                    text_field(
                        label, _values(getattr(sweep, name)),
                        lambda text, n=name: frame.save(
                            lambda p: update_sweep(p, **{n: parse_value_list(text)}), then=after),
                        mark=f"sweep-{name}", placeholder="e.g. 0.6, 0.8  or  -4:12:2",
                    )
            with ui.column().classes("gap-1"):
                if frame.session.project.settings.freestream.mode == "altitude":
                    text_field(
                        "Altitudes (km)", _values(sweep.altitudes_km),
                        lambda text: frame.save(lambda p: update_sweep(
                            p, altitudes_km=parse_value_list(text) if text.strip() else []), then=after),
                        mark="sweep-altitudes", placeholder="e.g. 0, 5, 11  or  0:12:3",
                    )
                    hint("each case is named with its altitude, e.g. 11km").mark("sweep-altitude-note")
                else:
                    text_field("Altitude label", sweep.altitude,
                               lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=after),
                               mark="sweep-altitude")
            with ui.column().classes("gap-1"):
                text_field("Base name", sweep.naming.base_name,
                           lambda text: frame.save(lambda p: update_sweep(p, base_name=text.strip()), then=after),
                           mark="sweep-base-name")
        with ui.row().classes("items-center gap-4"):
            ui.label("Name cases with").classes("as-label")
            for flag, label in NAMING:
                ui.checkbox(label, value=getattr(sweep.naming, flag),
                            on_change=lambda e, f=flag: _set_naming(frame, f, e.value, after)).mark(f"naming-{flag}")


def _set_naming(frame: ProjectFrame, flag: str, value: bool, after: Callable[[], None]) -> None:
    def change(p: Project) -> None:
        setattr(p.sweep.naming, flag, value)
        p.cases = build_cases(p)

    message = frame.save(change, then=after)
    if message:
        ui.notify(message, type="negative")


def _set_case(frame: ProjectFrame, name: str, after: Callable[[], None], **fields) -> None:
    def change(p: Project) -> None:
        case = next((c for c in p.cases if c.name == name), None)
        if case is None:
            raise ProjectError(f"Case {name} no longer exists")
        for key, value in fields.items():
            setattr(case, key, value)

    message = frame.save(change, then=after)
    if message:
        ui.notify(message, type="negative")


def _case_table(frame: ProjectFrame, after: Callable[[], None]) -> None:
    project = frame.session.project
    count = len(project.cases)
    with card_head("Cases", f"{count} case{'' if count == 1 else 's'}"):
        if project.cases:
            ui.space()
            ui.label("Set all restarts:").classes("as-label")
            chip_button("None", on_click=lambda: _set_all(frame, "none", after)).mark("restart-all-none")
            chip_button("Previous", on_click=lambda: _set_all(frame, "previous", after)).mark("restart-all-previous")
            chip_button("Custom…", on_click=lambda: _set_all_custom(frame, after)).mark("restart-all-custom")
    if not project.cases:
        ui.label("No cases yet: enter Mach numbers above.").classes("as-muted px-4 pb-4")
        return
    duplicates = set(find_collisions(case.name for case in project.cases))
    altitude_mode = project.settings.freestream.mode == "altitude"
    freestream = {}
    if altitude_mode:
        try:
            template = read_template(frame.session.directory, project)
        except AeroSuiteError:
            template = ""
        freestream = {row.name: row for row in case_freestream(project, template)}
    columns = "minmax(10rem, 1.2fr)" + (" minmax(4rem, .4fr)" if altitude_mode else "")
    columns += " repeat(3, minmax(3.5rem, .4fr))"
    headings = ["Case"] + (["Alt (km)"] if altitude_mode else []) + ["Mach", "α", "β"]
    if altitude_mode:
        columns += " minmax(6rem, .6fr) minmax(6rem, .6fr)"
        headings += ["Temperature", "Reynolds"]
    columns += " 11rem minmax(18rem, 2fr)"
    headings += ["Restart", "Restart from"]
    with table(columns):
        for heading in headings:
            th(heading)
        for case in project.cases:
            name_label = td(case.name, strong=True).mark(f"case-{case.name}")
            if case.name in duplicates:
                name_label.classes("as-dup").mark(f"case-{case.name} dup-{case.name}")
            if altitude_mode:
                td("—" if case.altitude_km is None else format_value(case.altitude_km)).mark(f"alt-{case.name}")
            td(format_value(case.mach))
            td(format_value(case.alpha))
            td(format_value(case.beta))
            if altitude_mode:
                row = freestream.get(case.name)
                values = row.values if row is not None else None
                td(f"{format_value(round(values.temperature_K, 2))} K" if values else "—").mark(f"temp-{case.name}")
                td(sci(values.reynolds) if values else "—").mark(f"re-{case.name}")
            with td_box():
                field(ui.select(
                    RESTART_OPTIONS, value=case.restart,
                    on_change=lambda e, n=case.name: _set_case(frame, n, after, restart=e.value, restart_ref=None),
                )).classes("w-full").mark(f"restart-{case.name}")
            with td_box():
                if case.restart == "custom":
                    with ui.column().classes("grow gap-0"):
                        text_field("Restart file or case folder", case.restart_ref,
                                   lambda text, n=case.name: frame.save(
                                       lambda p: _change_ref(p, n, text.strip() or None), then=after),
                                   mark=f"ref-{case.name}", mono=True)
                    secondary_button("Browse", on_click=lambda n=case.name: _browse_ref(frame, n, after)).mark(
                        f"ref-browse-{case.name}")


def set_all_restarts(project: Project, restart: str, folder: Optional[Path] = None) -> None:
    """Give every case the same restart choice.

    "previous" leaves the first case, and the first case of each altitude, at "none" (each altitude starts
    fresh); "custom" points each case at `folder / <case name>`, e.g. another study's runs/ folder.
    """
    for index, case in enumerate(project.cases):
        first_of_altitude = index == 0 or case.altitude_km != project.cases[index - 1].altitude_km
        if restart == "previous" and first_of_altitude:
            case.restart, case.restart_ref = "none", None
        elif restart == "custom":
            case.restart, case.restart_ref = "custom", str(Path(folder) / case.name)
        else:
            case.restart, case.restart_ref = restart, None


def _set_all(frame: ProjectFrame, restart: str, after: Callable[[], None], folder: Optional[Path] = None) -> None:
    message = frame.save(lambda p: set_all_restarts(p, restart, folder), then=after)
    if message:
        ui.notify(message, type="negative")


async def _set_all_custom(frame: ProjectFrame, after: Callable[[], None]) -> None:
    chosen = await pick_path("Folder holding one folder per case (e.g. another study's runs/)", mode="folder")
    if chosen is not None:
        _set_all(frame, "custom", after, chosen)


def _change_ref(p: Project, name: str, ref) -> None:
    case = next((c for c in p.cases if c.name == name), None)
    if case is None:
        raise ProjectError(f"Case {name} no longer exists")
    case.restart_ref = ref


async def _browse_ref(frame: ProjectFrame, name: str, after: Callable[[], None]) -> None:
    chosen = await pick_path("Restart file or case folder", mode="any")
    if chosen is None:
        return
    message = frame.save(lambda p: _change_ref(p, name, str(chosen)), then=after)
    if message:
        ui.notify(message, type="negative")

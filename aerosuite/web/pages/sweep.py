"""Sweep: Mach/alpha/beta lists, naming, per-case restarts, problems and Generate."""
from typing import Callable

from nicegui import ui

from ...engine.cfg import build_cases, generate_configs
from ...engine.editing import parse_value_list, update_sweep
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import find_collisions, format_value
from ...engine.preflight import has_errors, preflight
from ..fields import text_field
from ..layout import ProjectFrame, open_session

RESTART_OPTIONS = ["none", "previous", "initial", "custom", "from_case"]
NAMING = [
    ("include_mach", "Mach"),
    ("include_altitude", "Altitude"),
    ("include_alpha", "Alpha"),
    ("include_beta", "Beta"),
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
                _problems(frame, render_problems)

        def after() -> None:
            render_cases()
            render_problems()

        @ui.refreshable
        def body() -> None:
            _sweep_fields(frame, after)
            ui.label("Cases").classes("text-lg")
            holders["cases"] = ui.column().classes("w-full gap-2")
            ui.label("Checks").classes("text-lg")
            holders["problems"] = ui.column().classes("w-full gap-2")
            render_cases()
            render_problems()

        with frame.content:
            ui.label("Sweep").classes("text-2xl")
            body()


def _values(values: list[float]) -> str:
    return ", ".join(format_value(v) for v in values)


def _sweep_fields(frame: ProjectFrame, after: Callable[[], None]) -> None:
    sweep = frame.session.project.sweep
    for label, name in (("Mach", "mach"), ("Alpha (deg)", "alpha"), ("Beta (deg)", "beta")):
        text_field(
            label, _values(getattr(sweep, name)),
            lambda text, n=name: frame.save(lambda p: update_sweep(p, **{n: parse_value_list(text)}), then=after),
            mark=f"sweep-{name}", placeholder="e.g. 0.6, 0.8  or  -4:12:2",
        )
    text_field("Altitude label", sweep.altitude,
               lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=after),
               mark="sweep-altitude")
    text_field("Base name", sweep.naming.base_name,
               lambda text: frame.save(lambda p: update_sweep(p, base_name=text.strip()), then=after),
               mark="sweep-base-name")
    with ui.row().classes("items-center gap-4"):
        ui.label("Include in case names:")
        for flag, label in NAMING:
            ui.checkbox(label, value=getattr(sweep.naming, flag),
                        on_change=lambda e, f=flag: _set_naming(frame, f, e.value, after)).mark(f"naming-{flag}")
    text_field(
        "Initial restart file (used by cases with restart 'initial')", frame.session.project.run.initial_restart,
        lambda text: frame.save(lambda p: setattr(p.run, "initial_restart", text.strip() or None), then=after),
        mark="initial-restart",
    )


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
    if not project.cases:
        ui.label("No cases yet: enter Mach numbers above.").classes("text-grey-7")
        return
    duplicates = set(find_collisions(case.name for case in project.cases))
    with ui.grid(columns=6).classes("w-full items-center gap-x-4 gap-y-1"):
        for heading in ("Case", "Mach", "Alpha", "Beta", "Restart", "Restart from"):
            ui.label(heading).classes("text-bold")
        earlier: list[str] = []
        for case in project.cases:
            name_label = ui.label(case.name).mark(f"case-{case.name}")
            if case.name in duplicates:
                name_label.classes("text-negative text-bold").mark(f"case-{case.name} dup-{case.name}")
            ui.label(format_value(case.mach))
            ui.label(format_value(case.alpha))
            ui.label(format_value(case.beta))
            ui.select(
                RESTART_OPTIONS, value=case.restart,
                on_change=lambda e, n=case.name: _set_case(
                    frame, n, after, restart=e.value, restart_ref=None),
            ).mark(f"restart-{case.name}")
            if case.restart == "from_case":
                ui.select(
                    list(earlier), value=case.restart_ref if case.restart_ref in earlier else None,
                    on_change=lambda e, n=case.name: _set_case(frame, n, after, restart_ref=e.value),
                ).mark(f"ref-{case.name}")
            elif case.restart == "custom":
                text_field("Restart file", case.restart_ref,
                           lambda text, n=case.name: frame.save(
                               lambda p: _change_ref(p, n, text.strip() or None), then=after),
                           mark=f"ref-{case.name}")
            else:
                ui.label("")
            earlier.append(case.name)


def _change_ref(p: Project, name: str, ref) -> None:
    case = next((c for c in p.cases if c.name == name), None)
    if case is None:
        raise ProjectError(f"Case {name} no longer exists")
    case.restart_ref = ref


def _problems(frame: ProjectFrame, refresh: Callable[[], None]) -> None:
    found = preflight(frame.session.directory, frame.session.project, "generate")
    if not found:
        ui.label("No problems found.").classes("text-positive").mark("problems-none")
    for problem in found:
        style = "text-negative" if problem.severity == "error" else "text-warning"
        prefix = "Error" if problem.severity == "error" else "Warning"
        ui.label(f"{prefix}: {problem.message}").classes(style).mark(f"problem-{problem.severity}")

    def generate() -> None:
        stale = frame.ensure_current()
        if stale is not None:
            ui.notify("Project changed on disk and was reloaded; generate again", type="warning")
            return
        try:
            written = generate_configs(frame.session.directory, frame.session.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Wrote {len(written)} configs", type="positive")
        frame.refresh()
        refresh()

    button = ui.button("Generate configs", on_click=generate).mark("generate")
    button.set_enabled(not has_errors(found))

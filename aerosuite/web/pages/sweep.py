"""Sweep, in two tabs. Conditions: the Mach/alpha/beta (and, from altitude, altitude) lists, the case names, one
restart rule for the sweep and what all this makes. Cases: every case (folded by Mach and altitude when there are
many) with its restart; a case can be set differently from the rule. Problems and Generate stay on top."""
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
from ..run_view import case_groups, layout
from ..sweep_view import case_formula, detect_rule, restart_text, rule_restarts, values_text
from ..ui_kit import banner, card, card_head, field, flat_button, hint, sci, secondary_button, table, td, td_box, th

RESTART_OPTIONS = ["none", "previous", "custom"]
RULE_TEXT = [  # (rule, marker, what the tile says, the small print)
    ("none", "restart-all-none", "Every case starts from scratch", ""),
    ("previous", "restart-all-previous", "Each case continues from the previous one",
     "the first case of each altitude starts from scratch"),
    ("custom", "restart-all-custom", "All continue from a folder of solutions…",
     "one folder per case, e.g. another study's runs/"),
]
TABS = (("conditions", "Conditions"), ("cases", "Cases"))
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
        state = {"tab": "conditions", "editing": None, "open": {}}  # the tab, the case being changed, opened groups

        def render_cases() -> None:
            # Plain synchronous rebuilds, not `@ui.refreshable`: a select's `on_change` (e.g. picking a restart
            # choice) must leave the page showing the right thing the instant `frame.save` returns, but a
            # refreshable's `.refresh()` only *schedules* its rebuild for the next event-loop tick.
            if "cases" not in holders:
                return
            holders["made"].clear()
            with holders["made"]:
                _restart_rule(frame, after)
            holders["summary"].clear()
            with holders["summary"]:
                _summary(frame)
            holders["cases"].clear()
            with holders["cases"]:
                _case_table(frame, after, state)
            count = len(frame.session.project.cases)
            holders["tab-cases"].text = f"Cases {count}"

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

        def show(tab: str) -> None:
            state["tab"] = tab
            for key, _ in TABS:
                holders[f"tab-{key}"].classes(**({"add": "as-tab-on"} if key == tab else {"remove": "as-tab-on"}))
                holders[f"pane-{key}"].set_visibility(key == tab)

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
            with ui.row().classes("as-tabs w-full gap-1").mark("sweep-tabs"):
                for key, label in TABS:
                    holders[f"tab-{key}"] = ui.label(label).classes("as-tab").mark(f"sweep-tab-{key}")
                    holders[f"tab-{key}"].on("click", lambda _, k=key: show(k))
            with ui.element("div").classes("as-columns w-full") as holders["pane-conditions"]:
                with ui.column().classes("gap-4 w-full"):
                    _sweep_fields(frame, after)
                    with card("Restarts"):
                        holders["made"] = ui.column().classes("w-full gap-2")
                with card("What this makes"):
                    holders["summary"] = ui.column().classes("w-full gap-2")
            with card(flush=True) as pane:
                holders["pane-cases"] = holders["cases"] = pane
            render_cases()
            render_problems()
            show(state["tab"])

        with frame.content:
            body()


def _sweep_fields(frame: ProjectFrame, after: Callable[[], None]) -> None:
    sweep = frame.session.project.sweep
    with card("Flight conditions"):
        for label, name in (("Mach", "mach"), ("Angle of attack α (deg)", "alpha"), ("Sideslip β (deg)", "beta")):
            with ui.column().classes("gap-1 w-full"):
                text_field(
                    label, values_text(getattr(sweep, name)),
                    lambda text, n=name: frame.save(
                        lambda p: update_sweep(p, **{n: parse_value_list(text)}), then=after),
                    mark=f"sweep-{name}", placeholder="e.g. 0.6, 0.8  or  -4:12:2 (from:to:step)",
                )
        with ui.column().classes("gap-1 w-full"):
            if frame.session.project.settings.freestream.mode == "altitude":
                text_field(
                    "Altitudes (km)", values_text(sweep.altitudes_km),
                    lambda text: frame.save(lambda p: update_sweep(
                        p, altitudes_km=parse_value_list(text) if text.strip() else []), then=after),
                    mark="sweep-altitudes", placeholder="e.g. 0, 5, 11  or  0:12:3 (from:to:step)",
                )
                hint("each case is named with its altitude, e.g. 11km").mark("sweep-altitude-note")
            else:
                text_field("Altitude label", sweep.altitude,
                           lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=after),
                           mark="sweep-altitude")
        with ui.column().classes("gap-1 w-full"):
            text_field("Base name", sweep.naming.base_name,
                       lambda text: frame.save(lambda p: update_sweep(p, base_name=text.strip()), then=after),
                       mark="sweep-base-name")
        with ui.row().classes("items-center gap-4"):
            ui.label("Name cases with").classes("as-label")
            for flag, label in NAMING:
                ui.checkbox(label, value=getattr(sweep.naming, flag),
                            on_change=lambda e, f=flag: _set_naming(frame, f, e.value, after)).mark(f"naming-{flag}")


def _restart_rule(frame: ProjectFrame, after: Callable[[], None]) -> None:
    """One restart rule for the whole sweep (the one the most cases follow); a click sets every case to it."""
    cases = frame.session.project.cases
    rule, folder, differing = detect_rule(cases)
    for key, mark, text, small in RULE_TEXT:
        on = key == rule and bool(cases)
        with ui.row().classes("as-choice-tile as-rule items-center gap-2 no-wrap w-full" + (
                " as-choice-selected" if on else "")).mark(mark) as tile:
            ui.icon("radio_button_checked" if on else "radio_button_unchecked")
            with ui.column().classes("gap-0"):
                ui.label(text).classes("as-strong" if on else "")
                if on and key == "custom" and folder:
                    ui.label(folder).classes("as-mono as-muted")
                elif small:
                    ui.label(small).classes("as-muted")
        if key == "custom":
            tile.on("click", lambda: _set_all_custom(frame, after))
        else:
            tile.on("click", lambda _, k=key: _set_all(frame, k, after))
    if differing:
        count = len(differing)
        hint(f"{count} case{' is' if count == 1 else 's are'} set differently (Cases tab); choosing a rule here "
             "sets every case.").mark("restart-differs")


def _freestream(frame: ProjectFrame) -> dict:
    project = frame.session.project
    if project.settings.freestream.mode != "altitude":
        return {}
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        template = ""
    return {row.name: row for row in case_freestream(project, template)}


def _summary(frame: ProjectFrame) -> None:
    """What the conditions make: the count as a product, the names, one row per Mach and altitude."""
    project = frame.session.project
    sweep, cases = project.sweep, project.cases
    if not cases:
        ui.label("No cases yet: enter Mach numbers.").classes("as-muted").mark("sweep-none")
        return
    altitude_mode = project.settings.freestream.mode == "altitude"
    with ui.row().classes("items-baseline gap-2"):
        ui.label(str(len(cases))).classes("as-run-big").mark("sweep-count")
        ui.label("case" if len(cases) == 1 else "cases").classes("as-muted")
        ui.label("= " + case_formula(len(sweep.mach), len(sweep.alpha), len(sweep.beta),
                                     len(sweep.altitudes_km) if altitude_mode else 0)).classes(
            "as-muted").mark("sweep-formula")
    names = cases[0].name if len(cases) == 1 else f"{cases[0].name} … {cases[-1].name}"
    ui.label(f"Names: {names}").classes("as-mono as-muted").mark("sweep-names")
    freestream = _freestream(frame)
    columns = "minmax(4rem, 1fr)" + (" repeat(3, minmax(5rem, 1fr))" if altitude_mode else "") + " minmax(4rem, .6fr)"
    with table(columns).classes("as-table-compact").mark("sweep-summary"):
        for heading in ["Mach"] + (["Altitude", "Temperature", "Reynolds"] if altitude_mode else []) + ["Cases"]:
            th(heading)
        by_name = {case.name: case for case in cases}
        for group in case_groups(cases):
            first = by_name[group.names[0]]
            td(format_value(first.mach), strong=True)
            if altitude_mode:
                row = freestream.get(first.name)
                values = row.values if row is not None else None
                td("—" if first.altitude_km is None else f"{format_value(first.altitude_km)} km")
                td(f"{format_value(round(values.temperature_K, 2))} K" if values else "—")
                td(sci(values.reynolds) if values else "—")
            td(str(len(group.names)))


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


def _case_table(frame: ProjectFrame, after: Callable[[], None], state: dict) -> None:
    """Every case with its restart in words; "change" turns one row into its restart choice. From 13 cases with
    more than one Mach or altitude the rows fold into groups."""
    project = frame.session.project
    cases = project.cases
    count = len(cases)
    rule, _, differing = detect_rule(cases)
    rule_words = {"none": "every case starts from scratch", "previous": "each continues from the previous one",
                  "custom": "all continue from a folder of solutions"}[rule]
    subtitle = f"{count} case{'' if count == 1 else 's'}" + (f" · {rule_words}" if cases else "") + (
        f" · {len(differing)} set differently" if differing else "")
    card_head("Cases", subtitle)
    if not cases:
        ui.label("No cases yet: enter Mach numbers on the Conditions tab.").classes("as-muted px-4 pb-4")
        return
    duplicates = set(find_collisions(case.name for case in cases))
    altitude_mode = project.settings.freestream.mode == "altitude"
    freestream = _freestream(frame)
    index_of = {case.name: i for i, case in enumerate(cases)}
    columns = "minmax(10rem, 1.2fr)" + (" minmax(4rem, .4fr)" if altitude_mode else "")
    columns += " repeat(3, minmax(3rem, .35fr))"
    headings = ["Case"] + (["Alt (km)"] if altitude_mode else []) + ["Mach", "α", "β"]
    if altitude_mode:
        columns += " minmax(6rem, .5fr) minmax(6rem, .5fr)"
        headings += ["Temperature", "Reynolds"]
    columns += " minmax(18rem, 2.4fr) 6rem"
    headings += ["Restart", ""]

    def redraw() -> None:
        box = holders_box
        box.clear()
        with box:
            _case_table(frame, after, state)

    holders_box = ui.context.slot.parent

    def row(case) -> None:
        name_label = td(case.name, strong=True).mark(f"case-{case.name}")
        if case.name in duplicates:
            name_label.classes("as-dup").mark(f"case-{case.name} dup-{case.name}")
        if altitude_mode:
            td("—" if case.altitude_km is None else format_value(case.altitude_km)).mark(f"alt-{case.name}")
        td(format_value(case.mach))
        td(format_value(case.alpha))
        td(format_value(case.beta))
        if altitude_mode:
            found = freestream.get(case.name)
            values = found.values if found is not None else None
            td(f"{format_value(round(values.temperature_K, 2))} K" if values else "—").mark(f"temp-{case.name}")
            td(sci(values.reynolds) if values else "—").mark(f"re-{case.name}")
        differs = case.name in differing
        editing = state["editing"] == case.name
        with td_box() as cell:
            if editing:
                cell.classes("as-edit-cell")
                with ui.element("div").classes("w-40"):
                    field(ui.select(
                        RESTART_OPTIONS, value=case.restart,
                        on_change=lambda e, n=case.name: _set_case(frame, n, after, restart=e.value, restart_ref=None),
                    )).props("dense").classes("w-full").mark(f"restart-{case.name}")
                if case.restart == "custom":
                    with ui.column().classes("grow gap-0"):
                        text_field("Restart file or case folder", case.restart_ref,
                                   lambda text, n=case.name: frame.save(
                                       lambda p: _change_ref(p, n, text.strip() or None), then=after),
                                   mark=f"ref-{case.name}", mono=True)
                    secondary_button("Browse", on_click=lambda n=case.name: _browse_ref(frame, n, after)).mark(
                        f"ref-browse-{case.name}")
            else:
                text = ui.label(restart_text(cases, index_of[case.name])).mark(f"restart-text-{case.name}")
                text.classes("as-truncate" + ("" if differs else " as-muted"))
                if differs:
                    ui.label("differs").classes("as-pill as-pill-unconverged").mark(f"differs-{case.name}")
        with td_box():
            def toggle(n=case.name) -> None:
                state["editing"] = None if state["editing"] == n else n
                redraw()
            flat_button("Done" if editing else "Change", on_click=toggle).props("dense").mark(f"change-{case.name}")

    with table(columns).classes("as-table-compact"):
        for heading in headings:
            th(heading)
        if layout(cases) != "groups":
            for case in cases:
                row(case)
            return
        by_name = {case.name: case for case in cases}
        for number, group in enumerate(case_groups(cases)):
            changed = [n for n in group.names if n in differing]
            opened = state["open"].get(group.label, bool(changed) or state["editing"] in group.names)
            with td_box() as head:
                head.classes("as-group-cell as-group-name").style("grid-column: 1 / -1").mark(f"sweep-group-{number}")

                def fold(_=None, label=group.label, now=opened) -> None:
                    state["open"][label] = not now
                    redraw()
                head.on("click", fold)
                ui.icon("expand_more" if opened else "chevron_right")
                ui.label(group.label).classes("as-strong")
                ui.label(f"{len(group.names)} cases").classes("as-muted")
                if changed:
                    ui.label(f"{len(changed)} set differently").classes("as-pill as-pill-unconverged")
            if opened:
                for name in group.names:
                    row(by_name[name])


def set_all_restarts(project: Project, restart: str, folder: Optional[Path] = None) -> None:
    """Give every case the sweep's restart rule (sweep_view.rule_restarts)."""
    for case, (choice, ref) in zip(project.cases, rule_restarts(project.cases, restart, folder)):
        case.restart, case.restart_ref = choice, ref


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

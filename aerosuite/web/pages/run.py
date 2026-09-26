"""Run: checks, each case's latest status, rerun selection, Submit / Cancel and job history."""
from typing import NamedTuple, Optional

from nicegui import ui

from ...engine.cfg import generate_configs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import plan_restarts
from ...engine.naming import format_value
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import restart_file
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session
from ..ui_kit import (banner, card, card_head, chip_button, danger_button, failure_row, ok_line, pill, primary_button,
                      secondary_button, summary_tile, table, td, td_box, th)

POLL_SECONDS = 2.0
SELECTORS = [  # (label, statuses to tick; None = every case)
    ("All", None),
    ("Failed", {"FAILED"}),
    ("Unconverged", {"UNCONVERGED"}),
    ("Not run", {NOT_RUN}),
    ("None", set()),
]


def register() -> None:
    @ui.page("/run")
    def run_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "run", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            pages.append(RunPage(frame))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _snapshot(view: JobView) -> tuple:
    """What the page shows from `view`: the active job, each case's row and the job history."""
    active = view.active
    return (
        (active.id, active.state) if active is not None else None,
        tuple((row.name, row.status, row.job_id, row.failure_tail) for row in view.overview.rows),
        tuple((job.id, job.state, job.finished) for job in view.overview.jobs),
        tuple(view.overview.problems),
    )


def _answer(dialog: ui.dialog, value: bool) -> None:
    """Submit a dialog's result and delete it immediately (see the comment in confirm_cancel)."""
    dialog.submit(value)
    dialog.delete()


def tile_counts(rows) -> tuple[int, int, int, int]:
    """(converged, running, needs attention, pending) for the summary tiles."""
    statuses = [row.status for row in rows]
    converged = statuses.count("CONVERGED")
    running = statuses.count("RUNNING")
    attention = sum(statuses.count(s) for s in ("FAILED", "UNCONVERGED", "CANCELLED"))
    pending = sum(statuses.count(s) for s in ("PENDING", NOT_RUN))
    return converged, running, attention, pending


class _Selection(NamedTuple):
    ticked: list[str]  # ticked case names, in case order
    chosen: bool  # "Continue from each case's last solution" is ticked
    no_solution: list[str]  # ticked cases with nothing to continue from


class RunPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.ticked = {case.name for case in frame.session.project.cases}
        self.continue_choice: Optional[bool] = None  # None: the default for the ticked cases
        self.continue_cases: list[str] = []
        self.has_errors = False
        self.was_active = False
        self.shown: Optional[tuple] = None  # _snapshot() of the view on screen
        self.dialogs_open = 0  # a re-render while Cancel's confirm dialog awaits would orphan it
        self.holder = ui.column().classes("as-content w-full")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)

    @property
    def directory(self):
        return self.frame.session.directory

    @property
    def project(self):
        return self.frame.session.project

    def poll(self) -> None:
        if self.dialogs_open:
            return
        try:
            view = WATCHER.state(self.directory, self.project)
        except AeroSuiteError:
            return
        if view.active is None and not self.was_active:
            return
        # Rebuild only when something shown changed: a rebuild every poll would collapse an open
        # "Why it failed" and let clicks land on deleted elements during a long sweep.
        if _snapshot(view) != self.shown:
            self.render(view)
            self.frame.refresh()

    def render(self, view: Optional[JobView] = None) -> None:
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.project)
            except AeroSuiteError as exc:
                self.holder.clear()
                self.frame.actions.clear()
                with self.holder:
                    banner("error", f"Error: {exc}").mark("run-error")
                return
        self.was_active = view.active is not None
        self.shown = _snapshot(view)
        self.ticked &= {case.name for case in self.project.cases}  # the cases may have been rebuilt
        self.holder.clear()
        self.frame.actions.clear()
        with self.holder:
            self._checks(view)
            selection = self._selection(view)
            self._plan(view, selection)
            self._tiles(view)
            self._cases(view, selection)
            self._history(view)
        with self.frame.actions:
            self._actions(view, selection)

    def _checks(self, view: JobView) -> None:
        problems = preflight(self.directory, self.project, "submit")
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        if not found:
            ok_line("No problems found.").mark("run-problems-none")
        for severity, message in found:
            kind = "error" if severity == "error" else "warning"
            prefix = "Error" if severity == "error" else "Warning"
            banner(kind, f"{prefix}: {message}").mark(f"run-problem-{severity}")

    def _selection(self, view: JobView) -> _Selection:
        ticked = [case.name for case in self.project.cases if case.name in self.ticked]
        status = {row.name: row.status for row in view.overview.rows}
        no_solution = [name for name in ticked if restart_file(self.directory, name) is None]
        default = bool(ticked) and not no_solution and all(status.get(n) == "UNCONVERGED" for n in ticked)
        chosen = (default if self.continue_choice is None else self.continue_choice) and not no_solution
        self.continue_cases = ticked if chosen else []
        return _Selection(ticked, chosen, no_solution)

    def _plan(self, view: JobView, selection: _Selection) -> None:
        if not selection.ticked or view.active is not None:
            return
        try:
            plan = plan_restarts(self.directory, self.project, selection.ticked, self.continue_cases)
        except AeroSuiteError as exc:
            banner("error", f"Error: {exc}").mark("plan-error")
        else:
            for warning in plan.warnings:
                banner("warning", f"Warning: {warning}").mark("plan-warning")

    def _tiles(self, view: JobView) -> None:
        converged, running, attention, pending = tile_counts(view.overview.rows)
        with ui.element("div").classes("as-tiles"):
            summary_tile("Converged", converged).mark("tile-converged")
            summary_tile("Running", running).mark("tile-running")
            summary_tile("Needs attention", attention, "danger" if attention else None).mark("tile-attention")
            summary_tile("Pending", pending).mark("tile-pending")

    def _cases(self, view: JobView, selection: _Selection) -> None:
        with card(flush=True):
            with card_head("Cases"):
                if view.overview.rows:
                    for label, statuses in SELECTORS:
                        chip_button(label, on_click=lambda s=statuses: self._select(view, s)).mark(
                            f"select-{label.lower().replace(' ', '-')}")
                    ui.space()
                    box = ui.checkbox("Continue from each case's last solution", value=selection.chosen,
                                      on_change=lambda e: self._set_continue(e.value)).mark("continue")
                    if selection.no_solution:
                        box.disable()
            if not view.overview.rows:
                ui.label("No cases yet: set up the sweep first.").classes("as-muted px-4 pb-4")
                return
            if selection.no_solution:
                ui.label("No solution to continue from: " + ", ".join(selection.no_solution)).classes(
                    "as-hint px-4 pb-2").mark("continue-missing")
            cases = {case.name: case for case in self.project.cases}
            with table("36px minmax(10rem, 1.4fr) repeat(3, minmax(3.5rem, .5fr)) minmax(8rem, 1fr) "
                       "minmax(9rem, 1fr)"):
                for heading in ("", "Case", "Mach", "α", "β", "Status", "Last job"):
                    th(heading)
                for row in view.overview.rows:
                    case = cases.get(row.name)
                    with td_box():
                        ui.checkbox(value=row.name in self.ticked,
                                    on_change=lambda e, n=row.name: self._tick(n, e.value)).mark(f"tick-{row.name}")
                    td(row.name, strong=True)
                    td(format_value(case.mach) if case else "")
                    td(format_value(case.alpha) if case else "")
                    td(format_value(case.beta) if case else "")
                    with td_box():
                        pill(row.status).mark(f"status-{row.name}")
                    td(row.job_id or "—", mono=True).mark(f"job-{row.name}")
                    if row.status == "FAILED" and row.failure_tail:
                        failure_row(row.failure_tail).mark(f"tail-{row.name}")

    def _actions(self, view: JobView, selection: _Selection) -> None:
        if view.active is not None:
            danger_button("Cancel job", on_click=self.confirm_cancel).mark("cancel")
        submit = primary_button(f"Submit {_plural(len(selection.ticked), 'case')}", on_click=self.submit)
        submit.mark("submit").set_enabled(view.active is None and bool(selection.ticked) and not self.has_errors)

    def _history(self, view: JobView) -> None:
        with card(flush=True):
            card_head("Job history")
            if not view.overview.jobs:
                ui.label("No jobs yet.").classes("as-muted px-4 pb-4").mark("history-none")
                return
            with table("minmax(10rem, 1fr) minmax(7rem, auto) minmax(5rem, auto) minmax(9rem, 1fr) "
                       "minmax(9rem, 1fr)"):
                for heading in ("Job", "State", "Cases", "Started", "Finished"):
                    th(heading)
                for job in view.overview.jobs:
                    td(job.id, mono=True).mark(f"history-{job.id}")
                    with td_box():
                        pill(job.state)
                    td(_plural(len(job.cases), "case"))
                    td(f"{job.created:%Y-%m-%d %H:%M}")
                    td(f"{job.finished:%Y-%m-%d %H:%M}" if job.finished else "—")

    def _select(self, view: JobView, statuses: Optional[set]) -> None:
        rows = view.overview.rows
        self.ticked = {r.name for r in rows} if statuses is None else {r.name for r in rows if r.status in statuses}
        self.continue_choice = None
        self.render()

    def _tick(self, name: str, value: bool) -> None:
        if value:
            self.ticked.add(name)
        else:
            self.ticked.discard(name)
        self.continue_choice = None
        self.render()

    def _set_continue(self, value: bool) -> None:
        self.continue_choice = value
        self.render()

    def submit(self) -> None:
        stale = self.frame.ensure_current(notify=False)
        if stale is not None:
            if self.frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; submit again", type="warning")
            return
        cases = [case.name for case in self.project.cases if case.name in self.ticked]
        errors = [p for p in preflight(self.directory, self.project, "submit") if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            self.render()
            return
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            WATCHER.submit(self.directory, self.project, cases, self.continue_cases)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            self.render()
            return
        ui.notify(f"Started {_plural(len(cases), 'case')}", type="positive")
        self.frame.refresh()
        self.render()

    async def confirm_cancel(self) -> None:
        # poll() must not rebuild the page (and delete this button's row) while this dialog is
        # up: that would orphan its slot and break dialog creation for a second click queued
        # right after this one, before either has had a chance to run.
        self.dialogs_open += 1
        try:
            with ui.dialog() as dialog, ui.card():
                ui.label("Cancel the running job? Cases that have not finished are marked CANCELLED.")
                with ui.row().classes("w-full justify-end gap-2"):
                    # Delete the dialog the instant it is answered, in the same click, rather
                    # than after `await dialog` resumes (which needs a further event-loop tick):
                    # otherwise its buttons — "cancel-confirm" / "cancel-keep" — stay findable
                    # by marker, and a second Cancel click racing ahead of that tick can submit
                    # this (already-answered) dialog again instead of the new one it opens.
                    secondary_button("Keep running", on_click=lambda: _answer(dialog, False)).mark("cancel-keep")
                    danger_button("Cancel the job", on_click=lambda: _answer(dialog, True)).mark("cancel-confirm")
            confirmed = await dialog
        finally:
            self.dialogs_open -= 1
        if not confirmed:
            return
        try:
            job = WATCHER.cancel(self.directory, self.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        if job is not None:
            ui.notify(f"Job {job.id}: {job.state.value}", type="info")
        self.frame.refresh()
        self.render()

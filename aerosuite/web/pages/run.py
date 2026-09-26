"""Run: checks, each case's latest status, rerun selection, Submit / Cancel and job history."""
from typing import Optional

from nicegui import ui

from ...engine.cfg import generate_configs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import plan_restarts
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import restart_file
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session

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
        self.holder = ui.column().classes("w-full gap-4")
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
                with self.holder:
                    ui.label(f"Error: {exc}").classes("text-negative").mark("run-error")
                return
        self.was_active = view.active is not None
        self.shown = _snapshot(view)
        self.ticked &= {case.name for case in self.project.cases}  # the cases may have been rebuilt
        self.holder.clear()
        with self.holder:
            self._checks(view)
            self._cases(view)
            self._actions(view)
            self._history(view)

    def _checks(self, view: JobView) -> None:
        ui.label("Checks").classes("text-lg")
        problems = preflight(self.directory, self.project, "submit")
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        if not found:
            ui.label("No problems found.").classes("text-positive").mark("run-problems-none")
        for severity, message in found:
            style = "text-negative" if severity == "error" else "text-warning"
            prefix = "Error" if severity == "error" else "Warning"
            ui.label(f"{prefix}: {message}").classes(style).mark(f"run-problem-{severity}")

    def _cases(self, view: JobView) -> None:
        ui.label("Cases").classes("text-lg")
        if not view.overview.rows:
            ui.label("No cases yet: set up the sweep first.").classes("text-grey-7")
            return
        with ui.row().classes("gap-2 items-center"):
            ui.label("Select:")
            for label, statuses in SELECTORS:
                ui.button(label, on_click=lambda s=statuses: self._select(view, s)).props(
                    "flat dense no-caps").mark(f"select-{label.lower().replace(' ', '-')}")
        with ui.grid(columns=4).classes("w-full items-center gap-x-4 gap-y-1").style(
            "grid-template-columns: 2.5rem minmax(10rem, auto) minmax(10rem, auto) 1fr"
        ):
            for heading in ("", "Case", "Status", "Last job"):
                ui.label(heading).classes("text-bold")
            for row in view.overview.rows:
                ui.checkbox(value=row.name in self.ticked,
                            on_change=lambda e, n=row.name: self._tick(n, e.value)).mark(f"tick-{row.name}")
                ui.label(row.name)
                with ui.column().classes("gap-0"):
                    ui.label("Not run" if row.status == NOT_RUN else row.status).mark(f"status-{row.name}")
                    if row.status == "FAILED" and row.failure_tail:
                        with ui.expansion("Why it failed").mark(f"tail-{row.name}"):
                            ui.label(row.failure_tail).classes("font-mono text-xs whitespace-pre-wrap")
                ui.label(row.job_id or "—").mark(f"job-{row.name}")

    def _actions(self, view: JobView) -> None:
        ticked = [case.name for case in self.project.cases if case.name in self.ticked]
        status = {row.name: row.status for row in view.overview.rows}
        no_solution = [name for name in ticked if restart_file(self.directory, name) is None]
        default = bool(ticked) and not no_solution and all(status.get(n) == "UNCONVERGED" for n in ticked)
        chosen = (default if self.continue_choice is None else self.continue_choice) and not no_solution
        self.continue_cases = ticked if chosen else []
        box = ui.checkbox("Continue from each case's last solution", value=chosen,
                          on_change=lambda e: self._set_continue(e.value)).mark("continue")
        if no_solution:
            box.disable()
            ui.label("No solution to continue from: " + ", ".join(no_solution)).classes(
                "text-xs text-grey-7").mark("continue-missing")
        if ticked and view.active is None:
            try:
                plan = plan_restarts(self.directory, self.project, ticked, self.continue_cases)
            except AeroSuiteError as exc:
                ui.label(f"Error: {exc}").classes("text-negative").mark("plan-error")
            else:
                for warning in plan.warnings:
                    ui.label(f"Warning: {warning}").classes("text-warning").mark("plan-warning")
        with ui.row().classes("gap-2"):
            submit = ui.button(f"Submit {_plural(len(ticked), 'case')}", on_click=self.submit).mark("submit")
            submit.set_enabled(view.active is None and bool(ticked) and not self.has_errors)
            if view.active is not None:
                ui.button("Cancel", on_click=self.confirm_cancel).props("color=negative").mark("cancel")

    def _history(self, view: JobView) -> None:
        ui.label("Job history").classes("text-lg")
        if not view.overview.jobs:
            ui.label("No jobs yet.").classes("text-grey-7").mark("history-none")
            return
        for job in view.overview.jobs:
            finished = f", finished {job.finished:%Y-%m-%d %H:%M}" if job.finished else ""
            ui.label(f"{job.id} — {job.state.value}, {_plural(len(job.cases), 'case')}, "
                     f"started {job.created:%Y-%m-%d %H:%M}{finished}").mark(f"history-{job.id}")

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
                with ui.row():
                    # Delete the dialog the instant it is answered, in the same click, rather
                    # than after `await dialog` resumes (which needs a further event-loop tick):
                    # otherwise its buttons — "cancel-confirm" / "cancel-keep" — stay findable
                    # by marker, and a second Cancel click racing ahead of that tick can submit
                    # this (already-answered) dialog again instead of the new one it opens.
                    ui.button("Cancel the job", on_click=lambda: _answer(dialog, True)).props(
                        "color=negative").mark("cancel-confirm")
                    ui.button("Keep running", on_click=lambda: _answer(dialog, False)).props(
                        "flat").mark("cancel-keep")
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

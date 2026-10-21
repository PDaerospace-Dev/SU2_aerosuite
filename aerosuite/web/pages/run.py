"""Run: the cases on the left (a case card, a list, or the list folded by Mach and altitude) and a panel on the
right that stays in view: what will run and Submit (or the running job and Cancel), checks, the machine (or, with
the Slurm backend, a one-line cluster summary), the last job."""
from datetime import datetime
from typing import NamedTuple, Optional
from urllib.parse import quote

from nicegui import background_tasks, run, ui

from ...engine.cfg import generate_configs, read_template, render_case
from ...engine.errors import AeroSuiteError
from ...engine.jobs.executors import SlurmOptions, backend_of, slurm_options
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import plan_restarts
from ...engine.machine import machine, partitions_note, usage, usage_text
from ...engine.naming import format_value
from ...engine.packages import effective
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import restart_file
from ...engine.results import history_columns
from ...engine.settings import AppSettings, load_settings
from ...engine.slurm_checks import memory_notes
from ...engine.study_results import study_results
from ..cluster_view import can_resubmit, case_slurm_text, summary_line
from ..fields import text_field
from ..resubmit_dialog import resubmit_case
from ..slurm_fields import slurm_fields
from ..jobs import WATCHER, JobView, job_progress
from ..layout import ProjectFrame, open_session, project_url
from ..run_view import ATTENTION, case_conditions, case_groups, duration_text, layout, status_counts, time_left
from ..session import parse_int
from ..ui_kit import (banner, card, card_head, chip_button, danger_button, failure_row, flat_button, hint, ok_line,
                      pill, pill_text, pill_tone, primary_button, secondary_button, stat, table, td, td_box, th,
                      titled, warning_group)

MACHINE_SECONDS = 10.0  # how often the machine strip is read again
POLL_SECONDS = 2.0
SELECTORS = [  # (label, statuses to tick; None = every case)
    ("All", None),
    ("Failed", {"FAILED", "BLOCKED"}),
    ("Unconverged", {"UNCONVERGED"}),
    ("Not run", {NOT_RUN}),
    ("None", set()),
]
KEY_VALUES = 6  # a single case's card shows this many of the Results page's chosen parameters


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
    """What the page shows from `view`: the active job, each case's row and the job history (and, for a Slurm job,
    each case's Slurm state, node and pending reason; its run time is kept current by the queue panel)."""
    active = view.active
    return (
        (active.id, active.state) if active is not None else None,
        tuple((name, sc.job_id, sc.state, sc.node, sc.reason) for job in view.overview.jobs[:1]
              for name, sc in job.slurm.items()),
        tuple((row.name, row.status, row.job_id, row.failure_tail) for row in view.overview.rows),
        tuple((job.id, job.state, job.finished) for job in view.overview.jobs),
        tuple(view.overview.problems),
    )


def _answer(dialog: ui.dialog, value: bool) -> None:
    """Submit a dialog's result and delete it immediately (see the comment in confirm_cancel)."""
    dialog.submit(value)
    dialog.delete()


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
        self.opened: set[str] = set()  # failed cases whose "why it failed" box is open
        self.tab = "cases"  # or "history"; kept across redraws
        self.groups_open: dict[str, bool] = {}  # folded groups the user opened or closed (by label)
        self.clock: Optional[tuple] = None  # (job started, cases finished, cases in all) while a job runs
        self.has_errors = False
        self.was_active = False
        self.shown: Optional[tuple] = None  # _snapshot() of the view on screen
        self.dialogs_open = 0  # a re-render while Cancel's confirm dialog awaits would orphan it
        self.cancelling = False  # this page's Cancel is running (other tabs see WATCHER.is_cancelling)
        self.submitting = False  # a Slurm submit (or adding cases) is running in a worker thread
        self.add_partition: Optional[str] = None  # where "Add cases" sends them (not saved with the study)
        self.add_ntasks: Optional[int] = None  # None: that partition's default
        self.submit_error: Optional[str] = None  # why the last Slurm submit failed, shown until the next one
        self.holder = ui.column().classes("as-content w-full")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)
        ui.timer(MACHINE_SECONDS, self._machine_values)

    @property
    def directory(self):
        return self.frame.session.directory

    @property
    def project(self):
        return self.frame.session.project

    @property
    def slurm(self) -> bool:
        return self.backend == "slurm"

    def _load_settings(self) -> None:
        self.settings, self.settings_warnings = load_settings()
        self.backend = backend_of(self.project, self.settings)
        self.options: Optional[SlurmOptions] = slurm_options(self.project, self.settings) if self.slurm else None

    def poll(self) -> None:
        if self.dialogs_open:
            return
        try:
            view = WATCHER.state(self.directory, self.project)
        except AeroSuiteError:
            return
        self._tick_clock()
        if getattr(self, "backend", "local") == "slurm":
            self._summary_values()  # the poller's latest; cheap
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
        self._load_settings()
        self.ticked &= {case.name for case in self.project.cases}  # the cases may have been rebuilt
        self.jobs_by_id = {job.id: job for job in view.overview.jobs}
        self.holder.clear()
        self.frame.actions.clear()
        selection = self._selection(view)
        kind = layout(self.project.cases)
        with self.holder:
            with ui.element("div").classes("as-run w-full"):
                with ui.column().classes("as-run-main gap-4"):
                    if kind == "single":
                        self._case_card(view)
                        self._history(view)
                    else:
                        if view.overview.rows:
                            self._summary(view)
                        with ui.tabs(value=self.tab, on_change=lambda e: self._set_tab(e.value)).props(
                                "dense no-caps align=left inline-label").classes(
                                "as-tabs as-page-tabs w-full").mark("run-tabs"):
                            ui.tab("cases", "Cases", icon="view_list").mark("run-tab-cases")
                            ui.tab("history", f"Job history ({len(view.overview.jobs)})", icon="history").mark(
                                "run-tab-history")
                        if self.tab == "history":
                            self._history(view)
                        else:
                            self._cases(view, selection, grouped=kind == "groups")
                with ui.column().classes("as-run-panel gap-0").mark("run-panel"):
                    with ui.column().classes("as-run-part w-full gap-2" + (
                            " as-run-live" if view.active is not None else "")):
                        if view.active is not None:
                            self._running(view)
                        else:
                            self._launch(selection, single=kind == "single")
                    if view.active is not None and view.active.backend == "slurm" and kind != "single":
                        with ui.column().classes("as-run-part w-full gap-2").mark("run-add"):
                            self._add_block(view, selection)
                    with ui.column().classes("as-run-part w-full gap-2"):
                        ui.label("Checks").classes("as-run-head")
                        self._checks(view, selection)
                        self._plan(view, selection)
                    with ui.column().classes("as-run-part w-full gap-2"):
                        if self.slurm:
                            ui.label("Cluster").classes("as-run-head")
                            self._cluster_summary()
                        else:
                            ui.label("Machine").classes("as-run-head")
                            self._machine()
                    with ui.column().classes("as-run-part w-full gap-1"):
                        self._last_job(view, single=kind == "single")
        self._buttons_state(view, selection)

    # -- the panel on the right ------------------------------------------------

    def _launch(self, selection: _Selection, single: bool) -> None:
        """What will run: the ticked cases, where (this machine or Slurm) with how many cores, continuing, Submit."""
        with ui.row().classes("items-center w-full no-wrap"):
            ui.label("Run").classes("as-run-head")
            ui.space()
            ui.toggle({"local": "This machine", "slurm": "Slurm"}, value=self.backend,
                      on_change=lambda e: self._set_backend(e.value)).props("dense no-caps unelevated").mark(
                "run-backend")
        if single:
            ui.label(self.project.cases[0].name).classes("as-run-big as-mono").mark("run-what")
        else:
            with ui.row().classes("items-baseline gap-2 no-wrap"):
                ui.label(str(len(selection.ticked))).classes("as-run-big").mark("run-what")
                ui.label(f"of {_plural(len(self.project.cases), 'case')} ticked").classes("as-muted")
        if self.slurm:
            self._slurm_fields()
        else:
            text_field("Cores per case (MPI partitions)", self.project.run.partitions, self._set_partitions,
                       mark="run-partitions")
        box = ui.checkbox("Continue from the last solution" if single else "Continue from each case's last solution",
                          value=selection.chosen, on_change=lambda e: self._set_continue(e.value)).mark("continue")
        if selection.no_solution:
            box.disable()
            count = len(selection.no_solution)
            text = ("No solution to continue from yet" if single else
                    f"{_plural(count, 'ticked case')} {'has' if count == 1 else 'have'} no solution to continue from")
            titled(hint(text), ", ".join(selection.no_solution)).mark("continue-missing")
        if self.slurm and self.submit_error:
            banner("error", f"Submit failed: {self.submit_error}").mark("submit-error")
        label = "Run case" if single else f"Submit {_plural(len(selection.ticked), 'case')}"
        if self.slurm:
            label = "Submitting…" if self.submitting else (
                "Submit to Slurm" if single else f"Submit {_plural(len(selection.ticked), 'case')} to Slurm")
        self.submit_button = primary_button(label, on_click=self.submit, icon="play_arrow").classes("w-full").mark(
            "submit")
        self.blocked = hint("").mark("submit-blocked")

    def _slurm_fields(self) -> None:
        """Partition, tasks per case and time limit (saved with the project); always one node."""
        slurm_fields(self.frame, self.settings, self.render, mark="run")

    def _running(self, view: JobView) -> None:
        """The running job: how far it is, the case running now, elapsed and a rough time left, Cancel."""
        progress = job_progress(view)
        job = view.active
        ui.label("Running").classes("as-run-head")
        with ui.row().classes("items-baseline gap-2 no-wrap"):
            ui.label(str(min(progress.finished + 1, progress.total))).classes("as-run-big").mark("run-what")
            ui.label(f"of {_plural(progress.total, 'case')}").classes("as-muted")
        ui.linear_progress(progress.finished / progress.total if progress.total else 0, show_value=False).props(
            "rounded size=8px").mark("run-progress")
        if progress.current:
            with ui.row().classes("items-baseline gap-1 no-wrap w-full"):
                ui.label("Now").classes("as-muted")
                ui.label(progress.current).classes("as-mono as-strong as-truncate").mark("run-current")
        self.clock = (job.created, progress.finished, progress.total)
        self.clock_label = ui.label("").classes("as-muted").mark("run-elapsed")
        self._tick_clock()
        with ui.row().classes("w-full gap-2 no-wrap"):
            if self.cancelling or WATCHER.is_cancelling(self.directory):
                danger_button("Cancelling…").classes("grow").mark("cancel").set_enabled(False)
            else:
                danger_button("Cancel job", on_click=self.confirm_cancel, icon="stop").classes("grow").mark("cancel")
            secondary_button("Monitor", on_click=lambda: ui.navigate.to(self._monitor_url(progress.current))).mark(
                "run-monitor")

    def _add_block(self, view: JobView, selection: _Selection) -> None:
        """More cases into the running Slurm job, e.g. on the other node while it runs; the partition and tasks
        are for this batch only."""
        job = view.active
        busy = WATCHER.slurm_runner.busy_cases(job)
        addable = [name for name in selection.ticked if name not in busy]
        skipped = len(selection.ticked) - len(addable)
        partitions = self.settings.slurm.partitions
        names = [p.name for p in partitions]
        used = {job.slurm[name].partition for name in busy if name in job.slurm}
        if self.add_partition not in names:
            self.add_partition = next((name for name in names if name not in used), names[0] if names else None)
        part = self.settings.slurm.partition(self.add_partition)
        ntasks = self.add_ntasks or (part.default_ntasks if part else 1)
        ui.label("Add cases").classes("as-run-head")
        hint("Run more ticked cases in this job while it runs, e.g. on the other node").mark("add-note")
        ui.select(names, value=self.add_partition, label="Partition",
                  on_change=lambda e: self._set_add_partition(e.value)).classes("w-full").props("dense").mark(
            "add-partition")
        text_field("Tasks per case (MPI ranks)", ntasks, self._set_add_ntasks, mark="add-ntasks")
        if part is not None and part.ntasks_warn_above and ntasks > part.ntasks_warn_above:
            hint(f"{part.name} gains nothing above about {part.ntasks_warn_above} tasks").classes(
                "as-hint-warning").mark("add-ntasks-note")
        for note in memory_notes(self.directory, self.project, addable or None, self.add_partition, self.settings):
            hint(note).mark("add-memory")
        label = "Adding…" if self.submitting else f"Add {_plural(len(addable), 'case')} to the running job"
        button = primary_button(label, icon="playlist_add", on_click=lambda: self.add_cases(addable)).classes(
            "w-full").mark("add-cases")
        button.set_enabled(bool(addable) and not self.submitting)
        if skipped:
            count = f"{skipped} ticked case{' is' if skipped == 1 else 's are'}"
            hint(f"{count} already queued or running in this job: skipped").mark("add-skipped")
        elif not selection.ticked:
            hint("Tick the cases to add").mark("add-skipped")

    def _set_add_partition(self, name: str) -> None:
        if name != self.add_partition:
            self.add_partition, self.add_ntasks = name, None
            self.render()

    def _set_add_ntasks(self, text: str) -> Optional[str]:
        try:
            value = int(text.strip())
        except ValueError:
            return f"{text!r} is not a whole number"
        if value < 1:
            return "Tasks per case must be at least 1"
        self.add_ntasks = value
        self.render()
        return None

    def add_cases(self, cases: list) -> None:
        if self.submitting or not cases:
            return
        self._load_settings()
        options = slurm_options(self.project, self.settings, partition=self.add_partition, ntasks=self.add_ntasks)
        view = WATCHER.state(self.directory, self.project)
        if view.active is None or view.active.backend != "slurm":
            ui.notify("The job has ended: submit the cases instead", type="warning")
            self.render()
            return
        errors = [p for p in preflight(self.directory, self.project, "submit", cases=cases, options=options,
                                       settings=self.settings)
                  if p.severity == "error" and not p.message.startswith(f"Job {view.active.id} ")]
        if errors:
            ui.notify(errors[0].message, type="negative")
            return
        self.submitting = True
        self.render()
        continue_cases = [name for name in self.continue_cases if name in cases]
        background_tasks.create(self._add_slurm(view.active.id, cases, continue_cases, options))

    async def _add_slurm(self, job_id: str, cases: list, continue_cases: list, options: SlurmOptions) -> None:
        try:
            generate_configs(self.directory, self.project)  # as a submit: the current settings
            await run.io_bound(WATCHER.add_cases, self.directory, self.project, job_id, cases, continue_cases,
                               options)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
        else:
            ui.notify(f"Added {_plural(len(cases), 'case')} to the running job ({options.partition})",
                      type="positive")
        finally:
            self.submitting = False
        if not self.holder.is_deleted:
            self.frame.refresh()
            self.render()

    def _tick_clock(self) -> None:
        label = getattr(self, "clock_label", None)
        if self.clock is None or label is None or label.is_deleted:
            return
        started, finished, total = self.clock
        elapsed = max(0.0, (datetime.now() - started).total_seconds())
        left = time_left(elapsed, finished, total)
        label.text = f"Elapsed {duration_text(elapsed)}" + (
            f" · about {duration_text(left)} left" if left else " · time left shown after the first case")

    def _buttons_state(self, view: JobView, selection: _Selection) -> None:
        if view.active is None:  # one job at a time: while one runs the panel has Cancel, no Submit
            self.clock = None
            self.submit_button.set_enabled(bool(selection.ticked) and not self.has_errors and not self.submitting)
            self.blocked.text = ("Fix the error below to run" if self.has_errors else
                                 "Tick at least one case" if not selection.ticked else "")

    def _set_backend(self, backend: str) -> None:
        if backend == self.backend:
            return
        self.submit_error = None
        message = self.frame.save(lambda p: setattr(p.run, "backend", backend))
        if message is not None:
            ui.notify(message, type="negative")
        self.render()

    def _set_partitions(self, text: str) -> Optional[str]:
        message = self.frame.save(lambda p: setattr(p.run, "partitions", parse_int(text, "Cores per case")))
        if message is None:
            self._machine_values()
        return message

    def _monitor_url(self, case: Optional[str] = None) -> str:
        return project_url("monitor", self.directory) + (f"&case={quote(case, safe='')}" if case else "")

    def _last_job(self, view: JobView, single: bool) -> None:
        ui.label("This job" if view.active is not None else "Last job").classes("as-run-head")
        job = view.latest
        if job is None:
            ui.label("No job yet").classes("as-muted").mark("last-job")
            return
        took = f" · {duration_text((job.finished - job.created).total_seconds())}" if job.finished else ""
        state = pill_text(job.state).capitalize()
        ui.label(f"{job.id} · {state} · {_plural(len(job.cases), 'case')}{took}").classes("as-muted").mark("last-job")
        with ui.row().classes("gap-3"):
            flat_button("Log", on_click=lambda: self.frame.log.open(job.id), icon="terminal").props("dense").mark(
                "last-job-log")
            if not single:
                flat_button(f"Job history ({len(view.overview.jobs)})", on_click=lambda: self._set_tab("history"),
                            icon="history").props("dense").mark("last-job-history")

    def _checks(self, view: JobView, selection: _Selection) -> None:
        cases = selection.ticked or None
        problems = preflight(self.directory, self.project, "submit", cases=cases, options=self.options,
                             settings=self.settings)
        if self.slurm:
            for note in memory_notes(self.directory, self.project, cases, self.options.partition, self.settings):
                hint(note).mark("run-memory")
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        if not found:
            ok_line("No problems found.").mark("run-problems-none")
        for severity, message in found:  # errors stay in view; warnings fold into one row
            if severity == "error":
                banner("error", f"Error: {message}").mark("run-problem-error")
        warnings = [message for severity, message in found if severity != "error"]
        if warnings:
            warning_group(warnings, mark="run-warnings")

    def _machine(self) -> None:
        """This machine now: cores (free), memory, SU2 solvers running, who uses the cores; kept current by a
        timer."""
        with ui.row().classes("as-machine w-full").mark("run-machine"):
            self.machine_labels = {key: stat(label, "") for key, label in (
                ("cores", "Cores"), ("free", "Free now"), ("memory", "Memory free"), ("su2", "SU2 solvers"))}
            for key in self.machine_labels:
                self.machine_labels[key].mark(f"machine-{key}")
        self.machine_note = ui.label("").classes("as-hint-warning").mark("machine-note")
        with ui.column().classes("as-machine-usage w-full gap-0"):
            ui.label("Using the cores").classes("as-stat-label")
            self.machine_usage = ui.label("").classes("as-mono as-usage").mark("machine-usage")
        self._machine_values()

    def _machine_values(self) -> None:
        if getattr(self, "backend", "local") == "slurm":
            self._summary_values()
            return
        labels = getattr(self, "machine_labels", None)
        if not labels or labels["cores"].is_deleted:
            return
        here = machine()
        labels["cores"].text = (f"{here.cores}" if here.physical_cores == here.cores
                                else f"{here.cores} ({here.physical_cores} physical)")
        labels["free"].text = f"about {here.free_cores}"
        labels["memory"].text = f"{here.memory_free_gb:.0f} of {here.memory_total_gb:.0f} GB"
        labels["su2"].text = str(here.su2_processes)
        note = partitions_note(self.project.run.partitions, here) or ""
        self.machine_note.text = note
        self.machine_note.set_visibility(bool(note))
        self.machine_usage.text = "\n".join(usage_text(item) for item in usage()) or "nothing much"

    def _cluster_summary(self) -> None:
        """One line on the cluster (partitions, your jobs) and a link to the Cluster page; kept current by poll()."""
        with ui.row().classes("items-baseline w-full no-wrap gap-2"):
            self.summary_label = ui.label("").classes("as-muted").mark("run-cluster-summary")
            ui.space()
            ui.link("Cluster →", "/cluster").classes("no-wrap").mark("run-cluster-link")
        self._summary_values()

    def _summary_values(self) -> None:
        label = getattr(self, "summary_label", None)
        if label is None or label.is_deleted:
            return
        watch = WATCHER.slurm_watch
        text, bad = summary_line(watch.cluster, watch.snapshot, watch.user)
        label.text = text
        label.classes(replace="as-error-text" if bad else "as-muted")

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
            if plan.warnings:
                count = len(plan.warnings)
                warning_group(plan.warnings, mark="plan-warnings",
                              label=f"{count} warning{'' if count == 1 else 's'} about continuing")

    # -- the cases on the left -------------------------------------------------

    def _summary(self, view: JobView) -> None:
        """Every case's status at a glance: one bar, one count per status."""
        counts = status_counts(view.overview.rows)
        with card():
            with ui.row().classes("as-status-bar w-full no-wrap"):
                for status, count in counts:
                    ui.element("span").classes(f"as-status-seg as-seg-{pill_tone(status)}").style(f"flex: {count}")
            with ui.row().classes("items-center gap-2 w-full"):
                for status, count in counts:
                    ui.label(f"{count} {pill_text(status).lower()}").classes(
                        f"as-pill as-pill-{pill_tone(status)}").mark(f"count-{status.lower()}")

    def _case_card(self, view: JobView) -> None:
        """A single case: its status, what it runs, and after a run the Results page's chosen values."""
        row = view.overview.rows[0]
        case = self.project.cases[0]
        with card():
            with card_head():
                ui.label(case.name).classes("as-run-big as-mono")
                self._status(row)
                ui.space()
                flat_button("Open in Monitor", on_click=lambda: ui.navigate.to(self._monitor_url(case.name)),
                            icon="show_chart").props("dense").mark("case-monitor")
                if row.status in ("CONVERGED", "UNCONVERGED"):
                    flat_button("Results", on_click=lambda: ui.navigate.to(project_url("results", self.directory)),
                                icon="bar_chart").props("dense").mark("case-results")
            try:
                config = render_case(read_template(self.directory, self.project), self.project, case)
            except AeroSuiteError:
                config = ""
            items = case_conditions(config, self.project.mesh.path) + self._key_values(row)
            if items:
                with ui.row().classes("as-strip w-full").mark("case-conditions"):
                    for label, value in items:
                        stat(label, value).mark(f"case-{label}")
            job = self.jobs_by_id.get(row.job_id)
            if job is not None and job.backend == "slurm":
                with ui.row().classes("items-center gap-2"):
                    ui.label(case_slurm_text(job, row.name)).classes("as-mono as-muted").mark(f"slurm-{row.name}")
                    self._resubmit_button(job, row.name)
            if row.status in ("FAILED", "BLOCKED") and row.failure_tail and row.name in self.opened:
                failure_row(row.failure_tail).mark(f"tail-{row.name}")
            if row.status == NOT_RUN:
                ui.label("Nothing has run yet.").classes("as-muted").mark("case-not-run")

    def _key_values(self, row) -> list[tuple[str, str]]:
        if row.status not in ("CONVERGED", "UNCONVERGED"):
            return []
        try:
            definitions = effective(self.project.results, history_columns(self.directory, self.project))
            results = study_results(self.directory, definitions, self.project.results.average_last).table
        except AeroSuiteError:
            return []
        if results.empty or "Case" not in results:
            return []
        match = results[results["Case"] == row.name]
        if match.empty:
            return []
        values = match.iloc[0]
        return [(name, f"{values[name]:.5g}") for name in definitions.parameters[:KEY_VALUES]
                if name in values and isinstance(values[name], (int, float)) and values[name] == values[name]]

    def _status(self, row) -> None:
        """A case's status pill; a failed one opens "why it failed" with a click."""
        details = row.status in ("FAILED", "BLOCKED") and bool(row.failure_tail)
        opened = details and row.name in self.opened
        status = pill(row.status).mark(f"status-{row.name}")
        if details:
            status.classes("as-pill-toggle").on("click", lambda n=row.name: self._toggle(n))
            status.props(f'title="{"Hide" if opened else "Show"} why it failed"')
            ui.icon("expand_less" if opened else "expand_more").classes("as-pill-chevron").on(
                "click", lambda n=row.name: self._toggle(n))

    def _cases(self, view: JobView, selection: _Selection, grouped: bool) -> None:
        rows = {row.name: row for row in view.overview.rows}
        with card(flush=True):
            with card_head("Cases"):
                if rows:
                    ui.label("Tick").classes("as-label")
                    for label, statuses in SELECTORS:
                        count = len(rows) if statuses is None else sum(
                            1 for row in rows.values() if row.status in statuses)
                        chip = chip_button(label if statuses == set() else f"{label} {count}",
                                           on_click=lambda s=statuses: self._select(view, s))
                        chip.mark(f"select-{label.lower().replace(' ', '-')}")
                        if statuses and not count:
                            chip.props("disable")
            if not rows:
                ui.label("No cases yet: set up the sweep first.").classes("as-muted px-4 pb-4")
                return
            cases = {case.name: case for case in self.project.cases}
            with table("36px minmax(10rem, 1.4fr) repeat(3, minmax(3rem, .4fr)) minmax(8rem, 1fr) "
                       "minmax(13rem, 1fr)").classes("as-table-compact"):
                for heading in ("", "Case", "Mach", "α", "β", "Status", "Last job"):
                    th(heading)
                if not grouped:
                    for row in rows.values():
                        self._case_row(row, cases.get(row.name))
                    return
                for index, group in enumerate(case_groups(self.project.cases)):
                    members = [rows[name] for name in group.names if name in rows]
                    opened = self.groups_open.get(group.label, any(r.status in ATTENTION for r in members))
                    ticked = [r.name for r in members if r.name in self.ticked]
                    with td_box() as cell:
                        cell.classes("as-group-cell")
                        state = True if len(ticked) == len(members) else None if ticked else False
                        ui.checkbox(value=state, on_change=lambda e, g=group: self._tick_group(
                            g.names, e.value)).props("dense").mark(f"group-tick-{index}")
                    with td_box() as name:
                        name.classes("as-group-cell as-group-name").style("grid-column: span 4").mark(
                            f"group-{index}")
                        name.on("click", lambda _, g=group, o=opened: self._fold_group(g.label, not o))
                        ui.icon("expand_more" if opened else "chevron_right")
                        ui.label(group.label).classes("as-strong")
                        ui.label(_plural(len(members), "case")).classes("as-muted")
                    with td_box() as summary:
                        summary.classes("as-group-cell").style("grid-column: span 2")
                        for status, count in status_counts(members):
                            ui.label(f"{count} {pill_text(status).lower()}").classes(
                                f"as-pill as-pill-{pill_tone(status)}")
                    if opened:
                        for row in members:
                            self._case_row(row, cases.get(row.name))

    def _case_row(self, row, case) -> None:
        with td_box():
            ui.checkbox(value=row.name in self.ticked,
                        on_change=lambda e, n=row.name: self._tick(n, e.value)).props("dense").mark(
                f"tick-{row.name}")
        td(row.name, strong=True)
        td(format_value(case.mach) if case else "")
        td(format_value(case.alpha) if case else "")
        td(format_value(case.beta) if case else "")
        with td_box():
            self._status(row)
        job = self.jobs_by_id.get(row.job_id)
        if job is not None and job.backend == "slurm":
            with td_box() as cell:
                cell.classes("as-slurm-cell")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(row.job_id).classes("as-mono").mark(f"job-{row.name}")
                    ui.label(case_slurm_text(job, row.name)).classes("as-mono as-muted as-small").mark(
                        f"slurm-{row.name}")
                self._resubmit_button(job, row.name)
        else:
            td(row.job_id or "—", mono=True).mark(f"job-{row.name}")
        if row.status in ("FAILED", "BLOCKED") and row.failure_tail and row.name in self.opened:
            failure_row(row.failure_tail).mark(f"tail-{row.name}")

    def _tick_group(self, names: list, value: Optional[bool]) -> None:
        if value:
            self.ticked |= set(names)
        else:
            self.ticked -= set(names)
        self.continue_choice = None
        self.render()

    def _fold_group(self, label: str, opened: bool) -> None:
        self.groups_open[label] = opened
        self.render()

    def _history(self, view: JobView) -> None:
        with card("Job history", flush=True, fold="run-history"):
            if not view.overview.jobs:
                ui.label("No jobs yet.").classes("as-muted px-4 pb-4").mark("history-none")
                return
            with table("minmax(10rem, 1fr) minmax(7rem, auto) minmax(5rem, auto) minmax(9rem, 1fr) "
                       "minmax(9rem, 1fr) 100px"):
                for heading in ("Job", "State", "Cases", "Started", "Finished", ""):
                    th(heading)
                for job in view.overview.jobs:
                    td(job.id, mono=True).mark(f"history-{job.id}")
                    with td_box():
                        pill(job.state)
                    td(_plural(len(job.cases), "case"))
                    td(f"{job.created:%Y-%m-%d %H:%M}")
                    td(f"{job.finished:%Y-%m-%d %H:%M}" if job.finished else "—")
                    with td_box():
                        flat_button("Log", on_click=lambda j=job.id: self.frame.log.open(j), icon="terminal").props(
                            "dense").mark(f"history-log-{job.id}")

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

    def _set_tab(self, tab: str) -> None:
        if tab != self.tab:
            self.tab = tab
            self.render()

    def _toggle(self, name: str) -> None:
        self.opened ^= {name}
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
        self._load_settings()
        errors = [p for p in preflight(self.directory, self.project, "submit", cases=cases, options=self.options,
                                       settings=self.settings) if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            self.render()
            return
        if self.slurm:
            if not self.submitting:
                self.submitting = True
                self.submit_error = None
                self.render()
                background_tasks.create(self._submit_slurm(cases, list(self.continue_cases), self.options))
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

    async def _submit_slurm(self, cases: list, continue_cases: list, options: SlurmOptions) -> None:
        """sbatch once per case (seconds for a big sweep, or up to the timeout when Slurm is slow): in a worker
        thread, so the server keeps answering."""
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            await run.io_bound(WATCHER.submit, self.directory, self.project, cases, continue_cases, options)
        except AeroSuiteError as exc:
            self.submit_error = str(exc)
            ui.notify(str(exc), type="negative")
        else:
            ui.notify(f"Submitted {_plural(len(cases), 'case')} to Slurm ({options.partition})", type="positive")
        finally:
            self.submitting = False
        if not self.holder.is_deleted:
            self.frame.refresh()
            self.render()

    def _resubmit_button(self, job, case: str) -> None:
        if can_resubmit(job, case):
            chip_button("Resubmit", on_click=lambda j=job, c=case: self.confirm_resubmit(j, c)).mark(
                f"resubmit-{case}")

    async def confirm_resubmit(self, job, case: str) -> None:
        """NODE_FAIL / OUT_OF_MEMORY: submit the case again (and the cases blocked behind it) in the same job."""
        self.dialogs_open += 1
        try:
            await resubmit_case(self.directory, self.project, job, case)
        finally:
            self.dialogs_open -= 1
        if not self.holder.is_deleted:
            self.frame.refresh()
            self.render()

    async def confirm_cancel(self) -> None:
        # poll() must not rebuild the page (and delete this button's row) while this dialog is
        # up: that would orphan its slot and break dialog creation for a second click queued
        # right after this one, before either has had a chance to run.
        self.dialogs_open += 1
        try:
            with ui.dialog() as dialog, ui.card():
                ui.label("Cancel the running job? Cases that have not finished are marked CANCELLED." + (
                    " Its Slurm jobs are cancelled (scancel)." if self.slurm else ""))
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
        # Stopping SU2 can take ~20 s: in a worker thread, so the server keeps answering every page.
        self.cancelling = True
        self.render()  # shows "Cancelling…"
        try:
            job = await run.io_bound(WATCHER.cancel, self.directory, self.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            job = None
        finally:
            self.cancelling = False
        if job is not None:
            ui.notify(f"Job {job.id}: {job.state.value}", type="info")
        self.frame.refresh()
        self.render()

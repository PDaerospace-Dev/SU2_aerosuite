"""The Run page's case card (status, why it failed, earlier attempts, rerun), the job history, ticking cases, and
Submit, Resubmit and Cancel."""
from datetime import datetime
from typing import Optional

from nicegui import background_tasks, run, ui

from ...engine.attempts import attempts, make_current
from ...engine.cfg import generate_configs, read_template, render_case
from ...engine.errors import AeroSuiteError
from ...engine.jobs.diagnose import Diagnosis, diagnose, residual_trend
from ...engine.jobs.executors import SlurmOptions
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import START_MODES, started_from
from ...engine.jobs.rerun import describe
from ...engine.jobs.store import JOBS_DIR
from ...engine.packages import effective
from ...engine.preflight import preflight
from ...engine.restarts import RUNS_DIR
from ...engine.results import HISTORY_FILE, history_columns
from ...engine.study_results import study_results
from ..cluster_view import can_resubmit, case_slurm_text
from ..jobs import WATCHER, JobView
from ..layout import project_url
from ..rerun_dialog import ask_rerun, keep_changes, kept
from ..resubmit_dialog import resubmit_case
from ..run_view import (
    case_conditions,
    layout,
)
from ..ui_kit import (
    card,
    card_head,
    chip_button,
    danger_button,
    flat_button,
    pill,
    primary_button,
    secondary_button,
    stat,
    table,
    td,
    td_box,
    th,
)
from .run_parts import _START_MODE, KEY_VALUES, _answer, _attempt_number, _iterations, _plural


class RunCases:
    """Part of RunPage (pages/run.py), which holds the state these methods use."""

    # -- the cases on the left -------------------------------------------------

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
            if self._diagnosis(row) is not None:
                ui.label(self._diagnosis(row).summary).classes("as-failure-reason").mark(f"why-{row.name}")
            self._ran_with(row)
            if row.status == "UNCONVERGED":
                with ui.row():
                    self._rerun_button(row.name, "unconverged")
            self._attempts_link(row.name)
            if row.name in self.attempts_open:
                self._attempts_list(row.name)
            if row.status in ("FAILED", "BLOCKED") and row.failure_tail and row.name in self.opened:
                self._failure(row)
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

    def _diagnosis(self, row) -> Optional[Diagnosis]:
        """Why the case failed, in words (jobs/diagnose.py); None unless it failed or was blocked."""
        if row.status not in ("FAILED", "BLOCKED") or not row.failure_tail:
            return None
        job = self.jobs_by_id.get(row.job_id)
        sc = job.slurm.get(row.name) if job is not None else None
        return diagnose(row.failure_tail, sc.state if sc else None, sc.time_limit if sc else "")

    def _failure(self, row) -> None:
        """An opened failure: what happened, the residuals before a divergence, what to try (with the buttons
        that do it), and the output's end, folded."""
        found = self._diagnosis(row)
        with ui.element("div").classes("as-td-failure").style("grid-column: 1 / -1"):
            with ui.column().classes("as-failure-box gap-2 w-full").mark(f"failure-{row.name}"):
                ui.label(found.summary).classes("as-strong")
                if found.kind == "diverged":
                    trend = residual_trend(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
                    if trend:
                        ui.label(f"Before that, {trend}.").mark(f"trend-{row.name}")
                if found.advice:
                    ui.label(f"Try: {found.advice}.").classes("as-muted").mark(f"advice-{row.name}")
                if self._sources(row.name):
                    ui.label("The solution its run started from is kept, so a rerun can start from it.").classes(
                        "as-muted").mark(f"kept-start-{row.name}")
                with ui.row().classes("gap-2"):
                    self._failure_actions(row, found)
                with ui.expansion("Output (its last lines)").props("dense").classes("w-full").mark(
                        f"output-{row.name}"):
                    ui.label(row.failure_tail).classes("as-failure").mark(f"tail-{row.name}")

    def _failure_actions(self, row, found: Diagnosis) -> None:
        project = self.project
        form = "aircraft" if project.profile else "config"
        go = {"config": ("Open the config", form, "edit_note"),
              "mesh": ("Open Setup", "setup", "tune"),
              "restart": ("Open the restart", form if not project.sweep.enabled else "sweep", "restart_alt")}
        if found.kind in go:
            text, page, icon = go[found.kind]
            secondary_button(text, icon=icon, on_click=lambda p=page: ui.navigate.to(
                project_url(p, self.directory))).props("dense").mark(f"fix-{row.name}")
        elif found.kind == "launch":
            secondary_button("Open Settings", icon="settings", on_click=lambda: ui.navigate.to("/settings")).props(
                "dense").mark(f"fix-{row.name}")
        elif found.kind == "time_limit":
            secondary_button("Continue from its last solution", icon="play_arrow",
                             on_click=lambda n=row.name: self._only(n, continue_=True)).props("dense").mark(
                f"fix-{row.name}")
        elif found.kind == "blocked":
            secondary_button("Tick it to run again", icon="check_box",
                             on_click=lambda n=row.name: self._only(n, continue_=False)).props("dense").mark(
                f"fix-{row.name}")
        if found.kind in ("diverged", "time_limit", "su2", "failed"):
            self._rerun_button(row.name, found.kind)
            flat_button("Monitor", icon="show_chart", on_click=lambda n=row.name: ui.navigate.to(
                self._monitor_url(n))).props("dense").mark(f"monitor-{row.name}")

    def _sources(self, name: str) -> dict[str, str]:
        """More solutions a rerun of `name` can start from: the one its last (unfinished) run started from."""
        view = WATCHER.state(self.directory, self.project)
        row = next((r for r in view.overview.rows if r.name == name), None)
        started = started_from(self.directory / JOBS_DIR / row.job_id, name) if row and row.job_id else None
        return {str(started): "From the solution its last run started from"} if started is not None else {}

    async def rerun(self, name: str, kind: str, sources: Optional[dict] = None, chosen: Optional[str] = None
                    ) -> None:
        """Ask how (rerun_dialog), then run just this case with those changes: a new job, or added to the
        running Slurm job."""
        answer = await ask_rerun(self.directory, self.project, name, kind,
                                 sources if sources is not None else self._sources(name), chosen)
        if answer is None:
            return
        changes, start = answer
        self.ticked = {name}
        self.render()
        mode, starts = (start, {}) if start in START_MODES else ("sweep", {name: start})  # else a solution's path
        self.rerun_with = {"changes": {name: changes} if changes else {}, "starts": starts, "mode": mode}
        view = WATCHER.state(self.directory, self.project)
        if view.active is not None and view.active.backend == "slurm":
            await self.add_cases([name])
        else:
            await self.submit()

    def _rerun_button(self, name: str, kind: str) -> None:
        secondary_button("Rerun with changes…", icon="tune",
                         on_click=lambda: self.rerun(name, kind)).props("dense").mark(f"rerun-{name}")

    def _ran_with(self, row) -> None:
        """What the case last ran with, when that job changed its config; "Keep" writes it into the config."""
        job = self.jobs_by_id.get(row.job_id)
        changes = job.changes.get(row.name) if job is not None else None
        if not changes:
            return
        case = next((c for c in self.project.cases if c.name == row.name), None)
        try:
            config = render_case(read_template(self.directory, self.project), self.project, case) if case else ""
        except AeroSuiteError:
            config = ""
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.label(f"ran with {describe(changes)}").classes("as-muted as-small").mark(f"ran-with-{row.name}")
            if case is not None and not kept(config, changes):
                flat_button("Keep", icon="push_pin", on_click=lambda: self._keep(row.name, changes)).props(
                    "dense").mark(f"keep-{row.name}")

    def _keep(self, name: str, changes: dict) -> None:
        message = keep_changes(self.frame, name, changes)
        if message:
            ui.notify(message, type="negative")
        self.render()

    def _attempts_link(self, name: str) -> None:
        found = attempts(self.directory, name)
        if found:
            opened = name in self.attempts_open
            flat_button(f"{len(found)} earlier attempt{'' if len(found) == 1 else 's'}",
                        icon="expand_less" if opened else "history",
                        on_click=lambda: self._toggle_attempts(name)).props("dense").mark(f"attempts-{name}")

    def _toggle_attempts(self, name: str) -> None:
        self.attempts_open ^= {name}
        self.render()

    def _attempts_list(self, name: str) -> None:
        """The case's earlier attempts, newest first: how each ended, what it ran with, and what to do with it."""
        with ui.element("div").classes("as-td-failure").style("grid-column: 1 / -1"):
            with ui.column().classes("as-attempts gap-1 w-full").mark(f"attempts-list-{name}"):
                for attempt in reversed(attempts(self.directory, name)):
                    number = _attempt_number(attempt)
                    with ui.row().classes("items-center gap-2 no-wrap w-full").mark(f"attempt-{name}-{number}"):
                        ui.label(f"Attempt {number}").classes("as-strong")
                        if attempt.status:
                            pill(attempt.status)
                        details = [describe(attempt.changes)] if attempt.changes else []
                        iterations = _iterations(attempt.history)
                        if iterations:
                            details.append(f"{iterations} iterations")
                        if attempt.archived:
                            details.append(f"kept {datetime.fromtimestamp(attempt.archived):%d %b %H:%M}")
                        ui.label(" · ".join(details)).classes("as-muted grow as-truncate")
                        if attempt.solution is not None:
                            source = {str(attempt.folder): f"From attempt {number}'s solution"}
                            flat_button("Restart from this", icon="replay",
                                        on_click=lambda s=source: self.rerun(name, "attempt", s, next(iter(s)))
                                        ).props("dense").mark(f"attempt-restart-{name}-{number}")
                        flat_button("Make current", icon="restore",
                                    on_click=lambda a=attempt: self.confirm_make_current(a)).props("dense").mark(
                            f"attempt-current-{name}-{number}")

    async def confirm_make_current(self, attempt) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Make attempt {_attempt_number(attempt)} {attempt.case}'s current run? The current run "
                     "becomes an earlier attempt (its volume files are not kept).")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Keep as it is", on_click=lambda: _answer(dialog, False)).mark("current-keep")
                primary_button("Make current", on_click=lambda: _answer(dialog, True)).mark("current-confirm")
        if not await dialog:
            return
        try:
            make_current(self.directory, attempt)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"{attempt.case}: attempt {_attempt_number(attempt)} is the current run again", type="positive")
        self.frame.refresh()
        self.render()

    def _only(self, name: str, continue_: bool) -> None:
        """Tick just this case, starting from its own last solution or as the sweep says: Submit is then one click
        away."""
        self.ticked = {name}
        _START_MODE[str(self.directory)] = "last" if continue_ else "sweep"
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

    def _select(self, view: Optional[JobView], statuses: Optional[set]) -> None:
        """Select every case (None), none (an empty set), or those with these statuses."""
        if statuses == set():
            self.ticked = set()
        else:
            rows = view.overview.rows
            self.ticked = {r.name for r in rows} if statuses is None else {r.name for r in rows if r.status in statuses}
        self.render()

    def _tick(self, name: str, value: bool) -> None:
        if value:
            self.ticked.add(name)
        else:
            self.ticked.discard(name)
        self.render()

    def _set_tab(self, tab: str) -> None:
        if tab != self.tab:
            self.tab = tab
            self.render()

    def _toggle(self, name: str) -> None:
        """A status pill clicked: a single case opens its "why it failed"; a sweep's case shows its details."""
        if layout(self.project.cases) == "single":
            self.opened ^= {name}
            self.render()
        else:
            self._focus(name)

    async def submit(self) -> None:
        if self.over_memory:
            return
        stale = self.frame.ensure_current(notify=False)
        if stale is not None:
            if self.frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; submit again", type="warning")
            return
        extra, self.rerun_with = self.rerun_with or {}, None
        cases = [case.name for case in self.project.cases if case.name in self.ticked]
        if self.start_problem and not extra:
            return
        continue_cases, starts = self._run_starts(cases, extra)
        extra = {**extra, "starts": starts}
        self._load_settings()
        self.checking = True  # SU2 checks each config: a few seconds, off the event loop
        self.render()
        try:
            found = await run.io_bound(preflight, self.directory, self.project, "submit", cases=cases,
                                       options=self.options, settings=self.settings, check_su2=True)
        finally:
            self.checking = False
        errors = [p for p in found if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            self.render()
            return
        if self.slurm:
            if not self.submitting:
                self.submitting = True
                self.submit_error = None
                self.render()
                background_tasks.create(self._submit_slurm(cases, continue_cases, self.options, extra, self.note))
            return
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            WATCHER.submit(self.directory, self.project, cases, continue_cases,
                           changes=extra.get("changes"), starts=extra.get("starts"), note=self.note)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            self.render()
            return
        ui.notify(f"Started {_plural(len(cases), 'case')}", type="positive")
        self.note = ""
        self.frame.refresh()
        self.render()

    async def _submit_slurm(self, cases: list, continue_cases: list, options: SlurmOptions,
                            extra: Optional[dict] = None, note: str = "") -> None:
        """sbatch once per case (seconds for a big sweep, or up to the timeout when Slurm is slow): in a worker
        thread, so the server keeps answering."""
        extra = extra or {}
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            await run.io_bound(WATCHER.submit, self.directory, self.project, cases, continue_cases, options,
                               extra.get("changes"), extra.get("starts"), note)
        except AeroSuiteError as exc:
            self.submit_error = str(exc)
            ui.notify(str(exc), type="negative")
        else:
            self.note = ""
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

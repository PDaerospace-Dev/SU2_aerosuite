"""The Run page's panel on the right: a case's details, what will run and Submit (or adding cases to a running
Slurm job), the last job, the checks, and the machine or the cluster."""
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from nicegui import background_tasks, run, ui

from ...engine.cfg import generate_configs, read_template
from ...engine.errors import AeroSuiteError
from ...engine.jobs.changes import config_changes
from ...engine.jobs.executors import SlurmOptions, slurm_options
from ...engine.jobs.plan import last_solution, mode_starts, preview_starts
from ...engine.machine import machine, partitions_note, usage, usage_text
from ...engine.naming import format_value, parse_case_name
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import RUNS_DIR, restart_file
from ...engine.results import HISTORY_FILE
from ...engine.slurm_checks import memory_summary, outside_load_problems
from ..cluster_view import (
    case_slurm_text,
    fitting_partition,
    full_note,
    summary_parts,
)
from ..fields import text_field
from ..jobs import WATCHER, JobView
from ..layout import project_url
from ..notes import NoteField, changes_line, note_label
from ..run_view import (
    clock_text,
    duration_text,
    status_counts,
)
from ..session import parse_int
from ..slurm_fields import partition_row, select_partition, slurm_fields
from ..starts_view import start_choice, start_preview
from ..ui_kit import (
    banner,
    flat_button,
    hint,
    ok_line,
    pill,
    pill_text,
    primary_button,
    secondary_button,
    stat,
    titled,
    warning_group,
)
from .cluster import cluster_url
from .run_parts import (
    _OUT_OF_MEMORY,
    _START_MODE,
    _ago,
    _iterations,
    _plural,
    _Row,
    _Selection,
)


class RunPanel:
    """Part of RunPage (pages/run.py), which holds the state these methods use."""

    # -- a case's details ----------------------------------------------------------------------------------------

    def _details(self, view: JobView) -> None:
        """The clicked case: where it stands, why it failed and what to try, what it ran with, its earlier attempts,
        and its buttons."""
        row = next((r for r in view.overview.all_rows if r.name == self.focus), None)
        if row is None:
            return
        case = next((c for c in self.project.cases if c.name == row.name), None)
        with ui.column().classes("as-run-panel as-details w-full gap-2").mark("case-details"):
            with ui.row().classes("items-center w-full no-wrap gap-2"):
                ui.label(row.name).classes("as-mono as-strong as-truncate").mark("details-name")
                pill(row.status).mark("details-status")
                ui.space()
                ui.button(icon="close", on_click=lambda: self._focus(row.name), color=None).props(
                    "flat round dense size=sm").mark("details-close")
            parsed = parse_case_name(row.name)
            mach = case.mach if case else parsed.mach
            alpha = case.alpha if case else parsed.alpha
            parts = [f"Mach {format_value(mach)}" if mach is not None else "",
                     f"α {format_value(alpha)}°" if alpha is not None else "",
                     f"β {format_value(case.beta)}°" if case else "",
                     f"{format_value(case.altitude_km)} km" if case and case.altitude_km is not None else ""]
            hint(" · ".join(p for p in parts if p)).mark("details-conditions")
            if case is None:
                hint("In the running job, no longer in the sweep").mark("details-other")
            values = self._key_values(row)
            iterations = _iterations(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
            if iterations:
                values = [("Iterations", str(iterations))] + values
            if values:
                with ui.column().classes("w-full gap-0"):
                    for label, value in values:
                        with ui.row().classes("as-detail-row w-full no-wrap"):
                            ui.label(label).classes("as-muted grow")
                            ui.label(value).classes("as-strong").mark(f"details-{label}")
            job = self.jobs_by_id.get(row.job_id)
            if job is not None and job.backend == "slurm":
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{row.job_id} · {case_slurm_text(job, row.name)}").classes(
                        "as-mono as-muted as-small").mark("details-slurm")
                    self._resubmit_button(job, row.name)
            elif row.job_id:
                ui.label(f"job {row.job_id}").classes("as-mono as-muted as-small").mark("details-job")
            if self._diagnosis(row) is not None:
                self._failure(row)
            self._ran_with(row)
            with ui.row().classes("gap-2"):
                flat_button("Monitor", icon="show_chart", on_click=lambda: ui.navigate.to(
                    self._monitor_url(row.name))).props("dense").mark("details-monitor")
                if case is not None and row.status in ("UNCONVERGED", "CANCELLED") and \
                        restart_file(self.directory, row.name) is not None:
                    secondary_button("Continue it", icon="play_arrow",
                                     on_click=lambda: self._only(row.name, continue_=True)).props("dense").mark(
                        "details-continue")
                elif case is not None and row.status == "FAILED" and restart_file(self.directory, row.name) is None \
                        and last_solution(self.directory, row.name) is not None:  # it stopped before writing one
                    secondary_button("Run again from where it started", icon="replay",
                                     on_click=lambda: self._only(row.name, continue_=True)).props("dense").mark(
                        "details-continue")
                if case is not None and row.status == "UNCONVERGED":
                    self._rerun_button(row.name, "unconverged")
                if row.status in ("CONVERGED", "UNCONVERGED"):
                    flat_button("Results", icon="bar_chart", on_click=lambda: ui.navigate.to(
                        project_url("results", self.directory))).props("dense").mark("details-results")
            if case is not None:
                ui.checkbox("Selected for the next run", value=row.name in self.ticked,
                            on_change=lambda e: self._tick(row.name, e.value)).props("dense").mark("details-tick")
            self._attempts_link(row.name)
            if row.name in self.attempts_open:
                self._attempts_list(row.name)

    def _launch(self, view: JobView, selection: _Selection, single: bool) -> None:
        """What will run: the selected cases, where (this machine or Slurm) with how many cores, continuing, Submit."""
        with ui.row().classes("items-center w-full no-wrap"):
            ui.label("Run").classes("as-run-head")
            ui.space()
            ui.toggle({"local": "This machine", "slurm": "Slurm"}, value=self.backend,
                      on_change=lambda e: self._set_backend(e.value)).props(
                "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark("run-backend")
        if single:
            ui.label(self.project.cases[0].name).classes("as-run-big as-mono").mark("run-what")
        else:
            with ui.row().classes("items-baseline gap-2 no-wrap"):
                ui.label(str(len(selection.ticked))).classes("as-run-big").mark("run-what")
                ui.label(f"of {_plural(len(self.project.cases), 'case')} selected").classes("as-muted")
        over = False
        if self.slurm:
            partition = self.options.partition
            check = memory_summary(self.directory, self.project, selection.ticked or None, partition, self.settings)
            slurm_fields(self.frame, self.settings, self.render, mark="run", compact=True,
                         over=check is not None and check.over)
            self._full_note("run")
            over = self._memory("run", check, len(selection.ticked) or len(self.project.cases), partition,
                                self._pick_run)
        else:
            text_field("Cores per case (MPI partitions)", self.project.run.partitions, self._set_partitions,
                       mark="run-partitions")
        self.over_memory = over
        self._starts_box(selection.ticked, single)
        with ui.column().classes("as-run-checks w-full gap-1"):
            clean = self._checks(view, selection, self.options)
        if self.slurm and self.submit_error:
            banner("error", f"Submit failed: {self.submit_error}").mark("submit-error")
        NoteField(self.directory, self.note, self._set_note)
        self._changes(view, selection)
        count = len(selection.ticked)
        if self.checking:
            label = "Checking the configs with SU2…"
        elif self.submitting:
            label = "Submitting…"
        elif single:
            label = "Submit to Slurm" if self.slurm else "Run case"
        else:
            label = f"Submit {_plural(count, 'case')}" if count else "Submit cases"
        self.submit_button = primary_button(label, on_click=self.submit, icon="play_arrow").classes(
            "w-full as-btn-accent").mark("submit")
        self.blocked = hint("").mark("submit-blocked")
        if clean and count and not over:
            ok_line("Ready to submit").mark("run-problems-none")

    @property
    def start_mode(self) -> str:
        return _START_MODE.get(str(self.directory), "sweep")

    def _set_start_mode(self, mode: str) -> None:
        _START_MODE[str(self.directory)] = mode
        self.render()

    def _fold_starts(self, opened: bool) -> None:
        self.starts_open = opened  # no render: the expansion folds itself

    def _starts_box(self, cases: list, single: bool, busy=()) -> None:
        """How the run starts its cases (as the sweep says, each case's own last solution, from scratch) and what
        each selected case then starts from; a case with nothing to start from as chosen stops the run."""
        self.start_problem = None
        start_choice(self.start_mode, self.project.cases, self._set_start_mode, single)
        if not cases:
            return
        try:
            starts = preview_starts(self.directory, self.project, cases, self.start_mode, busy=busy)
        except AeroSuiteError as exc:
            self.start_problem = str(exc)
            start_preview([], self.starts_open, self._fold_starts, error=f"Error: {exc}")
            return
        start_preview(starts, self.starts_open, self._fold_starts)
        missing = [start.case for start in starts if start.kind == "none"]
        if missing:
            count = len(missing)
            self.start_problem = (f"{_plural(count, 'selected case')} {'has' if count == 1 else 'have'} no solution "
                                  "to start from: choose another start")

    def _run_starts(self, cases: list, extra: dict) -> tuple[list, dict]:
        """continue_cases and starts for running `cases`: the chosen start (a rerun's own, else Starts from) with a
        rerun's starts on top."""
        continue_cases, starts = mode_starts(extra.get("mode") or self.start_mode, cases)
        starts = {**starts, **(extra.get("starts") or {})}
        return [name for name in continue_cases if name not in starts], starts

    def _set_note(self, text: str) -> None:
        self.note = text

    def _changes(self, view: JobView, selection: _Selection) -> None:
        """"Note · N config changes since last run" under the note field: the config lines that differ from what the
        selected cases last ran with (rerun lines for the next job included)."""
        if not selection.ticked:
            return
        try:
            found = config_changes(self.directory, self.project, read_template(self.directory, self.project),
                                   selection.ticked, view.overview.jobs, (self.rerun_with or {}).get("changes"))
        except AeroSuiteError:
            return

        def toggle(opened: bool) -> None:
            self.changes_open = opened
            self.render()

        changes_line(found, self.changes_open, toggle)

    def _pick_run(self, name: str) -> None:
        """A node pill or "Switch to": the study's partition (saved with it)."""
        select_partition(self.frame, name, self.options.partition, self.render)

    def _pick_add(self, name: str) -> None:
        self._set_add_partition(name)

    def _full_note(self, mark: str) -> None:
        """A warning under the fields while the chosen partition has no free core; kept current by poll()."""
        self.full_label = banner("warning", "").mark(f"{mark}-full")
        self._full_note_values()

    def _full_note_values(self, parts=None) -> None:
        label = getattr(self, "full_label", None)
        if label is None or label.is_deleted:
            return
        parts = parts or self._summary()
        text = full_note(parts.nodes, self.summary_selected)
        label.text = text
        label.parent_slot.parent.set_visibility(bool(text))

    def _memory(self, mark: str, check, count: int, partition: str, pick) -> bool:
        """Memory per case on `partition`: the estimate of the largest mesh against its limit, a bar under it and the
        cells. Over the limit the bar is red and a box says by how much, names a node with enough memory and offers
        to switch to it. Returns whether that blocks the submit: only on a partition set to Block (else a warning)."""
        if check is None:
            return False
        if check.estimate_gb is None:
            hint(check.note).mark(f"{mark}-memory")
            return False
        over = check.over
        with ui.column().classes("as-memory w-full gap-1").mark(f"{mark}-memory"):
            with ui.row().classes("as-memory-row w-full gap-2"):
                ui.label("Memory per case").classes("as-muted")
                ui.space()
                ui.label(f"{check.estimate_gb:.0f} of {check.limit_gb:.0f} GB").classes(
                    "as-strong" + (" as-error-text" if over else "")).mark(f"{mark}-memory-value")
            ui.linear_progress(min(1.0, check.estimate_gb / check.limit_gb), show_value=False, size="4px",
                               color="negative" if over else "positive").classes("as-memory-bar w-full").mark(
                f"{mark}-memory-bar")
            hint(f"Largest case: {check.elements / 1e6:.1f}M cells").mark(f"{mark}-memory-cells")
        if over:
            short = max(1, round(check.estimate_gb - check.limit_gb))
            nodes = self._summary().nodes
            other = fitting_partition(check.estimate_gb, partition, self.settings.slurm.partitions, nodes)
            text = f"{'This case needs' if count == 1 else 'These cases need'} {short} GB more than {partition} has."
            text += f" {other[0]} has {other[1]:.0f} GB." if other else " No other node has enough memory."
            part = self.settings.slurm.partition(partition)
            blocks = part is not None and part.block_over_memory
            if not blocks:
                text += f" {partition} warns only, so you can still submit."
            with ui.column().classes("w-full gap-1"):
                banner("error" if blocks else "warning", text).mark(f"{mark}-over")
                if other:
                    secondary_button(f"Switch to {other[0]}", on_click=lambda n=other[0]: pick(n)).props(
                        "dense").mark(f"{mark}-switch")
            return blocks
        return False

    def _add_target(self, view: JobView) -> None:
        """Where "Add cases" sends them: the partition last chosen, else one the job does not use yet."""
        job = view.active
        busy = WATCHER.slurm_runner.busy_cases(job)
        names = [p.name for p in self.settings.slurm.partitions]
        used = {job.slurm[name].partition for name in busy if name in job.slurm}
        if self.add_partition not in names:
            self.add_partition = next((name for name in names if name not in used), names[0] if names else None)

    def _add_block(self, view: JobView, selection: _Selection) -> None:
        """More cases into the running Slurm job, e.g. on the other node while it runs; the partition and tasks
        are for this batch only."""
        job = view.active
        busy = WATCHER.slurm_runner.busy_cases(job)
        addable = [name for name in selection.ticked if name not in busy]
        skipped = len(selection.ticked) - len(addable)
        names = [p.name for p in self.settings.slurm.partitions]
        part = self.settings.slurm.partition(self.add_partition)
        ntasks = self.add_ntasks or (part.default_ntasks if part else 1)
        check = memory_summary(self.directory, self.project, addable or None, self.add_partition, self.settings)
        ui.label("Add cases").classes("as-run-head")
        hint("Run more selected cases in this job while it runs, e.g. on the other node").mark("add-note")
        partition_row(names, self.add_partition, ntasks, part, self._set_add_partition, self._set_add_ntasks, "add",
                      over=check is not None and check.over, ntasks_label="Tasks per case (MPI ranks)")
        self._full_note("add")
        over = self._memory("add", check, len(addable) or len(self.project.cases), self.add_partition,
                            self._pick_add)
        self.over_memory = over
        self._starts_box(addable, single=False, busy=busy)
        NoteField(self.directory, self.note, self._set_note)
        options = slurm_options(self.project, self.settings, partition=self.add_partition, ntasks=self.add_ntasks)
        clean = self._checks(view, selection, options)
        count = len(addable)
        label = "Adding…" if self.submitting else (f"Add {_plural(count, 'case')}" if count else "Add cases")
        button = primary_button(label, icon="playlist_add", on_click=lambda: self.add_cases(addable)).classes(
            "w-full as-btn-accent").mark("add-cases")
        button.set_enabled(bool(addable) and not self.submitting and not over and not self.start_problem)
        if self.start_problem and addable:
            hint(self.start_problem).mark("add-skipped")
        elif skipped:
            noun = f"{skipped} selected case{' is' if skipped == 1 else 's are'}"
            hint(f"{noun} already queued or running in this job: skipped").mark("add-skipped")
        elif not selection.ticked:
            hint("Select at least one case").mark("add-skipped")
        if clean and addable and not over:
            ok_line("Ready to submit").mark("run-problems-none")

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

    async def add_cases(self, cases: list) -> None:
        extra, self.rerun_with = self.rerun_with or {}, None
        if self.submitting or not cases or self.over_memory or (self.start_problem and not extra):
            return
        self._load_settings()
        options = slurm_options(self.project, self.settings, partition=self.add_partition, ntasks=self.add_ntasks)
        view = WATCHER.state(self.directory, self.project)
        if view.active is None or view.active.backend != "slurm":
            ui.notify("The job has ended: submit the cases instead", type="warning")
            self.render()
            return
        found = await run.io_bound(preflight, self.directory, self.project, "submit", cases=cases, options=options,
                                   settings=self.settings, check_su2=True)
        errors = [p for p in found if p.severity == "error" and not p.message.startswith(f"Job {view.active.id} ")]
        if errors:
            ui.notify(errors[0].message, type="negative")
            return
        continue_cases, starts = self._run_starts(cases, extra)
        self.submitting = True
        self.render()
        background_tasks.create(self._add_slurm(view.active.id, cases, continue_cases, options,
                                                {**extra, "starts": starts}))

    async def _add_slurm(self, job_id: str, cases: list, continue_cases: list, options: SlurmOptions,
                         extra: Optional[dict] = None) -> None:
        extra = extra or {}
        try:
            generate_configs(self.directory, self.project)  # as a submit: the current settings
            await run.io_bound(WATCHER.add_cases, self.directory, self.project, job_id, cases, continue_cases,
                               options, extra.get("changes"), extra.get("starts"))
            if self.note.strip():  # a job has one note: the batch's is added to it
                await run.io_bound(WATCHER.annotate, self.directory, job_id, " ".join(self.note.split()), None, True)
                self.note = ""
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
        started, ends = self.clock
        label.text = clock_text(max(0.0, (datetime.now() - started).total_seconds()),
                                None if ends is None else max(0.0, ends - time.time()))

    def _buttons_state(self, view: JobView, selection: _Selection) -> None:
        if view.active is None:  # one job at a time: while one runs the panel has Cancel, no Submit
            self.clock = None
            self.submit_button.set_enabled(bool(selection.ticked) and not self.has_errors and not self.submitting
                                           and not self.checking and not self.over_memory and not self.start_problem)
            self.blocked.text = ("Fix the error below to run" if self.has_errors else
                                 "Select at least one case" if not selection.ticked else self.start_problem or "")

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
            ui.timer(0, self._machine_values, once=True)  # the note on cores asked for
        return message

    def _monitor_url(self, case: Optional[str] = None) -> str:
        return project_url("monitor", self.directory) + (f"&case={quote(case, safe='')}" if case else "")

    def _last_job(self, view: JobView, single: bool) -> None:
        """No job running: the last job's outcome, its log and the job history."""
        job = view.latest
        with ui.column().classes("gap-0"):
            ui.label("No job running").classes("as-muted as-small")
            ui.label("Last job finished " + _ago(job.finished) if job is not None and job.finished else
                     "Nothing has run yet" if job is None else "Last job").classes("as-jobbar-title").mark(
                "last-job-when")
            if job is not None and job.note:
                note_label(job.note, job.outcome, quoted=True).classes("as-job-note").mark("last-job-note")
        if job is None:
            ui.space()
            ui.label("No job yet").classes("as-muted").mark("last-job")
            return
        took = f" · {duration_text((job.finished - job.created).total_seconds())}" if job.finished else ""
        counts = " · ".join(f"{count} {pill_text(status).lower()}" for status, count in
                            status_counts([_Row(status.value) for status in job.case_status.values()]))
        state = pill_text(job.state).capitalize()
        titled(ui.label(f"{state} · job {job.id} · {_plural(len(job.cases), 'case')}" + (f" · {counts}" if counts else "")
                        + took).classes("as-muted grow as-truncate"), f"Last job {job.id}").mark("last-job")
        with ui.row().classes("as-jobbar-actions items-center no-wrap"):
            secondary_button("Log", icon="terminal", on_click=lambda: self.frame.log.open(job.id)).mark("last-job-log")
            if not single:
                secondary_button("Job history", icon="history", on_click=lambda: self._set_tab("history")).mark(
                    "last-job-history")

    def _checks(self, view: JobView, selection: _Selection, options: Optional[SlurmOptions]) -> bool:
        """The problems with submitting: errors stay in view, warnings fold into one row. Returns whether there are
        none (the caller then says "Ready to submit" under its button)."""
        cases = selection.ticked or None
        problems = preflight(self.directory, self.project, "submit", cases=cases, options=options,
                             settings=self.settings)
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        if self.over_memory:  # the memory box says it
            problems = [p for p in problems if _OUT_OF_MEMORY not in p.message]
        if self.slurm:  # the nodes as the cluster watch last read them
            cluster = WATCHER.slurm_watch.cluster
            partition = (options or slurm_options(self.project, self.settings)).partition
            problems += outside_load_problems(partition, () if cluster is None else cluster.nodes)
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        for severity, message in found:
            if severity == "error":
                banner("error", f"Error: {message}").mark("run-problem-error")
        warnings = [message for severity, message in found if severity != "error"]
        if warnings:
            warning_group(warnings, mark="run-warnings")
        return not found

    def _machine(self) -> None:
        """This machine now: cores (free), memory, SU2 solvers running, who uses the cores; kept current by a
        timer. Read in a worker thread (a reading walks every process on the machine), so the page is up first."""
        with ui.row().classes("as-machine w-full").mark("run-machine"):
            self.machine_labels = {key: stat(label, "") for key, label in (
                ("cores", "Cores"), ("free", "Free now"), ("memory", "Memory free"), ("su2", "SU2 solvers"))}
            for key in self.machine_labels:
                self.machine_labels[key].mark(f"machine-{key}")
        self.machine_note = ui.label("").classes("as-hint-warning").mark("machine-note")
        with ui.column().classes("as-machine-usage w-full gap-0"):
            ui.label("Using the cores").classes("as-stat-label")
            self.machine_usage = ui.label("").classes("as-mono as-usage").mark("machine-usage")
        ui.timer(0, self._machine_values, once=True)

    async def _machine_values(self) -> None:
        if getattr(self, "backend", "local") == "slurm":
            self._summary_values()
            return
        labels = getattr(self, "machine_labels", None)
        if not labels or labels["cores"].is_deleted:
            return
        reading = await run.io_bound(lambda: (machine(), usage()))
        if reading is None or labels["cores"].is_deleted:  # the server is stopping, or the page was drawn again
            return
        here, items = reading
        labels["cores"].text = (f"{here.cores}" if here.physical_cores == here.cores
                                else f"{here.cores} ({here.physical_cores} physical)")
        labels["free"].text = f"about {here.free_cores}"
        labels["memory"].text = f"{here.memory_free_gb:.0f} of {here.memory_total_gb:.0f} GB"
        labels["su2"].text = str(here.su2_processes)
        note = partitions_note(self.project.run.partitions, here) or ""
        self.machine_note.text = note
        self.machine_note.set_visibility(bool(note))
        self.machine_usage.text = "\n".join(usage_text(item) for item in items) or "nothing much"

    def _node_strip(self, selected: Optional[str], pick, full: bool) -> None:
        """The top of the panel, in a light strip: a pill per partition, the ones with room first, the chosen one
        ringed; clicking a pill chooses it. `full`: also your jobs and a link to the Cluster page. Kept current by
        poll()."""
        self.summary_sig = None
        self.summary_selected, self.summary_pick = selected, pick
        with ui.column().classes("as-run-part as-run-strip w-full gap-1"):
            self.summary_box = ui.row().classes("items-center gap-1 w-full").mark("run-cluster-summary")
            self.summary_mine = None
            if full:
                with ui.row().classes("items-center w-full no-wrap gap-2"):
                    self.summary_mine = ui.label("").classes("as-muted as-small grow").mark("run-cluster-mine")
                    ui.link("Cluster →", cluster_url(project_url("run", self.directory))).style(
                        "white-space: nowrap").mark("run-cluster-link")
        self._summary_values()

    def _summary(self):
        """The node strip's pills: the partitions in the settings, as their cases would start there."""
        watch = WATCHER.slurm_watch
        return summary_parts(watch.cluster, watch.snapshot, watch.user, self.settings.slurm)

    def _summary_values(self) -> None:
        box = getattr(self, "summary_box", None)
        if box is None or box.is_deleted:
            return
        parts = self._summary()
        self._full_note_values(parts)
        if (parts, self.summary_selected) == self.summary_sig:
            return  # nothing visible changed: no redraw
        self.summary_sig = (parts, self.summary_selected)
        box.clear()
        with box:
            if parts.message:
                ui.label(parts.message).classes("as-error-text" if parts.bad else "as-muted").mark("run-cluster-message")
            for name, level, text, tip in parts.nodes:
                row = ui.row().classes(f"as-nodepill as-nodepill-{level} items-center no-wrap gap-1"
                                       + (" as-nodepill-on" if name == self.summary_selected else ""))
                row.props("role=button tabindex=0").mark(f"run-pill-{name}")
                row.on("click", lambda _, n=name: self.summary_pick(n))
                row.on("keydown.enter", lambda _, n=name: self.summary_pick(n))
                with row:
                    titled(ui.label(text), tip).classes("as-error-text" if level == "bad" else "").mark(
                        f"run-node-{name}")
        mine = getattr(self, "summary_mine", None)
        if mine is not None and not mine.is_deleted:
            mine.text = f"Your jobs: {parts.mine}" if parts.mine else ""
            mine.set_visibility(bool(parts.mine))

    def _selection(self, view: JobView) -> _Selection:
        return _Selection([case.name for case in self.project.cases if case.name in self.ticked])

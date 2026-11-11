"""Run: a job bar across the top (the running job, or the last one), the cases on the left as a Board (a grid per
altitude: Mach down, α across, one tile per case) or a List by state (running, queued, needs a look, not run, done),
and a panel on the right that stays in view: a case's details when one is clicked, then what will run and Submit (or,
while a Slurm job runs, adding cases to it), checks, the machine or the cluster. A single case is a card. The cases
earlier sweeps ran (kept, not in the next run) have a tab of their own, Earlier sweeps.

RunPage here holds the page's state, its poll and its frame; its methods are in three parts beside it: run_board.py
(the cases on the left), run_panel.py (the panel on the right) and run_cases.py (a case's card, and Submit, Rerun,
Cancel). run_parts.py has what they share."""
import time
from datetime import datetime
from typing import Optional

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.jobs.executors import SlurmOptions, backend_of, slurm_options
from ...engine.jobs.overview import NOT_RUN
from ...engine.settings import load_settings
from ..cluster_view import (
    node_groups,
    partition_nodes,
)
from ..jobs import WATCHER, JobView, job_nodes, job_progress
from ..layout import ProjectFrame, open_session
from ..run_view import (
    has_board,
    job_left,
    layout,
    status_counts,
)
from ..ui_kit import (
    banner,
    chip_button,
    danger_button,
    help_tip,
    hint,
    node_pills,
    pill_text,
    pill_tone,
    secondary_button,
    titled,
)
from .run_board import RunBoard
from .run_cases import RunCases
from .run_panel import RunPanel
from .run_parts import (
    SELECTORS,
    _snapshot,
)

MACHINE_SECONDS = 10.0  # how often the machine strip is read again
POLL_SECONDS = 2.0


def register() -> None:
    @ui.page("/run")
    def run_page(project: str = "", tab: str = "", case: str = "") -> None:
        """`tab`: board, list, earlier or history; `case`: the case whose details open."""
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "run", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            pages.append(RunPage(frame, tab=tab if tab in ("board", "list", "earlier", "history") else None,
                                 focus=case or None))


class RunPage(RunBoard, RunPanel, RunCases):
    def __init__(self, frame: ProjectFrame, tab: Optional[str] = None, focus: Optional[str] = None) -> None:
        self.frame = frame
        self.ticked: Optional[set] = None  # the selected cases; chosen at the first draw (see _default_ticked)
        self.starts_open = True  # "What each starts from" is unfolded
        self.start_problem: Optional[str] = None  # why the selected cases cannot start as chosen (nothing runs)
        self.opened: set[str] = set()  # failed cases whose "why it failed" box is open
        self.tab: Optional[str] = tab  # "board", "list", "earlier" or "history"; chosen at the first draw, then kept
        self.compact = True  # small tiles; the toggle by the status bar shows large ones
        self.sections_open: dict[str, bool] = {}  # board and list sections the user opened or closed
        self.focus: Optional[str] = focus  # the case whose details the panel shows
        self.clock: Optional[tuple] = None  # (job started, cases finished, cases in all) while a job runs
        self.has_errors = False
        self.was_active = False
        self.shown: Optional[tuple] = None  # _snapshot() of the view on screen
        self.dialogs_open = 0  # a re-render while Cancel's confirm dialog awaits would orphan it
        self.cancelling = False  # this page's Cancel is running (other tabs see WATCHER.is_cancelling)
        self.submitting = False  # a Slurm submit (or adding cases) is running in a worker thread
        self.checking = False  # SU2 is checking the configs before a submit
        self.attempts_open: set[str] = set()  # cases whose earlier attempts are listed
        self.rerun_with: Optional[dict] = None  # the next submit's {"changes": {case: lines}, "starts": {case: ref},
        # "mode": its start (START_MODES)}
        self.add_partition: Optional[str] = None  # where "Add cases" sends them (not saved with the study)
        self.add_ntasks: Optional[int] = None  # None: that partition's default
        self.submit_error: Optional[str] = None  # why the last Slurm submit failed, shown until the next one
        self.note = ""  # what the next run is for (kept while the panel is drawn again)
        self.changes_open = False  # the list of config changes under the note is open
        self.over_memory = False  # the memory estimate is over the chosen partition's limit: nothing is submitted
        self.summary_selected: Optional[str] = None  # the partition whose pill has the ring
        self.holder = ui.column().classes("as-content w-full")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)
        ui.timer(MACHINE_SECONDS, self._machine_values)  # not in this tick: a reading walks every process

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
        names = {case.name for case in self.project.cases}
        if self.ticked is None:
            self.ticked = self._default_ticked(view)
        self.ticked &= names  # the cases may have been rebuilt
        if self.tab == "earlier" and not view.overview.earlier:
            self.tab = None
        if self.tab is None:
            self.tab = "board" if has_board(self._shown_cases(view)) else "list"
        if self.focus is not None and self.focus not in {row.name for row in view.overview.all_rows}:
            self.focus = None
        self.jobs_by_id = {job.id: job for job in view.overview.jobs}
        self.holder.clear()
        self.frame.actions.clear()
        selection = self._selection(view)
        kind = layout(self.project.cases)
        with self.holder:
            self._job_bar(view, single=kind == "single")
            with ui.element("div").classes("as-run w-full"):
                with ui.column().classes("as-run-main gap-3"):
                    if kind == "single":
                        self._case_card(view)
                        if view.overview.others:  # the running job's cases the sweep no longer makes
                            self._list(view, view.overview.others)
                        self._history(view)
                    elif kind == "none":
                        ui.label("No cases yet: set up the sweep first.").classes("as-muted").mark("run-no-cases")
                    else:
                        self._views(view)
                        if self.tab == "history":
                            self._history(view)
                        elif self.tab == "earlier":
                            self._earlier(view)
                        else:
                            self._status_bar(view)
                            if self.tab == "board":
                                self._board(view)
                            else:
                                self._list(view)
                            self._selection_bar(selection)
                with ui.column().classes("as-run-side gap-3").mark("run-side"):
                    if self.focus is not None and (kind != "single" or self.focus != self.project.cases[0].name):
                        self._details(view)
                    with ui.column().classes("as-run-panel gap-0").mark("run-panel"):
                        adding = view.active is not None and view.active.backend == "slurm" and kind != "single"
                        if adding:
                            self._add_target(view)
                        if adding or (view.active is None and self.slurm):
                            self._node_strip(self.add_partition if adding else self.options.partition,
                                             self._pick_add if adding else self._pick_run, full=not adding)
                        if view.active is None:
                            with ui.column().classes("as-run-part w-full gap-2"):
                                self._launch(view, selection, single=kind == "single")
                        elif adding:
                            with ui.column().classes("as-run-part w-full gap-2").mark("run-add"):
                                self._add_block(view, selection)
                        else:
                            with ui.column().classes("as-run-part w-full gap-2").mark("run-wait"):
                                ui.label("One job at a time").classes("as-run-head")
                                hint("Cases can be run again once this job ends, or after Cancel.")
                            with ui.column().classes("as-run-part w-full gap-2"):
                                self._checks(view, selection, self.options)
                        if not self.slurm:
                            with ui.column().classes("as-run-part as-run-foot w-full gap-1"):
                                self._machine()
        self._buttons_state(view, selection)

    def _default_ticked(self, view: JobView) -> set:
        """What is selected when the page opens: every case when none has run yet, else the cases not run yet."""
        rows = view.overview.rows
        if all(row.status == NOT_RUN for row in rows):
            return {row.name for row in rows}
        return {row.name for row in rows if row.status == NOT_RUN}

    # -- the job bar -------------------------------------------------------------------------------------------

    def _job_bar(self, view: JobView, single: bool) -> None:
        """The running job across the top (how far, the case now, time, Monitor, Log, Cancel), or the last job."""
        job = view.active
        with ui.row().classes("as-jobbar w-full items-center" + (" as-jobbar-live" if job else "")).mark(
                "job-bar"):
            if job is None:
                self._last_job(view, single)
                return
            progress = job_progress(view)
            with ui.column().classes("gap-0"):
                where = f" · {job.slurm[next(iter(job.slurm))].partition}" if job.slurm else ""
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(f"Running · job {job.id}{where}").classes("as-muted as-small whitespace-nowrap").mark(
                        "run-job")
                    node_pills(job_nodes(job, partition_nodes(node_groups(WATCHER.slurm_watch.cluster))),
                               "job-node")
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    ui.label(f"{progress.finished} of {progress.total}").classes("as-run-big").mark("run-what")
                    ui.label("cases done").classes("as-muted")
            with ui.column().classes("gap-1 grow min-w-0"):
                ui.linear_progress(progress.finished / progress.total if progress.total else 0,
                                   show_value=False).props("rounded size=8px").classes("as-jobbar-progress").mark(
                    "run-progress")
                with ui.row().classes("items-baseline gap-1 min-w-0"):  # the time wraps under, when narrow
                    if progress.current:
                        ui.label("Now").classes("as-muted")
                        ui.label(progress.current).classes("as-mono as-strong as-truncate").mark("run-current")
                        ui.label("·").classes("as-muted")
                    left = job_left(job, max(0.0, (datetime.now() - job.created).total_seconds()))
                    self.clock = (job.created, None if left is None else time.time() + left)
                    self.clock_label = ui.label("").classes("as-muted").mark("run-elapsed")
                    self._tick_clock()
            with ui.row().classes("as-jobbar-actions items-center no-wrap"):  # wrap as one group
                secondary_button("Monitor", icon="show_chart",
                                 on_click=lambda: ui.navigate.to(self._monitor_url(progress.current))).mark("run-monitor")
                secondary_button("Log", icon="terminal", on_click=lambda: self.frame.log.open(job.id)).mark("run-log")
                if self.cancelling or WATCHER.is_cancelling(self.directory):
                    danger_button("Cancelling…").mark("cancel").set_enabled(False)
                else:
                    danger_button("Cancel", on_click=self.confirm_cancel, icon="stop").mark("cancel")

    # -- the views: board, list, job history ------------------------------------------------------------------

    def _views(self, view: JobView) -> None:
        rows = {row.name: row for row in view.overview.rows}
        with ui.row().classes("items-center w-full gap-2"):
            with ui.tabs(value=self.tab, on_change=lambda e: self._set_tab(e.value)).props(
                    "dense no-caps align=left inline-label").classes("as-tabs as-view-tabs").mark("run-tabs"):
                if has_board(self._shown_cases(view)):
                    ui.tab("board", "Board", icon="grid_view").mark("run-tab-board")
                ui.tab("list", "List", icon="view_list").mark("run-tab-list run-tab-cases")
                if view.overview.earlier:
                    titled(ui.tab("earlier", f"Earlier ({len(view.overview.earlier)})", icon="inventory_2").mark(
                        "run-tab-earlier"), "Earlier sweeps: cases kept, not in the next run")
                ui.tab("history", f"Job history ({len(view.overview.jobs)})", icon="history").mark("run-tab-history")
            ui.space()
            if self.tab not in ("board", "list") or not rows:
                return
            with ui.row().classes("items-center gap-2 no-wrap"):  # the chips wrap as one group, under the tabs
                ui.label("Select").classes("as-label")
                for label, statuses in SELECTORS:
                    count = len(rows) if statuses is None else sum(1 for row in rows.values() if row.status in statuses)
                    chip = chip_button(label if statuses == set() else f"{label} {count}",
                                       on_click=lambda s=statuses: self._select(view, s))
                    chip.mark(f"select-{label.lower().replace(' ', '-')}")
                    if statuses and not count:
                        chip.props("disable")

    def _compact(self) -> bool:
        return self.compact

    def _set_compact(self, value: bool) -> None:
        self.compact = value
        self.render()

    def _status_bar(self, view: JobView) -> None:
        """Every case's status at a glance, in one row: a bar with each status's count written in its part (coloured as
        the tiles, its words on hover), an (i) with the order and how to select, and on the board the tile size."""
        counts = status_counts(view.overview.rows)
        if not counts:
            return
        with ui.row().classes("items-center w-full no-wrap gap-2").mark("run-status-bar"):
            with ui.row().classes("as-status-bar grow no-wrap"):
                for status, count in counts:
                    segment = ui.label(str(count)).classes(f"as-status-seg as-seg-{pill_tone(status)}").style(
                        f"flex: {count}").mark(f"count-{status.lower()}")
                    titled(segment, f"{count} {pill_text(status).lower()}")
            order = ", ".join(pill_text(status).lower() for status, _ in counts)
            help_tip(ui.icon("info_outline", size="18px").classes("as-help-icon").mark("run-status-help"),
                     f"Left to right: {order}. Click a case for its details; Ctrl+click it, or a row or column name, "
                     "to select.")
            if self.tab == "board":
                compact = self._compact()
                with ui.row().classes("as-icon-toggle no-wrap").mark("run-density"):
                    for value, icon, tip in ((False, "grid_view", "Large tiles"), (True, "apps", "Compact tiles")):
                        button = ui.button(icon=icon, color=None, on_click=lambda v=value: self._set_compact(v)).props(
                            "flat dense").classes("as-icon-toggle-on" if compact == value else "").mark(
                            f"run-density-{'compact' if value else 'large'}")
                        titled(button, tip)

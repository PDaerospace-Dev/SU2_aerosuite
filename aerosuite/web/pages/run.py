"""Run: a job bar across the top (the running job, or the last one), the cases on the left as a Board (a grid per
altitude: Mach down, α across, one tile per case) or a List by state (running, queued, needs a look, not run, done),
and a panel on the right that stays in view: a case's details when one is clicked, then what will run and Submit (or,
while a Slurm job runs, adding cases to it), checks, the machine or the cluster. A single case is a card. The cases
earlier sweeps ran (kept, not in the next run) have a tab of their own, Earlier sweeps."""
import time
from datetime import datetime
from typing import NamedTuple, Optional
from urllib.parse import quote

from nicegui import background_tasks, run, ui

from ...engine.cfg import generate_configs, read_template, render_case
from ...engine.editing import update_sweep
from ...engine.freestream import sweeps_altitude
from ...engine.attempts import attempts, make_current
from ...engine.errors import AeroSuiteError
from ...engine.jobs.executors import SlurmOptions, backend_of, slurm_options
from ...engine.jobs.diagnose import Diagnosis, diagnose, residual_trend
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import started_from
from ...engine.jobs.rerun import describe
from ...engine.jobs.store import JOBS_DIR
from ...engine.jobs.plan import plan_restarts
from ...engine.machine import machine, partitions_note, usage, usage_text
from ...engine.naming import format_value, parse_case_name
from ...engine.packages import effective
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import RUNS_DIR, restart_file
from ...engine.results import HISTORY_FILE, history_columns
from ...engine.settings import AppSettings, load_settings
from ...engine.slurm_checks import memory_notes
from ...engine.study_results import study_results
from ..cluster_view import can_resubmit, case_slurm_text, node_groups, partition_nodes, summary_parts
from ..fields import text_field
from ..rerun_dialog import ask_rerun, keep_changes, kept
from ..resubmit_dialog import resubmit_case
from .cluster import cluster_url
from ..slurm_fields import slurm_fields
from ..jobs import WATCHER, JobView, job_nodes, job_progress
from ..layout import ProjectFrame, open_session, project_url
from ..run_view import (COMPACT_FROM, TILE_WORDS, board_sections, case_conditions, case_from_name, clock_text,
                        duration_text, earlier_groups, has_board, job_left, layout, state_sections, status_counts,
                        tile_text)
from ..session import parse_int
from ..ui_kit import (banner, card, card_head, chip_button, danger_button, flat_button, help_tip, hint, node_pills,
                      ok_line, pill, pill_text, pill_tone, primary_button, secondary_button, stat, status_dot, table,
                      td, td_box, th, titled, warning_group)

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


_NODE_DOTS = {"free": "done", "busy": "attention", "bad": "red"}
_JOB_DOTS = {"done": "done", "running": "running", "failed": "red", "unconverged": "attention", "cancelled": "plain",
             "pending": "plain"}


def _iterations(history) -> Optional[int]:
    """The iterations a history file holds (its rows), or None."""
    if history is None:
        return None
    try:
        with open(history, "rb") as handle:
            rows = sum(1 for _ in handle) - 1
    except OSError:
        return None
    return rows if rows > 0 else None


def _attempt_number(attempt) -> str:
    return attempt.folder.name.split("-", 1)[0].lstrip("0") or "0"


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
        tuple((row.name, row.status, row.job_id, row.failure_tail) for row in view.overview.all_rows),
        tuple((job.id, job.state, job.finished) for job in view.overview.jobs),
        tuple(view.overview.problems),
    )


class _Row(NamedTuple):
    status: str


def _ago(when: datetime) -> str:
    """"just now", "25 min ago", "3 h ago", "2 days ago"."""
    seconds = max(0.0, (datetime.now() - when).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'' if days == 1 else 's'} ago"


def _tone(status: str) -> str:
    """A tile's colour family: as the pills, with not run apart from queued."""
    return "notrun" if status == NOT_RUN else pill_tone(status)


def _answer(dialog: ui.dialog, value: bool) -> None:
    """Submit a dialog's result and delete it immediately (see the comment in confirm_cancel)."""
    dialog.submit(value)
    dialog.delete()


class _Selection(NamedTuple):
    ticked: list[str]  # the selected cases, in case order
    chosen: bool  # "Continue from each case's last solution" is ticked
    no_solution: list[str]  # selected cases with nothing to continue from


class RunPage:
    def __init__(self, frame: ProjectFrame, tab: Optional[str] = None, focus: Optional[str] = None) -> None:
        self.frame = frame
        self.ticked: Optional[set] = None  # the selected cases; chosen at the first draw (see _default_ticked)
        self.continue_choice: Optional[bool] = None  # None: the default for the selected cases
        self.continue_cases: list[str] = []
        self.opened: set[str] = set()  # failed cases whose "why it failed" box is open
        self.tab: Optional[str] = tab  # "board", "list", "earlier" or "history"; chosen at the first draw, then kept
        self.compact: Optional[bool] = None  # small tiles; None: by the number of cases
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
        self.rerun_with: Optional[dict] = None  # the next submit's {"changes": {case: lines}, "starts": {case: ref}}
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
                        if view.active is None:
                            with ui.column().classes("as-run-part w-full gap-2"):
                                self._launch(view, selection, single=kind == "single")
                        elif view.active.backend == "slurm" and kind != "single":
                            with ui.column().classes("as-run-part w-full gap-2").mark("run-add"):
                                self._add_block(view, selection)
                        else:
                            with ui.column().classes("as-run-part w-full gap-2").mark("run-wait"):
                                ui.label("One job at a time").classes("as-run-head")
                                hint("Cases can be run again once this job ends, or after Cancel.")
                        if view.active is not None:  # idle: the checks sit above Submit
                            with ui.column().classes("as-run-part w-full gap-2"):
                                self._checks(view, selection)
                                self._plan(view, selection)
                        with ui.column().classes("as-run-part as-run-foot w-full gap-1"):
                            if self.slurm:
                                self._cluster_summary()
                            else:
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
        with ui.row().classes("as-jobbar w-full items-center no-wrap" + (" as-jobbar-live" if job else "")).mark(
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
                with ui.row().classes("items-baseline gap-1 no-wrap min-w-0"):
                    if progress.current:
                        ui.label("Now").classes("as-muted")
                        ui.label(progress.current).classes("as-mono as-strong as-truncate").mark("run-current")
                        ui.label("·").classes("as-muted")
                    left = job_left(job, max(0.0, (datetime.now() - job.created).total_seconds()))
                    self.clock = (job.created, None if left is None else time.time() + left)
                    self.clock_label = ui.label("").classes("as-muted as-truncate").mark("run-elapsed")
                    self._tick_clock()
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
        return self.compact if self.compact is not None else len(self.project.cases) > COMPACT_FROM

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

    # -- the panel on the right ------------------------------------------------

    # -- the board -------------------------------------------------------------------------------------------

    def _rows(self, view: JobView) -> dict:
        return {row.name: row for row in view.overview.rows}

    def _places(self, view: JobView) -> dict[str, int]:
        """Each queued case's place in the running job (1 = next)."""
        job = view.active
        if job is None:
            return {}
        queued = [name for name in job.cases if job.case_status.get(name) is not None
                  and job.case_status[name].value == "PENDING"]
        return {name: index for index, name in enumerate(queued, 1)}

    def _open(self, key: str, members: list, first: bool, default: bool = False) -> bool:
        """Whether a section shows its cases: as the user left it; else open when something happens there (running,
        queued, failed), when it is the first one, or by `default`."""
        if key in self.sections_open:
            return self.sections_open[key]
        return first or default or any(row.status in ("RUNNING", "FAILED", "BLOCKED", "PENDING") for row in members)

    def _shown_cases(self, view: JobView) -> list:
        """The project's cases, then the cases a running job has that the sweep no longer makes (by their names)."""
        others = [case_from_name(row.name) for row in view.overview.others]
        return list(self.project.cases) + [case for case in others if case is not None]

    def _board(self, view: JobView) -> None:
        rows = {row.name: row for row in view.overview.all_rows}
        places = self._places(view)
        others = {row.name for row in view.overview.others}
        sections = board_sections(self._shown_cases(view))
        compact = self._compact()
        for index, section in enumerate(sections):
            members = [rows[name] for name in section.cells.values() if name in rows]
            key = f"board:{section.key}"
            opened = self._open(key, members, first=index == 0)
            with ui.column().classes("as-card w-full gap-2").mark(f"board-{section.key}"):
                with ui.row().classes("items-center w-full gap-2 no-wrap as-section-head").mark(
                        f"board-head-{section.key}") as head:
                    ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                    ui.label(section.label or "Cases").classes("as-strong")
                    ui.label(_plural(len(members), "case")).classes("as-muted")
                    if members and all(row.name in others for row in members):
                        ui.label("in the running job, not in the sweep now").classes("as-muted as-small").mark(
                            f"board-others-{section.key}")
                    for status, count in status_counts(members):  # the rest is in the bar above and on the tiles
                        if status in ("FAILED", "BLOCKED"):
                            ui.label(f"{count} {pill_text(status).lower()}").classes(
                                f"as-pill as-pill-{pill_tone(status)}").mark(f"board-{status.lower()}-{section.key}")
                head.on("click", lambda _, k=key, o=opened: self._fold(k, not o))
                if not opened:
                    continue
                with ui.element("div").classes("as-board" + (" as-board-compact" if compact else "")).style(
                        f"grid-template-columns: 64px repeat({len(section.alphas)}, minmax(0, 1fr))"):
                    corner = ui.label(section.corner).classes("as-board-col as-board-corner").mark(
                        f"board-all-{section.key}")
                    corner.on("click", lambda _, n=list(section.cells.values()): self._toggle_names(n))
                    for alpha in section.alphas:
                        names = [name for (m, a), name in section.cells.items() if a == alpha]
                        col = ui.label(f"α {format_value(alpha)}°").classes("as-board-col").mark(
                            f"board-col-{section.key}-{format_value(alpha)}")
                        col.on("click", lambda _, n=names: self._toggle_names(n))
                    for value in section.rows:
                        names = [name for (r, a), name in section.cells.items() if r == value]
                        head_cell = ui.label(section.row_text(value)).classes("as-board-row").mark(
                            f"board-row-{section.key}-{format_value(value)}")
                        head_cell.on("click", lambda _, n=names: self._toggle_names(n))
                        for alpha in section.alphas:
                            name = section.cells.get((value, alpha))
                            if name is None or name not in rows:
                                ui.element("div")
                                continue
                            self._tile(rows[name], places.get(name), compact, other=name in others)

    def _tile(self, row, place: Optional[int], compact: bool, other: bool = False) -> None:
        iterations = (_iterations(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
                      if row.status in ("CONVERGED", "UNCONVERGED", "RUNNING", "CANCELLED") else None)
        text = tile_text(row.status, iterations, place)
        classes = f"as-tile as-tile-{_tone(row.status)}"
        if row.name in self.ticked:
            classes += " as-tile-selected"
        if row.name == self.focus:
            classes += " as-tile-focus"
        with ui.column().classes(classes + " gap-0").mark(f"tile-{row.name}") as tile:
            if not compact:
                ui.label(TILE_WORDS.get(row.status, row.status)).classes("as-tile-word")
            ui.label(text).classes("as-tile-text")
        titled(tile, f"{row.name} · {TILE_WORDS.get(row.status, row.status)}"
               + (" · in the running job, not in the sweep now" if other else "")
               + ("" if row.name not in self.ticked else " · selected"))
        tile.on("click", lambda e, n=row.name: self._tile_click(n, e.args), ["ctrlKey", "metaKey", "shiftKey"])

    def _tile_click(self, name: str, keys) -> None:
        keys = keys if isinstance(keys, dict) else {}
        if keys.get("ctrlKey") or keys.get("metaKey") or keys.get("shiftKey"):
            self._tick(name, name not in self.ticked)
            return
        self.focus = None if self.focus == name else name
        self.render()

    def _toggle_names(self, names: list) -> None:
        """Select these cases, or, when all of them are selected, unselect them."""
        names = [name for name in names if name in {case.name for case in self.project.cases}]
        if names and all(name in self.ticked for name in names):
            self.ticked -= set(names)
        else:
            self.ticked |= set(names)
        self.continue_choice = None
        self.render()

    def _fold(self, key: str, opened: bool) -> None:
        self.sections_open[key] = opened
        self.render()

    # -- earlier sweeps ----------------------------------------------------------------------------------------

    def _earlier(self, view: JobView) -> None:
        """The cases earlier sweeps ran, kept but not in the next run: one folded line per altitude (its cases, their
        outcomes, the jobs), its grid when opened, a click on a case opening it in Monitor; Add to sweep puts the
        altitude back in the sweep, which makes its cases (same names) the sweep's again."""
        rows = view.overview.earlier
        hint(f"{_plural(len(rows), 'case')} from earlier sweeps: their runs, histories and results are kept. They are "
             "not part of the next run; click one for it in Monitor.").mark("earlier-note")
        can_add = sweeps_altitude(self.project)
        for group in earlier_groups(rows):
            key = f"earlier:{group.key}"
            opened = self.sections_open.get(key, False)
            jobs = list(dict.fromkeys(row.job_id for row in group.rows))
            counts = " · ".join(f"{count} {pill_text(status).lower()}" for status, count in status_counts(group.rows))
            with ui.column().classes("as-card as-earlier w-full gap-2").mark(f"earlier-{group.key}"):
                with ui.row().classes("items-center w-full gap-2 no-wrap"):
                    with ui.row().classes("items-center grow min-w-0 gap-2 no-wrap as-earlier-head").mark(
                            f"earlier-head-{group.key}") as head:
                        ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                        ui.label(group.label).classes("as-strong")
                        ui.label(f"{_plural(len(group.rows), 'case')} · {counts} · "
                                 f"job{'s' if len(jobs) > 1 else ''} {', '.join(jobs)}").classes("as-muted as-truncate")
                    head.on("click", lambda _, k=key, o=opened: self._fold(k, not o))
                    if can_add and group.altitude is not None:
                        secondary_button("Add to sweep", icon="add",
                                         on_click=lambda a=group.altitude: self._add_altitude(a)).mark(
                            f"earlier-add-{group.key}")
                if opened:
                    self._earlier_cases(group)

    def _earlier_cases(self, group) -> None:
        """An opened earlier altitude: a grid per β (Mach down, α across), then any case its name places on none."""
        compact = self._compact()
        by_name = {row.name: row for row in group.rows}
        sections = board_sections(group.cases)
        for section in sections:
            if len(sections) > 1:
                ui.label(section.label).classes("as-muted")
            with ui.element("div").classes("as-board" + (" as-board-compact" if compact else "")).style(
                    f"grid-template-columns: 64px repeat({len(section.alphas)}, minmax(0, 1fr))"):
                ui.label(section.corner).classes("as-board-col as-board-corner")
                for alpha in section.alphas:
                    ui.label(f"α {format_value(alpha)}°").classes("as-board-col")
                for value in section.rows:
                    ui.label(section.row_text(value)).classes("as-board-row")
                    for alpha in section.alphas:
                        name = section.cells.get((value, alpha))
                        if name is None:
                            ui.element("div")
                        else:
                            self._earlier_tile(by_name[name], compact)
        drawn = {case.name for case in group.cases}
        for row in group.rows:
            if row.name not in drawn:
                with ui.row().classes("items-center gap-2 w-full no-wrap").mark(f"earlier-row-{row.name}"):
                    ui.label(row.name).classes("as-mono")
                    pill(row.status)
                    ui.space()
                    flat_button("Monitor", icon="show_chart",
                                on_click=lambda n=row.name: ui.navigate.to(self._monitor_url(n)))

    def _earlier_tile(self, row, compact: bool) -> None:
        iterations = (_iterations(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
                      if row.status in ("CONVERGED", "UNCONVERGED", "CANCELLED") else None)
        with ui.column().classes(f"as-tile as-tile-{_tone(row.status)} gap-0").mark(f"tile-{row.name}") as tile:
            if not compact:
                ui.label(TILE_WORDS.get(row.status, row.status)).classes("as-tile-word")
            ui.label(tile_text(row.status, iterations)).classes("as-tile-text")
        titled(tile, f"{row.name} · {TILE_WORDS.get(row.status, row.status)} · job {row.job_id} · click for Monitor")
        tile.on("click", lambda _, n=row.name: ui.navigate.to(self._monitor_url(n)))

    def _add_altitude(self, altitude: float) -> None:
        message = self.frame.save(lambda p: update_sweep(
            p, altitudes_km=sorted({*p.sweep.altitudes_km, altitude})))
        if message is not None:
            ui.notify(message, type="negative")
            return
        ui.notify(f"{format_value(altitude)} km is in the sweep again: generate its configs, then run its cases",
                  type="positive")
        self.tab = None  # back to the board, where its cases now are
        self.render()

    # -- the list by state -------------------------------------------------------------------------------------

    def _list(self, view: JobView, rows: Optional[list] = None) -> None:
        """The cases by state (`rows`: only these, e.g. a single case's running job's others)."""
        cases = {case.name: case for case in self.project.cases}
        places = self._places(view)
        sections = state_sections(view.overview.all_rows if rows is None else rows)
        cases.update({c.name: c for c in self._shown_cases(view) if c.name not in cases})
        own = {case.name for case in self.project.cases}
        with ui.column().classes("as-card as-card-flush w-full gap-0").mark("run-list"):
            for key, title, members in sections:
                skey = f"list:{key}"
                # Queued and done fold when long; the rest is what to look at or act on
                opened = self.sections_open.get(skey, key in ("running", "attention", "not-run") or len(members) <= 8)
                ticked = [row.name for row in members if row.name in self.ticked]
                selectable = [row.name for row in members if row.name in own]
                with ui.row().classes(f"as-list-section as-list-{key} items-center w-full no-wrap gap-2").mark(
                        f"list-{key}") as head:
                    ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                    ui.label(title).classes("as-strong")
                    for status, count in status_counts(members):
                        ui.label(f"{count} {pill_text(status).lower()}").classes(f"as-pill as-pill-{pill_tone(status)}")
                    ui.space()
                    if key == "queued" and places:
                        nxt = min(places, key=places.get)
                        ui.label(f"next: {nxt}").classes("as-muted as-small")
                    if key in ("attention", "not-run", "done") and selectable:
                        everyone = len(ticked) == len(selectable)
                        flat_button("Unselect all" if everyone else f"Select all {len(selectable)}",
                                    on_click=lambda n=selectable: self._toggle_names(n)).props(
                            "dense").mark(f"list-select-{key}")
                head.on("click", lambda _, k=skey, o=opened: self._fold(k, not o))
                if not opened:
                    continue
                with table("36px minmax(10rem, 1.5fr) minmax(9rem, 1fr) minmax(8rem, .9fr) minmax(12rem, 1.2fr) "
                           "72px").classes("as-table-compact"):
                    for row in members:
                        self._list_row(row, cases.get(row.name), places.get(row.name), own=row.name in own)

    def _list_row(self, row, case, place: Optional[int], own: bool = True) -> None:
        with td_box():
            if own:  # a case the sweep no longer makes is the job's: it cannot be selected
                ui.checkbox(value=row.name in self.ticked,
                            on_change=lambda e, n=row.name: self._tick(n, e.value)).props("dense").mark(
                    f"tick-{row.name}")
            else:
                titled(ui.icon("lock", size="16px").classes("as-muted"),
                       "In the running job, not in the sweep now").mark(f"other-{row.name}")
        found = self._diagnosis(row)
        with td_box():
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(row.name).classes("as-strong as-mono")
                if found is not None:
                    ui.label(found.summary).classes("as-failure-reason as-truncate").mark(f"why-{row.name}")
                self._ran_with(row)
                self._attempts_link(row.name)
        conditions = [f"M {format_value(case.mach)}", f"α {format_value(case.alpha)}"] if case else []
        if case is not None and len({c.beta for c in self.project.cases}) > 1:
            conditions.append(f"β {format_value(case.beta)}")
        if case is not None and case.altitude_km is not None:
            conditions.append(f"{format_value(case.altitude_km)} km")
        td(" · ".join(conditions)).classes("as-muted")
        with td_box():
            self._status(row)
            if place:
                ui.label(f"#{place}").classes("as-muted as-small")
        job = self.jobs_by_id.get(row.job_id)
        if job is not None and job.backend == "slurm":
            with td_box() as cell:
                cell.classes("as-slurm-cell")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(row.job_id).classes("as-mono as-small").mark(f"job-{row.name}")
                    ui.label(case_slurm_text(job, row.name)).classes("as-mono as-muted as-small").mark(
                        f"slurm-{row.name}")
                self._resubmit_button(job, row.name)
        else:
            td(row.job_id or "—", mono=True).classes("as-small").mark(f"job-{row.name}")
        with td_box():
            flat_button("Details", on_click=lambda n=row.name: self._focus(n)).props("dense").mark(
                f"details-{row.name}")
        if row.name in self.attempts_open:
            with ui.element("div").style("grid-column: 1 / -1"):
                self._attempts_list(row.name)

    def _focus(self, name: str) -> None:
        self.focus = None if self.focus == name else name
        self.render()

    def _selection_bar(self, selection: _Selection) -> None:
        if not selection.ticked:
            return
        with ui.row().classes("as-selbar w-full items-center no-wrap gap-3").mark("selection-bar"):
            ui.label(f"{len(selection.ticked)} selected").classes("as-strong").mark("selection-count")
            shown = ", ".join(selection.ticked[:4]) + (f" … and {len(selection.ticked) - 4} more"
                                                       if len(selection.ticked) > 4 else "")
            ui.label(shown).classes("as-mono as-small as-truncate grow")
            flat_button("Clear", on_click=lambda: self._select(None, set())).props("dense").mark("selection-clear")

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
                    f"{_plural(count, 'selected case')} {'has' if count == 1 else 'have'} no solution to continue from")
            titled(hint(text), ", ".join(selection.no_solution)).mark("continue-missing")
        with ui.column().classes("as-run-checks w-full gap-1"):
            self._checks(view, selection)
            self._plan(view, selection)
        if self.slurm and self.submit_error:
            banner("error", f"Submit failed: {self.submit_error}").mark("submit-error")
        label = "Run case" if single else f"Submit {_plural(len(selection.ticked), 'case')}"
        if self.slurm:
            label = "Submitting…" if self.submitting else (
                "Submit to Slurm" if single else f"Submit {_plural(len(selection.ticked), 'case')} to Slurm")
        if self.checking:
            label = "Checking the configs with SU2…"
        self.submit_button = primary_button(label, on_click=self.submit, icon="play_arrow").classes("w-full").mark(
            "submit")
        self.blocked = hint("").mark("submit-blocked")

    def _slurm_fields(self) -> None:
        """Partition, tasks per case and time limit (saved with the project); always one node."""
        slurm_fields(self.frame, self.settings, self.render, mark="run", compact=True)

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
        hint("Run more selected cases in this job while it runs, e.g. on the other node").mark("add-note")
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
            count = f"{skipped} selected case{' is' if skipped == 1 else 's are'}"
            hint(f"{count} already queued or running in this job: skipped").mark("add-skipped")
        elif not selection.ticked:
            hint("Select cases to add them to this job").mark("add-skipped")

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
        if self.submitting or not cases:
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
        self.submitting = True
        self.render()
        continue_cases = [name for name in self.continue_cases if name in cases]
        background_tasks.create(self._add_slurm(view.active.id, cases, continue_cases, options, extra))

    async def _add_slurm(self, job_id: str, cases: list, continue_cases: list, options: SlurmOptions,
                         extra: Optional[dict] = None) -> None:
        extra = extra or {}
        try:
            generate_configs(self.directory, self.project)  # as a submit: the current settings
            await run.io_bound(WATCHER.add_cases, self.directory, self.project, job_id, cases, continue_cases,
                               options, extra.get("changes"), extra.get("starts"))
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
                                           and not self.checking)
            self.blocked.text = ("Fix the error below to run" if self.has_errors else
                                 "Select at least one case" if not selection.ticked else "")

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
        """No job running: the last job's outcome, its log and the job history."""
        job = view.latest
        with ui.column().classes("gap-0"):
            ui.label("No job running").classes("as-muted as-small")
            ui.label("Last job finished " + _ago(job.finished) if job is not None and job.finished else
                     "Nothing has run yet" if job is None else "Last job").classes("as-jobbar-title").mark(
                "last-job-when")
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
        secondary_button("Log", icon="terminal", on_click=lambda: self.frame.log.open(job.id)).mark("last-job-log")
        if not single:
            secondary_button("Job history", icon="history", on_click=lambda: self._set_tab("history")).mark(
                "last-job-history")

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
        """One pill per partition (free, share busy, or bad), your jobs under them and a link to the Cluster page;
        kept current by poll()."""
        self.summary_sig = None
        with ui.row().classes("items-center w-full no-wrap gap-2"):
            self.summary_box = ui.row().classes("items-center gap-1 grow").mark("run-cluster-summary")
            ui.link("Cluster →", cluster_url(project_url("run", self.directory))).style("white-space: nowrap").mark(
                "run-cluster-link")
        self.summary_mine = ui.label("").classes("as-muted").mark("run-cluster-mine")
        self._summary_values()

    def _summary_values(self) -> None:
        box = getattr(self, "summary_box", None)
        if box is None or box.is_deleted:
            return
        watch = WATCHER.slurm_watch
        parts = summary_parts(watch.cluster, watch.snapshot, watch.user)
        if parts == self.summary_sig:
            return  # nothing visible changed: no redraw
        self.summary_sig = parts
        box.clear()
        with box:
            if parts.message:
                ui.label(parts.message).classes("as-error-text" if parts.bad else "as-muted").mark("run-cluster-message")
            for name, level, text, tip in parts.nodes:
                with ui.row().classes("as-nodepill items-center no-wrap gap-1"):
                    status_dot(_NODE_DOTS[level])
                    titled(ui.label(text), tip).classes("as-error-text" if level == "bad" else "").mark(
                        f"run-node-{name}")
        self.summary_mine.text = f"Yours: {parts.mine}" if parts.mine else ""
        self.summary_mine.set_visibility(bool(parts.mine))

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
        self.continue_choice = start == "last"
        self.render()  # works out the Continue choice for the ticked case
        starts = {} if start == "last" else {name: None if start == "scratch" else start}
        self.rerun_with = {"changes": {name: changes} if changes else {}, "starts": starts}
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
        """Tick just this case (and Continue or not): Submit is then one click away."""
        self.ticked = {name}
        self.continue_choice = continue_
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
        """A status pill clicked: a single case opens its "why it failed"; a sweep's case shows its details."""
        if layout(self.project.cases) == "single":
            self.opened ^= {name}
            self.render()
        else:
            self._focus(name)

    def _set_continue(self, value: bool) -> None:
        self.continue_choice = value
        self.render()

    async def submit(self) -> None:
        stale = self.frame.ensure_current(notify=False)
        if stale is not None:
            if self.frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; submit again", type="warning")
            return
        extra, self.rerun_with = self.rerun_with or {}, None
        cases = [case.name for case in self.project.cases if case.name in self.ticked]
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
                background_tasks.create(self._submit_slurm(cases, list(self.continue_cases), self.options, extra))
            return
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            WATCHER.submit(self.directory, self.project, cases, self.continue_cases,
                           changes=extra.get("changes"), starts=extra.get("starts"))
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            self.render()
            return
        ui.notify(f"Started {_plural(len(cases), 'case')}", type="positive")
        self.frame.refresh()
        self.render()

    async def _submit_slurm(self, cases: list, continue_cases: list, options: SlurmOptions,
                            extra: Optional[dict] = None) -> None:
        """sbatch once per case (seconds for a big sweep, or up to the timeout when Slurm is slow): in a worker
        thread, so the server keeps answering."""
        extra = extra or {}
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            await run.io_bound(WATCHER.submit, self.directory, self.project, cases, continue_cases, options,
                               extra.get("changes"), extra.get("starts"))
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

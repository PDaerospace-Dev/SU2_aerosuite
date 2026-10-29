"""Cluster: every node (sinfo -N) and the user's AeroSuite cases on Slurm across every
study — queued, running, or ended in the last 7 days — with Cancel (one case), Resubmit and Log. Everything comes
from the server's Slurm poller and the job records; the page never runs a Slurm command itself."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from nicegui import run, ui

from ...engine.ascii_export import ascii_log_name
from ...engine.cluster import MAX_ROWS, RecordIndex, my_jobs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.store import load_job
from ...engine.project import open_project
from ...engine.settings import SettingsError, load_settings, save_settings
from ..cluster_view import (JOB_KINDS, JobGroup, NodeJob, cluster_status, expected_ends, filter_jobs, glance,
                            job_groups, job_state_text, job_studies, moved, node_groups, node_jobs, ordered_nodes,
                            partition_nodes, queue_starts, queue_text, sort_jobs, started_at, submitted_text,
                            when_text)
from ..jobs import WATCHER
from ..layout import header, project_url
from ..resubmit_dialog import resubmit_case
from ..run_view import about_text, duration_text
from .. import slurm_watch
from ..slurm_watch import WATCH
from ..ui_kit import banner, chip_button, danger_button, flat_button, hint, pill, secondary_button, table, td, td_box, th

POLL_SECONDS = 2.0
LOG_LINES = 200
INDEX = RecordIndex()  # shared by every Cluster page: a study's records are read once per change
KIND_LABELS = {"all": "All", "active": "Active", "failed": "Failed"}
_COLLAPSED: set[str] = set()  # "jobs": sections the user folded, kept while the server runs
_SORT = {"key": "submitted", "descending": True}  # My jobs' order, kept while the server runs
GROUPED_AT_FIRST = True  # My jobs under a line per study job (Group), an ended job's cases folded
_GROUP = {"on": GROUPED_AT_FIRST}  # Group switched on or off, kept while the server runs
_GROUP_OPEN: dict[str, bool] = {}  # a study job's line clicked open or shut (else open while the job is active)
SORTED_COLUMNS = {"Submitted": "submitted", "Study": "study", "Case": "case", "State": "state", "Elapsed": "elapsed"}


def register() -> None:
    @ui.page("/cluster")
    def cluster_page(back: str = "") -> None:
        header("cluster")
        with ui.column().classes("as-page w-full").mark("cluster-page"):
            with ui.row().classes("as-crumbs w-full items-center"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Cluster").classes("as-crumb-current").mark("crumb-page")
                ui.space()
                target = safe_back(back)
                ui.button(icon="close", color=None, on_click=lambda: ui.navigate.to(target)).props(
                    'flat round dense aria-label="Close"').tooltip("Back to the page you came from").mark(
                    "cluster-close")
            if not slurm_watch.slurm_available():
                banner("info", "Slurm is not installed on this machine.").mark("cluster-none")
                return
            ClusterPage()


def safe_back(back: str) -> str:
    """Where Close goes: the page you came from when it is a page of AeroSuite, else Projects (never another site)."""
    if back.startswith("/") and not back.startswith("//") and "\\" not in back and not back.startswith("/cluster"):
        return back
    return "/"


def cluster_url(back: str) -> str:
    """/cluster, remembering the page to go back to."""
    return f"/cluster?back={quote(back, safe='')}"


def _answer(dialog: ui.dialog, value: bool) -> None:
    dialog.submit(value)
    dialog.delete()


def _time(stamp: Optional[float]) -> str:
    return f"{datetime.fromtimestamp(stamp):%H:%M:%S}" if stamp else "—"


class ClusterPage:
    def __init__(self) -> None:
        self.kind = "all"
        self.study: Optional[str] = None
        self.dialogs_open = 0
        self.shown: Optional[tuple] = None
        self.good = None  # the last snapshot Slurm answered: shown, greyed, while it does not
        self.good_cluster = None  # likewise the last node list
        self.nodes_note = None
        self.taken = 0.0  # when the shown queue was asked
        self.clocks: list[tuple[ui.label, Callable[[datetime], str]]] = []  # node cards' times, ticked in place
        self.order = list(load_settings()[0].slurm.node_order)  # the node cards as the user dragged them
        self.dragging: Optional[str] = None  # the node card being dragged: the page is not redrawn meanwhile
        WATCH.show_page()
        ui.context.client.on_delete(WATCH.hide_page)  # not on_disconnect: a brief socket drop reconnects
        self.dialog_host = ui.element("div")  # dialogs live here: render() clears only the holder
        self.holder = ui.column().classes("w-full gap-4")
        self.poll()
        ui.timer(POLL_SECONDS, self.poll)

    def _data(self) -> tuple:
        """What the page shows, as a value: the page is drawn again only when it changes (the poll times are
        updated in place)."""
        snapshot, cluster, recent = WATCH.snapshot, WATCH.cluster, WATCH.recent
        if snapshot is not None and snapshot.ok:
            self.good = snapshot
        if cluster is not None and cluster.error is None and cluster.nodes:
            self.good_cluster = cluster
        queue = self.good.queue if self.good is not None else {}
        rows, more = my_jobs(queue, recent.rows if recent is not None else {}, WATCH.user, INDEX, MAX_ROWS)
        for row in rows:  # a study never opened here: the poller keeps its record current from now on
            if row.active and row.study is not None and row.job_id is not None:
                WATCH.track(row.study, row.job_id)
        tone, tip = cluster_status(snapshot, cluster)
        outage = tip if tone == "red" else None
        groups = tuple((name, default, tuple(nodes)) for name, default, nodes in node_groups(self.good_cluster))
        accounting_down = recent is not None and recent.error is not None
        taken = self.taken = self.good.taken if self.good is not None else 0.0  # not in the value: every poll
        on_nodes = node_jobs(rows, INDEX.lookup, partition_nodes(groups), taken)
        nodes = tuple(ordered_nodes(groups, self.order))
        tiles = glance(nodes, on_nodes, rows, INDEX.lookup) if nodes else ()
        ends, job_ends = expected_ends(rows, INDEX.lookup, taken)
        groups = tuple(job_groups(rows, INDEX.lookup, job_ends, taken)) if _GROUP["on"] else ()
        return (outage, nodes, tuple(rows), more, accounting_down, self.kind, self.study,
                _SORT["key"], _SORT["descending"], tuple(sorted(on_nodes.items())), tiles,
                tuple(sorted(ends.items())), groups)

    def poll(self) -> None:
        if self.dialogs_open or self.dragging is not None:
            return
        data = self._data()
        if data != self.shown:
            self.shown = data
            self.render(data)
        elif self.nodes_note is not None and not self.nodes_note.is_deleted:
            self.nodes_note.text = self._nodes_text(data[1], data[0] is not None)
            self._tick()

    def _tick(self) -> None:
        now = datetime.now()
        for label, text in self.clocks:
            if not label.is_deleted:
                label.text = text(now)

    def render(self, data: tuple) -> None:
        outage, groups, rows, more, accounting_down = data[:5]
        self.down = outage is not None
        self.holder.clear()
        with self.holder:
            if self.down:
                banner("error", f"{outage}. Showing the last known state, as of {_time(WATCH.last_ok)}.").mark(
                    "cluster-outage")
            self._glance(data[10])
            self._nodes(groups, dict(data[9]))
            self._jobs(list(rows), more, accounting_down, dict(data[11]), data[12], self.taken)
        self._tick()  # the group lines' times too

    def _nodes_text(self, nodes: tuple, down: bool) -> str:
        if not nodes:
            return "Asking Slurm…"
        nodes = [node for _p, _d, node in nodes]
        total, used = sum(n.total for n in nodes), sum(n.allocated for n in nodes)
        stamp = self.good_cluster.taken if self.good_cluster is not None else None
        when = f"as of {_time(stamp)}" if down else f"updated {_time(stamp)}"
        return f"{len(nodes)} node{'' if len(nodes) == 1 else 's'} · {used} / {total} CPUs in use · {when}"

    # -- nodes ------------------------------------------------------------------------------------------------

    def _glance(self, tiles: tuple) -> None:
        """The tiles at the top: what runs, what waits, cases to go, CPUs and nodes, at a glance."""
        if not tiles:
            return
        with ui.element("div").classes("as-glance w-full").mark("cluster-glance"):
            for tile in tiles:
                with ui.column().classes("as-glance-tile" + (" as-glance-alert" if tile.alert else "")).mark(
                        f"tile-{tile.key}"):
                    ui.label(tile.label).classes("as-glance-label")
                    ui.label(tile.value).classes("as-glance-value").mark(f"tile-{tile.key}-value")
                    ui.label(tile.sub).classes("as-glance-sub").mark(f"tile-{tile.key}-sub")

    def _nodes(self, nodes: tuple, jobs: dict) -> None:
        """A card per node, in the order the user dragged them to (else the default partition's first): CPU,
        memory and load dials, why a drained or down node is out, the study jobs running there and those queued
        for it."""
        self.clocks = []
        with ui.row().classes("items-baseline w-full gap-2").mark("nodes-card"):
            ui.label("Nodes").classes("as-card-title")
            self.nodes_note = ui.label(self._nodes_text(nodes, self.down)).classes("as-muted").mark("nodes-summary")
            ui.space()
            if len(nodes) > 1:
                ui.label("Drag a card to move it").classes("as-muted as-small")
        with ui.element("div").classes("as-node-grid w-full"):
            for partition, default, node in nodes:
                self._node_card(partition, default, node, jobs.get(node.node, ()))
        self._tick()

    def _node_card(self, partition: str, default: bool, node, jobs: tuple) -> None:
        name = node.node
        with ui.column().classes("as-node-card" + (" as-node-bad" if node.bad else "")).props(
                "draggable=true").mark(f"node-card-{name}") as card:
            card.on("dragstart", lambda n=name: self._drag(n),
                    js_handler=f"(e) => {{ e.dataTransfer.setData('text/plain', {name!r}); "
                               "e.dataTransfer.effectAllowed = 'move'; emit(); }")
            card.on("dragend", lambda: self._drag(None))
            card.on("dragover", js_handler="(e) => { e.preventDefault(); e.currentTarget.classList.add('as-drop'); }")
            card.on("dragleave", js_handler="(e) => e.currentTarget.classList.remove('as-drop')")
            card.on("drop", lambda n=name: self._drop(n),
                    js_handler="(e) => { e.preventDefault(); e.currentTarget.classList.remove('as-drop'); emit(); }")
            with ui.row().classes("as-node-head items-center w-full no-wrap gap-2"):
                ui.icon("drag_indicator").classes("as-node-grip").tooltip("Drag to move this node")
                ui.label(name).classes("as-node-name").mark(f"node-{name}")
                ui.label(partition + (" · default" if default else "")).classes("as-muted as-small")
                ui.space()
                ui.label(node.words).classes(f"as-node-state as-node-state-{_state_tone(node)}").tooltip(
                    f"Slurm: {node.state}").mark(f"node-{name}-state")
            with ui.row().classes("as-node-dials w-full no-wrap"):
                _dial(node.busy_percent / 100, f"{node.busy_percent}%", f"CPU · {node.cpus}", f"node-{name}-cpus")
                memory = node.memory_used
                _dial(memory or 0, "—" if memory is None else f"{round(100 * memory)}%",
                      f"Memory · {node.memory_gb} GB" if node.memory_gb else "Memory", f"node-{name}-memory").tooltip(
                    f"{node.memory} (Linux keeps its file cache out of free memory)")
                _dial(node.load_share, node.load if node.load == "—" else f"{float(node.load):.0f}", "Load",
                      f"node-{name}-load").tooltip(f"Load {node.load} on {node.total} CPUs")
            if node.reason:
                with ui.row().classes("as-node-why w-full no-wrap items-center gap-2"):
                    ui.icon("warning_amber").classes("as-node-why-icon")
                    ui.label(node.reason).mark(f"node-{name}-note")
            self._node_jobs(name, jobs, node.bad)

    def _node_jobs(self, node: str, jobs: tuple, bad: bool) -> None:
        """Running: a line per study job with cases running here (cases finished / in all and a bar, as on its Run
        page, the case now and about how long is left). Next: those queued for this node, in the queue's order, and
        about when each starts. Clicking a line opens the study's Run page."""
        running = [job for job in jobs if not job.waiting]
        waiting = [job for job in jobs if job.waiting]
        if not jobs:
            if not bad:
                ui.label("No AeroSuite job here").classes("as-muted as-small as-node-none w-full").mark(
                    f"node-{node}-nojob")
            return
        if running:
            with ui.column().classes("as-node-section w-full gap-1"):
                ui.label("Running").classes("as-node-section-title")
                for job in running:
                    self._job_line(node, job)
        if waiting:
            with ui.column().classes("as-node-section w-full gap-1"):
                ui.label("Next").classes("as-node-section-title")
                for index, job in enumerate(waiting):
                    self._job_line(node, job, lambda now, i=index: queue_text(*queue_starts(jobs, now)[i]))

    def _job_line(self, node: str, job: NodeJob, when: Optional[Callable[[datetime], str]] = None) -> None:
        mark = f"node-{node}-job-{job.job_id}"
        with ui.link(target=project_url("run", job.study)).classes("as-node-job flex flex-col w-full").props(
                'draggable="false"').mark(mark):
            ui.tooltip(job.tip)
            with ui.row().classes("items-center w-full no-wrap gap-2"):
                if job.waiting:
                    ui.element("span").classes("as-node-queued-ring")
                else:
                    ui.circular_progress(job.done, min=0, max=1, show_value=False, size="16px").props(
                        "thickness=0.4 track-color=grey-3")
                ui.label(job.study_name).classes("as-node-study")
                if job.waiting:
                    ui.label("Queued").classes("as-node-queued-pill")
                ui.space()
                count = f"{len(job.cases)} cases" if job.waiting else f"{job.finished} / {job.total}"
                ui.label(count).classes("as-mono as-small").mark(f"{mark}-done")
            if not job.waiting:
                ui.linear_progress(job.done, show_value=False).props("rounded size=5px").classes("as-node-job-bar")
            label = ui.label("").classes("as-muted as-small as-node-when").mark(f"{mark}-time")
            self.clocks.append((label, when or (lambda now, j=job: _running_text(j, now))))
            if job.elsewhere:
                ui.label(f"↳ {job.elsewhere}").classes("as-node-elsewhere").mark(f"{mark}-elsewhere")

    def _drag(self, node: Optional[str]) -> None:
        self.dragging = node
        if node is None:
            self.poll()  # what changed while the card was held

    def _drop(self, target: str) -> None:
        node, self.dragging = self.dragging, None
        if node is None or node == target or self.shown is None:
            return
        order = moved([n.node for _p, _d, n in self.shown[1]], node, target)
        self.order = order
        try:
            settings = load_settings()[0]
            settings.slurm.node_order = order
            save_settings(settings)
        except SettingsError as exc:
            ui.notify(f"The order is kept on this page only: {exc}", type="warning")
        self.shown = None
        self.poll()

    @contextmanager
    def _section(self, key: str, title: str, subtitle: str, mark: str):
        """A card whose title row folds it (open by default; the choice kept while the server runs). Yields
        (header row for extra controls, whether the body is shown)."""
        opened = key not in _COLLAPSED
        with ui.column().classes("as-card as-card-flush w-full gap-0").mark(mark):
            with ui.row().classes("items-center w-full no-wrap gap-2 pr-3") as head:
                with ui.button(on_click=lambda: self._toggle(key), color=None).props(
                        f'flat no-caps align=left aria-expanded={"true" if opened else "false"}').classes(
                        "as-section-toggle grow").mark(f"{mark}-toggle"):
                    ui.icon("expand_more" if opened else "chevron_right")
                    ui.label(title).classes("as-card-title")
                    ui.label(subtitle).classes("as-muted as-small")
            yield head, opened

    def _toggle(self, key: str) -> None:
        (_COLLAPSED.discard if key in _COLLAPSED else _COLLAPSED.add)(key)
        self.shown = None
        self.poll()

    # -- my jobs ----------------------------------------------------------------------------------------------

    def _jobs(self, rows: list, more: int, accounting_down: bool, ends: dict, groups: tuple, taken: float) -> None:
        failed = len(filter_jobs(rows, "failed"))
        grouped = _GROUP["on"]
        subtitle = (f"{len(rows)} · {'by study job' if grouped else 'all studies'} · queued, running or ended in the "
                    "last 7 days" + (f" · {failed} failed" if failed else ""))
        with self._section("jobs", "My jobs", subtitle, "jobs-card") as (head, opened):
            if not opened:
                return
            with head:
                group = chip_button("Group", on_click=self._toggle_group).props("icon=account_tree").tooltip(
                    "A line per study job: how far it is, when it started and when it ended or about when it ends")
                group.mark("jobs-group")
                if grouped:
                    group.classes("as-chip-on")
                for kind in JOB_KINDS:
                    chip = chip_button(KIND_LABELS[kind], on_click=lambda k=kind: self._set_kind(k)).mark(
                        f"jobs-filter-{kind}")
                    if kind == self.kind:
                        chip.classes("as-chip-on")
                studies = job_studies(rows)
                if len(studies) > 1:
                    ui.select({None: "All studies", **{s: s for s in studies}}, value=self.study,
                              on_change=lambda e: self._set_study(e.value)).props("dense").mark("jobs-study")
            if accounting_down:
                hint("Ended jobs need Slurm accounting, which does not answer; showing active cases only.").classes(
                    "as-hint-warning px-4").mark("jobs-accounting")
            shown = sort_jobs(filter_jobs(rows, self.kind, self.study), _SORT["key"], _SORT["descending"])
            if not shown:
                hint("No jobs").classes("px-4 pb-4").mark("jobs-none")
                return
            headings = ["Submitted", "Study", "Case", "Slurm job", "State", "Partition · node", "Started", "Ended",
                        "Elapsed", "Exit", ""]
            widths = ["minmax(7.5rem, auto)", "minmax(9rem, 1fr)", "minmax(9rem, 1.2fr)", "auto",
                      "minmax(9rem, 1.2fr)", "minmax(7rem, .9fr)", "auto", "auto", "auto", "auto",
                      "minmax(10rem, auto)"]
            if grouped:  # the group's line names the study; the cases keep their own times
                headings, widths = headings[2:], widths[2:]
            with table(" ".join(widths)).classes("as-table-compact w-full"):
                for heading in headings:
                    self._heading(heading)
                if grouped:
                    keep = {row.slurm_id for row in shown}
                    place = {row.slurm_id: index for index, row in enumerate(shown)}
                    found = [g for g in groups if any(row.slurm_id in keep for row in g.rows)]
                    found.sort(key=lambda g: min(place[row.slurm_id] for row in g.rows if row.slurm_id in keep))
                    for found_group in found:
                        opened = _GROUP_OPEN.get(found_group.key, found_group.active)
                        self._group_row(found_group, len(headings), opened)
                        if not opened:
                            continue
                        for row in sorted((r for r in found_group.rows if r.slurm_id in keep),
                                          key=lambda r: place[r.slurm_id]):
                            self._job_row(row, ends, taken, grouped=True)
                else:
                    for row in shown:
                        self._job_row(row, ends, taken)
            if more:
                hint(f"{more} older job{'' if more == 1 else 's'} not shown").classes("px-4 pb-4").mark("jobs-more")

    def _group_row(self, group: JobGroup, span: int, opened: bool) -> None:
        """A study job's line across the table: its state, how far it is, when it started, when it ended (or about
        when it ends) and how long it took (or about how long is left). Clicking it folds its cases (an active job's
        are open at first, an ended one's folded)."""
        with ui.row().classes("as-td as-job-group items-center gap-3").style(f"grid-column: span {span}").mark(
                f"group-{group.key}") as line:
            line.on("click", lambda _, k=group.key, o=opened: self._fold_group(k, not o))
            ui.icon("expand_more" if opened else "chevron_right").classes("as-muted").mark(f"group-{group.key}-fold")
            if group.study is not None:
                ui.link(group.study_name, project_url("run", group.study)).classes("as-strong").on(
                    "click.stop", lambda: None)  # opens the Run page, not folds
            else:
                ui.label(group.study_name).classes("as-strong as-muted")
            if group.state:
                ui.label(group.state).classes(f"as-job-group-state as-job-group-{group.state.lower()}")
            if group.job_id:
                ui.label(f"job {group.job_id}").classes("as-mono as-muted")
            if group.total:
                ui.linear_progress(group.finished / group.total, show_value=False).props("rounded size=5px").classes(
                    "as-job-group-bar")
                ui.label(f"{group.finished} / {group.total}").classes("as-mono").mark(f"group-{group.key}-done")
            if group.started is not None:
                with ui.row().classes("gap-1 items-baseline"):
                    ui.label("Started").classes("as-muted")
                    ui.label(when_text(group.started)).classes("as-strong").mark(f"group-{group.key}-started")
            if group.ended is not None or group.active:
                with ui.row().classes("gap-1 items-baseline"):
                    ui.label("Ends" if group.active else "Ended").classes("as-muted")
                    text = "—" if group.ended is None else (("≈ " if group.active else "") + when_text(group.ended))
                    ui.label(text).classes("as-strong" + (" as-expected" if group.active else "")).mark(
                        f"group-{group.key}-ended")
            span_label = ui.label("").classes("as-muted").mark(f"group-{group.key}-took")
            self.clocks.append((span_label, lambda now, g=group: _group_span(g, now)))
            if not opened:
                ui.label(f"{len(group.rows)} case{'' if len(group.rows) == 1 else 's'} folded").classes(
                    "as-muted as-small").mark(f"group-{group.key}-folded")

    def _fold_group(self, key: str, opened: bool) -> None:
        _GROUP_OPEN[key] = opened
        self.shown = None
        self.poll()

    def _heading(self, heading: str) -> None:
        """A column title; the sortable ones are buttons: click to sort by it, again to reverse."""
        key = SORTED_COLUMNS.get(heading)
        if key is None:
            th(heading)
            return
        arrow = (" ↓" if _SORT["descending"] else " ↑") if _SORT["key"] == key else ""
        ui.button(heading + arrow, color=None, on_click=lambda k=key: self._set_sort(k)).props(
            "flat dense no-caps align=left").classes("as-th as-sort-head").mark(f"sort-{key}")

    def _set_sort(self, key: str) -> None:
        if _SORT["key"] == key:
            _SORT["descending"] = not _SORT["descending"]
        else:
            _SORT.update(key=key, descending=key == "submitted")  # newest first; the rest A→Z / shortest first
        self.shown = None
        self.poll()

    def _job_row(self, row, ends: dict, taken: float, grouped: bool = False) -> None:
        if not grouped:
            td(submitted_text(row), mono=True).mark(f"job-{row.slurm_id}-submitted")
            with td_box() as cell:
                cell.classes("no-wrap min-w-0")
                if row.study is not None:
                    ui.link(row.study_name, project_url("run", row.study)).classes("as-truncate").tooltip(
                        row.study_name).mark(f"job-{row.slurm_id}-study")
                else:
                    ui.label(row.study_name).classes("as-muted as-truncate")
        with td_box() as cell:
            cell.classes("no-wrap gap-2")
            ui.label(row.case).classes("as-mono as-muted as-truncate").mark(f"job-{row.slurm_id}")
            if row.task:
                pill(row.task).classes("as-pill-small").mark(f"job-{row.slurm_id}-task")
        td(row.slurm_id, mono=True)
        with td_box():
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(job_state_text(row)).mark(f"job-{row.slurm_id}-state")
                if row.failure:
                    ui.label(row.failure).classes("as-failure-reason").mark(f"job-{row.slurm_id}-why")
        td(" · ".join(part for part in (row.partition, row.node) if part) or "—")
        td(when_text(started_at(row, taken)), mono=True).mark(f"job-{row.slurm_id}-started")
        if row.ended is not None:
            td(when_text(row.ended), mono=True).mark(f"job-{row.slurm_id}-ended")
        elif row.slurm_id in ends:
            td(f"≈ {when_text(ends[row.slurm_id])}", mono=True).classes("as-expected").tooltip(
                "About when it ends, at its job's average case run time").mark(f"job-{row.slurm_id}-ended")
        else:
            td("—", mono=True).mark(f"job-{row.slurm_id}-ended")
        td(row.elapsed or "—", mono=True)
        td(row.exit_code or "—", mono=True)
        with td_box() as cell:
            cell.classes("gap-1 no-wrap")
            live = row.study is not None and row.job_id is not None and not row.earlier_attempt
            if live and row.active:
                button = danger_button("Cancel", on_click=lambda r=row: self.confirm_cancel(r)).props("dense")
                button.mark(f"cancel-{row.slurm_id}").set_enabled(not self.down)
            if live and row.resubmittable:
                button = secondary_button("Resubmit", on_click=lambda r=row: self.resubmit(r)).props("dense")
                button.mark(f"resubmit-{row.slurm_id}").set_enabled(not self.down)
            if row.study is not None:
                flat_button("Log", on_click=lambda r=row: self.show_log(r), icon="terminal").props("dense").mark(
                    f"log-{row.slurm_id}")

    def _toggle_group(self) -> None:
        _GROUP["on"] = not _GROUP["on"]
        self.shown = None
        self.poll()

    def _set_kind(self, kind: str) -> None:
        self.kind = kind
        self.shown = None
        self.poll()

    def _set_study(self, study: Optional[str]) -> None:
        self.study = study
        self.shown = None
        self.poll()

    # -- actions ----------------------------------------------------------------------------------------------

    async def confirm_cancel(self, row) -> None:
        self.dialogs_open += 1
        try:
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Cancel {row.case} (Slurm job {row.slurm_id}) of {row.study_name}? Cases that restart "
                         "from its solution start from scratch instead; the job's other cases go on.")
                with ui.row().classes("w-full justify-end gap-2"):
                    secondary_button("Keep it", on_click=lambda: _answer(dialog, False)).mark("cancel-keep")
                    danger_button("Cancel the case", on_click=lambda: _answer(dialog, True)).mark("cancel-confirm")
            confirmed = await dialog
        finally:
            self.dialogs_open -= 1
        if not confirmed:
            return
        try:
            project = open_project(row.study)
            job = await run.io_bound(WATCHER.cancel_case, row.study, project, row.job_id, row.case)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
        else:
            cancelled = job.case_status.get(row.case) is not None and job.case_status[row.case].value == "CANCELLED"
            ui.notify(f"Cancelled {row.case}" if cancelled else f"{row.case} had already ended", type="info")
        self.shown = None
        self.poll()

    async def resubmit(self, row) -> None:
        self.dialogs_open += 1
        try:
            project = open_project(row.study)
            job = load_job(row.study, row.job_id)
            await resubmit_case(row.study, project, job, row.case)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
        finally:
            self.dialogs_open -= 1
        self.shown = None
        self.poll()

    def show_log(self, row) -> None:
        """The case's slurm-<id>.out, re-read every 2 s while open; Follow keeps it scrolled to the end."""
        name = ascii_log_name(row.slurm_id) if row.task else f"slurm-{row.slurm_id}.out"
        path = Path(row.study) / "runs" / row.case / name
        with self.dialog_host, ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"{row.study_name} / {row.case} · {path.name}").classes("as-dialog-title grow")
                follow = ui.checkbox("Follow", value=True).props("dense").mark("log-dialog-follow")
                ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark(
                    "log-dialog-close")
            with ui.scroll_area().classes("as-log-body").style("height: 60vh") as scroll:
                text = ui.label("").classes("as-log-text").mark("log-dialog-text")

        def update() -> None:
            content = _tail(path)
            if content != text.text:
                text.text = content
                if follow.value:
                    scroll.scroll_to(percent=1.0)

        update()
        with dialog:  # the timer lives with the dialog, not with the Log button the page may redraw
            timer = ui.timer(POLL_SECONDS, update)
        dialog.on("hide", lambda: (timer.cancel(), dialog.delete()))
        dialog.open()

def _state_tone(node) -> str:
    if node.bad:
        return "bad"
    return {"Full": "full", "Partly used": "part", "Free": "free"}.get(node.words, "other")


def _dial(value: float, text: str, caption: str, mark: str) -> ui.column:
    """A ring with `text` in it and `caption` under it."""
    with ui.column().classes("as-node-dial items-center gap-0") as box:
        with ui.circular_progress(value, min=0, max=1, show_value=False, size="58px").props(
                "thickness=0.22 track-color=grey-3 color=primary"):
            ui.label(text).classes("as-node-dial-value")
        ui.label(caption).classes("as-node-dial-caption").mark(mark)
    return box


def _group_span(group: JobGroup, now: datetime) -> str:
    """'took 28 h 36 min' once ended, 'about 3 h 31 min left' while it runs."""
    if group.active:
        if group.ended is None:
            return ""
        return f"about {about_text(group.ended - now.timestamp())} left"
    if group.started is not None and group.ended is not None:
        return f"took {duration_text(max(0.0, group.ended - group.started))}"
    return ""


def _running_text(job: NodeJob, now: datetime) -> str:
    """'Now M2p0_a3 · about 6 h 58 min left' (the whole job's, as on its Run page)."""
    here = job.cases[0] if len(job.cases) == 1 else f"{len(job.cases)} cases"
    left = job.left(now)
    return f"Now {here} · " + (f"about {about_text(left)} left" if left is not None
                               else "time left shown after the first case")


def _tail(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 256 * 1024))
            data = fh.read()
    except OSError:
        return f"(no output yet: {path.name} does not exist)"
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]) or "(nothing written yet)"

"""Cluster: every node (sinfo -N), everyone's queue (squeue) and the user's AeroSuite cases on Slurm across every
study — queued, running, or ended in the last 7 days — with Cancel (one case), Resubmit and Log. Everything comes
from the server's Slurm poller and the job records; the page never runs a Slurm command itself."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ...engine.cluster import MAX_ROWS, RecordIndex, my_jobs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.store import load_job
from ...engine.project import open_project
from ..cluster_view import (JOB_KINDS, cluster_queue, cluster_status, filter_jobs, job_state_text, job_studies,
                            node_groups)
from ..jobs import WATCHER
from ..layout import header, project_url
from ..resubmit_dialog import resubmit_case
from .. import slurm_watch
from ..slurm_watch import WATCH
from ..ui_kit import banner, chip_button, danger_button, flat_button, hint, pill, secondary_button, table, td, td_box, th

POLL_SECONDS = 2.0
LOG_LINES = 200
INDEX = RecordIndex()  # shared by every Cluster page: a study's records are read once per change
KIND_LABELS = {"all": "All", "active": "Active", "failed": "Failed"}
_COLLAPSED: set[str] = set()  # "jobs", "queue": sections the user folded, kept while the server runs


def register() -> None:
    @ui.page("/cluster")
    def cluster_page() -> None:
        header()
        with ui.column().classes("as-page w-full").mark("cluster-page"):
            with ui.row().classes("as-crumbs w-full"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Cluster").classes("as-crumb-current").mark("crumb-page")
            if not slurm_watch.slurm_available():
                banner("info", "Slurm is not installed on this machine.").mark("cluster-none")
                return
            ClusterPage()


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
        WATCH.show_page()
        ui.context.client.on_disconnect(WATCH.hide_page)
        self.holder = ui.column().classes("w-full gap-4")
        self.poll()
        ui.timer(POLL_SECONDS, self.poll)

    def _data(self) -> tuple:
        snapshot, cluster, recent = WATCH.snapshot, WATCH.cluster, WATCH.recent
        if snapshot is not None and snapshot.ok:
            self.good = snapshot
        queue = self.good.queue if self.good is not None else {}
        rows, more = my_jobs(queue, recent.rows if recent is not None else {}, WATCH.user, INDEX, MAX_ROWS)
        for row in rows:  # a study never opened here: the poller keeps its record current from now on
            if row.active and row.study is not None and row.job_id is not None:
                WATCH.track(row.study, row.job_id)
        return (cluster.taken if cluster else None, snapshot.taken if snapshot else None,
                recent.taken if recent else None, tuple(rows), more, self.kind, self.study)

    def poll(self) -> None:
        if self.dialogs_open:
            return
        data = self._data()
        if data != self.shown:
            self.shown = data
            self.render(data[3], data[4])

    def render(self, rows: tuple, more: int) -> None:
        snapshot, cluster, recent = WATCH.snapshot, WATCH.cluster, WATCH.recent
        tone, tip = cluster_status(snapshot, cluster)
        self.down = tone == "red"
        self.holder.clear()
        with self.holder:
            if self.down:
                banner("error", f"{tip}. Showing the last known state, as of {_time(WATCH.last_ok)}.").mark(
                    "cluster-outage")
            self._nodes(cluster)
            self._jobs(list(rows), more, recent)
            self._queue(self.good)

    # -- nodes ------------------------------------------------------------------------------------------------

    def _nodes(self, cluster) -> None:
        """One compact card per node, the default partition's first; a drained or down node is tinted red."""
        groups = node_groups(cluster)
        with ui.row().classes("items-baseline w-full gap-2").mark("nodes-card"):
            total = sum(n.total for _p, _d, nodes in groups for n in nodes)
            used = sum(n.allocated for _p, _d, nodes in groups for n in nodes)
            count = sum(len(nodes) for _p, _d, nodes in groups)
            ui.label("Nodes").classes("as-card-title")
            ui.label(f"{count} node{'' if count == 1 else 's'} · {used} / {total} CPUs in use · updated "
                     f"{_time(cluster.taken if cluster else None)}" if groups else "Asking Slurm…").classes(
                "as-muted").mark("nodes-summary")
        with ui.element("div").classes("as-node-grid w-full"):
            for partition, default, nodes in groups:
                for node in nodes:
                    with ui.column().classes("as-node-card" + (" as-node-bad" if node.bad else "")).mark(
                            f"node-card-{node.node}"):
                        with ui.row().classes("items-center w-full no-wrap gap-2"):
                            ui.label(node.node).classes("as-mono as-strong").mark(f"node-{node.node}")
                            ui.label(partition + (" · default" if default else "")).classes("as-muted as-small")
                            ui.space()
                            pill(node.state.upper() if node.bad else node.state).classes("as-pill-small").mark(
                                f"node-{node.node}-state")
                        with ui.row().classes("items-center w-full no-wrap gap-2"):
                            ui.linear_progress(node.busy_percent / 100, show_value=False).props(
                                "rounded size=6px").classes("grow")
                            ui.label(node.cpus).classes("as-mono as-small").mark(f"node-{node.node}-cpus")
                        with ui.row().classes("items-baseline w-full no-wrap gap-2 as-small"):
                            ui.label(node.memory).classes("as-muted").mark(f"node-{node.node}-memory")
                            ui.label(f"· load {node.load}").classes("as-muted")
                            ui.space()
                            ui.label(node.reason).classes("as-error-text").mark(f"node-{node.node}-note")

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

    # -- queue ------------------------------------------------------------------------------------------------

    def _queue(self, snapshot) -> None:
        lines = cluster_queue(snapshot, WATCH.user)
        mine = sum(1 for line in lines if line.own)
        subtitle = f"{len(lines)} job{'' if len(lines) == 1 else 's'}, all users · {mine} yours · yours highlighted"
        with self._section("queue", "Queue", subtitle, "queue-card") as (_head, opened):
            if not opened:
                return
            if not lines:
                hint("Queue empty").classes("px-4 pb-4").mark("queue-empty")
                return
            with table("auto minmax(5rem, .6fr) minmax(10rem, 1.6fr) minmax(7rem, .8fr) minmax(4rem, .5fr) "
                       "auto minmax(8rem, 1fr)").classes("as-table-compact w-full"):
                for heading in ("Job", "User", "Name", "State", "Node", "Time", "Reason"):
                    th(heading)
                for line in lines:
                    own = " as-own" if line.own else ""
                    td(line.job_id, mono=True).classes(own).mark(f"q-{line.job_id}")
                    td(line.user).classes(own).mark(f"q-{line.job_id}-user")
                    with td_box() as cell:
                        cell.classes(own)
                        if line.study is not None:
                            ui.link(line.name, project_url("run", line.study)).classes("as-mono").mark(
                                f"q-{line.job_id}-link")
                        else:
                            ui.label(line.name).classes("as-mono")
                    td(line.state).classes(own)
                    td(line.node or "—").classes(own)
                    td(line.time, mono=True).classes(own)
                    td(line.reason).classes(own)

    # -- my jobs ----------------------------------------------------------------------------------------------

    def _jobs(self, rows: list, more: int, recent) -> None:
        failed = len(filter_jobs(rows, "failed"))
        subtitle = (f"{len(rows)} · all studies · queued, running or ended in the last 7 days"
                    + (f" · {failed} failed" if failed else ""))
        with self._section("jobs", "My jobs", subtitle, "jobs-card") as (head, opened):
            if not opened:
                return
            with head:
                for kind in JOB_KINDS:
                    chip = chip_button(KIND_LABELS[kind], on_click=lambda k=kind: self._set_kind(k)).mark(
                        f"jobs-filter-{kind}")
                    if kind == self.kind:
                        chip.classes("as-chip-on")
                studies = job_studies(rows)
                if len(studies) > 1:
                    ui.select({None: "All studies", **{s: s for s in studies}}, value=self.study,
                              on_change=lambda e: self._set_study(e.value)).props("dense").mark("jobs-study")
            if recent is not None and recent.error:
                hint("Ended jobs need Slurm accounting, which does not answer; showing active cases only.").classes(
                    "as-hint-warning px-4").mark("jobs-accounting")
            shown = filter_jobs(rows, self.kind, self.study)
            if not shown:
                hint("No jobs").classes("px-4 pb-4").mark("jobs-none")
                return
            with table("minmax(7rem, .8fr) minmax(9rem, 1.2fr) auto minmax(10rem, 1.4fr) minmax(8rem, 1fr) auto "
                       "auto minmax(11rem, auto)").classes("as-table-compact w-full"):
                for heading in ("Study", "Case", "Slurm job", "State", "Partition · node", "Elapsed", "Exit", ""):
                    th(heading)
                for row in shown:
                    self._job_row(row)
            if more:
                hint(f"{more} older job{'' if more == 1 else 's'} not shown").classes("px-4 pb-4").mark("jobs-more")

    def _job_row(self, row) -> None:
        with td_box():
            if row.study is not None:
                ui.link(row.study_name, project_url("run", row.study)).mark(f"job-{row.slurm_id}-study")
            else:
                ui.label(row.study_name).classes("as-muted")
        td(row.case, mono=True).mark(f"job-{row.slurm_id}")
        td(row.slurm_id, mono=True)
        td(job_state_text(row)).mark(f"job-{row.slurm_id}-state")
        td(" · ".join(part for part in (row.partition, row.node) if part) or "—")
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
                         "from its solution become Blocked; the job's other cases go on.")
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
        path = Path(row.study) / "runs" / row.case / f"slurm-{row.slurm_id}.out"
        with ui.dialog().props("maximized=false") as dialog, ui.card().classes("w-[60rem] max-w-full"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"{row.study_name} / {row.case} · {path.name}").classes("as-dialog-title grow")
                ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense")
            with ui.scroll_area().classes("as-log-body").style("height: 60vh") as scroll:
                text = ui.label("").classes("as-log-text").mark("log-dialog-text")

        def update() -> None:
            text.text = _tail(path)
            scroll.scroll_to(percent=1.0)

        update()
        timer = ui.timer(POLL_SECONDS, update)
        dialog.on("hide", lambda: (timer.cancel(), dialog.delete()))
        dialog.open()


def _tail(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 256 * 1024))
            data = fh.read()
    except OSError:
        return f"(no output yet: {path.name} does not exist)"
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]) or "(nothing written yet)"

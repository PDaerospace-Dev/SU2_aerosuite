"""Monitor: one case's residuals and coefficients against iteration, its convergence and the job log."""
import math
from typing import Callable, Optional, Sequence

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.jobs.runner import CaseState, JobRecord
from ...engine.results import check_convergence
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session

POLL_SECONDS = 2.0
ITERATION_COLUMNS = ("Inner_Iter", "Outer_Iter")
DEFAULT_COEFFICIENTS = ("CL", "CD", "CMy")
MAX_POINTS = 2000  # per series; longer histories are thinned evenly


def register() -> None:
    @ui.page("/monitor")
    def monitor_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "monitor", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            ui.label("Monitor").classes("text-2xl")
            pages.append(MonitorPage(frame))


def iteration_values(df) -> list:
    for column in ITERATION_COLUMNS:
        if column in df.columns:
            return df[column].tolist()
    return list(range(len(df)))


def residual_columns(df) -> list:
    return [column for column in df.columns if column.startswith("rms[")]


def coefficient_columns(df) -> list:
    skip = set(residual_columns(df)) | set(ITERATION_COLUMNS)
    return [column for column in df.columns if column not in skip]


def line_options(x: list, df, columns: list, y_name: str) -> dict:
    """ECharts options: one line per column against iteration, thinned to MAX_POINTS; NaN is a gap."""
    count = len(x)
    step = max(1, math.ceil(count / MAX_POINTS))
    indices = list(range(0, count, step))  # length <= MAX_POINTS, since step >= count / MAX_POINTS
    if count and indices[-1] != count - 1:
        if len(indices) < MAX_POINTS:
            indices.append(count - 1)  # room to spare: add the last index as an extra point
        else:
            indices[-1] = count - 1  # already at the bound: swap in the last index, don't grow
    series = []
    for column in columns:
        values = df[column].tolist()
        data = [[x[i], None if math.isnan(values[i]) else values[i]] for i in indices]
        series.append({"name": column, "type": "line", "showSymbol": False, "data": data})
    return {
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "legend": {"data": list(columns)},
        "xAxis": {"type": "value", "name": "Iteration"},
        "yAxis": {"type": "value", "name": y_name, "scale": True},
        "series": series,
    }


def default_case(view: JobView, names: list, started: Callable[[JobRecord], Sequence[str]]) -> Optional[str]:
    """The case running now, else the last case that actually started (by log banner, via `started`)
    in the newest job that has one, else the first case.

    A case can be non-PENDING (e.g. CANCELLED) in a job without ever having started in it — cancelling
    a job marks every not-yet-finished case CANCELLED, including ones the sweep never reached — so
    `started` must reflect the log's "Running Case" banners, not just case_status.
    """
    if not names:
        return None
    job = view.latest
    if job is not None:
        running = [n for n in job.cases if n in names and job.case_status.get(n) is CaseState.RUNNING]
        if running:
            return running[0]
    for job in view.overview.jobs:  # newest first
        started_here = [n for n in started(job) if n in names]
        if started_here:
            return started_here[-1]
    return names[0]


class MonitorPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.case: Optional[str] = None
        self.columns: Optional[list] = None  # None: the default coefficients
        self.was_running = False
        self.holder = ui.column().classes("w-full gap-4")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)

    @property
    def directory(self):
        return self.frame.session.directory

    def _row(self, view: JobView):
        return next((row for row in view.overview.rows if row.name == self.case), None)

    def _running(self, view: JobView) -> bool:
        row = self._row(view)
        return row is not None and row.status == CaseState.RUNNING.value

    def _started(self, job: JobRecord) -> Sequence[str]:
        return WATCHER.started_cases(self.directory, job)

    def _data_job(self, view: JobView) -> Optional[JobRecord]:
        """The newest job in which `self.case` actually started (by log banner), if any."""
        for job in view.overview.jobs:  # newest first
            if self.case in self._started(job):
                return job
        return None

    def poll(self) -> None:
        try:
            view = WATCHER.state(self.directory, self.frame.session.project)
        except AeroSuiteError:
            return
        if self._running(view) or self.was_running:
            self.render(view)

    def render(self, view: Optional[JobView] = None) -> None:
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.frame.session.project)
            except AeroSuiteError as exc:
                self.holder.clear()
                with self.holder:
                    ui.label(f"Error: {exc}").classes("text-negative")
                return
        names = [case.name for case in self.frame.session.project.cases]
        if self.case not in names:
            self.case = default_case(view, names, self._started)
        self.was_running = self._running(view)
        self.holder.clear()
        with self.holder:
            if not names:
                ui.label("No cases yet: set up the sweep first.").classes("text-grey-7")
                return
            ui.select(names, value=self.case, label="Case",
                      on_change=lambda e: self._choose(e.value)).classes("w-80").mark("monitor-case")
            self._case_view(view)

    def _case_view(self, view: JobView) -> None:
        row = self._row(view)
        if row is None:
            ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
            return
        status_job = next((j for j in view.overview.jobs if j.id == row.job_id), None)
        if status_job is not None:
            ui.label(f"{row.status} in job {status_job.id}").mark("monitor-status")
        data_job = self._data_job(view)
        if data_job is None:
            # The case appears in a job's case_status (e.g. CANCELLED before it started) but its
            # "Running Case" banner is in no job's log: there is no run to show data for.
            ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
            return
        if status_job is None or data_job.id != status_job.id:
            ui.label(f"Showing the run from job {data_job.id}").classes("text-grey-7").mark("monitor-data-job")
        df = WATCHER.history(self.directory, data_job.id, self.case)
        if df.empty:
            ui.label("No history yet for this case.").classes("text-grey-7").mark("monitor-no-history")
        else:
            self._charts(df)
        ui.label("Solver log").classes("text-lg")
        log = WATCHER.log_tail(self.directory, data_job)
        ui.label(log if log is not None else "Log not available").classes(
            "font-mono text-xs whitespace-pre-wrap").mark("monitor-log")

    def _charts(self, df) -> None:
        x = iteration_values(df)
        ui.label("Residuals").classes("text-lg")
        ui.echart(line_options(x, df, residual_columns(df), "log10 residual")).classes(
            "w-full h-72").mark("chart-residuals")
        others = coefficient_columns(df)
        wanted = self.columns if self.columns is not None else list(DEFAULT_COEFFICIENTS)
        chosen = [column for column in wanted if column in others]
        ui.label("Coefficients").classes("text-lg")
        ui.select(others, multiple=True, value=chosen, label="Columns",
                  on_change=lambda e: self._set_columns(e.value)).classes("w-full").mark("monitor-columns")
        ui.echart(line_options(x, df, chosen, "value")).classes("w-full h-72").mark("chart-coefficients")
        _converged, message = check_convergence(df)
        ui.label(f"Convergence: {message}").mark("monitor-verdict")

    def _choose(self, case: str) -> None:
        self.case = case
        self.render()

    def _set_columns(self, columns) -> None:
        self.columns = list(columns or [])
        self.render()

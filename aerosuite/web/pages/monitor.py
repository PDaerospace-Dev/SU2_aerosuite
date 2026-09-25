"""Monitor: one case's residuals and coefficients against iteration, its convergence and the job log."""
import math
from typing import Any, Callable, NamedTuple, Optional, Sequence

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.jobs.overview import NOT_RUN, CaseRow
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
        if not any(n in job.case_status for n in names):
            continue  # none of these cases was in that job: don't scan its log
        started_here = [n for n in started(job) if n in names]
        if started_here:
            return started_here[-1]
    return names[0]


def data_job(view: JobView, case: str, started: Callable[[JobRecord], Sequence[str]]) -> Optional[JobRecord]:
    """The newest job in which `case` actually started (by log banner, via `started`), if any."""
    row = next((row for row in view.overview.rows if row.name == case), None)
    if row is None or row.status == NOT_RUN:
        return None
    for job in view.overview.jobs:  # newest first
        if case in job.case_status and case in started(job):
            return job
    return None


class _Content(NamedTuple):
    """What the part below the Case select shows for the chosen case."""
    shape: tuple  # that part is rebuilt when this changes, else updated in place
    row: Optional[CaseRow]
    status_job: Optional[JobRecord]  # the job the case's status comes from
    source: Optional[JobRecord]  # the job whose run is shown (see data_job)
    df: Any  # that run's history; None when there is no run to show


def _replace_options(chart, options: dict) -> None:
    chart.options.clear()
    chart.options.update(options)
    chart.update()


class MonitorPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.case: Optional[str] = None
        self.columns: Optional[list] = None  # None: the default coefficients
        self.was_running = False
        # Built once, and the charts below are updated in place while the case runs: rebuilding
        # them every poll would close an open dropdown and reset the charts.
        self.select = ui.select([], label="Case", on_change=lambda e: self._choose(e.value)).classes(
            "w-80").mark("monitor-case")
        self.body = ui.column().classes("w-full gap-4")
        self.shape: Optional[tuple] = None  # the _Content.shape self.body was built for
        self.parts: dict = {}  # elements of self.body that poll() updates in place
        self.df = None  # the history in the charts, if they are shown
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

    def poll(self) -> None:
        try:
            view = WATCHER.state(self.directory, self.frame.session.project)
        except AeroSuiteError:
            return
        running = self._running(view)
        if not (running or self.was_running):
            return
        self.was_running = running
        content = self._content(view)
        if content.shape != self.shape:
            self._build(content)
        else:
            self._fill(content)

    def render(self, view: Optional[JobView] = None) -> None:
        """Refresh the Case select's cases and rebuild everything below it."""
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.frame.session.project)
            except AeroSuiteError as exc:
                self.select.set_visibility(False)
                self._clear()
                with self.body:
                    ui.label(f"Error: {exc}").classes("text-negative")
                return
        names = [case.name for case in self.frame.session.project.cases]
        if self.case not in names:
            self.case = default_case(view, names, self._started)
        self.was_running = self._running(view)
        self.select.set_options(names, value=self.case)  # _choose sees the same case: no re-render
        self.select.set_visibility(bool(names))
        if not names:
            self._clear()
            with self.body:
                ui.label("No cases yet: set up the sweep first.").classes("text-grey-7")
            return
        self._build(self._content(view))

    def _content(self, view: JobView) -> _Content:
        row = self._row(view)
        status_job = source = df = None
        if row is not None:
            status_job = next((j for j in view.overview.jobs if j.id == row.job_id), None)
            source = data_job(view, self.case, self._started)
            if source is not None:
                df = WATCHER.history(self.directory, source.id, self.case)
        columns = None if df is None or df.empty else tuple(df.columns)
        shape = (self.case, row is not None, status_job.id if status_job else None,
                 source.id if source else None, columns)
        return _Content(shape, row, status_job, source, df)

    def _clear(self) -> None:
        self.body.clear()
        self.shape, self.parts, self.df = None, {}, None

    def _build(self, content: _Content) -> None:
        self._clear()
        self.shape = content.shape
        row, status_job, source, df = content.row, content.status_job, content.source, content.df
        with self.body:
            if row is None:
                ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
                return
            if status_job is not None:
                self.parts["status"] = ui.label(f"{row.status} in job {status_job.id}").mark("monitor-status")
            if source is None:
                # The case appears in a job's case_status (e.g. CANCELLED before it started) but its
                # "Running Case" banner is in no job's log: there is no run to show data for.
                ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
                return
            if status_job is None or source.id != status_job.id:
                ui.label(f"Showing the run from job {source.id}").classes("text-grey-7").mark("monitor-data-job")
            if df.empty:
                ui.label("No history yet for this case.").classes("text-grey-7").mark("monitor-no-history")
            else:
                self._charts(df)
            ui.label("Job log").classes("text-lg")
            self.parts["log"] = ui.label(self._log(source)).classes(
                "font-mono text-xs whitespace-pre-wrap").mark("monitor-log")

    def _fill(self, content: _Content) -> None:
        """Update the elements built for this same shape with the latest status, history and log."""
        if "status" in self.parts:
            self.parts["status"].set_text(f"{content.row.status} in job {content.status_job.id}")
        if self.df is not None:  # the charts are shown: same shape, so content.df has rows too
            self.df = content.df
            self._draw()
        if "log" in self.parts:
            self.parts["log"].set_text(self._log(content.source))

    def _log(self, job: JobRecord) -> str:
        log = WATCHER.log_tail(self.directory, job)
        return log if log is not None else "Log not available"

    def _chosen(self) -> list:
        others = coefficient_columns(self.df)
        wanted = self.columns if self.columns is not None else list(DEFAULT_COEFFICIENTS)
        return [column for column in wanted if column in others]

    def _options(self, which: str) -> dict:
        x = iteration_values(self.df)
        if which == "residuals":
            return line_options(x, self.df, residual_columns(self.df), "log10 residual")
        return line_options(x, self.df, self._chosen(), "value")

    def _verdict(self) -> str:
        _converged, message = check_convergence(self.df)
        return f"Convergence: {message}"

    def _charts(self, df) -> None:
        self.df = df
        ui.label("Residuals").classes("text-lg")
        self.parts["residuals"] = ui.echart(self._options("residuals")).classes("w-full h-72").mark(
            "chart-residuals")
        ui.label("Coefficients").classes("text-lg")
        ui.select(coefficient_columns(df), multiple=True, value=self._chosen(), label="Columns",
                  on_change=lambda e: self._set_columns(e.value)).classes("w-full").mark("monitor-columns")
        self.parts["coefficients"] = ui.echart(self._options("coefficients")).classes("w-full h-72").mark(
            "chart-coefficients")
        self.parts["verdict"] = ui.label(self._verdict()).mark("monitor-verdict")

    def _draw(self) -> None:
        """Put self.df into the existing charts and verdict."""
        for which in ("residuals", "coefficients"):
            _replace_options(self.parts[which], self._options(which))
        self.parts["verdict"].set_text(self._verdict())

    def _choose(self, case: str) -> None:
        if case == self.case:
            return
        self.case = case
        self.render()

    def _set_columns(self, columns) -> None:
        self.columns = list(columns or [])
        if self.df is not None:  # redraw the coefficients chart only: the Columns dropdown stays open
            _replace_options(self.parts["coefficients"], self._options("coefficients"))

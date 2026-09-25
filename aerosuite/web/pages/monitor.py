"""Monitor: one chart of a case's (or an opened file's) residuals/coefficients against iteration,
with a checkbox per column — like the old PyQt5 monitor."""
import math
import re
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional, Sequence

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.runner import CaseState, JobRecord
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session
from ..picker import pick_path

POLL_SECONDS = 2.0
ITERATION_COLUMNS = ("Inner_Iter", "Outer_Iter")
COLUMN_PATTERN = re.compile(r"rms|Res|^CL$|^CD$|^CFx$|^CFy$|^CFz$")
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


def filtered_columns(df) -> list:
    """The old monitor's column filter: residuals and the main force/moment coefficients."""
    return [column for column in df.columns if COLUMN_PATTERN.search(column)]


def normalize_series(values: list) -> list:
    """The old app's normalize_data: 1 + value - v0, where v0 is the first value from index 1
    onwards with |value| > 1e-6. Unchanged if there are fewer than 2 points or no such value."""
    if len(values) < 2:
        return values
    v0 = None
    for value in values[1:]:
        if not math.isnan(value) and abs(value) > 1e-6:
            v0 = value
            break
    if v0 is None:
        return values
    return [value if math.isnan(value) else 1 + value - v0 for value in values]


def line_options(x: list, df, columns: list, normalize: bool = False) -> dict:
    """ECharts options: one line per column against iteration, thinned to MAX_POINTS; NaN is a
    gap. `normalize` applies the old app's normalize_data to each series first."""
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
        if normalize:
            values = normalize_series(values)
        data = [[x[i], None if math.isnan(values[i]) else values[i]] for i in indices]
        series.append({"name": column, "type": "line", "showSymbol": False, "data": data})
    return {
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "legend": {"data": list(columns), "orient": "vertical", "right": 10, "top": "middle"},
        "xAxis": {"type": "value", "name": "Iteration"},
        "yAxis": {"type": "value", "name": "residuals", "scale": True},
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
    """What poll()/render() feeds into the source line, checkboxes and chart."""
    df: Any  # None: nothing to plot; else a (maybe empty) DataFrame
    state: str  # "chart" | "no-history" | "not-run"
    source_text: str
    source_tooltip: str  # only set in file mode


def _replace_options(chart, options: dict) -> None:
    chart.options.clear()
    chart.options.update(options)
    chart.update()


class MonitorPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.mode = "case"  # or "file"
        self.case: Optional[str] = None
        self.file_path: Optional[Path] = None
        self.stopped = False
        self.normalize = False
        self.ticked: dict = {}  # column name -> ticked, remembered across case/file switches
        self.was_running = False
        self.df = None  # the DataFrame behind the chart, if one is shown
        self.chart = None  # the ui.echart, if the right pane currently shows one
        self.columns_shape: tuple = ()  # the column names self.checkbox_holder was built for
        self.chart_state: Optional[str] = None  # the _Content.state self.chart_holder was built for
        # Built once; poll() updates these in place so it never closes an open dropdown or
        # resets a checkbox. Only the checkbox list and the chart-vs-message area are rebuilt,
        # and only when what they must show actually changes shape.
        with ui.row().classes("w-full gap-4 items-start no-wrap"):
            with ui.column().classes("gap-2").style("width: 16rem; min-width: 16rem;"):
                self.select = ui.select([], label="Case", on_change=lambda e: self._choose_case(e.value)).classes(
                    "w-full").mark("monitor-case")
                ui.button("Open file…", on_click=self._open_file).props("flat no-caps").mark("monitor-open-file")
                self.source_label = ui.label("").classes("text-xs text-grey-7").mark("monitor-source")
                self.stop_button = ui.button("Stop", on_click=self._toggle_stop).props("flat no-caps").mark(
                    "monitor-stop")
                ui.checkbox("Normalize", on_change=lambda e: self._set_normalize(e.value)).mark("monitor-normalize")
                self.checkbox_holder = ui.column().classes("gap-1")
            self.chart_holder = ui.column().classes("grow h-[32rem]")
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
        if self.stopped:
            return
        if self.mode == "case":
            try:
                view = WATCHER.state(self.directory, self.frame.session.project)
            except AeroSuiteError:
                return
            running = self._running(view)
            if not (running or self.was_running):
                return
            self.was_running = running
            content = self._case_content(view)
        else:
            if self.file_path is None:
                return
            content = self._file_content()
        self._apply(content, rebuild=False)

    def render(self, view: Optional[JobView] = None) -> None:
        """Refresh the Case select's cases and the content below (chart or message)."""
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.frame.session.project)
            except AeroSuiteError as exc:
                self.select.set_visibility(False)
                self._show_message(f"Error: {exc}", "text-negative")
                return
        names = [case.name for case in self.frame.session.project.cases]
        if self.mode == "case":
            if self.case not in names:
                self.case = default_case(view, names, self._started)
            self.was_running = self._running(view)
        self.select.set_options(names, value=self.case if self.mode == "case" else None)
        self.select.set_visibility(bool(names))
        if self.mode == "case" and not names:
            self._show_message("No cases yet: set up the sweep first.", "text-grey-7")
            return
        content = self._case_content(view) if self.mode == "case" else self._file_content()
        self._apply(content, rebuild=True)

    def _show_message(self, text: str, css: str) -> None:
        self.checkbox_holder.clear()
        self.chart_holder.clear()
        with self.chart_holder:
            ui.label(text).classes(css)
        self.columns_shape, self.chart_state, self.chart, self.df = (), None, None, None

    def _case_content(self, view: JobView) -> _Content:
        row = self._row(view)
        if row is None or row.status == NOT_RUN:
            return _Content(None, "not-run", "", "")
        status_job = next((job for job in view.overview.jobs if job.id == row.job_id), None)
        source = data_job(view, self.case, self._started)
        if source is None:
            # The case appears in a job's case_status (e.g. CANCELLED before it started) but its
            # "Running Case" banner is in no job's log: there is no run to show data for.
            text = f"{self.case} · job {status_job.id} · {row.status}" if status_job is not None else ""
            return _Content(None, "not-run", text, "")
        df = WATCHER.history(self.directory, source.id, self.case)
        if status_job is not None and source.id != status_job.id:
            text = f"{row.status} in job {status_job.id} · showing job {source.id}"
        else:
            text = f"{self.case} · job {status_job.id} · {row.status}" if status_job is not None else ""
        state = "no-history" if df is None or df.empty else "chart"
        return _Content(df, state, text, "")

    def _file_content(self) -> _Content:
        df = WATCHER.file_history(self.file_path)
        text = f"{self.file_path.parent.name}/{self.file_path.name}"
        return _Content(df, "chart", text, str(self.file_path))

    def _apply(self, content: _Content, rebuild: bool) -> None:
        self.df = content.df
        self.source_label.set_text(content.source_text)
        if content.source_tooltip:
            self.source_label.props["title"] = content.source_tooltip
        else:
            self.source_label.props.pop("title", None)
        columns = tuple(filtered_columns(content.df)) if content.df is not None else ()
        if rebuild or columns != self.columns_shape:
            self.columns_shape = columns
            self._build_checkboxes(columns)
        if rebuild or content.state != self.chart_state:
            self.chart_state = content.state
            self._build_chart_area(content.state)
        if content.state == "chart":
            self._draw_chart()

    def _build_checkboxes(self, columns: tuple) -> None:
        self.checkbox_holder.clear()
        with self.checkbox_holder:
            for column in columns:
                checked = self.ticked.setdefault(column, True)  # unseen columns start ticked
                ui.checkbox(column, value=checked, on_change=lambda e, c=column: self._toggle_column(
                    c, e.value)).mark(f"monitor-col-{column}")

    def _build_chart_area(self, state: str) -> None:
        self.chart_holder.clear()
        with self.chart_holder:
            if state == "not-run":
                ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
                self.chart = None
            elif state == "no-history":
                ui.label("No history yet for this case.").classes("text-grey-7").mark("monitor-no-history")
                self.chart = None
            else:
                self.chart = ui.echart({}).classes("w-full h-full").mark("chart-history")

    def _ticked_columns(self) -> list:
        return [column for column in filtered_columns(self.df) if self.ticked.get(column, True)]

    def _chart_options(self) -> dict:
        return line_options(iteration_values(self.df), self.df, self._ticked_columns(), self.normalize)

    def _draw_chart(self) -> None:
        if self.chart is not None:
            _replace_options(self.chart, self._chart_options())

    def _toggle_column(self, column: str, value: bool) -> None:
        self.ticked[column] = value
        self._draw_chart()

    def _set_normalize(self, value: bool) -> None:
        self.normalize = value
        self._draw_chart()

    def _toggle_stop(self) -> None:
        self.stopped = not self.stopped
        self.stop_button.set_text("Start" if self.stopped else "Stop")

    def _choose_case(self, case: Optional[str]) -> None:
        # A case is never really None: the select only ever offers real case names. None
        # arrives here when render() itself sets the select's value (e.g. clearing it while
        # switching to file mode), which fires this same on_change handler synchronously —
        # ignore that programmatic change rather than reentering render() mid-render.
        if case is None or (self.mode == "case" and case == self.case):
            return
        self.mode = "case"
        self.case = case
        self.render()

    async def _open_file(self) -> None:
        chosen = await pick_path("Open history file", mode="file", suffixes=(".csv", ".dat"))
        if chosen is None:
            return
        self.mode = "file"
        self.file_path = Path(chosen)
        self.render()

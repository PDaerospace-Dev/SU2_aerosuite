import asyncio
import json
import math
import time

import pandas as pd
import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.overview import NOT_RUN, CaseOverview, CaseRow
from aerosuite.engine.jobs.runner import CaseState, JobRecord
from aerosuite.web.jobs import JobView
from aerosuite.web.layout import project_url
from aerosuite.web.pages.monitor import MAX_POINTS, data_job, default_case, line_options

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _start(project_dir, project, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))
    runner = LocalRunner()
    return runner, runner.submit(project_dir, project)


def _wait(runner, project_dir, job, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.refresh(project_dir, job)
        if until(job):
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out: {job.case_status}")


async def _open(user, project_dir):
    await user.open(project_url("monitor", project_dir))


async def test_a_finished_case_shows_the_chart_with_every_column_ticked(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A4  # the case that ran last
    assert _element(user, "monitor-source").text == f"{A4} · job {job.id} · CONVERGED"
    series = _element(user, "chart-history").options["series"]
    assert [s["name"] for s in series] == ["rms[Rho]", "CL", "CD"]  # CMy is not a plotted column
    assert _element(user, "monitor-col-rms[Rho]").value is True
    assert _element(user, "monitor-col-CL").value is True
    assert _element(user, "monitor-col-CD").value is True
    await user.should_see(marker="badge-monitor-plain")


async def test_unticking_a_column_removes_it_and_ticks_are_remembered_across_case_switch(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    with user:
        _element(user, "monitor-col-CD").set_value(False)
    assert [s["name"] for s in _element(user, "chart-history").options["series"]] == ["rms[Rho]", "CL"]
    with user:
        _element(user, "monitor-case").set_value(A0)
    assert _element(user, "monitor-source").text == f"{A0} · job {job.id} · CONVERGED"
    # The checkbox list was rebuilt for the new case, but CD's tick is remembered by name.
    assert _element(user, "monitor-col-CD").value is False
    assert [s["name"] for s in _element(user, "chart-history").options["series"]] == ["rms[Rho]", "CL"]


async def test_normalize_shifts_each_series_like_the_old_app(user: User, ready_project, history_writer):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    history_writer(project_dir / "runs" / A2, [0.5, 0.6, 0.7, 0.8])
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        with user:
            _element(user, "monitor-normalize").set_value(True)
        cl = next(s for s in _element(user, "chart-history").options["series"] if s["name"] == "CL")["data"]
        # v0 = cl[1] = 0.6 (the first value from index 1 with |value| > 1e-6): 1 + value - 0.6.
        assert cl[0][1] == pytest.approx(1 + 0.5 - 0.6)
        assert cl[1][1] == pytest.approx(1.0)
        assert cl[2][1] == pytest.approx(1 + 0.7 - 0.6)
        assert cl[3][1] == pytest.approx(1 + 0.8 - 0.6)
        with user:
            _element(user, "monitor-normalize").set_value(False)
        cl = next(s for s in _element(user, "chart-history").options["series"] if s["name"] == "CL")["data"]
        assert [d[1] for d in cl] == pytest.approx([0.5, 0.6, 0.7, 0.8])
    finally:
        runner.cancel(project_dir, job)


async def test_open_file_plots_a_history_file_and_choosing_a_case_switches_back(
        user: User, ready_project, history_writer, tmp_path, eventually):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    external = history_writer(tmp_path / "external_run", [0.5, 0.6, 0.7])
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A4  # the case shown before Open file is used
    user.find(marker="monitor-open-file").click()
    # Open file... awaits pick_path in the background: give it a tick before poking the dialog.
    await user.should_see(marker="picker-entry-external_run")
    user.find(marker="picker-entry-external_run").click()
    await user.should_see(marker="picker-entry-history.csv")
    user.find(marker="picker-entry-history.csv").click()
    # chart-history is already on screen from the A4 case's own chart: wait for the source line
    # (unique to file mode) rather than the marker, so this doesn't race the async file-open.
    await eventually(lambda: _element(user, "monitor-source").text == "external_run/history.csv")
    assert _element(user, "monitor-case").value is None  # no longer following a case
    assert _element(user, "monitor-source").text == "external_run/history.csv"
    assert _element(user, "monitor-source").props.get("title", "").endswith("history.csv")
    series = _element(user, "chart-history").options["series"]
    assert [s["name"] for s in series] == ["rms[Rho]", "CL", "CD"]

    with user:
        _element(user, "monitor-case").set_value(A4)
    assert _element(user, "monitor-source").text == f"{A4} · job {job.id} · CONVERGED"


async def test_stop_pauses_updates_and_start_resumes(user: User, ready_project, history_writer, monkeypatch):
    from aerosuite.web.pages import monitor
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0.05)
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    history = history_writer(project_dir / "runs" / A2, [0.5] * 5)
    try:
        await _open(user, project_dir)

        def rows():
            return len(_element(user, "chart-history").options["series"][0]["data"])

        assert rows() == 5
        user.find(marker="monitor-stop").click()
        assert _element(user, "monitor-stop").text == "Start"
        with history.open("a") as fh:
            for i in range(5, 10):
                fh.write(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {0.5:12.8f}, {0.02:12.8f}, {-0.1:12.8f}\n")
        await asyncio.sleep(0.3)  # ~6 polls' worth of time, but stopped: no update
        assert rows() == 5
        user.find(marker="monitor-stop").click()
        assert _element(user, "monitor-stop").text == "Stop"
        deadline = time.monotonic() + 5
        while rows() != 10:
            assert time.monotonic() < deadline, "the chart never showed the new rows after Start"
            await asyncio.sleep(0.05)
    finally:
        runner.cancel(project_dir, job)


async def test_defaults_to_the_running_case_with_no_history_yet(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        assert _element(user, "monitor-source").text == f"{A2} · job {job.id} · RUNNING"
        await user.should_see(marker="monitor-no-history")
    finally:
        runner.cancel(project_dir, job)


async def test_a_never_started_cancelled_case_shows_the_older_jobs_data(user: User, ready_project):
    project_dir, project = ready_project
    runner1, job1 = _start(project_dir, project)
    _wait(runner1, project_dir, job1, lambda j: not j.is_active)
    runner2, job2 = _start(project_dir, project, **{A2: "hang"})
    _wait(runner2, project_dir, job2, lambda j: j.case_status[A2] is CaseState.RUNNING)
    job2 = runner2.cancel(project_dir, job2)
    # A4 never started in job2 (the sweep hung on A2 before reaching it) but is CANCELLED anyway.
    assert job2.case_status[A4] is CaseState.CANCELLED
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A2  # the case running when cancelled, not A4
    with user:
        _element(user, "monitor-case").set_value(A4)
    assert _element(user, "monitor-source").text == f"CANCELLED in job {job2.id} · showing job {job1.id}"
    assert [s["name"] for s in _element(user, "chart-history").options["series"]] == ["rms[Rho]", "CL", "CD"]


async def test_a_case_that_never_ran(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A0
    assert _element(user, "monitor-source").text == ""
    await user.should_see(marker="monitor-not-run")


def test_long_histories_are_thinned_but_keep_the_last_iteration():
    n = 25_001
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"])["series"][0]["data"]
    assert len(series) <= MAX_POINTS
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_thinning_never_exceeds_max_points_at_the_boundary():
    # count = 4000 -> step = ceil(4000 / 2000) = 2 -> range(0, 4000, 2) is already 2000 indices
    # ending at 3998, so naively appending the last index (3999) would land at 2001 points.
    n = 4000
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"])["series"][0]["data"]
    assert len(series) <= MAX_POINTS
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_short_histories_keep_every_point():
    n = 50
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"])["series"][0]["data"]
    assert len(series) == n
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_nan_values_become_gaps():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.5, math.nan, 0.6]})
    data = line_options([0, 1, 2], df, ["CL"])["series"][0]["data"]
    assert data == [[0, 0.5], [1, None], [2, 0.6]]


def test_normalize_option_shifts_a_series_to_start_at_one():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2, 3], "CL": [0.5, 0.6, 0.7, 0.8]})
    data = line_options([0, 1, 2, 3], df, ["CL"], normalize=True)["series"][0]["data"]
    assert [d[1] for d in data] == pytest.approx([1 + 0.5 - 0.6, 1.0, 1 + 0.7 - 0.6, 1 + 0.8 - 0.6])


def test_normalize_leaves_short_or_all_tiny_series_unchanged():
    df = pd.DataFrame({"Inner_Iter": [0], "CL": [0.5]})
    assert line_options([0], df, ["CL"], normalize=True)["series"][0]["data"] == [[0, 0.5]]
    df2 = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.0, 1e-8, -1e-8]})
    data = line_options([0, 1, 2], df2, ["CL"], normalize=True)["series"][0]["data"]
    assert [d[1] for d in data] == [0.0, 1e-8, -1e-8]


def _by_status(job: JobRecord) -> list:
    """Stand-in for the log-banner rule in tests that build JobRecords directly (no real log
    file to scan): "started" is every case not left at PENDING, in `job.cases` order."""
    return [n for n in job.cases if job.case_status.get(n, CaseState.PENDING) is not CaseState.PENDING]


def test_default_case_prefers_the_older_jobs_last_started_case_when_the_newest_job_is_all_pending():
    # Right after a submit, every case of the newest job is still PENDING: default_case must not
    # fall through to names[0] when an older, finished job has a genuine last-run case.
    newest = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                        case_status={A0: CaseState.PENDING, A2: CaseState.PENDING, A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.PENDING})
    overview = CaseOverview(rows=[], problems=[], jobs=[newest, older])
    view = JobView(latest=newest, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A2


def test_default_case_prefers_a_running_case_in_the_newest_job():
    running_job = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                             case_status={A0: CaseState.CONVERGED, A2: CaseState.RUNNING,
                                          A4: CaseState.PENDING})
    older = JobRecord(id="1", backend="local", cases=[A0, A2, A4], log_path="job1.log",
                       case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED,
                                    A4: CaseState.CONVERGED})
    overview = CaseOverview(rows=[], problems=[], jobs=[running_job, older])
    view = JobView(latest=running_job, active=running_job, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A2


def test_default_case_falls_back_to_the_first_case_with_no_jobs():
    overview = CaseOverview(rows=[], problems=[], jobs=[])
    view = JobView(latest=None, active=None, overview=overview)
    assert default_case(view, [A0, A2, A4], _by_status) == A0


def test_default_case_skips_a_cancelled_case_that_never_started():
    # Cancelling a job marks every not-yet-finished case CANCELLED, including ones the sweep never
    # reached. default_case must use the log-banner "started" rule, not case_status, to tell them
    # apart from the case that was genuinely running when the job was cancelled.
    newest = JobRecord(id="2", backend="local", cases=[A0, A2, A4], log_path="job2.log",
                        case_status={A0: CaseState.CONVERGED, A2: CaseState.CANCELLED,
                                     A4: CaseState.CANCELLED})
    overview = CaseOverview(rows=[], problems=[], jobs=[newest])
    view = JobView(latest=newest, active=None, overview=overview)
    started = {"2": [A0, A2]}  # A4's banner never printed: the sweep hung on A2 before reaching it
    assert default_case(view, [A0, A2, A4], lambda job: started[job.id]) == A2


async def test_a_poll_while_running_updates_the_chart_in_place(user: User, ready_project, history_writer,
                                                                monkeypatch):
    """Recreating the selects and charts every poll would close an open dropdown."""
    from aerosuite.web.pages import monitor

    monkeypatch.setattr(monitor, "POLL_SECONDS", 0.05)
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    history = history_writer(project_dir / "runs" / A2, [0.5] * 10)
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        kept = {m: _element(user, m) for m in ("monitor-case", "monitor-open-file", "monitor-source",
                                                "monitor-stop", "monitor-normalize", "monitor-col-rms[Rho]",
                                                "chart-history")}
        assert len(kept["chart-history"].options["series"][0]["data"]) == 10
        with history.open("a") as fh:
            for i in range(10, 15):
                fh.write(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {0.5:12.8f}, {0.02:12.8f}, {-0.1:12.8f}\n")
        deadline = time.monotonic() + 5
        while len(kept["chart-history"].options["series"][0]["data"]) != 15:
            assert time.monotonic() < deadline, "the chart never showed the new rows"
            await asyncio.sleep(0.05)
        assert {m: _element(user, m) for m in kept} == kept  # the very same elements, updated in place
    finally:
        runner.cancel(project_dir, job)


def _spy(started):
    calls = []

    def call(job):
        calls.append(job.id)
        return started[job.id]

    return call, calls


def test_data_job_only_scans_jobs_that_include_the_case():
    newest = JobRecord(id="2", backend="local", cases=[A0], log_path="job2.log",
                       case_status={A0: CaseState.CONVERGED})
    older = JobRecord(id="1", backend="local", cases=[A0, A2], log_path="job1.log",
                      case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED})
    rows = [CaseRow(A0, "CONVERGED", "2"), CaseRow(A2, "CONVERGED", "1"), CaseRow(A4, NOT_RUN, None)]
    view = JobView(latest=newest, active=None, overview=CaseOverview(rows=rows, problems=[], jobs=[newest, older]))
    started, calls = _spy({"2": [A0], "1": [A0, A2]})
    assert data_job(view, A2, started) is older
    assert calls == ["1"]  # job 2 never included A2: its log is not scanned
    calls.clear()
    assert data_job(view, A4, started) is None
    assert calls == []  # a case that never ran scans no log at all


def test_default_case_only_scans_jobs_that_include_a_current_case():
    newest = JobRecord(id="2", backend="local", cases=["old_case"], log_path="job2.log",
                       case_status={"old_case": CaseState.CONVERGED})
    older = JobRecord(id="1", backend="local", cases=[A0, A2], log_path="job1.log",
                      case_status={A0: CaseState.CONVERGED, A2: CaseState.CONVERGED})
    view = JobView(latest=newest, active=None, overview=CaseOverview(rows=[], problems=[], jobs=[newest, older]))
    started, calls = _spy({"2": ["old_case"], "1": [A0, A2]})
    assert default_case(view, [A0, A2, A4], started) == A2
    assert calls == ["1"]

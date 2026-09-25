import json
import time

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import JobRecord, JobState
from aerosuite.web.jobs import JobWatcher

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _prepare(project_dir, project, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))


class CountingRunner(LocalRunner):
    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def refresh(self, project_dir, job):
        self.refreshes += 1
        return super().refresh(project_dir, job)


def _wait_view(watcher, project_dir, project, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = watcher.state(project_dir, project)
        if until(view):
            return view
        time.sleep(0.2)
    raise AssertionError("timed out waiting for the job")


def test_state_refreshes_an_active_job_at_most_every_two_seconds(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    now = [100.0]
    runner = CountingRunner()
    watcher = JobWatcher(runner=runner, clock=lambda: now[0])
    job = watcher.submit(project_dir, project, [A0])
    for _ in range(5):
        view = watcher.state(project_dir, project)
    assert runner.refreshes == 1
    assert view.active is not None and view.active.id == job.id and view.latest.id == job.id
    now[0] += 2.0
    watcher.state(project_dir, project)
    assert runner.refreshes == 2
    watcher.cancel(project_dir, project)


def test_a_new_watcher_picks_up_a_running_job(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    job = JobWatcher().submit(project_dir, project, [A0])
    second = JobWatcher()  # e.g. after a server restart
    view = _wait_view(second, project_dir, project, lambda v: v.overview.rows[0].status == "RUNNING")
    assert view.active.id == job.id
    cancelled = second.cancel(project_dir, project)
    assert cancelled.state is JobState.CANCELLED
    assert second.state(project_dir, project).active is None


def test_history_is_read_per_job_and_case(ready_project, history_writer):
    project_dir, _ = ready_project
    folder = project_dir / RUNS_DIR / A0
    history_writer(folder, [0.5] * 20)
    watcher = JobWatcher()
    assert len(watcher.history(project_dir, "j1", A0)) == 20
    history_writer(folder, [0.5] * 30)
    assert len(watcher.history(project_dir, "j1", A0)) == 30
    history_writer(folder, [0.5] * 40)  # a rerun (new job) recreated the file
    assert len(watcher.history(project_dir, "j2", A0)) == 40
    assert watcher.history(project_dir, "j3", A2).empty


def test_log_tail_reads_only_the_end_of_a_big_log(ready_project):
    project_dir, _ = ready_project
    (project_dir / "jobs").mkdir()
    filler = "x" * 200 + "\n"
    (project_dir / "jobs" / "j.log").write_text(filler * 50_000 + "".join(f"line {i}\n" for i in range(100)))
    job = JobRecord(id="j", backend="local", cases=[A0], log_path="jobs/j.log")
    assert JobWatcher().log_tail(project_dir, job).splitlines() == [f"line {i}" for i in range(60, 100)]
    missing = JobRecord(id="k", backend="local", cases=[A0], log_path="jobs/k.log")
    assert JobWatcher().log_tail(project_dir, missing) is None

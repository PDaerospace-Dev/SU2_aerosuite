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


def test_state_does_not_refresh_a_job_being_cancelled(ready_project):
    """Cancel runs in a worker thread; a refresh meanwhile could record the dying job as Failed."""
    import threading

    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    release, entered = threading.Event(), threading.Event()

    class SlowCancel(CountingRunner):
        def cancel(self, project_dir, job):
            entered.set()
            release.wait(10)
            return super().cancel(project_dir, job)

    now = [100.0]
    runner = SlowCancel()
    watcher = JobWatcher(runner=runner, clock=lambda: now[0])
    watcher.submit(project_dir, project, [A0])
    watcher.state(project_dir, project)
    worker = threading.Thread(target=watcher.cancel, args=(project_dir, project))
    worker.start()
    assert entered.wait(10)
    before = runner.refreshes
    now[0] += 5.0
    assert watcher.is_cancelling(project_dir)
    assert watcher.state(project_dir, project).active is not None
    assert runner.refreshes == before  # skipped while the cancel runs
    release.set()
    worker.join(10)
    assert not watcher.is_cancelling(project_dir)
    assert watcher.state(project_dir, project).active is None


def test_refresh_throttle_holds_at_most_one_entry_per_project(ready_project):
    """The _refreshed throttle map must not grow with every job ever submitted."""
    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    now = [100.0]
    watcher = JobWatcher(runner=CountingRunner(), clock=lambda: now[0])

    watcher.submit(project_dir, project, [A0])
    watcher.state(project_dir, project)
    assert len(watcher._refreshed) == 1  # one entry for the one active job

    view = watcher.state(project_dir, project)
    assert view.active is not None
    watcher.cancel(project_dir, project)
    view = watcher.state(project_dir, project)
    assert view.active is None
    assert len(watcher._refreshed) == 0  # dropped once the project has no active job

    _prepare(project_dir, project, **{A2: "hang"})
    second = watcher.submit(project_dir, project, [A2])
    view = watcher.state(project_dir, project)
    assert view.active is not None and view.active.id == second.id
    assert len(watcher._refreshed) == 1  # still only one entry, now for the second job
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


from aerosuite.engine.jobs.overview import CaseOverview
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.web.jobs import JobProgress, JobView, job_progress


def _job(**status):
    return JobRecord(id="j1", backend="local", cases=list(status), log_path="runs/j1.log",
                     state=JobState.RUNNING, case_status={k: CaseState(v) for k, v in status.items()})


def test_job_progress_counts_finished_cases_and_names_the_running_one():
    job = _job(a="CONVERGED", b="FAILED", c="RUNNING", d="PENDING")
    progress = job_progress(JobView(job, job, CaseOverview([], [], [job])))
    assert progress == JobProgress(2, 4, "c")
    assert progress.text == "2 / 4 · c"
    assert progress.percent == 50


def test_no_active_job_no_progress():
    assert job_progress(JobView(None, None, CaseOverview([], [], []))) is None
    assert JobProgress(0, 3, None).text == "0 / 3"


def test_job_nodes_where_a_job_runs_waits_or_ran():
    from aerosuite.engine.jobs.runner import CaseState, SlurmCase
    from aerosuite.web.jobs import THIS_PC, job_nodes

    job = JobRecord(id="j", backend="slurm", cases=["a", "b", "c"], log_path="jobs/j.log", state=JobState.RUNNING,
                    case_status={"a": CaseState.CONVERGED, "b": CaseState.PENDING, "c": CaseState.PENDING})
    job.slurm = {"a": SlurmCase(job_id="1", partition="node1", ntasks=96, node="hpc1", started=True),
                 "b": SlurmCase(job_id="2", partition="node1", ntasks=96),
                 "c": SlurmCase(job_id="3", partition="node2", ntasks=48)}
    waiting = job_nodes(job)
    assert waiting.names == ("node1 · queued", "node2 · queued") and not waiting.live
    assert waiting.tip == "Every case is waiting in the Slurm queue"
    job.case_status.update(b=CaseState.RUNNING, c=CaseState.RUNNING)
    job.slurm["b"].node, job.slurm["c"].node = "hpc1", "hpc2"
    running = job_nodes(job)
    assert running.names == ("hpc1", "hpc2") and running.live and running.tip == "Running on hpc1, hpc2"
    job.state = JobState.DONE
    job.case_status.update(b=CaseState.CONVERGED, c=CaseState.CONVERGED)
    job.slurm["b"].started = job.slurm["c"].started = True
    ended = job_nodes(job)
    assert ended.names == ("hpc1", "hpc2") and not ended.live and ended.tip == "The last job ran on hpc1, hpc2"
    local = JobRecord(id="k", backend="local", cases=["a"], log_path="jobs/k.log", state=JobState.DONE)
    assert job_nodes(local).names == (THIS_PC,) and not job_nodes(local).live
    assert job_nodes(None) is None

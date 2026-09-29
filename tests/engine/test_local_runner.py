import json
import os
import time

import pytest

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import load_job, process_alive, read_lock, write_lock

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _prepare(project_dir, project, cases=None, delay=0.05):
    generate_configs(project_dir, project)
    plan = {"delay": delay, "cases": cases or {}}
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps(plan))


def _wait(runner, project_dir, job, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.refresh(project_dir, job)
        if until(job):
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out: state={job.state} cases={job.case_status}")


def _finished(job):
    return not job.is_active


def test_all_cases_converge(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    assert job.state is JobState.RUNNING
    assert read_lock(project_dir)["job_id"] == job.id
    job = _wait(runner, project_dir, job, _finished)
    assert job.state is JobState.DONE
    assert set(job.case_status.values()) == {CaseState.CONVERGED}
    assert (project_dir / RUNS_DIR / A4 / "history.csv").is_file()
    assert read_lock(project_dir) is None
    assert load_job(project_dir, job.id).state is JobState.DONE


def test_failed_and_unconverged_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "fail", A4: "diverge"})
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.FAILED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.UNCONVERGED,
    }
    assert "boom" in job.failure_tail[A2]


def test_cancel_stops_process_and_marks_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "hang"})
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    job = _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    pid, create_time = job.backend_ref["pid"], job.backend_ref["create_time"]
    job = runner.cancel(project_dir, job)
    assert job.state is JobState.CANCELLED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.CANCELLED, A4: CaseState.CANCELLED,
    }
    assert not process_alive(pid, create_time)
    assert read_lock(project_dir) is None


def test_second_submit_refused_while_running(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    try:
        with pytest.raises(JobError, match="already running"):
            runner.submit(project_dir, project)
    finally:
        runner.cancel(project_dir, job)


def test_state_survives_a_new_runner_instance(ready_project):
    """Simulates restarting the server: a fresh runner rebuilds state from disk and the OS."""
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    first = LocalRunner()
    job = first.submit(project_dir, project)
    _wait(first, project_dir, job, lambda j: j.case_status[A0] is CaseState.RUNNING)

    second = LocalRunner()
    reloaded = second.refresh(project_dir, load_job(project_dir, job.id))
    assert reloaded.state is JobState.RUNNING
    assert reloaded.case_status[A0] is CaseState.RUNNING
    cancelled = second.cancel(project_dir, reloaded)
    assert cancelled.state is JobState.CANCELLED
    assert not process_alive(job.backend_ref["pid"], job.backend_ref["create_time"])


def test_stale_lock_does_not_block_submit(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    write_lock(project_dir, "ghost", os.getpid(), 0.0)
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.DONE


def test_submit_without_configs(ready_project):
    project_dir, project = ready_project
    with pytest.raises(JobError, match="generate configs"):
        LocalRunner().submit(project_dir, project)


def test_submit_with_missing_python(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    project.run.sweep_python = str(project_dir / "no-such-python")
    with pytest.raises(JobError, match="Cannot start"):
        LocalRunner().submit(project_dir, project)
    assert read_lock(project_dir) is None
    assert list((project_dir / "jobs").iterdir()) == []  # no job folder and no job log


def test_losing_the_lock_race_leaves_nothing_behind(ready_project, monkeypatch):
    """Another submit took the lock between our check and our write_lock: undo everything."""
    import aerosuite.engine.jobs.local as local

    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    started = []

    def lost(project_dir, job_id, pid, create_time):
        started.append((pid, create_time))
        raise JobError("A job is already running for this project")

    monkeypatch.setattr(local, "write_lock", lost)
    with pytest.raises(JobError, match="already running"):
        LocalRunner().submit(project_dir, project)
    assert not process_alive(*started[0])
    assert list((project_dir / "jobs").iterdir()) == []


def test_a_previous_case_really_restarts_from_the_case_before(ready_project):
    project_dir, project = ready_project
    project.cases[1].restart = "previous"
    _prepare(project_dir, project)
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.DONE
    applied = {n: (project_dir / RUNS_DIR / n / "restart_applied.txt").read_text() for n in (A0, A2, A4)}
    assert applied == {A0: "no\n", A2: "yes\n", A4: "no\n"}
    assert (project_dir / RUNS_DIR / A2 / "restart_used.txt").read_text() == f"{A2}.cfg, previous\n"


def test_cancel_removes_the_restart_folder(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    runner = LocalRunner()
    _wait(runner, project_dir, runner.submit(project_dir, project, cases=[A2]), _finished)
    _prepare(project_dir, project, cases={A2: "hang"})
    job = runner.submit(project_dir, project, cases=[A2], continue_cases=[A2])
    restart = project_dir.resolve() / "jobs" / job.id / "restart"
    assert restart.is_dir()
    job = _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    job = runner.cancel(project_dir, job)
    assert job.state is JobState.CANCELLED
    assert not restart.exists()
    assert (project_dir / RUNS_DIR / A2 / "restart_applied.txt").read_text() == "yes\n"


def test_subset_runs_only_the_selected_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    earlier = project_dir / RUNS_DIR / A2
    earlier.mkdir(parents=True)
    (earlier / "keep.txt").write_text("earlier run")
    runner = LocalRunner()
    job = runner.submit(project_dir, project, cases=[A4, A0])
    assert job.cases == [A0, A4]  # project order
    job = _wait(runner, project_dir, job, _finished)
    assert job.case_status == {A0: CaseState.CONVERGED, A4: CaseState.CONVERGED}
    assert (earlier / "keep.txt").read_text() == "earlier run"
    assert (project_dir / "jobs" / job.id / "configs" / "run_control.txt").is_file()


def test_continue_reruns_a_case_from_its_own_solution(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "diverge"})
    runner = LocalRunner()
    first = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert first.case_status[A2] is CaseState.UNCONVERGED
    _prepare(project_dir, project)  # this time it converges
    second = _wait(runner, project_dir, runner.submit(project_dir, project, cases=[A2], continue_cases=[A2]),
                   _finished)
    assert second.case_status == {A2: CaseState.CONVERGED}
    copy = project_dir.resolve() / "jobs" / second.id / "restart" / A2 / "restart_flow.dat"
    assert (project_dir / RUNS_DIR / A2 / "restart_used.txt").read_text() == f"{A2}.cfg, custom, {copy}\n"
    assert (project_dir / RUNS_DIR / A2 / "restart_applied.txt").read_text() == "yes\n"
    assert "RESTART_SOL= YES" in (project_dir / RUNS_DIR / A2 / f"{A2}.cfg").read_text()
    assert not copy.parent.parent.exists()  # the job's restart/ folder goes when the job ends


def test_submit_os_error_is_a_job_error(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    (project_dir / RUNS_DIR).write_text("a file where the runs folder should be")
    with pytest.raises(JobError, match="Cannot create"):
        LocalRunner().submit(project_dir, project)


def test_failure_tail_keeps_error_log_ahead_of_su2_output(tmp_path):
    """Long SU2 output after the banner must not push the error.log text out of the tail."""
    from aerosuite.engine.jobs.runner import JobRecord

    (tmp_path / "jobs").mkdir()
    noise = "".join(f"SU2 line {i}\n" for i in range(200))
    (tmp_path / "jobs" / "j.log").write_text(f"=== Running Case 1/1: {A0}.cfg ===\n{noise}")
    folder = tmp_path / RUNS_DIR / A0
    folder.mkdir(parents=True)
    (folder / "error.log").write_text("Failed to run: the real reason\n")
    job = JobRecord(id="j", backend="local", cases=[A0], log_path="jobs/j.log",
                    case_status={A0: CaseState.RUNNING})
    LocalRunner()._evaluate_finished_case(tmp_path, job, folder, A0)
    assert job.case_status[A0] is CaseState.FAILED
    tail = job.failure_tail[A0]
    assert tail.startswith("Failed to run: the real reason")
    assert "SU2 line 199" in tail and "SU2 line 100" not in tail


def test_cancel_after_the_sweep_already_ended_reports_the_outcome(ready_project):
    """Cancel on a job whose process has already exited behaves like refresh, not CANCELLED."""
    import psutil

    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "fail"})
    job = LocalRunner().submit(project_dir, project)
    psutil.Process(job.backend_ref["pid"]).wait(timeout=20)
    job = LocalRunner().cancel(project_dir, load_job(project_dir, job.id))
    assert job.state is JobState.FAILED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.CONVERGED,
    }
    assert read_lock(project_dir) is None
    assert load_job(project_dir, job.id).state is JobState.FAILED


def test_sweep_exits_mid_case(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "exit"})
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.FAILED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.FAILED,
    }
    assert job.exit_code == 1
    assert job.failure_tail[A2].startswith("The sweep stopped during this case (exit code 1).")
    assert "No history.csv was written" in job.failure_tail[A2]
    assert job.failure_tail[A4].startswith("The sweep script stopped (exit code 1) before this case started")


def _running_partial(project_dir, project):
    """A job whose first case has written an unconverged history and is still running."""
    _prepare(project_dir, project, cases={A0: "partial"})
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    log = project_dir / job.log_path
    deadline = time.monotonic() + 20
    while "PARTIAL WRITTEN" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    return runner, job


def test_a_sweep_killed_mid_case_fails_that_case(ready_project):
    """E.g. the out-of-memory killer ends the sweep: the half-run case is Failed, not Unconverged."""
    import psutil

    project_dir, project = ready_project
    runner, job = _running_partial(project_dir, project)
    wrapper = psutil.Process(job.backend_ref["pid"])
    script = wrapper.children()[0]
    script.kill()
    job = _wait(runner, project_dir, job, _finished)
    assert job.state is JobState.FAILED
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.FAILED, A4: CaseState.FAILED}
    assert job.exit_code != 0
    assert job.failure_tail[A0].startswith("The sweep stopped during this case (")
    assert not (project_dir / "jobs" / f"{job.id}.exit").exists()  # kept in the job record instead


def test_a_sweep_killed_with_its_wrapper_fails_the_running_case(ready_project):
    from aerosuite.engine.jobs.store import kill_tree

    project_dir, project = ready_project
    runner, job = _running_partial(project_dir, project)
    kill_tree(job.backend_ref["pid"])  # from outside, not a Cancel: no exit code gets written
    job = _wait(LocalRunner(), project_dir, load_job(project_dir, job.id), _finished)
    assert job.state is JobState.FAILED and job.exit_code is None
    assert job.failure_tail[A0].startswith("The sweep stopped during this case (it was killed).")


def test_a_clean_run_records_exit_code_zero(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.DONE and job.exit_code == 0
    assert load_job(project_dir, job.id).exit_code == 0


def test_a_job_started_before_the_wrapper_is_judged_by_its_files_alone(ready_project):
    from aerosuite.engine.jobs.runner import JobRecord
    from aerosuite.engine.jobs.store import save_job

    project_dir, _ = ready_project
    (project_dir / "jobs").mkdir()
    (project_dir / "jobs" / "old.log").write_text(f"=== Running Case 1/1: {A0}.cfg ===\n")
    folder = project_dir / RUNS_DIR / A0
    folder.mkdir(parents=True)
    rows = [f"{i}, {-2 - 0.1 * i}, {0.5 + 0.2 * (-1) ** i}, 0.02, -0.1" for i in range(50)]
    (folder / "history.csv").write_text('"Inner_Iter","rms[Rho]","CL","CD","CMy"\n' + "\n".join(rows) + "\n")
    job = JobRecord(id="old", backend="local", cases=[A0], log_path="jobs/old.log",
                    backend_ref={"pid": -1, "create_time": 0.0}, state=JobState.RUNNING,
                    case_status={A0: CaseState.RUNNING})
    save_job(project_dir, job)
    job = LocalRunner().refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.UNCONVERGED and job.exit_code is None


def test_refresh_of_a_stale_copy_keeps_a_cancel_made_elsewhere(ready_project):
    """E.g. `status --watch` holds the RUNNING record while the web cancels the job."""
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    web = LocalRunner()
    job = web.submit(project_dir, project)
    stale = _wait(LocalRunner(), project_dir, load_job(project_dir, job.id),
                  lambda j: j.case_status[A0] is CaseState.RUNNING)
    web.cancel(project_dir, load_job(project_dir, job.id))
    watcher = LocalRunner()
    assert stale.state is JobState.RUNNING
    refreshed = watcher.refresh(project_dir, stale)
    assert refreshed.state is JobState.CANCELLED
    assert refreshed.case_status[A0] is CaseState.CANCELLED
    assert load_job(project_dir, job.id).state is JobState.CANCELLED


def test_cancel_of_a_stale_copy_keeps_the_newer_record(ready_project):
    """E.g. a web page holds the RUNNING record while `aerosuite cancel` already cancelled the job."""
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    job = LocalRunner().submit(project_dir, project)
    stale = _wait(LocalRunner(), project_dir, load_job(project_dir, job.id),
                  lambda j: j.case_status[A0] is CaseState.RUNNING)
    LocalRunner().cancel(project_dir, load_job(project_dir, job.id))
    result = LocalRunner().cancel(project_dir, stale)
    assert result.state is JobState.CANCELLED and result.case_status[A0] is CaseState.CANCELLED
    assert load_job(project_dir, job.id).state is JobState.CANCELLED


def test_two_projects_with_the_same_job_name_keep_apart(tmp_path):
    """Job names are only unique within a project (20260928-1358 in two studies started the same minute)."""
    from aerosuite.engine.jobs.runner import JobRecord

    runner = LocalRunner()
    logs = {"a": "=== Running Case 1/2: A1.cfg ===\n", "b": "=== Running Case 1/2: B1.cfg ===\n"}
    for name, text in logs.items():
        (tmp_path / name / "jobs").mkdir(parents=True)
        (tmp_path / name / "jobs" / "20260928-1358.log").write_text(text)
    job = JobRecord(id="20260928-1358", backend="local", cases=[], log_path="jobs/20260928-1358.log")
    assert runner.started_cases(tmp_path / "a", job) == ["A1"]
    assert runner.started_cases(tmp_path / "b", job) == ["B1"]

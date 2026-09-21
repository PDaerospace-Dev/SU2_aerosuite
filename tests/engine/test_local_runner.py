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

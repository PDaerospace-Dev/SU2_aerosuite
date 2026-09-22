from typer.testing import CliRunner

from aerosuite.cli import app, run_cmds
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import kill_tree, list_jobs, process_alive

runner = CliRunner()
A0, A2 = "M0p8_a0_b0", "M0p8_a2_b0"


def _start(project_dir, fake_plan, **cases):
    runner.invoke(app, ["generate", str(project_dir)])
    fake_plan(project_dir, **cases)
    result = runner.invoke(app, ["run", str(project_dir)])
    assert result.exit_code == 0, result.output


def test_status_without_jobs(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["status", str(project_dir)])
    assert result.exit_code == 0
    assert "No jobs yet" in result.output


def test_status_watch_follows_the_job_to_the_end(ready_project, su2_env, fake_plan):
    project_dir, _ = ready_project
    _start(project_dir, fake_plan)
    result = runner.invoke(app, ["status", str(project_dir), "--watch", "--interval", "0.1"])
    assert result.exit_code == 0, result.output
    assert "finished: DONE" in result.output
    assert f"{A0}" in result.output and "CONVERGED" in result.output


def test_status_shows_failure_tail(ready_project, su2_env, fake_plan, wait_job):
    project_dir, _ = ready_project
    _start(project_dir, fake_plan, M0p8_a2_b0="fail")
    wait_job(project_dir)
    result = runner.invoke(app, ["status", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "FAILED" in result.output
    assert f"--- {A2} (last log lines) ---" in result.output
    assert "boom" in result.output


def test_ctrl_c_stops_watching_not_the_job(ready_project, su2_env, fake_plan, wait_job, monkeypatch):
    project_dir, _ = ready_project
    _start(project_dir, fake_plan, M0p8_a0_b0="hang")
    try:
        wait_job(project_dir, until=lambda j: j.case_status[A0] is CaseState.RUNNING)

        def interrupt(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(run_cmds.time, "sleep", interrupt)
        result = runner.invoke(app, ["status", str(project_dir), "--watch"])
        assert result.exit_code == 0, result.output
        assert "Stopped watching; the job keeps running." in result.output
        assert list_jobs(project_dir)[0].is_active
    finally:
        monkeypatch.undo()
        runner.invoke(app, ["cancel", str(project_dir)])


def test_cancel_stops_the_running_job(ready_project, su2_env, fake_plan, wait_job):
    project_dir, _ = ready_project
    _start(project_dir, fake_plan, M0p8_a2_b0="hang")
    try:
        job = wait_job(project_dir, until=lambda j: j.case_status[A2] is CaseState.RUNNING)
        result = runner.invoke(app, ["cancel", str(project_dir)])
        assert result.exit_code == 0, result.output
        assert f"Cancelled job {job.id}." in result.output
        final = list_jobs(project_dir)[0]
        assert final.state is JobState.CANCELLED
        assert not process_alive(job.backend_ref["pid"], job.backend_ref["create_time"])
    finally:
        latest = list_jobs(project_dir)[0]
        kill_tree(latest.backend_ref["pid"])


def test_cancel_without_a_running_job(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["cancel", str(project_dir)])
    assert result.exit_code == 1
    assert "No running job" in result.output


def test_cancel_unknown_job_id(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["cancel", str(project_dir), "nope"])
    assert result.exit_code == 1
    assert "Error: No job nope" in result.output


def test_status_outside_a_project(tmp_path):
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: No project found" in result.output


def test_cancel_outside_a_project(tmp_path):
    result = runner.invoke(app, ["cancel", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: No project found" in result.output

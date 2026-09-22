"""The ready_project teardown must kill any fake sweep a test leaves running."""
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.jobs.store import kill_tree, process_alive

runner = CliRunner()


def test_teardown_kills_a_job_left_running(ready_project, su2_env, fake_plan, wait_job, kill_project_jobs):
    project_dir, _ = ready_project
    runner.invoke(app, ["generate", str(project_dir)])
    fake_plan(project_dir, M0p8_a0_b0="hang")
    result = runner.invoke(app, ["run", str(project_dir)])
    assert result.exit_code == 0, result.output
    job = wait_job(project_dir, until=lambda j: j.case_status["M0p8_a0_b0"] is CaseState.RUNNING)
    pid, create_time = job.backend_ref["pid"], job.backend_ref["create_time"]
    try:
        assert process_alive(pid, create_time)
        kill_project_jobs(project_dir)
        assert not process_alive(pid, create_time)
        kill_project_jobs(project_dir)  # dead pids are harmless
    finally:
        kill_tree(pid)


def test_teardown_ignores_unreadable_job_records(tmp_path, kill_project_jobs):
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "broken.json").write_text("{not json")
    kill_project_jobs(tmp_path)  # must not raise

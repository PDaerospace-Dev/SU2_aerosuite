from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.project import open_project

runner = CliRunner()


def test_generate_writes_configs(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["generate", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Wrote 3 configs" in result.output
    assert (project_dir / "configs" / "run_control.txt").is_file()


def test_generate_prints_warnings_and_continues(ready_project):
    project_dir, _ = ready_project
    runner.invoke(app, ["set", str(project_dir), "--key", "MARKER_HEATFLUX=( wall, fuselage, 0.0 )"])
    result = runner.invoke(app, ["generate", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Warning: MARKER_HEATFLUX refers to 'fuselage'" in result.output


def test_generate_stops_on_errors(ready_project):
    project_dir, _ = ready_project
    (project_dir / "template.cfg").unlink()
    result = runner.invoke(app, ["generate", str(project_dir)])
    assert result.exit_code == 1
    assert "Error: Template not found" in result.output
    assert not (project_dir / "configs").exists()


def test_run_needs_generated_configs(ready_project, su2_env):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["run", str(project_dir)])
    assert result.exit_code == 1
    assert "have not been generated" in result.output


def test_run_starts_the_sweep_and_returns(ready_project, su2_env, fake_plan, wait_job):
    project_dir, _ = ready_project
    runner.invoke(app, ["generate", str(project_dir)])
    fake_plan(project_dir)
    result = runner.invoke(app, ["run", str(project_dir), "-n", "8"])
    assert result.exit_code == 0, result.output
    assert "Started job" in result.output and "3 cases" in result.output
    assert f"aerosuite status {project_dir} --watch" in result.output
    assert open_project(project_dir).run.partitions == 8
    job = wait_job(project_dir)
    assert job.state is JobState.DONE
    assert set(job.case_status.values()) == {CaseState.CONVERGED}


def test_run_refuses_a_second_job(ready_project, su2_env, fake_plan, wait_job):
    project_dir, _ = ready_project
    runner.invoke(app, ["generate", str(project_dir)])
    fake_plan(project_dir, M0p8_a0_b0="hang")
    runner.invoke(app, ["run", str(project_dir)])
    try:
        wait_job(project_dir, until=lambda j: j.case_status["M0p8_a0_b0"] is CaseState.RUNNING)
        result = runner.invoke(app, ["run", str(project_dir)])
        assert result.exit_code == 1
        assert "still running" in result.output
    finally:
        runner.invoke(app, ["cancel", str(project_dir)])

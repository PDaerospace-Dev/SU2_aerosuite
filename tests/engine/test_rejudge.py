"""Judging finished runs again with the convergence check as it is now."""
from datetime import datetime, timedelta

from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.rejudge import rejudge
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import load_job, save_job
from aerosuite.engine.models import Project
from aerosuite.engine.project import save_project

NEAR_ZERO = [0.002 + 5e-5 * (-1) ** i for i in range(50)]  # steady by the absolute floor, not by std/mean
WOBBLY = [0.5 + 0.2 * (-1) ** i for i in range(50)]


def _job(project_dir, job_id, cases, hours_ago=0, state=JobState.DONE):
    save_job(project_dir, JobRecord(id=job_id, backend="local", cases=list(cases), log_path=f"jobs/{job_id}.log",
                                    state=state, created=datetime(2026, 11, 1) - timedelta(hours=hours_ago),
                                    case_status=dict(cases)))


def _project(tmp_path, history_writer):
    project_dir = tmp_path / "wing"
    project_dir.mkdir()
    save_project(project_dir, Project(name="wing"))
    history_writer(project_dir / "runs" / "a0", NEAR_ZERO)
    history_writer(project_dir / "runs" / "a5", WOBBLY)
    return project_dir


def test_a_verdict_the_check_now_gives_otherwise_is_changed(tmp_path, history_writer):
    project_dir = _project(tmp_path, history_writer)
    _job(project_dir, "j", {"a0": CaseState.UNCONVERGED, "a5": CaseState.UNCONVERGED})
    assert [(item.case, item.new) for item in rejudge(project_dir, write=False)] == [("a0", CaseState.CONVERGED)]
    assert load_job(project_dir, "j").case_status["a0"] is CaseState.UNCONVERGED  # a dry run
    changed = rejudge(project_dir)
    assert changed[0].reason.startswith("Converged (near zero: CL")
    assert load_job(project_dir, "j").case_status == {"a0": CaseState.CONVERGED, "a5": CaseState.UNCONVERGED}
    assert rejudge(project_dir) == []


def test_only_the_newest_job_that_ran_a_case_is_judged(tmp_path, history_writer):
    project_dir = _project(tmp_path, history_writer)
    _job(project_dir, "old", {"a0": CaseState.UNCONVERGED}, hours_ago=5)
    _job(project_dir, "new", {"a0": CaseState.FAILED})  # runs/a0 is this job's, whatever is in it
    _job(project_dir, "never", {"a0": CaseState.CANCELLED}, hours_ago=-1)  # newer, but never ran it
    _job(project_dir, "live", {"a5": CaseState.CONVERGED}, state=JobState.RUNNING)
    assert rejudge(project_dir) == []
    assert load_job(project_dir, "old").case_status["a0"] is CaseState.UNCONVERGED


def test_the_rejudge_command(tmp_path, history_writer):
    project_dir = _project(tmp_path, history_writer)
    _job(project_dir, "j", {"a0": CaseState.UNCONVERGED})
    result = CliRunner().invoke(app, ["rejudge", str(project_dir), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "a0 (job j): UNCONVERGED -> CONVERGED" in result.output and "1 verdict would change." in result.output
    result = CliRunner().invoke(app, ["rejudge", str(project_dir)])
    assert "1 verdict changed." in result.output
    assert load_job(project_dir, "j").case_status["a0"] is CaseState.CONVERGED

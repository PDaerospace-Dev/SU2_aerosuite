"""Earlier attempts of a case: kept (without volume files) when a rerun empties its run folder."""
import json

import pytest

from aerosuite.engine.attempts import KEEP, archive, attempts, make_current
from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.overview import case_overview
from aerosuite.engine.jobs.plan import prepare_job
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import save_job
from aerosuite.engine.restarts import RUNS_DIR

from slurm_helpers import A0, A2, STEADY, slurm_study  # noqa: F401  (fixture)


def _run(project_dir, case, marker="first order"):
    folder = project_dir / RUNS_DIR / case
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{case}.cfg").write_text("VOLUME_FILENAME= flow\nSURFACE_FILENAME= surface_flow\n")
    (folder / "history.csv").write_text('"Inner_Iter","rms[Rho]"\n0, -1\n1, -2\n')
    (folder / "restart_flow.dat").write_text(marker)
    (folder / "surface_flow.vtu").write_text("surface")
    (folder / "flow.vtu").write_text("volume " * 100)
    (folder / "flow_0.vtu").write_text("zone 0")
    (folder / "flow.vtm").write_text("multiblock")
    (folder / "flow").mkdir()
    (folder / "flow" / "block.vtu").write_text("block")
    (folder / "slurm-101.out").write_text("output")
    return folder


def _job(project_dir, job_id, statuses, created, changes=None):
    job = JobRecord(id=job_id, backend="local", cases=list(statuses), log_path=f"jobs/{job_id}.log",
                    created=created, state=JobState.DONE, case_status=statuses, changes=changes or {})
    save_job(project_dir, job)
    return job


def test_a_run_is_kept_without_its_volume_files(ready_project):
    project_dir, _ = ready_project
    _run(project_dir, A0)
    kept = archive(project_dir, A0, "j1", "UNCONVERGED", {"MUSCL_FLOW": "NO"})
    assert kept == project_dir / "attempts" / A0 / "001-j1"
    assert not (project_dir / RUNS_DIR / A0).exists()
    assert sorted(p.name for p in kept.iterdir()) == [
        f"{A0}.cfg", "attempt.json", "history.csv", "restart_flow.dat", "slurm-101.out", "surface_flow.vtu"]
    info = json.loads((kept / "attempt.json").read_text())
    assert (info["job_id"], info["status"], info["changes"]) == ("j1", "UNCONVERGED", {"MUSCL_FLOW": "NO"})
    [attempt] = attempts(project_dir, A0)
    assert attempt.solution.read_text() == "first order" and attempt.history is not None


def test_only_the_last_attempts_are_kept(ready_project):
    project_dir, _ = ready_project
    for number in range(KEEP + 2):
        _run(project_dir, A0, f"run {number}")
        archive(project_dir, A0, f"j{number}")
    assert [a.folder.name for a in attempts(project_dir, A0)] == ["003-j2", "004-j3", "005-j4"]


def test_a_folder_without_a_run_is_left_alone(ready_project):
    project_dir, _ = ready_project
    folder = project_dir / RUNS_DIR / A0
    folder.mkdir(parents=True)
    (folder / f"{A0}.cfg").write_text("MACH_NUMBER= 0.8\n")
    assert archive(project_dir, A0, "j1") is None and (folder / f"{A0}.cfg").is_file()


def test_make_current_swaps_and_the_overview_follows_until_a_newer_job(ready_project):
    from datetime import datetime, timedelta

    project_dir, project = ready_project
    t0 = datetime.now() - timedelta(hours=2)
    _run(project_dir, A0, "first order")
    _job(project_dir, "j1", {A0: CaseState.UNCONVERGED}, t0, {A0: {"MUSCL_FLOW": "NO"}})
    archive(project_dir, A0, "j1", "UNCONVERGED", {"MUSCL_FLOW": "NO"})
    _run(project_dir, A0, "second order, diverged")
    _job(project_dir, "j2", {A0: CaseState.FAILED}, t0 + timedelta(hours=1))
    [first] = attempts(project_dir, A0)
    make_current(project_dir, first)
    assert (project_dir / RUNS_DIR / A0 / "restart_flow.dat").read_text() == "first order"
    assert [(a.job_id, a.status) for a in attempts(project_dir, A0)] == [("j2", "FAILED")]
    row = next(r for r in case_overview(project_dir, project).rows if r.name == A0)
    assert (row.status, row.job_id) == ("UNCONVERGED", "j1")
    _job(project_dir, "j3", {A0: CaseState.PENDING}, datetime.now() + timedelta(minutes=1))  # a newer run
    assert next(r for r in case_overview(project_dir, project).rows if r.name == A0).status == "PENDING"


def test_make_current_waits_for_a_running_job(ready_project):
    from aerosuite.engine.jobs.store import write_lock

    project_dir, _ = ready_project
    _run(project_dir, A0)
    archive(project_dir, A0, "j1")
    save_job(project_dir, JobRecord(id="j9", backend="slurm", cases=[A2], log_path="jobs/j9.log",
                                    state=JobState.RUNNING, case_status={A2: CaseState.RUNNING}))
    write_lock(project_dir, "j9", -1, 0.0, backend="slurm")
    with pytest.raises(JobError, match="A job is running"):
        make_current(project_dir, attempts(project_dir, A0)[0])


def test_a_slurm_rerun_keeps_the_earlier_run_with_how_it_ended(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    first = runner.submit(project_dir, project, cases=[A0])
    history_writer(project_dir / RUNS_DIR / A0, STEADY)
    fake.finish("101", "COMPLETED", "0:0")
    runner.refresh(project_dir, first)
    runner.submit(project_dir, project, cases=[A0])
    [kept] = attempts(project_dir, A0)
    assert (kept.job_id, kept.status) == (first.id, "CONVERGED") and kept.history is not None


def test_a_rerun_from_an_attempt_copies_its_solution_aside(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    _run(project_dir, A2, "kept solution")
    attempt = archive(project_dir, A2, "j1")
    configs = prepare_job(project_dir, project, "j2", [A2], starts={A2: str(attempt)})
    line = (configs / "run_control.txt").read_text().strip()
    assert line == f"{A2}.cfg, custom, {project_dir.resolve() / 'jobs' / 'j2' / 'restart' / A2 / 'restart_flow.dat'}"
    assert (project_dir / "jobs" / "j2" / "restart" / A2 / "restart_flow.dat").read_text() == "kept solution"


def test_when_a_job_ends_a_case_that_never_started_gets_its_run_back(ready_project):
    from aerosuite.engine.attempts import archive_before_rerun, settle_attempts

    project_dir, _ = ready_project
    _run(project_dir, A0, "A0 before")
    _run(project_dir, A2, "A2 before")
    archived = archive_before_rerun(project_dir, [A0, A2])
    for name in (A0, A2):  # the job's own files in the emptied folders
        (project_dir / RUNS_DIR / name).mkdir()
        (project_dir / RUNS_DIR / name / f"{name}.cfg").write_text("rerun")
    (project_dir / RUNS_DIR / A0 / "history.csv").write_text('"Inner_Iter","rms[Rho]"\n0, -1\n')  # A0 ran
    settle_attempts(project_dir, archived, started={A0})
    assert (project_dir / RUNS_DIR / A2 / "restart_flow.dat").read_text() == "A2 before"  # put back, whole
    assert (project_dir / RUNS_DIR / A2 / "flow.vtu").is_file() and attempts(project_dir, A2) == []
    [kept] = attempts(project_dir, A0)
    assert kept.solution.read_text() == "A0 before" and not (kept.folder / "flow.vtu").exists()

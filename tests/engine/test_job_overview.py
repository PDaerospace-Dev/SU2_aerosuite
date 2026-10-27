from datetime import datetime, timedelta

import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.overview import NOT_RUN, case_overview
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import list_jobs, save_job

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"
T0 = datetime(2026, 9, 25, 10, 0)


def _job(project_dir, job_id, created, statuses, tails=None):
    job = JobRecord(
        id=job_id, backend="local", cases=list(statuses), log_path=f"jobs/{job_id}.log",
        created=created, state=JobState.DONE, case_status=statuses, failure_tail=tails or {},
    )
    save_job(project_dir, job)
    return job


def test_newest_job_that_ran_a_case_wins(ready_project):
    project_dir, project = ready_project
    _job(project_dir, "old", T0, {A0: CaseState.FAILED, A2: CaseState.UNCONVERGED}, {A0: "boom"})
    _job(project_dir, "new", T0 + timedelta(hours=1), {A2: CaseState.CONVERGED})
    overview = case_overview(project_dir, project)
    assert [(r.name, r.status, r.job_id, r.failure_tail) for r in overview.rows] == [
        (A0, "FAILED", "old", "boom"),
        (A2, "CONVERGED", "new", ""),
        (A4, NOT_RUN, None, ""),
    ]
    assert [job.id for job in overview.jobs] == ["new", "old"]
    assert overview.problems == []


def test_an_unreadable_job_record_is_skipped_with_a_warning(ready_project):
    project_dir, project = ready_project
    _job(project_dir, "good", T0, {A0: CaseState.CONVERGED})
    (project_dir / "jobs" / "bad.json").write_text("{not json")
    overview = case_overview(project_dir, project)
    assert [job.id for job in overview.jobs] == ["good"]
    assert overview.problems == ["Job record jobs/bad.json can't be read; ignored"]
    with pytest.raises(JobError):
        list_jobs(project_dir)  # the CLI stays strict


def test_no_jobs_yet(ready_project):
    project_dir, project = ready_project
    overview = case_overview(project_dir, project)
    assert {row.status for row in overview.rows} == {NOT_RUN}
    assert overview.jobs == [] and overview.problems == []


def test_a_job_record_that_is_not_utf8_is_skipped_with_a_warning(ready_project):
    project_dir, project = ready_project
    _job(project_dir, "good", T0, {A0: CaseState.CONVERGED})
    (project_dir / "jobs" / "bad.json").write_bytes(b"\xff\xfe not a job record")
    overview = case_overview(project_dir, project)
    assert [job.id for job in overview.jobs] == ["good"]
    assert overview.problems == ["Job record jobs/bad.json can't be read; ignored"]
    with pytest.raises(JobError):
        list_jobs(project_dir)


def test_run_solutions_lists_runs_with_a_restart_file_newest_first(ready_project):
    import os

    from aerosuite.engine.jobs.overview import run_solutions

    project_dir, _ = ready_project
    for name, stamp in (("M1p2_0km_a0_b0", 2000), ("M0p8_0km_a2_b0", 1000)):
        solution = project_dir / "runs" / name / "restart_flow.dat"
        solution.parent.mkdir(parents=True)
        solution.write_text("solution")
        os.utime(solution, (stamp, stamp))
    (project_dir / "runs" / "no_solution").mkdir()
    _job(project_dir, "j", T0, {"M1p2_0km_a0_b0": CaseState.UNCONVERGED})
    found = run_solutions(project_dir)
    assert [(s.name, s.status, s.modified) for s in found] == [
        ("M1p2_0km_a0_b0", "UNCONVERGED", 2000), ("M0p8_0km_a2_b0", None, 1000)]
    assert [s.name for s in run_solutions(project_dir, exclude=["M1p2_0km_a0_b0"])] == ["M0p8_0km_a2_b0"]
    assert run_solutions(project_dir / "missing") == []


def test_a_running_job_keeps_the_cases_the_sweep_no_longer_makes(ready_project):
    """The sweep changed (0 km became 10 km) and the new cases were added to the running job: the old ones are
    still the job's, listed apart from the project's own."""
    project_dir, project = ready_project
    old = "M0p8_0km_a0_b0"
    job = JobRecord(
        id="run", backend="slurm", cases=[old, A0], log_path="jobs/run.log", created=T0, state=JobState.RUNNING,
        case_status={old: CaseState.RUNNING, A0: CaseState.PENDING},
    )
    save_job(project_dir, job)
    overview = case_overview(project_dir, project)
    assert [(r.name, r.status) for r in overview.rows] == [(A0, "PENDING"), (A2, NOT_RUN), (A4, NOT_RUN)]
    assert [(r.name, r.status, r.job_id) for r in overview.others] == [(old, "RUNNING", "run")]
    assert [r.name for r in overview.all_rows] == [A0, A2, A4, old]
    job.state = JobState.DONE  # once the job ends, they are no longer shown
    job.case_status[old] = CaseState.CONVERGED
    save_job(project_dir, job)
    assert case_overview(project_dir, project).others == []


def test_cases_an_earlier_sweep_ran_are_kept_apart(ready_project):
    # 0 km ran in a finished job, then the sweep moved on: its cases are the earlier ones, while their folders last
    project_dir, project = ready_project
    old = ["M0p8_0km_a0", "M0p8_0km_a2", "M0p8_0km_a4"]
    _job(project_dir, "old", T0, {old[0]: CaseState.CONVERGED, old[1]: CaseState.UNCONVERGED,
                                  old[2]: CaseState.CANCELLED, A0: CaseState.FAILED})
    _job(project_dir, "newer", T0 + timedelta(hours=1), {old[1]: CaseState.CONVERGED})
    for name in old[:2]:
        (project_dir / "runs" / name).mkdir(parents=True)  # the cancelled one never got a folder
    overview = case_overview(project_dir, project)
    assert [(r.name, r.status, r.job_id) for r in overview.earlier] == [
        (old[0], "CONVERGED", "old"), (old[1], "CONVERGED", "newer")]
    assert {r.name for r in overview.all_rows} == {A0, A2, A4}  # never selected for a run
    assert [r.name for r in overview.known_rows][-2:] == old[:2]

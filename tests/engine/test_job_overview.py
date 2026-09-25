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

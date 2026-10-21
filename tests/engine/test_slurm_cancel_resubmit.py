import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.executors import SlurmOptions
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import active_lock, load_job, save_job
from aerosuite.engine.project import save_project

from slurm_helpers import A0, A2, A4, STEADY, slurm_study  # noqa: F401  (fixture)


def test_cancel_scancels_every_unfinished_case_in_one_call(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project)
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101")
    fake.run("102")
    job = runner.refresh(project_dir, job)
    fake.clear_calls()
    job = runner.cancel(project_dir, job)
    assert fake.calls("scancel") == [["scancel", "102", "103"]]
    assert job.case_status == {A0: CaseState.CONVERGED, A2: CaseState.CANCELLED, A4: CaseState.CANCELLED}
    assert job.state is JobState.CANCELLED and active_lock(project_dir) is None
    assert load_job(project_dir, job.id).state is JobState.CANCELLED
    assert runner.cancel(project_dir, job) is job  # already ended: nothing more to do


def test_cancel_when_scancel_fails_changes_nothing(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.update(controller_down=True)
    with pytest.raises(JobError, match="Cannot cancel Slurm jobs 101"):
        runner.cancel(project_dir, job)
    again = load_job(project_dir, job.id)
    assert again.is_active and again.case_status[A0] is CaseState.PENDING
    assert active_lock(project_dir)["job_id"] == job.id


def _fail_first(slurm_study, state="NODE_FAIL", previous=True):
    project_dir, project, runner, fake = slurm_study
    if previous:
        for case in project.cases[1:]:
            case.restart = "previous"
        save_project(project_dir, project)
    job = runner.submit(project_dir, project)
    fake.run("101", node="hpc2")
    runner.refresh(project_dir, job)
    fake.finish("101", state, "0:0" if state == "NODE_FAIL" else "0:125", node="hpc2")
    fake.finish("102", "CANCELLED", elapsed="00:00:00")
    fake.finish("103", "CANCELLED", elapsed="00:00:00")
    return runner.refresh(project_dir, job)


def test_resubmit_a_node_fail_case_with_the_cases_blocked_behind_it(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _fail_first(slurm_study)
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.BLOCKED, A4: CaseState.BLOCKED}
    assert not job.is_active and active_lock(project_dir) is None
    assert runner.resubmittable(job) == [A0]
    job = runner.resubmit(project_dir, project, job)
    assert job.is_active and job.state is JobState.RUNNING and job.finished is None
    assert {name: (sc.job_id, sc.attempts) for name, sc in job.slurm.items()} == {
        A0: ("104", ["101"]), A2: ("105", ["102"]), A4: ("106", ["103"])}
    assert all(state is CaseState.PENDING for state in job.case_status.values())
    assert fake.job("104")["dependency"] is None
    assert fake.job("105")["dependency"] == "afterok:104"
    assert fake.job("106")["dependency"] == "afterok:105"
    assert fake.job("104")["partition"] == "node1"  # as before
    assert active_lock(project_dir)["job_id"] == job.id
    assert not job.failure_tail
    assert "resubmit of 101" in (project_dir / "runs" / A0 / "su2_job.sh").read_text()


def test_resubmit_out_of_memory_on_another_partition(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _fail_first(slurm_study, "OUT_OF_MEMORY", previous=False)
    assert job.case_status[A0] is CaseState.FAILED
    options = SlurmOptions(partition="node2", ntasks=48, time_limit="", exclusive=True, account="pdas")
    job = runner.resubmit(project_dir, project, job, [A0], options=options)
    script = (project_dir / "runs" / A0 / "su2_job.sh").read_text()
    assert "#SBATCH -p node2" in script and "#SBATCH -n 48" in script
    assert job.slurm[A0].partition == "node2" and job.slurm[A0].attempts == ["101"]
    assert job.case_status[A2] is CaseState.CANCELLED  # not blocked: no restart, so not resubmitted


def test_resubmit_is_refused_for_other_states_and_while_another_job_runs(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.finish("101", "FAILED", "1:0")
    job = runner.refresh(project_dir, job)
    with pytest.raises(JobError, match="Only cases that ended NODE_FAIL or OUT_OF_MEMORY"):
        runner.resubmit(project_dir, project, job, [A0])
    with pytest.raises(JobError, match="No case of this job"):
        runner.resubmit(project_dir, project, job)
    fake.finish("101", "NODE_FAIL", "0:0")
    failed = load_job(project_dir, job.id)
    failed.slurm[A0].state = "NODE_FAIL"
    save_job(project_dir, failed)
    other = runner.submit(project_dir, project, cases=[A2])
    with pytest.raises(JobError, match=f"Job {other.id} is running"):
        runner.resubmit(project_dir, project, failed, [A0])


def test_resubmit_failing_in_sbatch_keeps_the_job_failed(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _fail_first(slurm_study, previous=False)
    fake.update(controller_down=True)
    with pytest.raises(JobError, match="Cannot submit"):
        runner.resubmit(project_dir, project, job)
    again = load_job(project_dir, job.id)
    assert again.case_status[A0] is CaseState.FAILED and again.slurm[A0].job_id == "101"
    assert not again.is_active and active_lock(project_dir) is None


def test_cancel_one_case_lets_the_others_run(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project)
    fake.run("101")
    job = runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, job, A2)
    assert fake.calls("scancel") == [["scancel", "102"]]
    assert job.case_status == {A0: CaseState.RUNNING, A2: CaseState.CANCELLED, A4: CaseState.PENDING}
    assert job.failure_tail[A2] == "Cancelled from the Cluster page."
    assert job.is_active and active_lock(project_dir)["job_id"] == job.id


def test_cancel_a_case_others_restart_from_blocks_them(slurm_study):
    project_dir, project, runner, fake = slurm_study
    for case in project.cases[1:]:
        case.restart = "previous"
    save_project(project_dir, project)
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.cancel_case(project_dir, runner.refresh(project_dir, job), A0)
    fake.finish("102", "CANCELLED", elapsed="00:00:00")  # Slurm: --kill-on-invalid-dep
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.CANCELLED, A2: CaseState.BLOCKED}
    assert job.state is JobState.CANCELLED and active_lock(project_dir) is None


def test_cancelling_the_last_case_ends_the_job(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101")
    job = runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, job, A2)
    assert job.state is JobState.CANCELLED and job.finished is not None
    assert active_lock(project_dir) is None


def test_cancel_a_case_that_already_ended_does_nothing(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.finish("101", "FAILED", "1:0")
    stale = job  # the page's copy, from before the case ended
    runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, stale, A0)
    assert fake.calls("scancel") == [] and job.case_status[A0] is CaseState.FAILED


def test_cancel_case_errors(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    with pytest.raises(JobError, match="not a Slurm case of job"):
        runner.cancel_case(project_dir, job, A2)
    fake.update(controller_down=True)
    with pytest.raises(JobError, match="Cannot cancel M0p8_a0_b0"):
        runner.cancel_case(project_dir, job, A0)
    assert load_job(project_dir, job.id).case_status[A0] is CaseState.PENDING


def test_cancel_a_case_that_just_ended_in_slurm_keeps_its_result(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.refresh(project_dir, job)  # the record says RUNNING
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101")  # Slurm finished it; no poll has seen that yet
    fake.clear_calls()
    job = runner.cancel_case(project_dir, job, A0)
    assert fake.calls("scancel") == []
    assert job.case_status[A0] is CaseState.CONVERGED
    assert runner.refresh(project_dir, job).case_status[A0] is CaseState.CONVERGED

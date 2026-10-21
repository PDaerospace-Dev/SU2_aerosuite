import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.executors import SlurmOptions
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import active_lock, list_jobs, load_job
from aerosuite.engine.project import save_project

from slurm_helpers import A0, A2, A4, STEADY, slurm_study  # noqa: F401  (fixture)

NODE2 = SlurmOptions(partition="node2", ntasks=48, time_limit="", exclusive=True, account="pdas")


def test_cases_go_to_the_other_partition_inside_the_running_job(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    job = runner.add_cases(project_dir, project, job, [A4], options=NODE2)
    assert len(list_jobs(project_dir)) == 1  # the same job
    assert job.cases == [A0, A2, A4] and job.is_active
    assert job.slurm[A4].job_id == "103" and job.slurm[A4].partition == "node2" and job.slurm[A4].ntasks == 48
    assert job.case_status[A4] is CaseState.PENDING and job.case_status[A0] is CaseState.RUNNING
    assert fake.job("103")["partition"] == "node2" and fake.job("103")["dependency"] is None
    assert (project_dir / "jobs" / job.id / "add-2" / "configs" / f"{A4}.cfg").is_file()
    assert (project_dir / "jobs" / job.id / "configs" / f"{A0}.cfg").is_file()  # the first batch's, untouched
    assert active_lock(project_dir)["job_id"] == job.id
    assert "Adding 1 case(s) to Slurm partition node2, 48 tasks each" in (project_dir / job.log_path).read_text()


def test_queued_and_running_cases_are_skipped(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    assert runner.busy_cases(job) == {A0, A2}
    job = runner.add_cases(project_dir, project, job, [A0, A2, A4], options=NODE2)
    assert [call[0] for call in fake.calls("sbatch")] == ["sbatch"] * 3  # only A4 was added
    assert job.slurm[A0].job_id == "101" and job.slurm[A4].job_id == "103"
    with pytest.raises(JobError, match="already queued or running"):
        runner.add_cases(project_dir, project, job, [A0, A4], options=NODE2)


def test_a_finished_case_runs_again_and_keeps_its_earlier_id(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.finish("101", "NODE_FAIL")
    fake.run("102")
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.FAILED and job.is_active
    job = runner.add_cases(project_dir, project, job, [A0], options=NODE2)
    assert job.slurm[A0].job_id == "103" and job.slurm[A0].attempts == ["101"]
    assert job.case_status[A0] is CaseState.PENDING and A0 not in job.failure_tail
    assert job.cases == [A0, A2]


def test_an_added_case_waits_for_the_running_case_it_restarts_from(slurm_study):
    project_dir, project, runner, fake = slurm_study
    project.cases[1].restart = "previous"  # A2 restarts from A0
    save_project(project_dir, project)
    job = runner.submit(project_dir, project, cases=[A0])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    job = runner.add_cases(project_dir, project, job, [A2], options=NODE2)
    assert job.slurm[A2].depends_on == A0
    assert fake.job("102")["dependency"] == "afterany:101"
    cfg = (project_dir / "runs" / A2 / f"{A2}.cfg").read_text()
    assert f"SOLUTION_FILENAME= {project_dir / 'runs' / A0 / 'restart_flow'}" in cfg
    assert "RESTART_SOL= YES" in cfg
    assert f"[ ! -f {project_dir / 'runs' / A0 / 'restart_flow'} ]" in (project_dir / "runs" / A2 / "su2_job.sh").read_text()
    fake.finish("101", "FAILED", "1:0")
    fake.run("102")
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.RUNNING}  # from scratch
    assert job.is_active


def test_cancel_stops_the_added_cases_too(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    job = runner.add_cases(project_dir, project, job, [A2, A4], options=NODE2)
    job = runner.cancel(project_dir, job)
    assert fake.calls("scancel") == [["scancel", "101", "102", "103"]]
    assert set(job.case_status.values()) == {CaseState.CANCELLED} and job.state is JobState.CANCELLED


def test_adding_to_a_job_that_ended_is_refused(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101")
    job = runner.refresh(project_dir, job)
    assert not job.is_active
    with pytest.raises(JobError, match="not running: submit the cases instead"):
        runner.add_cases(project_dir, project, job, [A2], options=NODE2)


def test_a_failed_sbatch_while_adding_leaves_the_running_cases_alone(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    fake.update(sbatch_fail_after=2, sbatch_message="Invalid partition name specified")
    with pytest.raises(JobError, match="Cannot submit M0p8_a4_b0"):
        runner.add_cases(project_dir, project, job, [A2, A4], options=NODE2)
    job = load_job(project_dir, job.id)
    assert fake.calls("scancel") == [["scancel", "102"]]  # only this batch
    assert job.case_status == {A0: CaseState.RUNNING, A2: CaseState.FAILED, A4: CaseState.FAILED}
    assert "could not be submitted" in job.failure_tail[A2] and "Not submitted" in job.failure_tail[A4]
    assert job.is_active and active_lock(project_dir)["job_id"] == job.id


def test_restart_copies_of_added_batches_are_removed_when_the_job_ends(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    solution = project_dir / "runs" / A2 / "restart_flow.dat"
    solution.parent.mkdir(parents=True)
    solution.write_text("x")
    job = runner.submit(project_dir, project, cases=[A0])
    job = runner.add_cases(project_dir, project, job, [A2], continue_cases=[A2], options=NODE2)
    copies = project_dir / "jobs" / job.id / "add-2" / "restart"
    assert copies.is_dir()
    for slurm_id, name in (("101", A0), ("102", A2)):
        history_writer(project_dir / "runs" / name, STEADY)
        fake.finish(slurm_id)
    job = runner.refresh(project_dir, job)
    assert job.state is JobState.DONE and not copies.exists()


def test_configs_can_be_regenerated_while_a_slurm_job_runs(slurm_study):
    from aerosuite.engine.cfg import generate_configs

    project_dir, project, runner, fake = slurm_study
    runner.submit(project_dir, project, cases=[A0])
    assert generate_configs(project_dir, project)  # the running case uses runs/<case>/<case>.cfg
    from aerosuite.engine.preflight import preflight

    running = [p.message for p in preflight(project_dir, project, "generate") if p.severity == "error"]
    assert running == []  # the Sweep page's Generate stays available
    assert any("still running" in p.message for p in preflight(project_dir, project, "submit"))

import pytest
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import open_project
from aerosuite.engine.settings import AppSettings, save_settings, set_value

runner = CliRunner()
A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


@pytest.fixture
def study(ready_project, tmp_path, fake_slurm):
    project_dir, _ = ready_project
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)))
    assert runner.invoke(app, ["generate", str(project_dir)]).exit_code == 0
    return project_dir, fake_slurm


def test_run_with_slurm_options_submits_and_saves_them(study):
    project_dir, fake = study
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--partition", "node2",
                                 "--ntasks", "48", "--time", "1:00:00"])
    assert result.exit_code == 0, result.output
    assert "Submitted job" in result.output and "partition node2, 48 tasks each" in result.output
    assert "Slurm jobs 101, 102, 103" in result.output
    project = open_project(project_dir)
    assert project.run.backend == "slurm"
    assert (project.run.slurm.partition, project.run.slurm.ntasks) == ("node2", 48)
    assert project.run.slurm.time_limit is None  # --time is for this run only
    assert fake.job("101")["partition"] == "node2" and fake.job("101")["ntasks"] == "48"
    assert "#SBATCH -t 1:00:00" in (project_dir / "runs" / "M0p8_a0_b0" / "su2_job.sh").read_text()


def test_another_partition_uses_its_own_default_tasks(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--partition", "node1", "--ntasks", "96"])
    runner.invoke(app, ["cancel", str(project_dir)])
    result = runner.invoke(app, ["run", str(project_dir), "--partition", "node2"])
    assert result.exit_code == 0, result.output
    assert "node2, 48 tasks each" in result.output


def test_options_of_the_other_backend_are_refused(study):
    project_dir, fake = study
    result = runner.invoke(app, ["run", str(project_dir), "--ntasks", "48"])
    assert result.exit_code == 1 and "--ntasks is for the Slurm backend" in result.output
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "-n", "4"])
    assert result.exit_code == 1 and "for Slurm use --ntasks" in result.output
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "pbs"])
    assert result.exit_code == 1 and "local or slurm" in result.output
    assert fake.calls("sbatch") == []


def test_preflight_errors_stop_the_run(study, tmp_path):
    project_dir, fake = study
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path / "elsewhere")))
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    assert result.exit_code == 1
    assert "must be under" in result.output
    assert fake.calls("sbatch") == []


def test_node2_above_48_tasks_warns_but_runs(study):
    project_dir, fake = study
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--partition", "node2",
                                 "--ntasks", "96"])
    assert result.exit_code == 0, result.output
    assert "Warning: node2 gains nothing above about 48 tasks; 96 asked" in result.output


def test_status_shows_slurm_ids_nodes_and_reasons(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    fake.run("101", node="hpc1", time="1:02:03")
    fake.set_job("102", reason="Resources")
    fake.finish("103", "OUT_OF_MEMORY", "0:125", node="hpc1")
    result = runner.invoke(app, ["status", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert f"{A0}  RUNNING  Slurm 101 RUNNING on hpc1 1:02:03" in result.output
    assert f"{A2}  PENDING  Slurm 102 PENDING (Resources)" in result.output
    assert f"{A4}  FAILED  Slurm 103 OUT_OF_MEMORY exit 0:125 on hpc1" in result.output


def test_status_when_the_controller_is_down(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    fake.update(controller_down=True)
    result = runner.invoke(app, ["status", str(project_dir)])
    assert result.exit_code == 1
    assert "Slurm unreachable since" in result.output and "Unable to contact slurm controller" in result.output


def test_status_watch_follows_a_slurm_job(study, history_writer):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    for name, slurm_id in ((A0, "101"), (A2, "102"), (A4, "103")):
        history_writer(project_dir / "runs" / name, [0.5] * 30)
        fake.finish(slurm_id)
    result = runner.invoke(app, ["status", str(project_dir), "--watch", "--interval", "0"])
    assert result.exit_code == 0, result.output
    assert "finished: DONE" in result.output


def test_cancel_a_slurm_job(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    result = runner.invoke(app, ["cancel", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "Cancelled job" in result.output
    assert fake.calls("scancel") == [["scancel", "101", "102", "103"]]
    assert list_jobs(project_dir)[0].state is JobState.CANCELLED


def test_resubmit_node_fail_cases(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--partition", "node2"])
    fake.finish("101", "NODE_FAIL", node="hpc2")
    fake.finish("102", "FAILED", "1:0")
    fake.run("103")
    result = runner.invoke(app, ["resubmit", str(project_dir), "--partition", "node1"])
    assert result.exit_code == 0, result.output
    assert "Resubmitted to node1, 96 tasks" in result.output
    job = list_jobs(project_dir)[0]
    assert job.slurm[A0].job_id == "104" and job.slurm[A0].attempts == ["101"]
    assert job.case_status[A2] is CaseState.FAILED  # FAILED is not resubmitted
    result = runner.invoke(app, ["resubmit", str(project_dir), A2])
    assert result.exit_code == 1 and "Only cases that ended NODE_FAIL or OUT_OF_MEMORY" in result.output


def test_resubmit_without_a_slurm_job(ready_project):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["resubmit", str(project_dir)])
    assert result.exit_code == 1 and "No Slurm job" in result.output


def test_add_cases_to_the_running_job(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--case", A0, "--case", A2])
    fake.run("101")
    result = runner.invoke(app, ["run", str(project_dir), "--add", "--partition", "node2"])
    assert result.exit_code == 0, result.output
    assert f"Skipped (already queued or running): {A0}, {A2}" in result.output
    assert "Added 1 case(s) to job" in result.output and "node2, 48 tasks each (Slurm jobs 103)" in result.output
    jobs = list_jobs(project_dir)
    assert len(jobs) == 1 and jobs[0].slurm[A4].partition == "node2"
    result = runner.invoke(app, ["run", str(project_dir), "--add"])
    assert result.exit_code == 1 and "Nothing to add" in result.output


def test_add_needs_a_running_slurm_job(study):
    project_dir, fake = study
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--add"])
    assert result.exit_code == 1 and "No Slurm job is running" in result.output
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "local", "--add"])
    assert result.exit_code == 1 and "--add is for the Slurm backend" in result.output


def test_run_only_some_cases(study):
    project_dir, fake = study
    result = runner.invoke(app, ["run", str(project_dir), "--backend", "slurm", "--case", A2])
    assert result.exit_code == 0, result.output
    assert list_jobs(project_dir)[0].cases == [A2]
    result = runner.invoke(app, ["run", str(project_dir), "--case", "nope"])
    assert result.exit_code == 1 and "Unknown case(s): nope" in result.output

import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.executors import SlurmOptions
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.slurm import job_name, job_script
from aerosuite.engine.jobs.store import active_lock, list_jobs, load_job, read_lock
from aerosuite.engine.project import save_project
from aerosuite.engine.settings import SlurmSettings

from slurm_helpers import A0, A2, A4, slurm_study  # noqa: F401  (fixture)

OPTIONS = SlurmOptions(partition="node1", ntasks=96, time_limit="", exclusive=True, account="pdas")


def test_job_script_matches_the_reference_script():
    text = job_script("X07 cruise", "M0p8_a2", "M0p8_a2.cfg", OPTIONS, SlurmSettings(), "20261019-1412")
    lines = text.splitlines()
    assert lines[:8] == [
        "#!/bin/bash -l", "#SBATCH -J X07_cruise/M0p8_a2", "#SBATCH -p node1", "#SBATCH -N 1", "#SBATCH -n 96",
        "#SBATCH --exclusive", "#SBATCH -A pdas", "#SBATCH -o slurm-%j.out"]
    assert "module load mpi/openmpi-x86_64" in lines
    assert "export PATH=/opt/su2/bin:\"$PATH\"" in lines
    assert "export OMPI_MCA_osc='^ucx'" in lines  # before srun, so every rank gets it
    assert lines.index("export OMPI_MCA_osc='^ucx'") < lines.index("srun --mpi=pmix SU2_CFD M0p8_a2.cfg")
    assert 'cd "$SLURM_SUBMIT_DIR"' in lines
    assert "srun --mpi=pmix SU2_CFD M0p8_a2.cfg" in lines
    assert lines[-4:] == ["code=$?", "echo $code > aerosuite_exit", 'echo "AEROSUITE_EXIT $code $(date -Is)"',
                          "exit $code"]
    assert lines.index("rm -f aerosuite_exit") < lines.index("srun --mpi=pmix SU2_CFD M0p8_a2.cfg")
    assert "--dependency" not in text and "-t " not in text and "RESTART_SOL" not in text


def test_node0_script_launches_with_mpirun_and_a_clean_environment():
    options = SlurmOptions(partition="node0", ntasks=32, time_limit="", exclusive=False, account="pdas")
    text = job_script("X07 cruise", "M0p8_a2", "M0p8_a2.cfg", options, SlurmSettings(), "20261019-1412")
    lines = text.splitlines()
    assert lines[:7] == ["#!/bin/bash", "#SBATCH -J X07_cruise/M0p8_a2", "#SBATCH -p node0", "#SBATCH -N 1",
                         "#SBATCH -n 32", "#SBATCH -A pdas", "#SBATCH -o slurm-%j.out"]
    assert "export PATH=/usr/local/bin:/usr/bin:/bin" in lines
    assert "unset LD_LIBRARY_PATH" in lines
    launch = 'mpirun --bind-to core -np "$SLURM_NTASKS" SU2_CFD M0p8_a2.cfg'
    assert launch in lines
    assert lines.index("export PATH=/usr/local/bin:/usr/bin:/bin") < lines.index("unset LD_LIBRARY_PATH") \
        < lines.index('cd "$SLURM_SUBMIT_DIR"') < lines.index(launch)
    # the cluster nodes' environment is not for this machine
    assert "srun" not in text and "pmix" not in text and "module load" not in text and "OMPI_MCA" not in text
    assert "/opt/su2/bin" not in text and "--exclusive" not in text
    assert "--export" not in text  # the job keeps the submitting user's environment (uid 1000 is pdas there)
    assert lines[-4:] == ["code=$?", "echo $code > aerosuite_exit", 'echo "AEROSUITE_EXIT $code $(date -Is)"',
                          "exit $code"]


def test_node0_script_with_its_own_module_line_and_environment():
    slurm = SlurmSettings()
    node0 = slurm.partition("node0")
    node0.module_line = "module load openmpi"
    node0.job_env = "OMPI_MCA_btl=self,vader"
    node0.login_shell = True
    options = SlurmOptions(partition="node0", ntasks=8, time_limit="", exclusive=False, account="")
    lines = job_script("s", "c", "c.cfg", options, slurm, "j").splitlines()
    assert lines[0] == "#!/bin/bash -l"
    assert lines.index("module load openmpi") < lines.index("export OMPI_MCA_btl=self,vader") \
        < lines.index("export PATH=/usr/local/bin:/usr/bin:/bin")


def test_node0_restart_check_still_runs_before_mpirun():
    options = SlurmOptions(partition="node0", ntasks=32, time_limit="", exclusive=False, account="pdas")
    text = job_script("s", "a2", "a2.cfg", options, SlurmSettings(), "j", after="101",
                      restart_from=("a0", "/data/s/runs/a0", "/data/s/runs/a0/restart_flow.dat"))
    assert text.index("RESTART_SOL= NO") < text.index("mpirun")
    assert "#SBATCH --dependency=afterany:101" in text


def test_job_script_options():
    options = SlurmOptions(partition="node2", ntasks=48, time_limit="12:00:00", exclusive=False, account="")
    text = job_script("s", "c", "c.cfg", options, SlurmSettings(), "j", after="101", note="restarts from b",
                      restart_from=("b", "/r/b", "/r/b/restart_flow.dat"))
    assert "#SBATCH -t 12:00:00" in text and "#SBATCH -A" not in text and "--exclusive" not in text
    assert "#SBATCH --dependency=afterany:101\n#SBATCH --kill-on-invalid-dep=yes\n" in text
    assert ('if [ "$(cat /r/b/aerosuite_exit 2>/dev/null)" != 0 ] || ! { [ -f /r/b/restart_flow.dat ] || '
            '[ -f /r/b/restart_flow.dat.dat ] || [ -f /r/b/restart_flow.dat.csv ]; }; then') in text
    assert "case c (restarts from b)." in text


@pytest.mark.parametrize("exit_code, solution, restarts", [
    ("0", True, True),  # the case before ended with a solution: restart from it
    ("1", True, False),  # it failed (a file from before it diverged may be there): from scratch
    (None, True, False),  # killed before it could write its exit code (time limit, node failure)
    ("0", False, False),  # no solution file
])
def test_a_restarting_case_starts_from_scratch_without_a_solution(tmp_path, exit_code, solution, restarts):
    import subprocess

    before, folder = tmp_path / "a0", tmp_path / "a2"
    before.mkdir(), folder.mkdir()
    if exit_code is not None:
        (before / "aerosuite_exit").write_text(exit_code + "\n")
    if solution:
        (before / "restart_flow.dat").write_text("solution")
    (folder / "a2.cfg").write_text("MACH_NUMBER= 0.8\nRESTART_SOL= YES\n")
    settings = SlurmSettings(module_line=":", srun_command="true")
    text = job_script("s", "a2", "a2.cfg", OPTIONS, settings, "j", after="101",
                      restart_from=("a0", str(before), str(before / "restart_flow.dat")))
    (folder / "su2_job.sh").write_text(text)
    done = subprocess.run(["bash", "su2_job.sh"], cwd=folder, env={"PATH": "/usr/bin:/bin", "SLURM_SUBMIT_DIR": str(folder)},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert ("RESTART_SOL= YES" if restarts else "RESTART_SOL= NO") in (folder / "a2.cfg").read_text()
    assert ("starting from scratch" in done.stdout) is not restarts
    assert (folder / "aerosuite_exit").read_text().strip() == "0"  # for the case after this one


@pytest.mark.parametrize("written", ["restart_flow.dat", "restart_flow.csv", "restart_flow"])
def test_a_restart_finds_the_solution_su2_wrote_from_the_name_in_the_config(tmp_path, written):
    # SOLUTION_FILENAME names it without an extension (as SU2 is given it); SU2 writes restart_flow.dat (or .csv)
    import subprocess

    before, folder = tmp_path / "a0", tmp_path / "a2"
    before.mkdir(), folder.mkdir()
    (before / "aerosuite_exit").write_text("0\n")
    (before / written).write_text("solution")
    (folder / "a2.cfg").write_text("RESTART_SOL= YES\n")
    settings = SlurmSettings(module_line=":", srun_command="true")
    text = job_script("s", "a2", "a2.cfg", OPTIONS, settings, "j", after="101",
                      restart_from=("a0", str(before), str(before / "restart_flow")))
    (folder / "su2_job.sh").write_text(text)
    done = subprocess.run(["bash", "su2_job.sh"], cwd=folder, env={"PATH": "/usr/bin:/bin", "SLURM_SUBMIT_DIR": str(folder)},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "RESTART_SOL= YES" in (folder / "a2.cfg").read_text()
    assert "starting from scratch" not in done.stdout


@pytest.mark.parametrize("change", [dict(partition="node1\n#SBATCH -p x"), dict(account="a b"),
                                    dict(time_limit="1:00; rm -rf /")])
def test_job_script_refuses_unsafe_values(change):
    values = {**OPTIONS.__dict__, **change}
    with pytest.raises(JobError):
        job_script("s", "c", "c.cfg", SlurmOptions(**values), SlurmSettings(), "j")


def test_job_name_is_safe():
    assert job_name("My study (v2)", "M0p8_a2") == "My_study__v2_/M0p8_a2"


def test_submit_writes_each_case_folder_and_records_the_ids(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project)
    assert job.state is JobState.RUNNING and job.backend == "slurm"
    assert {name: sc.job_id for name, sc in job.slurm.items()} == {A0: "101", A2: "102", A4: "103"}
    assert all(state is CaseState.PENDING for state in job.case_status.values())
    for name, slurm_id in ((A0, "101"), (A2, "102"), (A4, "103")):
        folder = project_dir / "runs" / name
        script = (folder / "su2_job.sh").read_text()
        assert f"#SBATCH -J study/{name}" in script and "--dependency" not in script
        assert f"srun --mpi=pmix SU2_CFD {name}.cfg" in script
        assert (folder / f"{name}.cfg").is_file()
        submitted = fake.job(slurm_id)
        assert submitted["cwd"] == str(folder) and submitted["partition"] == "node1"
        assert submitted["env_virtual_env"] is None
    sbatch = fake.calls("sbatch")
    assert sbatch == [["sbatch", "--parsable", "su2_job.sh"]] * 3
    assert load_job(project_dir, job.id) == job
    assert read_lock(project_dir)["backend"] == "slurm" and active_lock(project_dir)["job_id"] == job.id
    log = (project_dir / job.log_path).read_text()
    assert f"{A2} -> Slurm job 102 on node1, 96 tasks" in log


def test_submit_empties_the_case_folder(slurm_study):
    project_dir, project, runner, fake = slurm_study
    old = project_dir / "runs" / A0
    old.mkdir(parents=True)
    (old / "history.csv").write_text("old")
    runner.submit(project_dir, project, cases=[A0])
    assert not (old / "history.csv").exists()


def test_submit_parses_an_id_with_the_cluster_name(slurm_study):
    project_dir, project, runner, fake = slurm_study
    fake.update(sbatch_suffix=";pdas-cfd")
    job = runner.submit(project_dir, project, cases=[A0])
    assert job.slurm[A0].job_id == "101"


def test_submit_uses_the_given_options(slurm_study):
    project_dir, project, runner, fake = slurm_study
    options = SlurmOptions(partition="node2", ntasks=48, time_limit="2:00:00", exclusive=True, account="")
    job = runner.submit(project_dir, project, cases=[A0], options=options)
    assert (job.slurm[A0].partition, job.slurm[A0].ntasks, job.slurm[A0].time_limit) == ("node2", 48, "2:00:00")
    script = (project_dir / "runs" / A0 / "su2_job.sh").read_text()
    assert "#SBATCH -p node2" in script and "#SBATCH -n 48" in script and "#SBATCH -t 2:00:00" in script


def test_previous_restarts_wait_for_the_case_before(slurm_study):
    project_dir, project, runner, fake = slurm_study
    for case in project.cases[1:]:
        case.restart = "previous"
    save_project(project_dir, project)
    job = runner.submit(project_dir, project)
    assert (job.slurm[A0].depends_on, job.slurm[A2].depends_on, job.slurm[A4].depends_on) == (None, A0, A2)
    assert fake.job("101")["dependency"] is None
    assert fake.job("102")["dependency"] == "afterany:101"
    assert fake.job("103")["dependency"] == "afterany:102"
    assert job.slurm[A2].scratch_fallback and not job.slurm[A0].scratch_fallback
    script = (project_dir / "runs" / A4 / "su2_job.sh").read_text()
    assert "#SBATCH --kill-on-invalid-dep=yes" in script
    solution = project_dir / "runs" / A2 / "restart_flow"
    assert f"[ -f {solution} ] || [ -f {solution}.dat ] || [ -f {solution}.csv ]" in script
    assert f"cat {project_dir / 'runs' / A2 / 'aerosuite_exit'}" in script
    cfg = (project_dir / "runs" / A2 / f"{A2}.cfg").read_text()
    assert f"SOLUTION_FILENAME= {project_dir / 'runs' / A0 / 'restart_flow'}" in cfg
    assert "RESTART_SOL= YES" in cfg
    assert "RESTART_SOL= NO" in (project_dir / "runs" / A0 / f"{A0}.cfg").read_text()


def test_a_restart_from_a_case_outside_the_job_has_no_dependency(slurm_study):
    project_dir, project, runner, fake = slurm_study
    solution = project_dir / "runs" / A0 / "restart_flow.dat"
    solution.parent.mkdir(parents=True)
    solution.write_text("solution")
    project.cases[1].restart = "previous"
    save_project(project_dir, project)
    job = runner.submit(project_dir, project, cases=[A2])
    assert job.slurm[A2].depends_on is None and fake.job("101")["dependency"] is None
    cfg = (project_dir / "runs" / A2 / f"{A2}.cfg").read_text()
    assert f"SOLUTION_FILENAME= {project_dir / 'jobs' / job.id / 'restart' / A0 / 'restart_flow.dat'}" in cfg


def test_a_second_submit_while_one_runs_is_refused(slurm_study):
    project_dir, project, runner, fake = slurm_study
    runner.submit(project_dir, project, cases=[A0])
    with pytest.raises(JobError, match="already running"):
        runner.submit(project_dir, project, cases=[A2])


def test_a_failed_sbatch_part_way_cancels_the_rest_and_fails_the_job(slurm_study):
    project_dir, project, runner, fake = slurm_study
    fake.update(sbatch_fail_after=1, sbatch_message="Invalid account or account/partition combination")
    with pytest.raises(JobError, match="Cannot submit M0p8_a2_b0: sbatch failed: .*Invalid account"):
        runner.submit(project_dir, project)
    assert fake.job("101")["state"] == "CANCELLED"
    assert fake.calls("scancel") == [["scancel", "101"]]
    job = list_jobs(project_dir)[0]
    assert job.state is JobState.FAILED and not job.is_active
    assert all(state is CaseState.FAILED for state in job.case_status.values())
    assert "could not be submitted" in job.failure_tail[A0]
    assert "Not submitted" in job.failure_tail[A2] and "Invalid account" in job.failure_tail[A4]
    assert active_lock(project_dir) is None
    assert "Submit failed" in (project_dir / job.log_path).read_text()


def test_controller_down_at_submit(slurm_study):
    project_dir, project, runner, fake = slurm_study
    fake.update(controller_down=True)
    with pytest.raises(JobError, match="Unable to contact slurm controller"):
        runner.submit(project_dir, project)
    assert active_lock(project_dir) is None
    assert not list_jobs(project_dir)[0].is_active


def test_sbatch_missing(slurm_study, tmp_path, monkeypatch):
    project_dir, project, runner, fake = slurm_study
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))
    with pytest.raises(JobError, match="sbatch was not found on PATH"):
        runner.submit(project_dir, project, cases=[A0])
    assert active_lock(project_dir) is None


def test_job_environment_is_exported_quoted():
    from aerosuite.engine.settings import AppSettings, set_value

    slurm = set_value(AppSettings(), "slurm.job_env", "OMPI_MCA_osc=^ucx UCX_LOG_LEVEL=error EMPTY=").slurm
    lines = job_script("s", "c", "c.cfg", OPTIONS, slurm, "j").splitlines()
    assert ["export OMPI_MCA_osc='^ucx'", "export UCX_LOG_LEVEL=error", "export EMPTY=''"] == [
        line for line in lines if line.startswith("export ") and "PATH" not in line]
    none = set_value(AppSettings(), "slurm.job_env", "").slurm
    assert [line for line in job_script("s", "c", "c.cfg", OPTIONS, none, "j").splitlines()
            if line.startswith("export ")] == ['export PATH=/opt/su2/bin:"$PATH"']

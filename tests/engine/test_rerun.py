"""Rerun with changes: config lines for one job only, in its own copy of the case's config."""
from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.plan import prepare_job
from aerosuite.engine.jobs.rerun import describe, rerun_changes
from aerosuite.engine.project import save_project

from slurm_helpers import A0, A2, A4, slurm_study  # noqa: F401  (fixture)

LOWER = rerun_changes(cfl=0.5, first_order=True, iterations=3000)


def test_the_changes_and_their_words():
    assert LOWER == {"CFL_NUMBER": "0.5", "CFL_ADAPT": "NO", "MUSCL_FLOW": "NO", "MUSCL_TURB": "NO", "ITER": "3000"}
    assert describe(LOWER) == "CFL 0.5 (fixed), first order, 3000 iterations"
    assert describe({"ITER": "500", "LINEAR_SOLVER_ITER": "20"}) == "500 iterations, LINEAR_SOLVER_ITER= 20"
    assert rerun_changes() == {}


def test_only_the_jobs_copy_of_that_case_changes(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    template = (project_dir / "template.cfg").read_text()
    configs = prepare_job(project_dir, project, "j1", [A0, A2], changes={A2: LOWER})
    changed, other = (configs / f"{A2}.cfg").read_text(), (configs / f"{A0}.cfg").read_text()
    assert all(f"{key}= {value}" in changed for key, value in LOWER.items())
    assert "CFL_NUMBER= 0.5" not in other and "MUSCL_FLOW= NO" not in other
    assert (project_dir / "template.cfg").read_text() == template
    assert "CFL_NUMBER= 0.5" not in (project_dir / "configs" / f"{A2}.cfg").read_text()


def test_from_scratch_whatever_the_cases_restart(ready_project):
    project_dir, project = ready_project
    project.cases[1].restart = "previous"
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j2", [A0, A2], fresh_cases=[A2])
    assert "RESTART_SOL= NO" in (configs / f"{A2}.cfg").read_text()
    assert (configs / "run_control.txt").read_text().splitlines()[1] == f"{A2}.cfg, none"
    assert project.cases[1].restart == "previous"  # the project itself keeps it


def test_a_slurm_job_records_and_logs_them_and_the_case_folder_has_them(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0], changes={A0: LOWER})
    assert job.changes == {A0: LOWER}
    assert "CFL_NUMBER= 0.5" in (project_dir / "runs" / A0 / f"{A0}.cfg").read_text()
    assert f"{A0} runs with CFL 0.5 (fixed), first order, 3000 iterations (this job only)" in (
        project_dir / job.log_path).read_text()


def test_adding_a_case_with_changes_to_a_running_job(slurm_study):
    from aerosuite.engine.jobs.executors import SlurmOptions

    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    options = SlurmOptions(partition="node2", ntasks=48, time_limit="", exclusive=True, account="pdas")
    job = runner.add_cases(project_dir, project, job, [A4], options=options, changes={A4: {"ITER": "50"}})
    assert job.changes == {A4: {"ITER": "50"}}
    assert "ITER= 50" in (project_dir / "runs" / A4 / f"{A4}.cfg").read_text()

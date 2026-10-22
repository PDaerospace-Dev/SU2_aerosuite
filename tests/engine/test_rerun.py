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
    configs = prepare_job(project_dir, project, "j2", [A0, A2], starts={A2: None})
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


def test_a_failed_rerun_keeps_the_solution_it_started_from_and_a_finished_one_not(slurm_study, history_writer):
    from aerosuite.engine.jobs.plan import started_from
    from aerosuite.engine.restarts import RUNS_DIR

    from slurm_helpers import STEADY

    project_dir, project, runner, fake = slurm_study
    for name in (A0, A2):
        (project_dir / RUNS_DIR / name).mkdir(parents=True, exist_ok=True)
        (project_dir / RUNS_DIR / name / "restart_flow.dat").write_text(f"first-order solution of {name}")
    job = runner.submit(project_dir, project, cases=[A0, A2], continue_cases=[A0, A2])
    job_dir = project_dir / "jobs" / job.id
    assert started_from(job_dir, A0).read_text() == f"first-order solution of {A0}"
    fake.finish("101", "FAILED", "1:0")  # A0 diverges
    history_writer(project_dir / RUNS_DIR / A2, STEADY)
    fake.finish("102", "COMPLETED", "0:0")  # A2 converges
    job = runner.refresh(project_dir, job)
    assert not job.is_active
    assert started_from(job_dir, A0).read_text() == f"first-order solution of {A0}"  # kept for a rerun
    assert started_from(job_dir, A2) is None  # converged: nothing to keep


def test_a_rerun_can_start_from_a_given_solution(ready_project, tmp_path):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    solution = tmp_path / "kept" / "restart_flow.dat"
    solution.parent.mkdir()
    solution.write_text("solution")
    configs = prepare_job(project_dir, project, "j3", [A2], starts={A2: str(solution)})
    assert (configs / "run_control.txt").read_text().strip() == f"{A2}.cfg, custom, {solution}"
    assert "RESTART_SOL= YES" in (configs / f"{A2}.cfg").read_text()


def test_a_kept_solution_goes_once_the_case_has_one_of_its_own(slurm_study, history_writer):
    from aerosuite.engine.jobs.plan import started_from
    from aerosuite.engine.restarts import RUNS_DIR

    from slurm_helpers import STEADY

    project_dir, project, runner, fake = slurm_study
    (project_dir / RUNS_DIR / A0).mkdir(parents=True)
    (project_dir / RUNS_DIR / A0 / "restart_flow.dat").write_text("first order")
    failed = runner.refresh(project_dir, runner.submit(project_dir, project, cases=[A0], continue_cases=[A0]))
    fake.finish("101", "FAILED", "1:0")
    failed = runner.refresh(project_dir, failed)
    kept = started_from(project_dir / "jobs" / failed.id, A0)
    again = runner.submit(project_dir, project, cases=[A0], starts={A0: str(kept)})
    history_writer(project_dir / RUNS_DIR / A0, STEADY)
    fake.finish("102", "COMPLETED", "0:0")
    runner.refresh(project_dir, again)
    assert started_from(project_dir / "jobs" / failed.id, A0) is None
    assert not (project_dir / "jobs" / failed.id / "restart").exists()

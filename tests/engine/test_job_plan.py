import pytest

from aerosuite.engine.cfg import CONFIGS_DIR, RUN_CONTROL_FILE, generate_configs
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.plan import plan_restarts, prepare_job
from aerosuite.engine.restarts import RUNS_DIR

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _control(configs):
    return (configs / RUN_CONTROL_FILE).read_text().splitlines()


def _solve(project_dir, name, file="restart_flow.dat"):
    folder = project_dir / RUNS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(f"solution of {name}")
    return folder / file


def test_full_run_writes_every_case_as_its_option(ready_project):
    project_dir, project = ready_project
    project.cases[1].restart = "previous"
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j1", [A0, A2, A4])
    assert configs == project_dir.resolve() / "jobs" / "j1" / CONFIGS_DIR
    assert sorted(p.name for p in configs.glob("*.cfg")) == sorted(f"{n}.cfg" for n in (A0, A2, A4))
    assert _control(configs) == [f"{A0}.cfg, none", f"{A2}.cfg, previous", f"{A4}.cfg, none"]


def test_subset_previous_uses_the_earlier_solution_copied_aside(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "previous"  # A4's previous is A2
    generate_configs(project_dir, project)
    _solve(project_dir, A2)
    configs = prepare_job(project_dir, project, "j2", [A4])
    copy = project_dir.resolve() / "jobs" / "j2" / "restart" / A2 / "restart_flow.dat"
    assert _control(configs) == [f"{A4}.cfg, custom, {copy}"]
    assert copy.read_text() == f"solution of {A2}"
    assert [p.name for p in configs.glob("*.cfg")] == [f"{A4}.cfg"]


def test_reference_to_a_case_running_earlier_in_the_job_uses_its_fresh_solution(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "custom"
    project.cases[2].restart_ref = str(project_dir / RUNS_DIR / A0)
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j3", [A0, A2, A4])
    assert _control(configs) == [f"{A0}.cfg, none", f"{A2}.cfg, none", f"{A4}.cfg, from_case, {A0}.cfg"]
    # when the referenced case runs just before, the script's own `previous` does the same
    configs = prepare_job(project_dir, project, "j3b", [A0, A4])
    assert _control(configs) == [f"{A0}.cfg, none", f"{A4}.cfg, previous"]


def test_reference_without_a_solution_starts_fresh_with_a_warning(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "previous"
    generate_configs(project_dir, project)
    plan = plan_restarts(project_dir, project, [A4])
    assert plan.warnings == [f"{A4}: {A2} has no restart file, so {A4} starts from scratch"]
    configs = prepare_job(project_dir, project, "j4", [A4])
    assert _control(configs) == [f"{A4}.cfg, none"]


def test_custom_folder_elsewhere_resolves_to_its_file(ready_project, tmp_path):
    project_dir, project = ready_project
    other = tmp_path / "other" / "M0p5_a0_b0"
    other.mkdir(parents=True)
    (other / "M0p5_a0_b0.cfg").write_text("RESTART_FILENAME= my_restart\n")
    (other / "my_restart.dat").write_text("x")
    project.cases[0].restart, project.cases[0].restart_ref = "custom", str(other)
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j5", [A0])
    assert _control(configs) == [f"{A0}.cfg, custom, {other / 'my_restart.dat'}"]


def test_continue_copies_the_solution_and_sets_restart_sol_in_the_job_copy(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    _solve(project_dir, A2)
    configs = prepare_job(project_dir, project, "j6", [A2], continue_cases=[A2])
    copy = project_dir.resolve() / "jobs" / "j6" / "restart" / A2 / "restart_flow.dat"
    assert _control(configs) == [f"{A2}.cfg, custom, {copy}"]
    assert "RESTART_SOL= YES" in (configs / f"{A2}.cfg").read_text()
    assert "RESTART_SOL" not in (project_dir / CONFIGS_DIR / f"{A2}.cfg").read_text()
    assert "RESTART_SOL" not in (project_dir / "template.cfg").read_text()


def test_continue_without_a_solution_fails_and_leaves_nothing(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    with pytest.raises(JobError, match=f"no solution to continue from: {A2}"):
        prepare_job(project_dir, project, "j7", [A2], continue_cases=[A2])
    assert not (project_dir / "jobs" / "j7").exists()


def test_missing_configs_unknown_and_empty_selections(ready_project):
    project_dir, project = ready_project
    with pytest.raises(JobError, match="generate configs first"):
        prepare_job(project_dir, project, "j8", [A0])
    assert not (project_dir / "jobs" / "j8").exists()
    generate_configs(project_dir, project)
    with pytest.raises(JobError, match="Unknown cases: nope"):
        prepare_job(project_dir, project, "j9", ["nope"])
    with pytest.raises(JobError, match="No cases selected"):
        prepare_job(project_dir, project, "j9", [])


def test_an_existing_job_folder_is_never_overwritten(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    existing = project_dir / "jobs" / "j10"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(JobError, match="already exists"):
        prepare_job(project_dir, project, "j10", [A0])
    assert (existing / "keep.txt").read_text() == "keep"

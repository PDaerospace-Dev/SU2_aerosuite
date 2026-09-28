from aerosuite.engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, build_cases, generate_configs
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.project import TEMPLATE_FILE, create_project
from aerosuite.engine.study import create_study
from aerosuite.web.status import STEPS, step_badges, visible_steps


def test_steps_order():
    assert [key for key, _ in STEPS] == [
        "setup", "aircraft", "config", "sweep", "run", "monitor", "results"]


def test_ready_project(ready_project):
    project_dir, project = ready_project
    assert step_badges(project_dir, project) == {
        "setup": "done", "config": "done", "aircraft": "done", "sweep": "todo",  # configs not generated yet
        "run": "todo", "monitor": "plain", "results": "later",
    }


def test_visible_steps(ready_project):
    _, project = ready_project
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "config", "sweep", "run", "monitor", "results"]
    project.profile = "x07"
    project.sweep.enabled = False
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "aircraft", "config", "run", "monitor", "results"]


def test_new_project(tmp_path):
    project = create_project(tmp_path / "p")
    badges = step_badges(tmp_path / "p", project)
    assert (badges["setup"], badges["config"], badges["sweep"]) == ("todo", "todo", "todo")


def test_new_aircraft_study_gets_a_todo_sweep_badge_not_a_fake_case(tmp_path):
    project = create_study(tmp_path / "q", profile_id="x07", use_reference_template=True)
    assert project.cases == []
    assert step_badges(tmp_path / "q", project)["sweep"] == "todo"


def test_config_badge_flags_template_warnings(ready_project):
    project_dir, project = ready_project
    (project_dir / TEMPLATE_FILE).write_text("AOA= 1\nAOA= 2\n")
    assert step_badges(project_dir, project)["config"] == "attention"


def test_broken_setup_and_duplicate_cases(ready_project, tmp_path):
    project_dir, project = ready_project
    project.mesh.path = str(tmp_path / "gone.su2")
    project.cases.append(project.cases[0].model_copy())
    badges = step_badges(project_dir, project)
    assert badges["setup"] == "attention"
    assert badges["sweep"] == "attention"


def test_non_utf8_template_does_not_crash_step_badges(ready_project):
    project_dir, project = ready_project
    (project_dir / TEMPLATE_FILE).write_bytes(b"% Latin-1 degree sign \xb0\nAOA= 0.0\n")
    badges = step_badges(project_dir, project)
    assert badges["config"] == "attention"


def test_run_badge(ready_project):
    import os
    from datetime import datetime, timedelta

    import psutil

    from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
    from aerosuite.engine.jobs.store import clear_lock, save_job, write_lock

    project_dir, project = ready_project
    names = [case.name for case in project.cases]
    t0 = datetime(2026, 9, 25, 10, 0)
    assert step_badges(project_dir, project)["run"] == "todo"
    save_job(project_dir, JobRecord(
        id="a", backend="local", cases=names, log_path="jobs/a.log", created=t0, state=JobState.DONE,
        case_status={n: CaseState.CONVERGED for n in names}))
    assert step_badges(project_dir, project)["run"] == "done"
    save_job(project_dir, JobRecord(
        id="b", backend="local", cases=[names[1]], log_path="jobs/b.log", created=t0 + timedelta(hours=1),
        state=JobState.FAILED, case_status={names[1]: CaseState.FAILED}))
    assert step_badges(project_dir, project)["run"] == "attention"
    write_lock(project_dir, "c", os.getpid(), psutil.Process().create_time())
    try:
        assert step_badges(project_dir, project)["run"] == "running"
    finally:
        clear_lock(project_dir)


def test_sweep_badge_is_done_once_its_configs_are_generated_and_current(ready_project):
    """There is no Configs step: Generate lives on Sweep, so Sweep's badge says whether it was done."""
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    assert step_badges(project_dir, project)["sweep"] == "done"
    update_sweep(project, alpha=[0.0, 2.0])
    assert step_badges(project_dir, project)["sweep"] == "attention"  # generated for another sweep
    (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).write_text("{broken")
    assert step_badges(project_dir, project)["sweep"] == "attention"


def test_with_the_sweep_off_config_badge_follows_the_generated_config(ready_project):
    """With the sweep off, Generate is on the Config page, so Config's badge carries it."""
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    assert step_badges(project_dir, project)["config"] == "todo"  # a good template, not generated yet
    generate_configs(project_dir, project)
    assert step_badges(project_dir, project)["config"] == "done"
    (project_dir / TEMPLATE_FILE).write_text("AOA= 1\nAOA= 2\n")
    assert step_badges(project_dir, project)["config"] == "attention"  # template warnings still win


from aerosuite.engine.cfg import build_cases
from aerosuite.engine.models import Project
from aerosuite.web.status import project_kind


def test_project_kind():
    project = Project(name="p")
    project.sweep.mach = [0.8]
    project.sweep.alpha = [0.0, 2.0]
    project.sweep.beta = [0.0]
    project.cases = build_cases(project)
    assert project_kind(project) == "sweep · 2 cases"
    project.sweep.alpha = [0.0]
    project.cases = build_cases(project)
    assert project_kind(project) == "sweep · 1 case"
    project.sweep.enabled = False
    assert project_kind(project) == "single case"

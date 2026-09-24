from aerosuite.engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, build_cases, generate_configs
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.project import TEMPLATE_FILE, create_project
from aerosuite.web.status import STEPS, step_badges, visible_steps


def test_steps_order():
    assert [key for key, _ in STEPS] == [
        "setup", "config", "aircraft", "sweep", "configs", "run", "monitor", "results"]


def test_ready_project(ready_project):
    project_dir, project = ready_project
    assert step_badges(project_dir, project) == {
        "setup": "done", "config": "done", "aircraft": "done", "sweep": "done", "configs": "todo",
        "run": "later", "monitor": "later", "results": "later",
    }


def test_visible_steps(ready_project):
    _, project = ready_project
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "config", "sweep", "configs", "run", "monitor", "results"]
    project.profile = "x07"
    project.sweep.enabled = False
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "config", "aircraft", "configs", "run", "monitor", "results"]


def test_new_project(tmp_path):
    project = create_project(tmp_path / "p")
    badges = step_badges(tmp_path / "p", project)
    assert (badges["setup"], badges["config"], badges["sweep"], badges["configs"]) == ("todo", "todo", "todo", "todo")


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


def test_configs_badge_follows_the_sweep(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    assert step_badges(project_dir, project)["configs"] == "done"
    update_sweep(project, alpha=[0.0, 2.0])
    assert step_badges(project_dir, project)["configs"] == "attention"
    (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).write_text("{broken")
    assert step_badges(project_dir, project)["configs"] == "attention"

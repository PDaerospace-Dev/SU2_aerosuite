import json
import time

from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import JobState
from aerosuite.engine.results import load_case_index, summarize
from aerosuite.engine.cfg import (
    CASE_INDEX_FILE,
    CONFIGS_DIR,
    build_cases,
    generate_configs,
    read_template,
    render_case,
    single_case_name,
    template_case_values,
)
from aerosuite.engine.models import Project
from aerosuite.engine.preflight import preflight, sweep_problems
from aerosuite.engine.project import create_project, open_project, save_project, PROJECT_FILE


def _single(ready_project):
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)
    return project_dir, project


def test_single_case_name_is_a_safe_stem():
    assert single_case_name(Project(name="nozzle_study")) == "nozzle_study"
    assert single_case_name(Project(name="My wing: v2")) == "My_wing_v2"
    assert single_case_name(Project(name="...")) == "case"


def test_template_case_values():
    assert template_case_values("MACH_NUMBER= 0.3\nAOA= 2.5 % deg\nSIDESLIP_ANGLE= -1\n") == (0.3, 2.5, -1.0)
    assert template_case_values("AOA= abc\n") == (0.0, 0.0, 0.0)


def test_sweep_off_builds_one_case_and_keeps_its_restart(ready_project):
    project_dir, project = _single(ready_project)
    assert [c.name for c in project.cases] == ["study"]
    project.cases[0].restart = "previous"
    assert build_cases(project)[0].restart == "previous"


def test_sweep_off_renders_the_template_as_written(ready_project):
    project_dir, project = _single(ready_project)
    project.settings.overrides = {"CFL_NUMBER": "5"}
    text = render_case(read_template(project_dir, project), project, project.cases[0])
    assert "MACH_NUMBER= 0.3" in text and "AOA= 0.0" in text
    assert "BREAKDOWN_FILENAME" not in text
    assert "CFL_NUMBER= 5" in text
    assert "MESH_FILENAME=" in text and "wing.su2" in text


def test_sweep_off_generate_indexes_values_from_the_template(ready_project):
    project_dir, project = _single(ready_project)
    written = generate_configs(project_dir, project)
    assert [p.name for p in written] == ["study.cfg"]
    index = json.loads((project_dir / CONFIGS_DIR / CASE_INDEX_FILE).read_text())
    assert index == {"study": {"mach": 0.3, "alpha": 0.0, "beta": 0.0}}


def test_single_case_runs_and_summarizes(ready_project):
    project_dir, project = _single(ready_project)
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": {}}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    deadline = time.monotonic() + 20
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.1)
        job = runner.refresh(project_dir, job)
    assert job.state is JobState.DONE
    assert set(job.case_status) == {"study"}
    table, _ = summarize(project_dir / RUNS_DIR, ["CL"],
                         case_index=load_case_index(project_dir / CONFIGS_DIR))
    assert table["Case"].tolist() == ["study"]
    assert table["Mach"].tolist() == [0.3]


def test_no_mach_check_only_applies_to_sweeps(ready_project):
    project_dir, project = _single(ready_project)
    project.sweep.mach = []
    assert not any("No Mach" in p.message for p in sweep_problems(project))
    assert not any(p.severity == "error" for p in preflight(project_dir, project, "generate"))


def test_schema_1_projects_upgrade_to_sweep_on_without_profile(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 1
    del data["profile"]
    del data["sweep"]["enabled"]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 3
    assert project.profile is None and project.sweep.enabled is True

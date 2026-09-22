import os
import sys

import psutil

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.store import write_lock
from aerosuite.engine.models import Case
from aerosuite.engine.preflight import Problem, has_errors, preflight


def _messages(problems, severity):
    return [p.message for p in problems if p.severity == severity]


def test_valid_project_has_no_generate_problems(ready_project):
    project_dir, project = ready_project
    assert preflight(project_dir, project, "generate") == []


def test_missing_template_and_mesh(ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").unlink()
    project.mesh.path = str(project_dir / "gone.su2")
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("Template not found" in m for m in errors)
    assert any("Mesh not found" in m for m in errors)


def test_no_mesh_and_no_cases(ready_project):
    project_dir, project = ready_project
    project.mesh.path = ""
    project.cases = []
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert "No mesh selected" in errors
    assert "The sweep has no cases" in errors


def test_duplicate_case_names(ready_project):
    project_dir, project = ready_project
    project.cases.append(project.cases[0].model_copy())
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("M0p8_a0_b0" in m and "Duplicate" in m for m in errors)


def test_unknown_marker_is_a_warning(ready_project):
    project_dir, project = ready_project
    project.settings.markers = {"MARKER_HEATFLUX": "( wall, fuselage, 0.0 )", "MARKER_PLOTTING": None}
    problems = preflight(project_dir, project, "generate")
    assert not has_errors(problems)
    assert _messages(problems, "warning") == [
        "MARKER_HEATFLUX refers to 'fuselage', which is not a marker in the mesh"
    ]


def test_restart_problems(ready_project, tmp_path):
    project_dir, project = ready_project
    a0, a2, a4 = project.cases
    a0.restart = "previous"
    a2.restart, a2.restart_ref = "from_case", "M0p8_a4_b0"  # later case: invalid
    a4.restart, a4.restart_ref = "custom", str(tmp_path / "missing.dat")
    project.cases.append(Case(name="extra", mach=0.8, alpha=6, beta=0, restart="initial"))
    problems = preflight(project_dir, project, "generate")
    assert any("first case" in m for m in _messages(problems, "warning"))
    errors = _messages(problems, "error")
    assert any("M0p8_a2_b0" in m and "earlier case" in m for m in errors)
    assert any("M0p8_a4_b0" in m and "restart file not found" in m for m in errors)
    assert any("extra" in m and "initial_restart" in m for m in errors)


def test_run_checks(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.delenv("SU2_RUN", raising=False)
    project.run.sweep_script = str(project_dir / "missing_script.py")
    project.run.sweep_python = "definitely-not-a-python-xyz"
    errors = _messages(preflight(project_dir, project, "run"), "error")
    assert any("have not been generated" in m for m in errors)
    assert any("SU2_RUN" in m for m in errors)
    assert any("Sweep script not found" in m for m in errors)
    assert any("Python for the sweep script not found" in m for m in errors)


def test_run_ready_and_locked(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    generate_configs(project_dir, project)
    assert _messages(preflight(project_dir, project, "run"), "error") == []
    write_lock(project_dir, "j1", os.getpid(), psutil.Process().create_time())
    errors = _messages(preflight(project_dir, project, "run"), "error")
    assert errors == ["Job j1 is still running for this project"]


def test_has_errors():
    assert has_errors([Problem("warning", "w"), Problem("error", "e")])
    assert not has_errors([Problem("warning", "w")])


def test_sweep_python_inside_aerosuite_env_is_a_warning(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    generate_configs(project_dir, project)
    project.run.sweep_python = sys.executable
    problems = preflight(project_dir, project, "run")
    assert not has_errors(problems)
    assert _messages(problems, "warning") == [
        f"The sweep script would run under AeroSuite's own Python ({sys.executable}); "
        "SU2 is normally importable only from the system Python "
        "— set run.sweep_python to that interpreter"
    ]


def test_configs_out_of_date_with_sweep_is_a_warning(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    generate_configs(project_dir, project)
    stale = "Generated configs are out of date with the sweep; regenerate before running"
    assert stale not in _messages(preflight(project_dir, project, "run"), "warning")
    project.cases = project.cases[:2]
    assert stale in _messages(preflight(project_dir, project, "run"), "warning")
    assert stale not in _messages(preflight(project_dir, project, "generate"), "warning")


def test_relative_mesh_path_is_an_error(ready_project):
    project_dir, project = ready_project
    project.mesh.path = "wing.su2"
    for action in ("generate", "run"):
        errors = _messages(preflight(project_dir, project, action), "error")
        assert "Mesh must be an absolute path (the sweep runs from the runs/ folder): wing.su2" in errors
        assert not any("Mesh not found" in m for m in errors)


def test_relative_custom_restart_is_an_error(ready_project):
    project_dir, project = ready_project
    project.cases[1].restart, project.cases[1].restart_ref = "custom", "restart.dat"
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert errors == [
        "M0p8_a2_b0: restart file must be an absolute path (the sweep runs from the runs/ folder): restart.dat"
    ]


def test_relative_initial_restart_is_an_error(ready_project):
    project_dir, project = ready_project
    project.run.initial_restart = "solution.dat"
    assert preflight(project_dir, project, "generate") == []  # not used by any case
    project.cases[0].restart = "initial"
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert errors == [
        "M0p8_a0_b0: initial restart file must be an absolute path "
        "(the sweep runs from the runs/ folder): solution.dat"
    ]


def test_live_lock_blocks_generate(ready_project):
    project_dir, project = ready_project
    write_lock(project_dir, "j1", os.getpid(), psutil.Process().create_time())
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert errors == ["Job j1 is still running for this project"]


def test_empty_mach_list_is_an_error(ready_project):
    project_dir, project = ready_project
    project.sweep.mach = []
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert "No Mach numbers in the sweep" in errors

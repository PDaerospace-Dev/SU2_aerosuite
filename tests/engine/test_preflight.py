import os
import sys

import psutil

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.store import write_lock
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
    a2.restart, a2.restart_ref = "custom", str(tmp_path / "missing.dat")
    a4.restart, a4.restart_ref = "custom", None
    problems = preflight(project_dir, project, "generate")
    assert any("first case" in m for m in _messages(problems, "warning"))
    errors = _messages(problems, "error")
    assert any("M0p8_a2_b0" in m and "restart path not found" in m for m in errors)
    assert any("M0p8_a4_b0" in m and "needs a restart file or case folder" in m for m in errors)


def test_custom_restart_paths(ready_project, tmp_path):
    project_dir, project = ready_project
    a0, a2, a4 = project.cases
    empty = tmp_path / "empty_case"
    empty.mkdir()
    solved = tmp_path / "solved_case"
    solved.mkdir()
    (solved / "restart_flow.dat").write_text("x")
    a0.restart, a0.restart_ref = "custom", "solution.dat"
    a2.restart, a2.restart_ref = "custom", str(empty)
    a4.restart, a4.restart_ref = "custom", str(solved)
    assert _messages(preflight(project_dir, project, "generate"), "error") == [
        "M0p8_a0_b0: restart path must be an absolute path (the sweep runs from the runs/ folder): solution.dat",
        f"M0p8_a2_b0: no restart file found in folder {empty}",
    ]


def test_custom_restart_path_with_a_comma_is_an_error(ready_project, tmp_path):
    project_dir, project = ready_project
    odd = tmp_path / "run,2"
    odd.mkdir()
    (odd / "restart_flow.dat").write_text("x")
    project.cases[0].restart, project.cases[0].restart_ref = "custom", str(odd)
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert errors == [f"M0p8_a0_b0: restart path must not contain a comma (run_control.txt separates "
                      f"fields with commas): {odd}"]


def test_custom_restart_to_a_case_of_this_project_is_allowed_before_it_ran(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "custom"
    project.cases[2].restart_ref = str(project_dir / "runs" / "M0p8_a0_b0")
    assert _messages(preflight(project_dir, project, "generate"), "error") == []


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


def test_non_utf8_template_is_a_problem_not_a_crash(ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").write_bytes(b"% comment with a Latin-1 degree sign \xb0\nAOA= 0.0\n")
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("not UTF-8 text" in m for m in errors)


def test_submit_checks_skip_the_generated_config_state(ready_project, monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    project_dir, project = ready_project  # configs never generated
    run_errors = _messages(preflight(project_dir, project, "run"), "error")
    assert any("Configs have not been generated" in m for m in run_errors)
    assert _messages(preflight(project_dir, project, "submit"), "error") == []
    monkeypatch.delenv("SU2_RUN")
    assert any("SU2_RUN is not set" in m for m in _messages(preflight(project_dir, project, "submit"), "error"))

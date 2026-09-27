from aerosuite.engine.cfg import build_cases
from aerosuite.engine.editing import set_freestream
from aerosuite.engine.preflight import preflight, sweep_problems
from aerosuite.engine.project import save_project


def _messages(problems, severity):
    return [p.message for p in problems if p.severity == severity]


def test_manual_mode_adds_no_problems(ready_project):
    project_dir, project = ready_project
    assert not [m for m in _messages(sweep_problems(project, project_dir), "error") if "altitude" in m.lower()]


def test_missing_altitude_and_length_are_both_errors(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude")
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("needs an altitude" in e for e in errors)
    assert any("Reynolds length greater than 0" in e for e in errors)


def test_out_of_range_altitude_is_an_error(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=120.0, reynolds_length=6.0)
    assert any("outside the standard atmosphere" in e for e in _messages(sweep_problems(project, project_dir), "error"))


def test_a_single_case_without_a_template_mach_is_an_error(ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").write_text("AOA= 0.0\n")
    project.sweep.enabled = False
    project.cases = build_cases(project)
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    errors = _messages(sweep_problems(project, project_dir), "error")
    assert any(e.startswith(f"{project.cases[0].name}: ") and "MACH_NUMBER" in e for e in errors)


def test_a_valid_altitude_project_has_no_freestream_problems(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    save_project(project_dir, project)
    assert not any("altitude" in p.message.lower() or "reynolds" in p.message.lower()
                   for p in sweep_problems(project, project_dir))


def test_overrides_of_freestream_keys_are_a_warning(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.settings.overrides["REYNOLDS_NUMBER"] = "5"
    warnings = _messages(sweep_problems(project, project_dir), "warning")
    assert "REYNOLDS_NUMBER ignored: freestream comes from the altitude" in warnings


def _warnings_for(project_dir, project, template):
    (project_dir / "template.cfg").write_text(template)
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    return _messages(sweep_problems(project, project_dir), "warning")


def test_an_init_option_other_than_reynolds_is_a_warning(ready_project):
    project_dir, project = ready_project
    warnings = _warnings_for(project_dir, project, "MACH_NUMBER= 0.8\nINIT_OPTION= TD_CONDITIONS\n")
    assert any("INIT_OPTION= TD_CONDITIONS" in w and "INIT_OPTION= REYNOLDS" in w for w in warnings)


def test_an_override_of_init_option_counts_too(ready_project):
    project_dir, project = ready_project
    project.settings.overrides["INIT_OPTION"] = "TD_CONDITIONS"
    assert any("INIT_OPTION= TD_CONDITIONS" in w for w in _warnings_for(project_dir, project, "INIT_OPTION= REYNOLDS\n"))


def test_an_incompressible_solver_is_a_warning(ready_project):
    project_dir, project = ready_project
    warnings = _warnings_for(project_dir, project, "SOLVER= INC_RANS\n")
    assert any("SOLVER= INC_RANS" in w and "ignores" in w for w in warnings)


def test_reynolds_initialisation_gives_no_such_warning(ready_project):
    project_dir, project = ready_project
    for template in ("SOLVER= RANS\nINIT_OPTION= REYNOLDS\n", "SOLVER= RANS\n"):
        warnings = _warnings_for(project_dir, project, template)
        assert not any("INIT_OPTION" in w or "SOLVER" in w for w in warnings)

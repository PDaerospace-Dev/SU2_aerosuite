"""AeroSuite's own config checks, for what SU2's dry run cannot see or accepts although it is rarely meant."""
from aerosuite.engine.config_rules import config_problems


def _with(project_dir, *lines):
    path = project_dir / "template.cfg"
    path.write_text(path.read_text() + "".join(line + "\n" for line in lines))


def _messages(project_dir, project, severity):
    return [p.message for p in config_problems(project_dir, project) if p.severity == severity]


def test_a_template_like_the_tests_has_no_problems(ready_project):
    project_dir, project = ready_project
    assert config_problems(project_dir, project) == []


def test_a_mesh_marker_without_a_boundary_condition_is_an_error(ready_project):
    project_dir, project = ready_project
    project.mesh.markers = ["farfield", "wall", "fin", "tail"]
    _with(project_dir, "MARKER_MONITORING= ( wall, fin )")  # monitoring is no boundary condition
    assert _messages(project_dir, project, "error") == [
        "The mesh's markers fin, tail have no boundary condition in the config (e.g. MARKER_HEATFLUX, MARKER_FAR): "
        "SU2 stops when it reads the mesh"]
    _with(project_dir, "MARKER_EULER= ( fin, tail )")
    assert _messages(project_dir, project, "error") == []


def test_an_adaptive_cfl_whose_minimum_is_above_the_start_is_a_warning(ready_project):
    project_dir, project = ready_project
    _with(project_dir, "CFL_NUMBER= 1", "CFL_ADAPT= YES", "CFL_ADAPT_PARAM= ( 0.5, 1.2, 25.0, 100.0 )")
    assert _messages(project_dir, project, "warning") == [
        "CFL_ADAPT_PARAM's minimum CFL 25 is above CFL_NUMBER 1: the CFL jumps to 25 at the first adaptation"]


def test_an_aircraft_study_warns_of_unit_reference_values_and_no_coefficients_in_the_history(ready_project):
    project_dir, project = ready_project
    project.profile = "x07"
    _with(project_dir, "REF_AREA= 1.0", "HISTORY_OUTPUT= ( ITER, RMS_RES )")
    warnings = _messages(project_dir, project, "warning")
    assert warnings[:2] == ["REF_AREA is 1 (SU2's default): the coefficients are per 1 m²; set it on the Aircraft page",
                            "REF_LENGTH is 1 (SU2's default): the coefficients are per 1 m; set it on the Aircraft "
                            "page"]
    assert "HISTORY_OUTPUT has no AERO_COEFF" in warnings[2]
    project.settings.reference.ref_area, project.settings.reference.ref_length = 11.996, 5.3
    _with(project_dir, "HISTORY_OUTPUT= ( ITER, RMS_RES, AERO_COEFF )")
    assert _messages(project_dir, project, "warning") == []


def test_ascii_volume_output_on_a_big_mesh_is_a_warning(ready_project):
    project_dir, project = ready_project
    mesh = project_dir.parent / "wing.su2"
    mesh.write_text("NDIME= 3\nNELEM= 15036158\n")
    _with(project_dir, "OUTPUT_FILES= ( RESTART, PARAVIEW_ASCII, SURFACE_PARAVIEW_ASCII )")
    assert _messages(project_dir, project, "warning") == [
        "OUTPUT_FILES writes PARAVIEW_ASCII for a 15.0M-element mesh: large, slow text files at every write; "
        "PARAVIEW (binary) is several times smaller"]
    mesh.write_text("NDIME= 3\nNELEM= 1000\n")
    assert _messages(project_dir, project, "warning") == []

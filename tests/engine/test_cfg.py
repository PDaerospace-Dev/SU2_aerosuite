import json

import pytest

from aerosuite.engine.cfg import (
    CASE_INDEX_FILE,
    CONFIGS_DIR,
    RUN_CONTROL_FILE,
    apply_parameters,
    build_cases,
    extract_markers,
    generate_configs,
    render_case,
    run_control_text,
    settings_parameters,
)
from aerosuite.engine.errors import GenerationError, ProjectError, TemplateError
from aerosuite.engine.models import Case, Project

TEMPLATE = """\
% test template
MACH_NUMBER= 0.3
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_TEMPERATURE= 288.15
MARKER_FAR= ( farfield )
MARKER_HEATFLUX= ( wall, 0.0 )
MARKER_PLOTTING= ( wall )
MESH_FILENAME= mesh.su2
"""


def _project(**sweep):
    project = Project(name="t")
    project.sweep.mach = sweep.get("mach", [0.8])
    project.sweep.alpha = sweep.get("alpha", [0.0, 2.5])
    project.sweep.beta = sweep.get("beta", [0.0])
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    return project


def test_extract_markers(tmp_path):
    mesh = tmp_path / "m.su2"
    mesh.write_text("NDIME= 3\nNMARK= 2\nMARKER_TAG= farfield\nMARKER_ELEMS= 1\nMARKER_TAG = wall\n")
    assert extract_markers(mesh) == ["farfield", "wall"]


def test_extract_markers_missing_file(tmp_path):
    with pytest.raises(ProjectError):
        extract_markers(tmp_path / "nope.su2")


def test_apply_parameters_replaces_removes_and_appends():
    out = apply_parameters(TEMPLATE, {"AOA": "2.5", "MARKER_PLOTTING": None, "CFL_NUMBER": "5"})
    assert "AOA= 2.5\n" in out
    assert "MARKER_PLOTTING" not in out
    assert out.endswith("\n\nCFL_NUMBER= 5\n")


def test_apply_parameters_keeps_backslashes_literal():
    out = apply_parameters(TEMPLATE, {"MESH_FILENAME": r"C:\meshes\wing.su2"})
    assert r"MESH_FILENAME= C:\meshes\wing.su2" in out


def test_apply_parameters_does_not_touch_longer_keys():
    out = apply_parameters("MARKER_FARFIELD= x\nMARKER_FAR= y\n", {"MARKER_FAR": "z"})
    assert out == "MARKER_FARFIELD= x\nMARKER_FAR= z\n"


def test_settings_parameters_skip_unset_and_format_numbers():
    project = Project(name="t")
    project.settings.freestream.reynolds = 6.5e6
    project.settings.numerics.iter = 2000
    project.settings.markers = {"MARKER_PLOTTING": None}
    params = settings_parameters(project.settings)
    assert params == {"REYNOLDS_NUMBER": "6500000", "ITER": "2000", "MARKER_PLOTTING": None}


def test_render_case_layers_case_values_last(tmp_path):
    project = _project()
    project.mesh.path = str(tmp_path / "wing.su2")
    project.settings.overrides = {"AOA": "99", "CONV_FIELD": "LIFT"}
    project.settings.markers = {"MARKER_PLOTTING": None}
    case = project.cases[1]  # alpha 2.5
    out = render_case(TEMPLATE, project, case)
    assert "AOA= 2.5\n" in out
    assert "MACH_NUMBER= 0.8\n" in out
    assert "CONV_FIELD= LIFT" in out
    assert "MARKER_PLOTTING" not in out
    assert f"MESH_FILENAME= {(tmp_path / 'wing.su2').resolve()}" in out
    assert f"BREAKDOWN_FILENAME= {case.name}_FB.dat" in out


def test_build_cases_names_values_and_keeps_restart_choices():
    project = _project(mach=[0.8, 0.85], alpha=[0.0, 2.5], beta=[0.0])
    assert [c.name for c in project.cases] == [
        "M0p8_a0_b0", "M0p8_a2p5_b0", "M0p85_a0_b0", "M0p85_a2p5_b0",
    ]
    project.cases[1].restart = "previous"
    project.sweep.beta = [0.0, 1.0]
    rebuilt = build_cases(project)
    assert len(rebuilt) == 8
    assert next(c for c in rebuilt if c.name == "M0p8_a2p5_b0").restart == "previous"
    assert next(c for c in rebuilt if c.name == "M0p8_a2p5_b1").restart == "none"


def test_build_cases_empty_lists_default_to_zero():
    project = _project(mach=[0.5], alpha=[], beta=[])
    assert [(c.alpha, c.beta) for c in project.cases] == [(0.0, 0.0)]


def test_run_control_text():
    cases = [
        Case(name="c1", mach=0.8, alpha=0, beta=0),
        Case(name="c2", mach=0.8, alpha=2, beta=0, restart="previous"),
        Case(name="c3", mach=0.8, alpha=4, beta=0, restart="custom", restart_ref="/r/restart.dat"),
        Case(name="c4", mach=0.8, alpha=6, beta=0, restart="from_case", restart_ref="c1"),
        Case(name="c5", mach=0.8, alpha=8, beta=0, restart="initial"),
    ]
    assert run_control_text(cases) == (
        "c1.cfg, none\n"
        "c2.cfg, previous\n"
        "c3.cfg, custom, /r/restart.dat\n"
        "c4.cfg, from_case, c1.cfg\n"
        "c5.cfg, initial\n"
    )


def test_generate_configs_writes_cfgs_control_and_index(tmp_path):
    (tmp_path / "template.cfg").write_text(TEMPLATE)
    configs = tmp_path / CONFIGS_DIR
    configs.mkdir()
    (configs / "stale_old_case.cfg").write_text("old")
    project = _project()
    written = generate_configs(tmp_path, project)
    assert sorted(p.name for p in written) == ["M0p8_a0_b0.cfg", "M0p8_a2p5_b0.cfg"]
    assert not (configs / "stale_old_case.cfg").exists()
    assert "AOA= 2.5\n" in (configs / "M0p8_a2p5_b0.cfg").read_text()
    assert (configs / RUN_CONTROL_FILE).read_text() == "M0p8_a0_b0.cfg, none\nM0p8_a2p5_b0.cfg, none\n"
    index = json.loads((configs / CASE_INDEX_FILE).read_text())
    assert index["M0p8_a2p5_b0"] == {"mach": 0.8, "alpha": 2.5, "beta": 0.0}


def test_generate_configs_refuses_duplicate_names(tmp_path):
    (tmp_path / "template.cfg").write_text(TEMPLATE)
    project = _project(alpha=[2.0, 2.0])
    with pytest.raises(GenerationError, match="M0p8_a2_b0"):
        generate_configs(tmp_path, project)


def test_generate_configs_missing_template(tmp_path):
    with pytest.raises(TemplateError):
        generate_configs(tmp_path, _project())

"""An aircraft study's single case is named like a sweep case, from the template's Mach, AoA and β."""
import json

import pytest
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.cfg import (CASE_INDEX_FILE, CONFIGS_DIR, build_cases, generate_configs, render_case,
                                  stale_case_name)
from aerosuite.engine.editing import set_altitudes, set_freestream
from aerosuite.engine.errors import GenerationError
from aerosuite.engine.preflight import sweep_problems
from aerosuite.engine.project import follow_template, open_project, save_project, set_template_text

TEMPLATE = "MACH_NUMBER= 1.2\nAOA= 2.0\nSIDESLIP_ANGLE= 0.0\nMARKER_FAR= ( farfield )\nMARKER_EULER= ( wall )\n"


def _aircraft_single(project_dir, project, template=TEMPLATE):
    (project_dir / "template.cfg").write_text(template)
    project.profile = "x07"
    project.sweep.enabled = False
    project.cases = build_cases(project, template)
    save_project(project_dir, project)
    return project


def test_the_case_is_named_from_the_template(ready_project):
    project_dir, project = ready_project
    project = _aircraft_single(project_dir, project)
    [case] = project.cases
    assert (case.name, case.mach, case.alpha, case.beta) == ("M1p2_a2_b0", 1.2, 2.0, 0.0)
    assert "BREAKDOWN_FILENAME= M1p2_a2_b0_FB.dat" in render_case(TEMPLATE, project, case)


def test_a_general_study_keeps_the_project_name(ready_project):
    project_dir, project = ready_project
    project.sweep.enabled = False
    assert [c.name for c in build_cases(project, TEMPLATE)] == ["study"]


def test_the_altitude_and_the_naming_options_apply(ready_project):
    project_dir, project = ready_project
    project = _aircraft_single(project_dir, project)
    project.sweep.naming.include_altitude = True
    set_freestream(project, mode="altitude", reynolds_length=1.0)
    set_altitudes(project, [0.0])  # no template given: the case keeps its Mach, AoA and β
    [case] = project.cases
    assert (case.name, case.altitude_km) == ("M1p2_0km_a2_b0", 0.0)
    project.sweep.naming.include_beta = False
    assert build_cases(project)[0].name == "M1p2_0km_a2"


def test_saving_the_template_renames_the_case_and_keeps_its_restart(ready_project):
    project_dir, project = ready_project
    project = _aircraft_single(project_dir, project)
    project.cases[0].restart, project.cases[0].restart_ref = "custom", "old_run"
    set_template_text(project_dir, project, "MACH_NUMBER= 1.5\nAOA= 0\n")
    [case] = project.cases
    assert (case.name, case.mach, case.restart, case.restart_ref) == ("M1p5_a0_b0", 1.5, "custom", "old_run")


def test_an_outside_edit_is_refused_until_the_case_follows(ready_project):
    project_dir, project = ready_project
    project = _aircraft_single(project_dir, project)
    (project_dir / "template.cfg").write_text("MACH_NUMBER= 1.5\nAOA= 0\n")  # edited outside AeroSuite
    assert stale_case_name(project, "MACH_NUMBER= 1.5\nAOA= 0\n") == "M1p5_a0_b0"
    errors = [p.message for p in sweep_problems(project, project_dir) if p.severity == "error"]
    assert any("named M1p2_a2_b0" in e and "make it M1p5_a0_b0" in e for e in errors)
    with pytest.raises(GenerationError, match="open the Aircraft page"):
        generate_configs(project_dir, project)
    assert follow_template(project_dir, project) and not follow_template(project_dir, project)
    written = generate_configs(project_dir, project)
    assert [p.name for p in written] == ["M1p5_a0_b0.cfg"]
    index = json.loads((project_dir / CONFIGS_DIR / CASE_INDEX_FILE).read_text())
    assert index == {"M1p5_a0_b0": {"mach": 1.5, "alpha": 0.0, "beta": 0.0}}


def test_cli_generate_renames_a_case_left_behind_by_an_outside_edit(ready_project):
    project_dir, project = ready_project
    _aircraft_single(project_dir, project)
    (project_dir / "template.cfg").write_text(TEMPLATE.replace("MACH_NUMBER= 1.2\nAOA= 2.0", "MACH_NUMBER= 1.5\nAOA= 0"))
    result = CliRunner().invoke(app, ["generate", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert "case M1p2_a2_b0 is now M1p5_a0_b0" in result.output
    assert [c.name for c in open_project(project_dir).cases] == ["M1p5_a0_b0"]

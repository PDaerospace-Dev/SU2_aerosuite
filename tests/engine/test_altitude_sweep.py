"""Altitude as a sweep dimension (spec 2026-09-29-altitude-sweep-design.md)."""
import json

import pytest

from aerosuite.engine.cfg import (CASE_INDEX_FILE, CONFIGS_DIR, build_cases, case_altitude, case_freestream,
                                  generate_configs, render_case)
from aerosuite.engine.editing import set_altitudes, set_freestream, update_sweep
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.freestream import freestream_setup_errors, naming_altitude
from aerosuite.engine.models import SCHEMA_VERSION, Project
from aerosuite.engine.preflight import sweep_problems
from aerosuite.engine.project import PROJECT_FILE, create_project, open_project, save_project

TEMPLATE = "MACH_NUMBER= 0.3\nREYNOLDS_NUMBER= 1e6\nFREESTREAM_TEMPERATURE= 288.15\n"


def _project(altitudes=(0.0, 11.0), machs=(0.6, 0.8)) -> Project:
    project = Project(name="p")
    project.sweep.mach, project.sweep.alpha, project.sweep.beta = list(machs), [0.0], [0.0]
    project.sweep.naming.include_base = False
    fs = project.settings.freestream
    fs.mode, fs.reynolds_length = "altitude", 6.0
    project.sweep.altitudes_km = list(altitudes)
    project.cases = build_cases(project)
    return project


def test_altitude_is_the_outermost_loop_and_names_carry_each_altitude():
    project = _project()
    assert [(c.name, c.altitude_km) for c in project.cases] == [
        ("M0p6_0km_a0_b0", 0.0), ("M0p8_0km_a0_b0", 0.0),
        ("M0p6_11km_a0_b0", 11.0), ("M0p8_11km_a0_b0", 11.0)]
    assert naming_altitude(project) == "0km, 11km"


def test_each_case_gets_the_temperature_and_reynolds_number_of_its_altitude():
    project = _project()
    texts = {c.name: render_case(TEMPLATE, project, c) for c in project.cases}
    assert "FREESTREAM_TEMPERATURE= 288.15" in texts["M0p8_0km_a0_b0"]
    assert "FREESTREAM_TEMPERATURE= 216.65" in texts["M0p8_11km_a0_b0"]
    assert "REYNOLDS_NUMBER= 36258390" in texts["M0p8_11km_a0_b0"]
    rows = case_freestream(project, TEMPLATE)
    assert [row.altitude_km for row in rows] == [0.0, 0.0, 11.0, 11.0]
    assert rows[0].values.reynolds > rows[2].values.reynolds  # denser air at sea level


def test_manual_mode_ignores_the_altitude_list():
    project = _project()
    project.settings.freestream.mode = "manual"
    project.cases = build_cases(project)
    assert [c.name for c in project.cases] == ["M0p6_sl_a0_b0", "M0p8_sl_a0_b0"]
    assert all(c.altitude_km is None for c in project.cases)


def test_without_the_altitude_label_two_altitudes_collide():
    project = _project()
    project.sweep.naming.include_altitude = False
    project.cases = build_cases(project)
    assert any("Duplicate case names" in p.message for p in sweep_problems(project))


def test_an_empty_altitude_list_is_reported_once():
    project = _project(altitudes=())
    assert [c.altitude_km for c in project.cases] == [None, None]
    assert freestream_setup_errors(project) == ["No altitudes in the sweep"]


def test_each_bad_altitude_is_reported_once():
    project = _project(altitudes=(0.0, 120.0))
    errors = freestream_setup_errors(project)
    assert len(errors) == 1 and "120 km" in errors[0]


def test_a_single_case_uses_the_freestream_altitude():
    project = _project()
    project.sweep.enabled = False
    project.settings.freestream.altitude_km = 11.0
    project.cases = build_cases(project)
    case = project.cases[0]
    assert case.altitude_km is None and case_altitude(project, case) == 11.0
    assert "FREESTREAM_TEMPERATURE= 216.65" in render_case(TEMPLATE, project, case)
    project.settings.freestream.altitude_km = None
    assert "needs an altitude" in freestream_setup_errors(project)[0]


def test_restart_choices_follow_the_case_when_its_label_changes():
    project = _project()
    project.cases[2].restart = "previous"
    project.sweep.naming.include_altitude = False
    project.sweep.altitudes_km = [11.0]
    project.cases = build_cases(project)
    assert [(c.name, c.restart) for c in project.cases] == [("M0p6_a0_b0", "previous"), ("M0p8_a0_b0", "none")]


def test_changing_a_single_altitude_keeps_the_restart_choices():
    project = _project(altitudes=(11.0,))
    project.cases[1].restart = "previous"
    update_sweep(project, altitudes_km=[10.0])
    assert [(c.name, c.restart) for c in project.cases] == [("M0p6_10km_a0_b0", "none"),
                                                             ("M0p8_10km_a0_b0", "previous")]
    update_sweep(project, altitudes_km=[10.0, 12.0])  # the new altitude's cases start with none
    assert [c.restart for c in project.cases] == ["none", "previous", "none", "none"]


def test_update_sweep_sets_the_altitudes_and_rebuilds():
    project = _project()
    assert update_sweep(project, altitudes_km=[5.0])
    assert [c.name for c in project.cases] == ["M0p6_5km_a0_b0", "M0p8_5km_a0_b0"]
    with pytest.raises(ProjectError, match="must be numbers"):
        update_sweep(project, altitudes_km=[float("inf")])


def test_set_altitudes_routes_by_the_sweep():
    project = _project()
    set_altitudes(project, [0.0, 5.0])
    assert project.sweep.altitudes_km == [0.0, 5.0] and len(project.cases) == 4
    project.sweep.enabled = False
    project.cases = build_cases(project)
    set_altitudes(project, [5.0])
    assert project.settings.freestream.altitude_km == 5.0
    with pytest.raises(ProjectError, match="single case has one altitude"):
        set_altitudes(project, [0.0, 5.0])


def test_switching_the_mode_rebuilds_the_cases():
    project = _project()
    set_freestream(project, mode="manual")
    assert len(project.cases) == 2
    set_freestream(project, mode="altitude")
    assert len(project.cases) == 4


def test_cases_json_holds_each_cases_altitude(tmp_path):
    project = _project()
    (tmp_path / project.template).write_text(TEMPLATE)
    generate_configs(tmp_path, project)
    index = json.loads((tmp_path / CONFIGS_DIR / CASE_INDEX_FILE).read_text())
    assert index["M0p6_11km_a0_b0"] == {"mach": 0.6, "alpha": 0.0, "beta": 0.0, "altitude_km": 11.0}


def _schema_4(tmp_path, freestream, cases, enabled=True):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 4
    data["settings"]["freestream"] = freestream
    data["sweep"].update({"enabled": enabled, "mach": [0.8], "alpha": [0.0], "beta": [0.0]})
    data["cases"] = cases
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    return open_project(tmp_path)


def test_schema_4_altitude_projects_migrate_to_a_list_of_one(tmp_path):
    case = {"name": "M0p8_11km_a0_b0_x", "mach": 0.8, "alpha": 0.0, "beta": 0.0, "restart": "previous"}
    project = _schema_4(tmp_path, {"mode": "altitude", "altitude_km": 11.0, "reynolds_length": 6.0}, [case])
    assert project.schema_version == SCHEMA_VERSION
    assert project.sweep.altitudes_km == [11.0]
    assert project.settings.freestream.altitude_km == 11.0
    assert (project.cases[0].altitude_km, project.cases[0].restart) == (11.0, "previous")
    save_project(tmp_path, project)
    assert open_project(tmp_path).cases[0].altitude_km == 11.0


def test_schema_4_manual_projects_migrate_unchanged(tmp_path):
    case = {"name": "M0p8_sl_a0_b0_x", "mach": 0.8, "alpha": 0.0, "beta": 0.0}
    project = _schema_4(tmp_path, {"temperature_K": 250.0}, [case])
    assert project.sweep.altitudes_km == [] and project.cases[0].altitude_km is None

import json

import pytest

from aerosuite.engine.cfg import build_cases, case_freestream, render_case
from aerosuite.engine.editing import set_freestream, update_sweep
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.freestream import (altitude_label, freestream_for, freestream_setup_errors, naming_altitude)
from aerosuite.engine.models import Freestream, Project, Settings
from aerosuite.engine.profiles import apply_profile, load_profile, save_profile
from aerosuite.engine.project import PROJECT_FILE, create_project, open_project, save_project

TEMPLATE = "MACH_NUMBER= 0.3\nREYNOLDS_NUMBER= 1e6\nFREESTREAM_TEMPERATURE= 288.15\n"


def _altitude(altitude_km=11.0, length=6.0) -> Settings:
    return Settings(freestream=Freestream(mode="altitude", altitude_km=altitude_km, reynolds_length=length))


def _sweep_project(**freestream) -> Project:
    project = Project(name="p")
    project.sweep.mach = [0.6, 0.8]
    project.sweep.alpha = [0.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_base = False
    for key, value in freestream.items():
        setattr(project.settings.freestream, key, value)
    project.cases = build_cases(project)
    return project


def test_manual_mode_adds_nothing():
    assert freestream_for(Settings(), 0.8) is None


def test_values_for_known_inputs():
    assert freestream_for(_altitude(), 0.8) == {
        "FREESTREAM_TEMPERATURE": "216.65", "REYNOLDS_NUMBER": "34769586", "REYNOLDS_LENGTH": "6"}
    assert freestream_for(_altitude(), 0.6)["REYNOLDS_NUMBER"] == "26077190"


@pytest.mark.parametrize("altitude, length, mach, message", [
    (None, 6.0, 0.8, "needs an altitude"),
    (120.0, 6.0, 0.8, "outside the standard atmosphere"),
    (-1.0, 6.0, 0.8, "outside the standard atmosphere"),
    (11.0, None, 0.8, "Reynolds length greater than 0"),
    (11.0, 0.0, 0.8, "Reynolds length greater than 0"),
    (11.0, 6.0, 0.0, "must be greater than 0"),
])
def test_invalid_inputs_are_refused(altitude, length, mach, message):
    with pytest.raises(ProjectError, match=message):
        freestream_for(_altitude(altitude, length), mach)


def test_setup_errors_list_every_missing_value():
    errors = freestream_setup_errors(Freestream(mode="altitude"))
    assert len(errors) == 2 and "altitude" in errors[0] and "Reynolds length" in errors[1]


def test_altitude_labels():
    assert (altitude_label(11.0), altitude_label(10.5), altitude_label(0.0)) == ("11km", "10p5km", "0km")


def test_case_names_use_the_derived_label_only_with_an_altitude():
    assert [c.name for c in _sweep_project(mode="altitude").cases] == ["M0p6_sl_a0_b0", "M0p8_sl_a0_b0"]
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    assert naming_altitude(project) == "11km"
    assert [c.name for c in project.cases] == ["M0p6_11km_a0_b0", "M0p8_11km_a0_b0"]


def test_each_case_gets_its_own_reynolds_number_over_an_override():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.settings.overrides["REYNOLDS_NUMBER"] = "5"
    project.settings.freestream.reynolds = 1.2e7  # the kept by-hand value
    texts = [render_case(TEMPLATE, project, case) for case in project.cases]
    assert "REYNOLDS_NUMBER= 26077190" in texts[0] and "REYNOLDS_NUMBER= 34769586" in texts[1]
    assert "FREESTREAM_TEMPERATURE= 216.65" in texts[1] and "REYNOLDS_LENGTH= 6" in texts[1]


def test_a_single_case_uses_the_templates_mach():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.sweep.enabled = False
    project.cases = build_cases(project)
    assert "REYNOLDS_NUMBER= 13038595" in render_case(TEMPLATE, project, project.cases[0])


def test_manual_mode_renders_as_before():
    project = _sweep_project()
    project.settings.freestream.reynolds = 1.2e7
    assert "REYNOLDS_NUMBER= 12000000" in render_case(TEMPLATE, project, project.cases[0])


def test_case_freestream_rows_carry_values_or_the_error():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    rows = case_freestream(project, TEMPLATE)
    assert [(r.name, r.mach, round(r.values.reynolds)) for r in rows] == [
        ("M0p6_11km_a0_b0", 0.6, 26077190), ("M0p8_11km_a0_b0", 0.8, 34769586)]
    project.settings.freestream.altitude_km = 120.0
    assert all(r.values is None and "outside" in r.error for r in case_freestream(project, TEMPLATE))


def test_set_freestream_rebuilds_names_and_keeps_restarts():
    project = _sweep_project()
    assert set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    assert [c.name for c in project.cases] == ["M0p6_11km_a0_b0", "M0p8_11km_a0_b0"]
    project.cases[1].restart = "previous"
    set_freestream(project, reynolds_length=7.0)  # the label doesn't change: names and restarts stay
    assert project.cases[1].restart == "previous"
    set_freestream(project, altitude_km=None)  # cleared: back to the typed label
    assert project.cases[1].name == "M0p8_sl_a0_b0"
    assert not set_freestream(project, mode="altitude")  # no change


def test_set_freestream_refuses_bad_input():
    project = _sweep_project()
    with pytest.raises(ProjectError, match="manual' or 'altitude"):
        set_freestream(project, mode="sky")
    with pytest.raises(ProjectError, match="Altitude must be a number"):
        set_freestream(project, altitude_km=float("nan"))


def test_the_typed_label_is_refused_in_altitude_mode():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    with pytest.raises(ProjectError, match="follows the altitude"):
        update_sweep(project, altitude="cruise")


def test_schema_3_projects_open_in_manual_mode(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 3
    data["settings"]["freestream"] = {"temperature_K": 250.0}
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 4
    assert project.settings.freestream.mode == "manual" and project.settings.freestream.temperature_K == 250.0


def test_applying_a_profile_rebuilds_the_case_names(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))
    source = tmp_path / "source"
    project = create_project(source)
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    save_project(source, project)
    save_profile(source, project, "cruise", "Cruise")
    target = tmp_path / "target"
    other = create_project(target)
    other.sweep.mach, other.sweep.alpha, other.sweep.beta = [0.8], [0.0], [0.0]
    other.cases = build_cases(other)
    apply_profile(target, other, load_profile("cruise"), copy_template=False)
    assert other.settings.freestream.mode == "altitude"
    assert [c.name for c in other.cases] == [c.name for c in build_cases(other)]
    assert "_11km_" in other.cases[0].name

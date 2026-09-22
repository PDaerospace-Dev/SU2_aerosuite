import pytest

from aerosuite.engine.editing import (
    parse_key_value,
    parse_value_list,
    set_parameter,
    unset_parameter,
    update_sweep,
)
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.models import Project, Settings


@pytest.mark.parametrize(
    "text, values",
    [
        ("0.6,0.8,0.85", [0.6, 0.8, 0.85]),
        ("0.6 0.8, 0.85", [0.6, 0.8, 0.85]),
        ("-4:4:2", [-4.0, -2.0, 0.0, 2.0, 4.0]),
        ("0:1:0.3", [0.0, 0.3, 0.6, 0.9]),
        ("0.1:0.3:0.1", [0.1, 0.2, 0.3]),
        ("-2, 0:4:2", [-2.0, 0.0, 2.0, 4.0]),
        ("5", [5.0]),
    ],
)
def test_parse_value_list(text, values):
    assert parse_value_list(text) == values


def test_parse_value_list_normalises_negative_zero():
    values = parse_value_list("-0.4:0.4:0.2")
    assert values == [-0.4, -0.2, 0.0, 0.2, 0.4]
    assert str(values[2]) == "0.0"


@pytest.mark.parametrize("text", ["", "  ", "abc", "1:2", "1:2:0", "4:0:1", "1:x:1"])
def test_parse_value_list_rejects_bad_input(text):
    with pytest.raises(ProjectError):
        parse_value_list(text)


def test_parse_key_value():
    assert parse_key_value("cfl_number = 5") == ("CFL_NUMBER", "5")
    assert parse_key_value("MARKER_FAR=( farfield )") == ("MARKER_FAR", "( farfield )")
    with pytest.raises(ProjectError):
        parse_key_value("CFL_NUMBER")
    with pytest.raises(ProjectError):
        parse_key_value("=5")


def test_parse_key_value_rejects_an_empty_value():
    with pytest.raises(ProjectError, match="has no value; use --unset CFL_NUMBER to go back to the template value"):
        parse_key_value("cfl_number= ")


def test_set_parameter_routes_markers_and_overrides():
    settings = Settings()
    set_parameter(settings, "CFL_NUMBER", "5")
    set_parameter(settings, "MARKER_FAR", "( farfield )")
    set_parameter(settings, "MARKER_PLOTTING", "none")
    assert settings.overrides == {"CFL_NUMBER": "5"}
    assert settings.markers == {"MARKER_FAR": "( farfield )", "MARKER_PLOTTING": None}


def test_set_parameter_refuses_case_keys_invalid_names_and_removing_non_markers():
    settings = Settings()
    with pytest.raises(ProjectError, match="set per case"):
        set_parameter(settings, "AOA", "3")
    with pytest.raises(ProjectError, match="not a valid SU2 option"):
        set_parameter(settings, "1BAD KEY", "3")
    with pytest.raises(ProjectError, match="--unset"):
        set_parameter(settings, "CFL_NUMBER", "none")


def test_unset_parameter():
    settings = Settings(overrides={"CFL_NUMBER": "5"}, markers={"MARKER_FAR": None})
    unset_parameter(settings, "cfl_number")
    unset_parameter(settings, "MARKER_FAR")
    assert settings.overrides == {} and settings.markers == {}
    with pytest.raises(ProjectError, match="not set"):
        unset_parameter(settings, "ITER")


def test_update_sweep_rebuilds_cases_and_keeps_restarts():
    project = Project(name="t")
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    assert update_sweep(project, mach=[0.8], alpha=[0.0, 2.0], beta=[0.0])
    assert [c.name for c in project.cases] == ["M0p8_a0_b0", "M0p8_a2_b0"]
    project.cases[1].restart = "previous"
    assert update_sweep(project, alpha=[0.0, 2.0, 4.0])
    assert [c.restart for c in project.cases] == ["none", "previous", "none"]
    assert not update_sweep(project)


def test_update_sweep_rejects_non_positive_mach():
    with pytest.raises(ProjectError, match="Mach"):
        update_sweep(Project(name="t"), mach=[0.0])

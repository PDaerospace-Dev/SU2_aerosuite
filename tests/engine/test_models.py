import pytest
from pydantic import ValidationError

from aerosuite.engine.models import SCHEMA_VERSION, Case, Project, RunSettings


def test_new_project_defaults():
    project = Project(name="demo")
    assert project.schema_version == SCHEMA_VERSION
    assert project.template == "template.cfg"
    assert project.cases == []
    assert project.run.partitions == 1
    assert project.run.sweep_python == "python3"
    assert project.sweep.altitude == "sl"
    assert project.sweep.naming.include_mach is True


def test_json_round_trip_keeps_marker_removal_and_cases():
    project = Project(name="demo")
    project.settings.markers = {"MARKER_FAR": "( farfield )", "MARKER_PLOTTING": None}
    project.settings.freestream.reynolds = 6.5e6
    project.cases = [Case(name="M0p8_a0_b0", mach=0.8, alpha=0.0, beta=0.0, restart="previous")]
    restored = Project.model_validate_json(project.model_dump_json())
    assert restored == project
    assert restored.settings.markers["MARKER_PLOTTING"] is None


def test_partitions_must_be_positive():
    with pytest.raises(ValidationError):
        RunSettings(partitions=0)


def test_unknown_restart_option_rejected():
    with pytest.raises(ValidationError):
        Case(name="x", mach=0.8, alpha=0, beta=0, restart="sometimes")

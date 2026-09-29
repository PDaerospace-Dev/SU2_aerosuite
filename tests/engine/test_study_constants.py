"""Study constants a derived formula can use: reference size, and the freestream per case from ISA."""
import pytest

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.formula import Missing
from aerosuite.engine.models import Project
from aerosuite.engine.study_results import CONSTANT_NAMES, study_constants

TEMPLATE = "MACH_NUMBER= 0.3\nREF_AREA= 16.2\nREF_LENGTH= 1.9\n"


def _project(mode="altitude") -> Project:
    project = Project(name="p")
    project.sweep.mach, project.sweep.alpha, project.sweep.beta = [0.8], [0.0], [0.0]
    project.settings.freestream.mode, project.settings.freestream.reynolds_length = mode, 2.5
    project.sweep.altitudes_km = [11.0]
    project.cases = build_cases(project)
    return project


def test_names():
    assert CONSTANT_NAMES == ("S_ref", "L_ref", "rho_inf", "p_inf", "T_inf", "V_inf", "q_inf")


def test_freestream_from_isa_at_the_cases_altitude_and_mach():
    project = _project()
    values = study_constants(project, project.cases[0], TEMPLATE)
    assert values["T_inf"] == pytest.approx(216.65)
    assert values["p_inf"] == pytest.approx(22632.1, rel=1e-4)
    assert values["rho_inf"] == pytest.approx(0.3639, rel=1e-3)
    assert values["V_inf"] == pytest.approx(0.8 * 295.0695, rel=1e-5)
    assert values["q_inf"] == pytest.approx(0.5 * values["rho_inf"] * values["V_inf"] ** 2)


def test_reference_size_from_the_settings_else_the_template():
    project = _project()
    assert (study_constants(project, project.cases[0], TEMPLATE)["S_ref"],
            study_constants(project, project.cases[0], TEMPLATE)["L_ref"]) == (16.2, 1.9)
    project.settings.reference.ref_area = 20.0
    assert study_constants(project, project.cases[0], TEMPLATE)["S_ref"] == 20.0
    assert study_constants(project, project.cases[0], "AOA= 0\n")["L_ref"] == Missing(
        "no reference length (REF_LENGTH)")


def test_manual_freestream_has_no_isa_values():
    project = _project(mode="manual")
    values = study_constants(project, project.cases[0], TEMPLATE)
    assert values["q_inf"] == Missing("q_inf needs the freestream from altitude")
    assert values["S_ref"] == 16.2


def test_a_bad_altitude_gives_the_reason():
    project = _project()
    project.cases[0].altitude_km = 120.0
    assert "outside the standard atmosphere" in study_constants(project, project.cases[0], TEMPLATE)["rho_inf"].reason

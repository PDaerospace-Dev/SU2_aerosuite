from aerosuite.engine.cfg import build_cases
from aerosuite.engine.models import Project
from aerosuite.web.calculators.isa_rules import SWEEP_REASON, isa_prefill, plan_isa_apply

TEMPLATE = "MACH_NUMBER= 0.3\nREYNOLDS_NUMBER= 1e6\n"


def _sweep(profile=None) -> Project:
    project = Project(name="p", profile=profile)
    project.sweep.mach, project.sweep.alpha, project.sweep.beta = [0.6, 0.8], [0.0], [0.0]
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    return project


def test_prefill_outside_a_project():
    assert isa_prefill(None, "") == (0.0, 0.8, 1.0, "")


def test_prefill_from_a_sweep_project():
    project = _sweep()
    project.settings.freestream.mode, project.settings.freestream.altitude_km = "altitude", 11.0
    project.settings.freestream.reynolds_length = 6.0
    prefill = isa_prefill(project, TEMPLATE)
    assert (prefill.altitude_km, prefill.mach, prefill.length_m) == (11.0, 0.8, 6.0)
    assert "Mach 0.8 (the sweep's highest)" in prefill.note


def test_prefill_single_case_uses_the_template_mach():
    project = _sweep()
    project.sweep.enabled = False
    assert isa_prefill(project, TEMPLATE).mach == 0.3


def test_plan_for_an_aircraft_project_lists_changes_and_renames():
    plan = plan_isa_apply(_sweep(profile="x07"), TEMPLATE, 11.0, 0.8, 6.0)
    assert plan.kind == "aircraft"
    assert plan.changes[:3] == [("Freestream", "Set by hand", "From altitude"), ("Altitude", "—", "11 km"),
                                ("Reynolds length", "—", "6 m")]
    assert plan.changes[3] == ("Altitude label (case names)", "sl", "11km")
    assert plan.note == "Renames 2 cases"


def test_plan_for_a_general_single_case_writes_template_lines_at_the_templates_mach():
    project = _sweep()
    project.sweep.enabled = False
    plan = plan_isa_apply(project, TEMPLATE, 11.0, 0.8, 6.0)
    assert plan.kind == "template"
    assert plan.template_params == {"FREESTREAM_TEMPERATURE": "216.65", "REYNOLDS_NUMBER": "13596896",
                                    "REYNOLDS_LENGTH": "6"}
    assert ("REYNOLDS_NUMBER", "1e6", "13596896") in plan.changes
    assert ("FREESTREAM_TEMPERATURE", "—", "216.65") in plan.changes
    assert plan.note == "The Reynolds number is computed for Mach 0.3 (the template's), not 0.8"


def test_plan_is_blocked_for_a_general_sweep_and_a_template_without_mach():
    assert plan_isa_apply(_sweep(), TEMPLATE, 11.0, 0.8, 6.0).reason == SWEEP_REASON
    project = _sweep()
    project.sweep.enabled = False
    blocked = plan_isa_apply(project, "AOA= 0\n", 11.0, 0.8, 6.0)
    assert blocked.kind == "blocked" and "MACH_NUMBER" in blocked.reason
    assert plan_isa_apply(project, None, 11.0, 0.8, 6.0).kind == "blocked"

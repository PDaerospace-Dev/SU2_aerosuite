"""The Aircraft Config tab's edits: each changed line goes back to the template or to the layer that writes it."""
import pytest

from aerosuite.engine.cfg import build_cases, render_case
from aerosuite.engine.config_edit import apply_changes, split_edit
from aerosuite.engine.models import Project

TEMPLATE = """% wing study
SOLVER= RANS
MACH_NUMBER= 0.5
REF_AREA= 1.0
% numerics
CFL_NUMBER= 1.0
MARKER_EULER= ( wall )
CONV_FILENAME= history
"""


def _project(**overrides) -> Project:
    project = Project(name="p")
    project.sweep.mach = [0.8]
    project.sweep.alpha = [2.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.settings.reference.ref_area = 10.0  # the form writes over the template's 1.0
    project.settings.numerics.iter = 500  # not in the template: appended
    project.settings.overrides.update(overrides)
    project.cases = build_cases(project)
    return project


def _shown(project, template=TEMPLATE):
    return render_case(template, project, project.cases[0])


def _edit(project, change, template=TEMPLATE):
    shown = _shown(project, template)
    return split_edit(template, project, project.cases[0], change(shown))


def test_an_unchanged_config_changes_nothing():
    project = _project(CONV_FILENAME=None)  # a placeholder that removes a template line
    edit = _edit(project, lambda text: text)
    assert edit.template == TEMPLATE and not edit.changes and not edit.notes


@pytest.mark.parametrize("change, expected", [
    (lambda t: t.replace("SOLVER= RANS", "SOLVER= EULER"), TEMPLATE.replace("SOLVER= RANS", "SOLVER= EULER")),
    (lambda t: t.replace("% numerics\n", "% numerics, tuned\n"), TEMPLATE.replace("% numerics\n", "% numerics, tuned\n")),
    (lambda t: t.replace("CFL_NUMBER= 1.0\n", "CFL_NUMBER= 1.0\nCFL_ADAPT= YES\n"),
     TEMPLATE.replace("CFL_NUMBER= 1.0\n", "CFL_NUMBER= 1.0\nCFL_ADAPT= YES\n")),  # in place, not at the end
    (lambda t: t.replace("MARKER_EULER= ( wall )\n", ""), TEMPLATE.replace("MARKER_EULER= ( wall )\n", "")),
])
def test_template_lines_change_in_the_template_in_place(change, expected):
    edit = _edit(_project(), change)
    assert edit.template == expected and not edit.changes and not edit.notes


def test_a_line_the_form_writes_changes_the_form_not_the_template():
    project = _project()
    edit = _edit(project, lambda t: t.replace("REF_AREA= 10", "REF_AREA= 12.5").replace("ITER= 500", "ITER= 900"))
    assert edit.template == TEMPLATE  # its REF_AREA= 1.0 stays, and no ITER line is added to it
    assert edit.changes == {"REF_AREA": "12.5", "ITER": "900"}
    done, notes = apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert (project.settings.reference.ref_area, project.settings.numerics.iter) == (12.5, 900)
    assert done == ["REF_AREA (Reference)", "ITER (Numerics)"] and not notes


def test_a_removed_form_line_stays_with_a_note():
    edit = _edit(_project(), lambda t: t.replace("REF_AREA= 10\n", ""))
    assert edit.template == TEMPLATE and not edit.changes
    assert edit.notes == ["REF_AREA is set by the form (Reference): clear it there to use the template's value"]


def test_placeholders_change_where_they_are_set():
    project = _project(CFL_NUMBER="5", CONV_FILENAME=None)
    edit = _edit(project, lambda t: t.replace("CFL_NUMBER= 5", "CFL_NUMBER= 8") + "CONV_FILENAME= conv\n")
    assert edit.template == TEMPLATE and edit.changes == {"CFL_NUMBER": "8", "CONV_FILENAME": "conv"}
    done, _ = apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert project.settings.overrides == {"CFL_NUMBER": "8", "CONV_FILENAME": "conv"}
    assert done == ["CFL_NUMBER (Placeholders)", "CONV_FILENAME (Placeholders)"]


def test_per_case_lines_are_refused_with_where_to_change_them():
    project = _project()
    edit = _edit(project, lambda t: t.replace("MACH_NUMBER= 0.8", "MACH_NUMBER= 0.9"))
    assert edit.template == TEMPLATE and edit.changes == {"MACH_NUMBER": "0.9"}
    done, notes = apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert not done and notes == ["MACH_NUMBER is set per case by the sweep: change Mach on the Sweep page"]


def test_the_freestream_from_the_altitude_is_refused_but_its_length_is_the_forms():
    project = _project()
    project.settings.freestream.mode = "altitude"
    project.settings.freestream.reynolds_length = 1.0
    project.sweep.altitudes_km = [0.0]
    project.cases = build_cases(project)
    edit = _edit(project, lambda t: t.replace("FREESTREAM_PRESSURE= 101325", "FREESTREAM_PRESSURE= 9")
                 .replace("REYNOLDS_LENGTH= 1", "REYNOLDS_LENGTH= 4.2"))
    done, notes = apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert done == ["REYNOLDS_LENGTH (Freestream)"] and project.settings.freestream.reynolds_length == 4.2
    assert notes == ["FREESTREAM_PRESSURE comes from the altitude: change the altitude or the Mach, or set the "
                     "freestream by hand on the Freestream card"]


def test_a_value_that_is_not_a_number_is_refused():
    project = _project()
    edit = _edit(project, lambda t: t.replace("ITER= 500", "ITER= lots"))
    done, notes = apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert not done and notes == ["ITER: 'lots' is not an integer"] and project.settings.numerics.iter == 500


def test_a_single_case_edits_its_own_mach_in_the_template():
    project = _project()
    project.sweep.enabled = False
    project.cases = build_cases(project, TEMPLATE)
    edit = _edit(project, lambda t: t.replace("MACH_NUMBER= 0.5", "MACH_NUMBER= 1.2"))
    assert edit.template == TEMPLATE.replace("MACH_NUMBER= 0.5", "MACH_NUMBER= 1.2") and not edit.changes


def test_what_is_saved_renders_back_to_what_was_typed():
    project = _project(CFL_NUMBER="5")
    shown = _shown(project)
    typed = (shown.replace("SOLVER= RANS", "SOLVER= EULER").replace("REF_AREA= 10", "REF_AREA= 11")
             .replace("CFL_NUMBER= 5", "CFL_NUMBER= 6").replace("% wing study\n", "% wing study\nMGLEVEL= 2\n"))
    edit = split_edit(TEMPLATE, project, project.cases[0], typed)
    apply_changes(project, project.cases[0], TEMPLATE, edit.changes)
    assert render_case(edit.template, project, project.cases[0]) == typed


def test_trailing_blank_lines_and_a_repeated_key_survive_an_unchanged_save():
    template = TEMPLATE.replace("SOLVER= RANS\n", "SOLVER= RANS\nREF_AREA= 2.0\n") + "\n\n"
    edit = _edit(_project(), lambda text: text, template)
    assert edit.template == template and not edit.changes and not edit.notes


def test_a_line_typed_after_the_written_over_lines_goes_to_the_end_of_the_template():
    edit = _edit(_project(), lambda t: t + "OUTPUT_FILES= RESTART\n")
    assert edit.template == TEMPLATE + "OUTPUT_FILES= RESTART\n" and not edit.changes

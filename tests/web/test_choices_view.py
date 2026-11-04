"""The Sweep page's "Your choices" without NiceGUI: the values, which the project changes from the template and which
differ from what the cases last ran with."""
from aerosuite.engine.models import Case, Project
from aerosuite.web.choices_view import last_run_options, folded_line, project_choices

TEMPLATE = """\
SOLVER= RANS
KIND_TURB_MODEL= SST
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
CFL_NUMBER= 1.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.5, 1.05, 1.0, 50 )
ITER= 800
REF_LENGTH= 2.49
REF_AREA= 12
"""


def _project():
    project = Project(name="study")
    project.cases = [Case(name=f"M0p3_a{a}", mach=0.3, alpha=float(a), beta=0.0, restart="previous" if a else "none")
                     for a in (0, 5, 10)]
    return project


def _by_key(choices):
    return {choice.key: choice for choice in choices}


def test_the_template_values_stand_until_the_project_changes_them():
    project = _project()
    choices = _by_key(project_choices(project, TEMPLATE))
    assert choices["solver"].value == "RANS · SST"
    assert choices["scheme"].value == "ROE · 2nd order" and not choices["scheme"].own
    assert choices["cfl"].value == "1.0 · adaptive" and choices["cfl"].detail == "adapt ( 0.5, 1.05, 1.0, 50 )"
    assert choices["iterations"].value == "800 per case"
    assert [choice.key for choice in project_choices(project, TEMPLATE)] == [
        "mesh", "solver", "scheme", "cfl", "iterations", "freestream", "reference", "hand-set"]
    assert choices["hand-set"].value == "none"
    project.settings.numerics.muscl = "NO"
    project.settings.numerics.cfl = 1.0  # the template's value written another way: not a change
    choices = _by_key(project_choices(project, TEMPLATE))
    assert choices["scheme"].value == "ROE · 1st order" and choices["scheme"].own
    assert not choices["cfl"].own


def test_a_choice_that_differs_from_the_last_run_says_what_the_cases_ran_with():
    project = _project()
    last = {"ITER": {"600"}, "MUSCL_FLOW": {"YES"}, "CFL_NUMBER": {"1", "2"}}
    choices = _by_key(project_choices(project, TEMPLATE, last))
    assert choices["iterations"].last_run == "ITER= 600"
    assert choices["scheme"].last_run == ""  # ran with the same
    assert choices["cfl"].last_run == "CFL_NUMBER= 1 / 2"  # some cases ran with another


def test_the_last_run_is_read_from_each_case_folder(tmp_path):
    project = _project()
    for name, iters in (("M0p3_a0", 600), ("M0p3_a5", 800)):  # M0p3_a10 never ran
        folder = tmp_path / "runs" / name
        folder.mkdir(parents=True)
        (folder / f"{name}.cfg").write_text(f"ITER= {iters}\nMUSCL_FLOW= NO  % first order\n")
    assert last_run_options(tmp_path, project.cases, ("ITER", "MUSCL_FLOW", "CFL_NUMBER")) == {
        "ITER": {"600", "800"}, "MUSCL_FLOW": {"NO"}}


def test_the_folded_line():
    assert folded_line(project_choices(_project(), TEMPLATE)) == (
        "RANS · SST · ROE · 2nd order · CFL 1.0 · adaptive · 800 iterations · Set by hand")

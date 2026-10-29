"""Each case's config through SU2's dry run before it runs (a fake SU2_CFD here; one test with the real one)."""
from pathlib import Path

import pytest

from aerosuite.engine.preflight import preflight
from aerosuite.engine.settings import AppSettings, set_value
from aerosuite.engine.su2_check import check_cases, dry_run, su2_message

BAD = "CFL_ADAPT= YES\nCFL_ADAPT_PARAM= ( 1.5, 0.5, 25.0, 100000.0 )\n"
SU2_OUTPUT = """
Error in "void CConfig::SetPostprocessing(SU2_COMPONENT, short unsigned int, short unsigned int)":
-------------------------------------------------------------------------
CFL adaption factor down should be less than 1.0.
------------------------------ Error Exit -------------------------------
"""


def _bad_template(project_dir):
    path = project_dir / "template.cfg"
    path.write_text(path.read_text() + BAD)
    return path.read_text().splitlines().index("CFL_ADAPT_PARAM= ( 1.5, 0.5, 25.0, 100000.0 )") + 1


def test_su2s_message_is_one_line():
    assert su2_message(SU2_OUTPUT) == "CFL adaption factor down should be less than 1.0."
    assert su2_message("Line 257 BOGUS: invalid option name.\n") == "Line 257 BOGUS: invalid option name."


def test_every_case_is_checked_and_one_message_names_the_template_line(ready_project, fake_su2):
    project_dir, project = ready_project
    line = _bad_template(project_dir)
    problems = check_cases(project_dir, project, None, AppSettings(), run=True)
    assert [(p.severity, p.message) for p in problems] == [(
        "error", f"{project.cases[0].name} and 2 more cases: SU2 rejects the config: CFL adaption factor down "
                 f"should be less than 1.0. (CFL_ADAPT_PARAM, template line {line})")]
    assert fake_su2() == 3


def test_an_unchanged_config_is_not_checked_again(ready_project, fake_su2):
    project_dir, project = ready_project
    assert check_cases(project_dir, project, None, AppSettings(), run=True) == []
    assert check_cases(project_dir, project, None, AppSettings(), run=True) == []
    assert fake_su2() == 3  # cached


def test_the_configs_are_rendered_once_until_something_changes(ready_project, fake_su2, monkeypatch):
    from aerosuite.engine import su2_check

    project_dir, project = ready_project
    rendered = []
    real = su2_check.render_case
    monkeypatch.setattr(su2_check, "render_case", lambda *args: rendered.append(1) or real(*args))
    for _ in range(3):  # the Run and Sweep pages ask on every drawing
        check_cases(project_dir, project, None, AppSettings(), run=False)
    assert len(rendered) == 3
    template = project_dir / "template.cfg"
    template.write_text(template.read_text() + "% changed\n")  # the template changed: rendered again
    for _ in range(2):
        check_cases(project_dir, project, None, AppSettings(), run=False)
    assert len(rendered) == 6


def test_without_running_only_known_verdicts_are_reported(ready_project, fake_su2):
    project_dir, project = ready_project
    _bad_template(project_dir)
    assert check_cases(project_dir, project, None, AppSettings(), run=False) == []
    assert fake_su2() == 0
    check_cases(project_dir, project, None, AppSettings(), run=True)
    assert check_cases(project_dir, project, None, AppSettings(), run=False)[0].severity == "error"


def test_submit_and_generate_run_it_and_stop_on_an_error(ready_project, fake_su2):
    project_dir, project = ready_project
    _bad_template(project_dir)
    for action in ("generate", "submit"):
        errors = [p.message for p in preflight(project_dir, project, action, check_su2=True) if p.severity == "error"]
        assert any("SU2 rejects the config" in e for e in errors), action


def test_the_setting_turns_it_off(ready_project, fake_su2):
    project_dir, project = ready_project
    _bad_template(project_dir)
    settings = set_value(AppSettings(), "check_with_su2", "false")
    assert check_cases(project_dir, project, None, settings, run=True) == [] and fake_su2() == 0


def test_a_missing_su2_is_a_warning_not_an_error(ready_project, fake_su2, monkeypatch, tmp_path):
    project_dir, project = ready_project
    monkeypatch.setenv("AEROSUITE_SU2_CFD", str(tmp_path / "nowhere" / "SU2_CFD"))
    problems = check_cases(project_dir, project, None, AppSettings(), run=True)
    assert [p.severity for p in problems] == ["warning"] and "were not checked with SU2" in problems[0].message


@pytest.mark.skipif(not Path("/opt/su2/bin/SU2_CFD").is_file(), reason="needs SU2 in /opt/su2/bin")
def test_the_real_su2_rejects_the_swapped_cfl_parameters():
    su2 = Path("/opt/su2/bin/SU2_CFD")
    text = "SOLVER= EULER\nMACH_NUMBER= 0.8\nMESH_FILENAME= missing.su2\n" + BAD
    result = dry_run(text, su2)
    assert not result.ok and "factor down should be less than 1.0" in result.message

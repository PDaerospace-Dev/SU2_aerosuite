import pytest

from aerosuite.engine.errors import TemplateError
from aerosuite.engine.project import (
    TEMPLATE_FILE,
    create_project,
    read_template_text,
    set_template_text,
    template_warnings,
)


def test_template_warnings():
    text = "% comment\n\nSOLVER= RANS\nnot an option\nAOA= 1\nAOA= 2\n"
    assert template_warnings(text) == [
        'Line 4 is not an option or a comment: "not an option"',
        "AOA is set on lines 5 and 6; both will be changed together",
    ]
    assert template_warnings("A= 1\nA= 2\nA= 3\n") == [
        "A is set on lines 1, 2 and 3; all will be changed together"
    ]
    assert template_warnings("SOLVER= EULER\n") == []


def test_set_and_read_template_text(tmp_path):
    project = create_project(tmp_path)
    warnings = set_template_text(tmp_path, project, "SOLVER= RANS\nbroken\n")
    assert (tmp_path / TEMPLATE_FILE).read_text() == "SOLVER= RANS\nbroken\n"
    assert project.template == TEMPLATE_FILE
    assert warnings == ['Line 2 is not an option or a comment: "broken"']
    assert read_template_text(tmp_path, project) == "SOLVER= RANS\nbroken\n"


def test_read_missing_template(tmp_path):
    project = create_project(tmp_path)
    with pytest.raises(TemplateError):
        read_template_text(tmp_path, project)


def test_preflight_lists_template_warnings(ready_project):
    from aerosuite.engine.preflight import has_errors, preflight

    project_dir, project = ready_project
    (project_dir / TEMPLATE_FILE).write_text("MACH_NUMBER= 0.3\nAOA= 1\nAOA= 2\n")
    found = preflight(project_dir, project, "generate")
    assert any(p.severity == "warning" and "AOA is set on lines 2 and 3" in p.message for p in found)
    assert not has_errors(found)


def test_set_template_text_reports_os_errors(tmp_path):
    project = create_project(tmp_path / "p")
    (tmp_path / "p" / TEMPLATE_FILE).mkdir()  # a folder where the file should go
    with pytest.raises(TemplateError, match="Cannot write"):
        set_template_text(tmp_path / "p", project, "A= 1\n")


def test_edited_text_is_saved_under_the_templates_own_name(tmp_path):
    project = create_project(tmp_path)
    project.template = "x07_base.cfg"
    set_template_text(tmp_path, project, "SOLVER= RANS\n")
    assert (tmp_path / "x07_base.cfg").read_text() == "SOLVER= RANS\n"
    assert project.template == "x07_base.cfg"
    assert not (tmp_path / TEMPLATE_FILE).exists()

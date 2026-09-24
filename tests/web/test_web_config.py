import json

from nicegui.testing import User

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.project import TEMPLATE_FILE, open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _single(project_dir):
    project = open_project(project_dir)
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)


async def _open(user, project_dir):
    await user.open(project_url("config", project_dir))


async def test_editor_shows_and_saves_the_template(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    editor = _element(user, "config-text")
    assert editor.value.startswith("MACH_NUMBER= 0.3")
    user.find(marker="config-text").type("CFL_NUMBER= 5\n").trigger("blur")
    assert (project_dir / TEMPLATE_FILE).read_text().endswith("CFL_NUMBER= 5\n")


async def test_warnings_are_shown_but_do_not_block(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="config-text").type("oops\nAOA= 5\n").trigger("blur")
    await user.should_see("is not an option or a comment")
    await user.should_see("AOA is set on lines")
    assert "oops" in (project_dir / TEMPLATE_FILE).read_text()


async def test_insert_from_the_reference(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="ref-search").type("marker_euler")
    user.find(marker="ref-insert-MARKER_EULER").click()
    text = (project_dir / TEMPLATE_FILE).read_text()
    assert text.endswith("% --- added from reference ---\nMARKER_EULER= ( airfoil )\n")
    await user.should_see(marker="ref-in-config-MARKER_EULER")
    user.find(marker="ref-search").clear().type("marker_sym")
    user.find(marker="ref-insert-MARKER_SYM").click()
    text = (project_dir / TEMPLATE_FILE).read_text()
    assert text.count("% --- added from reference ---") == 1
    assert text.endswith("MARKER_EULER= ( airfoil )\nMARKER_SYM= ( NONE )\n")


async def test_insert_of_an_option_already_typed(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="ref-search").type("marker_euler")
    user.find(marker="config-text").type("MARKER_EULER= ( wing )\n")  # typed, not yet saved
    user.find(marker="ref-insert-MARKER_EULER").click()
    await user.should_see("MARKER_EULER is already set on line")


async def test_preview_of_a_sweep_case(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="preview")
    toggle = _element(user, "preview-toggle")
    with user:
        toggle.set_value(True)
    assert "MACH_NUMBER= 0.8" in _element(user, "preview").content
    await user.should_not_see(marker="config-checks")  # sweep on: Generate lives on the Sweep page


async def test_single_case_preview_checks_and_generate(user: User, ready_project):
    project_dir, _ = ready_project
    _single(project_dir)
    await _open(user, project_dir)
    toggle = _element(user, "preview-toggle")
    with user:
        toggle.set_value(True)
    content = _element(user, "preview").content
    assert "MACH_NUMBER= 0.3" in content and "BREAKDOWN_FILENAME" not in content
    await user.should_see(marker="config-checks")
    user.find(marker="generate").click()
    await user.should_see("Wrote 1 config")
    index = json.loads((project_dir / "configs" / "cases.json").read_text())
    assert index == {"study": {"mach": 0.3, "alpha": 0.0, "beta": 0.0}}

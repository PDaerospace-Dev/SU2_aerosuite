import asyncio
import json

from nicegui.testing import User

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.project import TEMPLATE_FILE, open_project, save_project
from aerosuite.web import layout
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


async def test_editor_has_a_fixed_scrolling_height(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    editor = _element(user, "config-text")
    assert "autogrow" not in editor.props
    assert editor.props.get("input-style") == "height: 70vh"


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


async def test_an_outside_project_json_change_does_not_drop_unsaved_editor_text(
        user: User, ready_project, monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, project = ready_project
    await _open(user, project_dir)
    user.find(marker="config-text").type("CFL_NUMBER= 5\n")  # not yet blurred

    other = open_project(project_dir)
    other.name = "renamed-elsewhere"
    save_project(project_dir, other)
    await asyncio.sleep(0.5)  # the watcher notices and reloads project.json
    await user.should_see("Project changed on disk; reloaded")

    editor = _element(user, "config-text")
    assert editor.value.endswith("CFL_NUMBER= 5\n")  # the typed text survived the reload
    assert "CFL_NUMBER= 5" not in (project_dir / TEMPLATE_FILE).read_text()  # not yet saved

    user.find(marker="config-text").trigger("blur")
    assert (project_dir / TEMPLATE_FILE).read_text().endswith("CFL_NUMBER= 5\n")
    assert _element(user, "config-text").value.endswith("CFL_NUMBER= 5\n")


async def test_non_utf8_template_shows_an_error_and_a_read_only_editor(user: User, ready_project):
    project_dir, _ = ready_project
    (project_dir / TEMPLATE_FILE).write_bytes(b"% Latin-1 degree sign \xb0\nAOA= 0.0\n")
    await _open(user, project_dir)
    await user.should_see("not UTF-8 text")
    editor = _element(user, "config-text")
    assert editor.value == ""
    assert editor.props.get("readonly") is True
    before = (project_dir / TEMPLATE_FILE).read_bytes()
    user.find(marker="config-text").type("MACH_NUMBER= 0.5\n").trigger("blur")
    assert (project_dir / TEMPLATE_FILE).read_bytes() == before  # the real content is not overwritten


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

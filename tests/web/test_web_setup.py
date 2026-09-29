import sys

from nicegui.testing import User

from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


async def _open(user, project_dir):
    await user.open(project_url("setup", project_dir))


async def test_shows_mesh_and_template(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="mesh-marker-farfield")
    await user.should_see(marker="mesh-marker-wall")
    await user.should_see("(copied into the project)")


async def test_a_chosen_mesh_and_template_are_highlighted(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert "as-selected" in _element(user, "mesh-status").classes
    assert _element(user, "mesh-name").text == "wing.su2"
    assert "as-selected" in _element(user, "template-status-box").classes


async def test_missing_mesh_and_template_are_not_highlighted(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    project = open_project(project_dir)
    project.mesh.path = str(tmp_path / "gone.su2")
    save_project(project_dir, project)
    (project_dir / "template.cfg").unlink()
    await _open(user, project_dir)
    assert "as-selected-missing" in _element(user, "mesh-status").classes
    await user.should_see("File not found")
    assert "as-selected-empty" in _element(user, "template-status-box").classes
    await user.should_see("No template yet")


async def test_no_mesh_at_all(user: User, ready_project):
    project_dir, _ = ready_project
    project = open_project(project_dir)
    project.mesh.path, project.mesh.markers = "", []
    save_project(project_dir, project)
    await _open(user, project_dir)
    assert "as-selected-empty" in _element(user, "mesh-status").classes
    await user.should_see("No mesh selected")


async def test_set_mesh_by_pasting(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    mesh = tmp_path / "wing2.su2"
    mesh.write_text("MARKER_TAG= skin\n")
    await _open(user, project_dir)
    user.find(marker="mesh-input").type(str(mesh))
    user.find(marker="mesh-set").click()
    await user.should_see(marker="mesh-marker-skin")
    assert _element(user, "mesh-name").text == "wing2.su2"
    assert open_project(project_dir).mesh.markers == ["skin"]


async def test_bad_mesh_path_is_reported(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="mesh-input").type(str(tmp_path / "gone.su2"))
    user.find(marker="mesh-set").click()
    await user.should_see("Mesh not found")
    assert open_project(project_dir).mesh.markers == ["farfield", "wall"]


async def test_set_template_with_the_picker(user: User, ready_project, tmp_path, eventually):
    project_dir, _ = ready_project
    (tmp_path / "master2.cfg").write_text("AOA= 7\n")
    await _open(user, project_dir)
    user.find(marker="template-browse").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-master2.cfg").click()
    copy = project_dir / "master2.cfg"
    await eventually(lambda: copy.is_file() and copy.read_text() == "AOA= 7\n")
    await user.should_see("(copied into the project)")
    await user.should_see("master2.cfg")  # shown under its own name
    assert not (project_dir / "template.cfg").exists()  # the old copy is gone


async def test_partitions_autosave_and_errors(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="partitions").clear().type("64").trigger("blur")
    assert open_project(project_dir).run.partitions == 64
    user.find(marker="partitions").clear().type("0").trigger("blur")
    await user.should_see("greater than or equal to 1")
    user.find(marker="partitions").clear().type("abc").trigger("blur")
    await user.should_see("not a whole number")
    assert open_project(project_dir).run.partitions == 64


async def test_sweep_python_warns_about_aerosuites_own_python(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-python").clear().type(sys.executable).trigger("blur")
    await user.should_see("AeroSuite's own Python")
    assert open_project(project_dir).run.sweep_python == sys.executable


async def test_sweep_script_blank_means_bundled(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-script").clear().trigger("blur")
    await user.should_see("bundled aoa_sweep_v8.py")
    assert open_project(project_dir).run.sweep_script == ""


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_setup_shows_the_project_card(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "setup-project-name").text == "study"
    assert _element(user, "setup-folder").text == str(project_dir)
    assert "as-mono" in _element(user, "setup-folder").classes


async def test_mono_fields_keep_their_label_in_the_body_font(user: User, ready_project):
    # Only the typed path is monospace: the generic as-mono class on the field would change its label too.
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    classes = _element(user, "mesh-input").classes
    assert "as-field-mono" in classes and "as-mono" not in classes


def _inside(element, container) -> bool:
    while element is not None:
        if element is container:
            return True
        element = element.parent_slot.parent if element.parent_slot else None
    return False


async def test_partitions_come_first_and_the_rest_is_advanced(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    project = open_project(project_dir)
    project.run.sweep_python = str(tmp_path / "python3")  # not AeroSuite's own: no warning
    save_project(project_dir, project)
    await _open(user, project_dir)
    advanced = _element(user, "run-advanced")
    assert advanced.value is False  # closed: rarely changed
    assert _inside(_element(user, "sweep-python"), advanced)
    assert _inside(_element(user, "sweep-script"), advanced)
    assert not _inside(_element(user, "partitions"), advanced)
    card = _element(user, "run-settings")
    order = [child for child in card.descendants() if child in (_element(user, "partitions"), advanced)]
    assert order == [_element(user, "partitions"), advanced]


async def test_advanced_opens_by_itself_when_the_sweep_python_looks_wrong(user: User, ready_project):
    project_dir, _ = ready_project  # the fixture's sweep Python is AeroSuite's own
    await _open(user, project_dir)
    assert _element(user, "run-advanced").value is True
    await user.should_see("AeroSuite's own Python")

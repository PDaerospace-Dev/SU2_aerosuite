import sys

from nicegui.testing import User

from aerosuite.engine.project import open_project
from aerosuite.web.layout import project_url


async def _open(user, project_dir):
    await user.open(project_url("setup", project_dir))


async def test_shows_mesh_and_template(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see("Markers: farfield, wall")
    await user.should_see("template.cfg (copied into the project)")


async def test_set_mesh_by_pasting(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    mesh = tmp_path / "wing2.su2"
    mesh.write_text("MARKER_TAG= skin\n")
    await _open(user, project_dir)
    user.find(marker="mesh-input").type(str(mesh))
    user.find(marker="mesh-set").click()
    await user.should_see("Markers: skin")
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
    await eventually(lambda: (project_dir / "template.cfg").read_text() == "AOA= 7\n")
    await user.should_see("template.cfg (copied into the project)")


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

import asyncio

from nicegui.testing import User

from aerosuite.engine.project import PROJECT_FILE, open_project, save_project
from aerosuite.web import layout


async def test_frame_shows_project_and_badges(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(layout.project_url("setup", project_dir))
    await user.should_see("study")
    await user.should_see(marker="badge-setup-done")
    await user.should_see(marker="badge-sweep-done")
    await user.should_see(marker="badge-configs-todo")
    await user.should_see(marker="badge-run-todo")


async def test_non_utf8_template_does_not_lock_the_project_pages_out(user: User, ready_project):
    project_dir, _ = ready_project
    (project_dir / "template.cfg").write_bytes(b"% Latin-1 degree sign \xb0\nAOA= 0.0\n")
    await user.open(layout.project_url("setup", project_dir))
    await user.should_see("study")
    await user.should_see(marker="badge-config-attention")


async def test_missing_and_bad_project_parameter(user: User, tmp_path):
    await user.open("/setup")
    await user.should_see("No project selected.")
    await user.open(layout.project_url("setup", tmp_path / "nowhere"))
    await user.should_see("Error: No project found")


async def test_outside_changes_reload_the_page(user: User, ready_project, monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, _ = ready_project
    await user.open(layout.project_url("setup", project_dir))
    other = open_project(project_dir)
    other.name = "renamed-elsewhere"
    save_project(project_dir, other)
    await asyncio.sleep(0.5)
    await user.should_see("Project changed on disk; reloaded")
    await user.should_see("renamed-elsewhere")


async def test_an_invalid_file_on_disk_blocks_saving_until_fixed(user: User, ready_project, monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, project = ready_project
    await user.open(layout.project_url("setup", project_dir))
    await user.should_see(marker="partitions")
    hand_edit = '{"name": "half-typed", '
    (project_dir / PROJECT_FILE).write_text(hand_edit)
    await asyncio.sleep(0.5)  # the watcher tries to reload and fails
    await user.should_see("Could not reload the project")

    user.find(marker="partitions").clear().type("5").trigger("blur")
    await user.should_see("project.json on disk is invalid")
    assert (project_dir / PROJECT_FILE).read_text() == hand_edit

    project.name = "fixed-by-hand"
    save_project(project_dir, project)
    await asyncio.sleep(0.5)  # the watcher keeps polling and now reloads
    await user.should_see("Project changed on disk; reloaded")
    await user.should_see("fixed-by-hand")
    user.find(marker="partitions").clear().type("5").trigger("blur")
    assert open_project(project_dir).run.partitions == 5

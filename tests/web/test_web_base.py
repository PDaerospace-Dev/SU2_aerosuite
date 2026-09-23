"""Tests for the shared page frame, autosaving field and file picker (via the /_test/base page)."""
import asyncio
from pathlib import Path

from nicegui.testing import User

from aerosuite.engine.project import PROJECT_FILE, open_project, save_project
from aerosuite.web import layout


def _url(project_dir: Path) -> str:
    return layout.project_url("_test/base", project_dir)


async def test_commit_on_blur(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    field = user.find(marker="t-partitions")
    field.clear().type("5")
    field.trigger("blur")
    assert open_project(project_dir).run.partitions == 5


async def test_commit_on_enter(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    field = user.find(marker="t-partitions")
    field.clear().type("7")
    field.trigger("keydown.enter")
    assert open_project(project_dir).run.partitions == 7


async def test_unchanged_text_is_not_resaved(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    before = (project_dir / PROJECT_FILE).stat().st_mtime_ns
    user.find(marker="t-partitions").trigger("blur")  # same value ("1") the field already had
    after = (project_dir / PROJECT_FILE).stat().st_mtime_ns
    assert before == after


async def test_invalid_value_shows_error_and_saves_nothing(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    field = user.find(marker="t-partitions")
    field.clear().type("abc")
    field.trigger("blur")
    await user.should_see("is not a whole number")
    assert open_project(project_dir).run.partitions == 1


async def test_retry_after_fixing_an_invalid_value_saves(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    field = user.find(marker="t-partitions")
    field.clear().type("abc")
    field.trigger("blur")
    await user.should_see("is not a whole number")
    field.clear().type("5")
    field.trigger("blur")
    await user.should_not_see("is not a whole number")
    assert open_project(project_dir).run.partitions == 5


async def test_stale_save_is_refused(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    await user.should_see(marker="t-partitions")
    other = open_project(project_dir)
    other.run.partitions = 9
    save_project(project_dir, other)  # an outside change, made after the page opened its session
    field = user.find(marker="t-partitions")
    field.clear().type("5")
    field.trigger("blur")
    await user.should_see("enter your change again")
    # the outside change (9) survives on disk; the user's own "5" was never written
    assert open_project(project_dir).run.partitions == 9


async def test_picker_lists_only_matching_files(user: User, ready_project):
    project_dir, _ = ready_project
    (project_dir.parent / "a.cfg").write_text("")
    (project_dir.parent / "notes.txt").write_text("")
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-location")
    await user.should_see(marker="picker-entry-a.cfg")
    await user.should_not_see(marker="picker-entry-notes.txt")
    user.find(marker="picker-cancel").click()
    await asyncio.sleep(0.05)


async def test_picker_click_entry_selects_it(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    cfg = project_dir.parent / "a.cfg"
    cfg.write_text("")
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-entry-a.cfg")
    user.find(marker="picker-entry-a.cfg").click()
    label = next(iter(user.find(marker="t-script").elements))
    await eventually(lambda: label.text == str(cfg))
    assert open_project(project_dir).run.sweep_script == str(cfg)


async def test_picker_paste_matching_path_selects_it(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    cfg = project_dir.parent / "b.cfg"
    cfg.write_text("")
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-path")
    user.find(marker="picker-path").type(str(cfg))
    user.find(marker="picker-use").click()
    label = next(iter(user.find(marker="t-script").elements))
    await eventually(lambda: label.text == str(cfg))
    assert open_project(project_dir).run.sweep_script == str(cfg)


async def test_picker_paste_non_matching_path_shows_error(user: User, ready_project):
    project_dir, _ = ready_project
    original_script = open_project(project_dir).run.sweep_script
    txt = project_dir.parent / "notes.txt"
    txt.write_text("")
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-path")
    user.find(marker="picker-path").type(str(txt))
    user.find(marker="picker-use").click()
    await user.should_see("Not a matching file")
    user.find(marker="picker-cancel").click()
    await asyncio.sleep(0.05)
    assert open_project(project_dir).run.sweep_script == original_script


async def test_picker_up_shows_the_parent_folder(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-entry-study")
    user.find(marker="picker-entry-study").click()  # descend into the project folder
    location = next(iter(user.find(marker="picker-location").elements))
    assert location.text == str(project_dir)
    user.find(marker="picker-up").click()
    assert location.text == str(project_dir.parent)
    user.find(marker="picker-cancel").click()
    await asyncio.sleep(0.05)


async def test_picker_cancel_saves_nothing(user: User, ready_project):
    project_dir, _ = ready_project
    before = open_project(project_dir).run.sweep_script
    await user.open(_url(project_dir))
    user.find(marker="t-browse").click()
    await user.should_see(marker="picker-cancel")
    user.find(marker="picker-cancel").click()
    await asyncio.sleep(0.05)
    assert open_project(project_dir).run.sweep_script == before

from nicegui.testing import User

from aerosuite.engine.editing import set_freestream
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


async def test_preview_shows_an_error_when_altitude_mode_is_invalid(user: User, ready_project):
    project_dir, _ = ready_project
    project = open_project(project_dir)
    set_freestream(project, mode="altitude")  # no altitude yet
    save_project(project_dir, project)
    await user.open(project_url("config", project_dir))
    with user:
        next(iter(user.find(marker="preview-toggle").elements)).set_value(True)
    await user.should_see(marker="preview-error")
    await user.should_see("needs an altitude")

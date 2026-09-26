import json
import re

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.errors import AeroSuiteError
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.project import open_project, save_project
from aerosuite.web import layout
from aerosuite.web.guide import app_version
from aerosuite.web.layout import badge_color, initials, project_url
from aerosuite.web.theme import BADGE_COLORS, TOGGLE_SIDEBAR

A0 = "M0p8_a0_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _shown(user, marker) -> bool:
    """Whether an element with this marker is visible (user.find raises when none is)."""
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


def test_initials_and_badge_colour():
    assert initials("visual-study") == "VS"
    assert initials("study") == "ST"
    assert initials("my big_study") == "MB"
    assert initials("--") == "?"
    assert badge_color("study") == badge_color("study") and badge_color("study") in BADGE_COLORS


async def test_the_switcher_names_the_project(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "project-name").text == "study"
    assert _element(user, "project-kind").text == "sweep · 3 cases"


async def test_the_switcher_menu_goes_to_all_projects(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    _element(user, "project-menu").open()
    user.find(marker="menu-all-projects").click()
    await user.should_see(marker="open-path")


@pytest.mark.parametrize("page, title", [("setup", "Setup"), ("config", "Config"), ("sweep", "Sweep"),
                                         ("run", "Run"), ("monitor", "Monitor")])
async def test_breadcrumbs_name_the_project_and_the_page(user: User, ready_project, page, title):
    project_dir, _ = ready_project
    await user.open(project_url(page, project_dir))
    assert _element(user, "crumb-projects").text == "Projects"
    assert _element(user, "crumb-project").text == "study"
    assert _element(user, "crumb-page").text == title
    assert "as-step-current" in _element(user, f"step-{page}").classes


async def test_long_names_truncate_in_the_frame(user: User, ready_project):
    project_dir, project = ready_project
    project.name = "a-" * 60 + "study"
    save_project(project_dir, project)
    await user.open(project_url("setup", project_dir))
    for marker in ("project-name", "crumb-project"):
        element = _element(user, marker)
        assert element.text == project.name  # the whole name: CSS truncates, not the code
        assert "as-truncate" in element.classes


async def test_the_toggle_collapses_the_sidebar(user: User, ready_project, monkeypatch):
    # A fire-and-forget run_javascript has no request id, so the simulated user's javascript_rules
    # never see it: record what the toggle sends instead.
    project_dir, _ = ready_project
    sent = []
    monkeypatch.setattr(layout.ui, "run_javascript", lambda code, **kwargs: sent.append(code))
    await user.open(project_url("setup", project_dir))
    user.find(marker="sidebar-toggle").click()
    assert sent == [TOGGLE_SIDEBAR]


async def test_help_shows_the_version_and_the_web_ui_guide(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_see(f"AeroSuite {app_version()}", marker="help-version")
    _element(user, "help-menu").open()
    user.find(marker="help-guide").click()
    await eventually(lambda: "Pages:" in _element(user, "guide-text").content)


async def test_the_job_indicator_follows_a_job_started_elsewhere(user: User, ready_project, eventually,
                                                                  monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, project = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_not_see(marker="job-indicator")  # hidden elements are not found
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": {A0: "hang"}}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)  # like the CLI: not through this page
    await eventually(lambda: _shown(user, "job-indicator"), timeout=10)
    await eventually(lambda: re.fullmatch(rf"0 / 3( · {A0})?", _element(user, "job-progress").text), timeout=10)
    runner.cancel(project_dir, runner.refresh(project_dir, job))
    await eventually(lambda: not _shown(user, "job-indicator"), timeout=20)


async def test_a_broken_job_state_hides_the_indicator_and_keeps_the_page(user: User, ready_project, monkeypatch):
    project_dir, _ = ready_project

    def broken(*args, **kwargs):
        raise AeroSuiteError("job record unreadable")

    monkeypatch.setattr(layout, "active_lock", lambda directory: {"pid": 1})
    monkeypatch.setattr(layout.WATCHER, "state", broken)
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="partitions")
    await user.should_not_see(marker="job-indicator")


async def test_the_projects_page_has_the_top_bar_without_a_switcher(user: User):
    await user.open("/")
    await user.should_see("AeroSuite")
    await user.should_see(marker="help")
    await user.should_not_see(marker="project-switcher")

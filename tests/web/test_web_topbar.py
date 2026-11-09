import json

import pytest
from nicegui import ElementFilter
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
    assert _element(user, "project-switcher").props["title"] == "sweep · 3 cases"  # its kind on hover


async def test_the_switcher_menu_goes_to_all_projects(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    _element(user, "project-menu").open()
    user.find(marker="menu-all-projects").click()
    await user.should_see(marker="tab-open")


@pytest.mark.parametrize("page, title", [("setup", "Setup"), ("config", "CFG setup"), ("sweep", "Sweep"),
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


@pytest.mark.parametrize("url", ["/", "/settings", "/tracker", "setup", "aircraft", "run", "monitor", "results"])
async def test_every_page_has_the_search_run_matrix_and_the_menu(user: User, ready_project, url):
    project_dir, _ = ready_project
    await user.open(url if url.startswith("/") else project_url(url, project_dir))
    for marker in ("command-search", "topbar-tracker", "calculators", "app-menu"):
        await user.should_see(marker=marker)
    for gone in ("refresh", "help", "sidebar-tracker", "job-indicator"):  # the old bar's
        await user.should_not_see(marker=gone)


async def test_the_menu_shows_the_version_and_the_web_ui_guide(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    await user.open(project_url("run", project_dir))
    await user.should_see(f"AeroSuite {app_version()}", marker="menu-version")
    _element(user, "app-menu-items").open()
    user.find(marker="menu-guide").click()
    await eventually(lambda: _element(user, "guide-title").text == "Run")  # the page's own section
    assert "job bar" in _element(user, "guide-text").content
    user.find(marker="guide-link-0").click()
    await eventually(lambda: _element(user, "guide-title").text == "Getting started")
    assert "Your first study" in _element(user, "guide-text").content


async def test_the_guide_is_grouped_and_searched(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("run", project_dir))
    _element(user, "app-menu-items").open()
    user.find(marker="menu-guide").click()
    nav = _element(user, "guide-nav")
    groups = [child.text for child in nav.default_slot.children if "as-guide-group" in child.classes]
    assert groups == ["Start here", "Your study, step by step", "More tools", "Reference"]
    links = {child.text: child for child in nav.default_slot.children if "as-guide-link" in child.classes}
    assert "Command line" in links
    _element(user, "guide-search").set_value("summarize")  # a command: the Command line section has it
    shown = [name for name, link in links.items() if link.visible]
    assert "Command line" in shown and "Monitor" not in shown
    _element(user, "guide-search").set_value("no such words here")
    assert not any(link.visible for link in links.values()) and _element(user, "guide-none").visible
    _element(user, "guide-search").set_value("")
    assert all(link.visible for link in links.values())


async def test_settings_and_profiles_are_in_the_menu_and_collapse_is_under_the_steps(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    _element(user, "app-menu-items").open()
    user.find(marker="menu-settings").click()
    await user.should_see(marker="settings-backend")
    await user.open(project_url("setup", project_dir))
    toggle, sidebar = _element(user, "sidebar-toggle"), _element(user, "sidebar")
    parent = toggle
    while parent is not None and parent is not sidebar:
        parent = parent.parent_slot.parent if parent.parent_slot else None
    assert parent is sidebar and toggle.props.get("role") == "button"


async def test_run_matrix_is_in_the_top_bar_and_lit_on_its_pages(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    tracker = _element(user, "topbar-tracker")
    assert tracker.props["href"] == "/tracker" and "as-topbar-link-on" not in tracker.classes
    await user.open("/tracker")
    assert "as-topbar-link-on" in _element(user, "topbar-tracker").classes


async def test_the_job_indicator_follows_a_job_started_elsewhere(user: User, ready_project, eventually,
                                                                  monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, project = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_not_see(marker="step-run-progress")  # hidden elements are not found
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": {A0: "hang"}}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)  # like the CLI: not through this page
    await eventually(lambda: _shown(user, "step-run-progress"), timeout=10)
    await eventually(lambda: _element(user, "step-run-progress").text == "0/3", timeout=10)
    assert _shown(user, "project-running-dot") and _shown(user, "step-run-bar")
    await user.should_see(marker="menu-job-log")
    runner.cancel(project_dir, runner.refresh(project_dir, job))
    await eventually(lambda: not _shown(user, "step-run-progress"), timeout=20)
    assert not _shown(user, "project-running-dot")


async def test_a_broken_job_state_hides_the_indicator_and_keeps_the_page(user: User, ready_project, monkeypatch):
    project_dir, _ = ready_project

    def broken(*args, **kwargs):
        raise AeroSuiteError("job record unreadable")

    monkeypatch.setattr(layout, "active_lock", lambda directory: {"pid": 1})
    monkeypatch.setattr(layout.WATCHER, "state", broken)
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="partitions")
    await user.should_not_see(marker="step-run-progress")


async def test_the_projects_page_has_the_top_bar_without_a_switcher(user: User):
    await user.open("/")
    await user.should_see("AeroSuite")
    await user.should_see(marker="app-menu")
    await user.should_not_see(marker="project-switcher")


async def test_a_lock_of_the_wrong_shape_does_not_break_the_page(user: User, ready_project):
    project_dir, _ = ready_project
    (project_dir / ".lock").write_text("[]", encoding="utf-8")
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="partitions")
    await user.should_not_see(marker="step-run-progress")


async def test_the_top_bar_controls_and_kind_tiles_take_the_keyboard(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    for marker in ("project-switcher", "calculators", "sidebar-toggle"):
        with user.client:
            element = next(iter(ElementFilter(only_visible=False, local_scope=False, marker=marker)))
        assert element.props.get("tabindex") == "0" and element.props.get("role") == "button"
    user.find(marker="project-switcher").trigger("keydown.enter")
    await user.should_see(marker="menu-all-projects")
    await user.open("/")
    tile = _element(user, "new-kind-aircraft")
    assert tile.props.get("tabindex") == "0"
    user.find(marker="new-kind-aircraft").trigger("keydown.enter")
    assert "as-choice-selected" in tile.classes


async def test_the_search_goes_to_a_step_and_a_case(user: User, ready_project, search):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await search(user, "")
    await user.should_see(marker="command-projects")  # before anything is typed: the places
    await user.should_not_see(marker="command-step-run")  # the sidebar has the steps
    await search(user, "res", pick="step-results")
    await user.should_see(marker="results-body")
    await search(user, A0, pick=f"case-{A0}")
    await user.should_see("Monitor", marker="crumb-page")


async def test_the_search_moves_with_the_arrow_keys(user: User, ready_project, search):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await search(user, "settings")
    rows = [element for element in user.find(marker="command-settings").elements]
    assert rows and "as-palette-on" in rows[0].classes
    user.find(marker="command-input").trigger("keydown.enter")
    await user.should_see(marker="settings-backend")


async def test_the_search_says_when_nothing_matches(user: User, search):
    await user.open("/")
    await search(user, "no such thing anywhere")
    await user.should_see(marker="command-none")

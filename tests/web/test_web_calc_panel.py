"""Calculators open as a panel from the right, over whatever page is showing (from the top bar's search)."""
from nicegui.testing import User

from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_the_search_opens_the_panel_on_the_page(user: User, ready_project, search):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_not_see(marker="calc-panel")
    await search(user, "calc", pick="calculators")
    await user.should_see(marker="calc-panel")
    await user.should_see(marker="isa-altitude")
    await user.should_see(marker="isa-apply")  # inside a project, ISA can apply to it
    await user.should_see(marker="partitions")  # still on the Setup page underneath


async def test_the_panel_switches_calculators_and_closes(user: User, ready_project, search):
    project_dir, _ = ready_project
    await user.open(project_url("run", project_dir))
    await search(user, "calculators", pick="calculators")
    user.find(marker="calc-item-yplus").click()
    await user.should_see(marker="yplus-velocity")
    user.find(marker="calc-panel-close").click()
    await user.should_not_see(marker="calc-panel")
    await search(user, "isa", pick="calc-isa")  # a calculator by name opens the panel on it
    await user.should_see(marker="isa-altitude")


async def test_the_top_bar_button_opens_and_closes_the_panel(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("aircraft", project_dir))
    user.find(marker="calculators").click()
    await user.should_see(marker="calc-panel")
    user.find(marker="calculators").click()  # a second click closes it
    await user.should_not_see(marker="calc-panel")


async def test_on_the_projects_page_the_panel_has_no_apply(user: User, search):
    await user.open("/")
    await search(user, "calculators", pick="calculators")
    await user.should_see(marker="calc-panel")
    await user.should_see(marker="isa-altitude")
    await user.should_not_see(marker="isa-apply")

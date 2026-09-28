"""Calculators open as a panel from the right, over whatever page is showing."""
from nicegui.testing import User

from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_the_button_is_labelled_and_opens_the_panel_on_the_page(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "calculators").text == "Calculators"
    await user.should_not_see(marker="calc-panel")
    user.find(marker="calculators").click()
    await user.should_see(marker="calc-panel")
    await user.should_see(marker="isa-altitude")
    await user.should_see(marker="isa-apply")  # inside a project, ISA can apply to it
    await user.should_see(marker="partitions")  # still on the Setup page underneath


async def test_the_panel_switches_calculators_and_closes(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("run", project_dir))
    user.find(marker="calculators").click()
    user.find(marker="calc-item-yplus").click()
    await user.should_see(marker="yplus-velocity")
    user.find(marker="calc-panel-close").click()
    await user.should_not_see(marker="calc-panel")
    user.find(marker="calculators").click()  # a second click on the button toggles it too
    await user.should_see(marker="calc-panel")
    user.find(marker="calculators").click()
    await user.should_not_see(marker="calc-panel")


async def test_on_the_projects_page_the_panel_has_no_apply(user: User):
    await user.open("/")
    user.find(marker="calculators").click()
    await user.should_see(marker="calc-panel")
    await user.should_see(marker="isa-altitude")
    await user.should_not_see(marker="isa-apply")

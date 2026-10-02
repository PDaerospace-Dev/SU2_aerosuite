"""The top bar's ParaView menu: the cases with flow files, opened on the workstation."""
import pytest
from nicegui.testing import User

from aerosuite.engine.restarts import RUNS_DIR
from aerosuite.web import paraview_menu
from aerosuite.web.layout import project_url
from aerosuite.web.paraview_menu import is_local

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _flow(project_dir, case, files=("flow.vtu", "surface_flow.vtu")):
    folder = project_dir / RUNS_DIR / case
    folder.mkdir(parents=True, exist_ok=True)
    for file in files:
        (folder / file).write_text("x")
    return folder


@pytest.fixture
def opened(monkeypatch):
    """What the menu asked ParaView to open, with the browser on the workstation."""
    calls = []
    monkeypatch.setattr(paraview_menu, "open_in_paraview", lambda files: calls.append([p.name for p in files]))
    monkeypatch.setattr(paraview_menu, "is_local", lambda ip: True)
    return calls


def test_only_a_loopback_browser_is_local():
    assert is_local("127.0.0.1") and is_local("::1") and is_local("localhost")
    assert not is_local("192.168.1.20") and not is_local("")


async def test_without_flow_files_the_menu_says_so(user: User, ready_project, opened):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "paraview").text == "ParaView"
    _element(user, "paraview-menu").open()
    await user.should_see(marker="paraview-none")
    await user.should_not_see(marker="paraview-all")


async def test_a_case_opens_its_flow_files(user: User, ready_project, opened):
    project_dir, _ = ready_project
    _flow(project_dir, A0)
    await user.open(project_url("sweep", project_dir))
    _element(user, "paraview-menu").open()
    await user.should_not_see(marker=f"paraview-case-{A2}")  # no files: not listed
    await user.should_not_see(marker="paraview-all")  # one case: nothing more to open
    user.find(marker=f"paraview-case-{A0}").click()
    await user.should_see(f"Opening {A0} in ParaView")
    assert opened == [["surface_flow.vtu", "flow.vtu"]]


async def test_all_cases_open_their_surfaces_and_new_files_show_on_reopening(user: User, ready_project, opened):
    project_dir, _ = ready_project
    _flow(project_dir, A0)
    await user.open(project_url("run", project_dir))
    menu = _element(user, "paraview-menu")
    menu.open()
    await user.should_see(marker=f"paraview-case-{A0}")
    menu.close()
    _flow(project_dir, A2, files=("flow.vtu",))
    menu.open()
    await user.should_see(marker=f"paraview-case-{A2}")
    user.find(marker="paraview-all").click()
    await user.should_see("Opening 2 cases in ParaView")
    assert sorted(opened[0]) == ["flow.vtu", "surface_flow.vtu"]  # A2 has no surface file: its volume


async def test_a_failure_to_start_is_reported(user: User, ready_project, monkeypatch):
    from aerosuite.engine.errors import AeroSuiteError

    def fail(files):
        raise AeroSuiteError("ParaView not found: 'paraview' is not on the PATH")

    monkeypatch.setattr(paraview_menu, "open_in_paraview", fail)
    monkeypatch.setattr(paraview_menu, "is_local", lambda ip: True)
    project_dir, _ = ready_project
    _flow(project_dir, A0)
    await user.open(project_url("setup", project_dir))
    _element(user, "paraview-menu").open()
    user.find(marker=f"paraview-case-{A0}").click()
    await user.should_see("ParaView not found")


async def test_from_another_pc_a_case_copies_its_path_instead(user: User, ready_project, opened, monkeypatch):
    monkeypatch.setattr(paraview_menu, "is_local", lambda ip: False)
    project_dir, _ = ready_project
    folder = _flow(project_dir, A0)
    _flow(project_dir, A2)
    await user.open(project_url("setup", project_dir))
    _element(user, "paraview-menu").open()
    await user.should_see(marker="paraview-remote")
    await user.should_not_see(marker="paraview-all")
    user.find(marker=f"paraview-case-{A0}").click()
    await user.should_see(f"Path copied: {folder}")
    assert opened == []
    user.find(marker="paraview-copy").click()
    await user.should_see(f"Path copied: {project_dir / RUNS_DIR}")


async def test_the_projects_page_has_no_paraview_button(user: User):
    await user.open("/")
    await user.should_not_see(marker="paraview")

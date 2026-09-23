import asyncio

from nicegui.testing import User

from aerosuite.engine.editing import set_parameter
from aerosuite.engine.project import PROJECT_FILE, open_project, save_project
from aerosuite.web.layout import project_url


async def _open(user, project_dir):
    await user.open(project_url("sweep", project_dir))


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_changing_mach_rebuilds_the_cases(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.6, 0.8").trigger("blur")
    project = open_project(project_dir)
    assert project.sweep.mach == [0.6, 0.8]
    assert len(project.cases) == 6
    await user.should_see(marker="case-M0p6_a0_b0")


async def test_ranges_and_bad_values(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-alpha").clear().type("-4:4:4").trigger("blur")
    assert [c.name for c in open_project(project_dir).cases] == ["M0p8_an4_b0", "M0p8_a0_b0", "M0p8_a4_b0"]
    user.find(marker="sweep-alpha").clear().type("abc").trigger("blur")
    await user.should_see("'abc' in 'abc' is not a number")
    assert open_project(project_dir).sweep.alpha == [-4.0, 0.0, 4.0]


async def test_naming_checkbox_changes_case_names(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    checkbox = _element(user, "naming-include_beta")
    with user:
        checkbox.set_value(False)
    assert open_project(project_dir).cases[0].name == "M0p8_a0"
    await user.should_see(marker="case-M0p8_a0")


async def test_duplicates_block_generate(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.8, 0.8").trigger("blur")
    await user.should_see(marker="dup-M0p8_a0_b0")
    await user.should_see(marker="problem-error")
    assert not _element(user, "generate").enabled


async def test_restart_choices(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    select = _element(user, "restart-M0p8_a2_b0")
    with user:
        select.set_value("from_case")
    assert open_project(project_dir).cases[1].restart == "from_case"
    await user.should_see("'from_case' must reference an earlier case")
    ref = _element(user, "ref-M0p8_a2_b0")
    with user:
        ref.set_value("M0p8_a0_b0")
    case = open_project(project_dir).cases[1]
    assert (case.restart, case.restart_ref) == ("from_case", "M0p8_a0_b0")
    await user.should_see(marker="problems-none")


async def test_generate_writes_configs_and_updates_the_badge(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="badge-configs-todo")
    user.find(marker="generate").click()
    await user.should_see("Wrote 3 configs")
    assert (project_dir / "configs" / "M0p8_a4_b0.cfg").is_file()
    await user.should_see(marker="badge-configs-done")


async def test_generate_refuses_a_stale_project(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)

    # Change project.json through the engine, as the CLI or another tab would.
    project = open_project(project_dir)
    set_parameter(project.settings, "CFL_NUMBER", "9")
    save_project(project_dir, project)

    user.find(marker="generate").click()
    await user.should_see("generate again")
    assert not (project_dir / "configs").exists()
    # Generate's own message is the only toast: no plain reload toast, no "enter it again".
    assert not user.notify.contains("Project changed on disk; reloaded")
    assert not user.notify.contains("your last change was not saved")

    user.find(marker="generate").click()
    await user.should_see("Wrote 3 configs")
    assert "CFL_NUMBER= 9" in (project_dir / "configs" / "M0p8_a4_b0.cfg").read_text()


async def test_generate_refuses_while_project_json_is_invalid(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    (project_dir / PROJECT_FILE).write_text('{"name": "half-typed", ')
    user.find(marker="generate").click()
    await user.should_see("project.json on disk is invalid")
    assert not user.notify.contains("generate again")
    assert not (project_dir / "configs").exists()


async def test_a_stale_mach_edit_tells_the_user_to_enter_it_again(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    project = open_project(project_dir)
    set_parameter(project.settings, "CFL_NUMBER", "9")
    save_project(project_dir, project)

    user.find(marker="sweep-mach").clear().type("0.6, 0.8").trigger("blur")
    await asyncio.sleep(0.2)  # the page rebuilds after the reload, dropping the field's error label
    await user.should_see("your last change was not saved")
    assert not user.notify.contains("Project changed on disk; reloaded")
    project = open_project(project_dir)
    assert project.settings.overrides == {"CFL_NUMBER": "9"}
    assert project.sweep.mach == [0.8]

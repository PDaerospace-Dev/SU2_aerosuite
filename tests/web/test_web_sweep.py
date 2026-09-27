import asyncio
from pathlib import Path

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


async def test_a_field_without_a_placeholder_has_no_stack_label(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert _element(user, "sweep-base-name").props.get("stack-label") is None


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


async def test_restart_choices(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="initial-restart")
    select = _element(user, "restart-M0p8_a2_b0")
    assert list(select.options) == ["none", "previous", "custom"]
    with user:
        select.set_value("custom")
    assert open_project(project_dir).cases[1].restart == "custom"
    await user.should_see("'custom' restart needs a restart file or case folder")
    solution = tmp_path / "solution.dat"
    solution.write_text("x")
    user.find(marker="ref-M0p8_a2_b0").type(str(solution)).trigger("blur")
    case = open_project(project_dir).cases[1]
    assert (case.restart, case.restart_ref) == ("custom", str(solution))
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


async def test_browse_picks_a_case_folder(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    folder = tmp_path / "earlier_study" / "runs" / "M0p8_a0_b0"
    folder.mkdir(parents=True)
    (folder / "restart_flow.dat").write_text("x")
    await _open(user, project_dir)
    with user:
        _element(user, "restart-M0p8_a2_b0").set_value("custom")
    user.find(marker="ref-browse-M0p8_a2_b0").click()
    await user.should_see(marker="picker-choose-folder")
    user.find(marker="picker-path").type(str(folder))
    user.find(marker="picker-use").click()
    await user.should_see(marker="problems-none")
    case = open_project(project_dir).cases[1]
    assert (case.restart, case.restart_ref) == ("custom", str(folder))


async def test_browse_picks_a_restart_file(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    solution = tmp_path / "restart_flow.dat"
    solution.write_text("x")
    await _open(user, project_dir)
    with user:
        _element(user, "restart-M0p8_a2_b0").set_value("custom")
    user.find(marker="ref-browse-M0p8_a2_b0").click()
    await user.should_see(marker="picker-entry-restart_flow.dat")  # the picker starts at tmp_path
    user.find(marker="picker-entry-restart_flow.dat").click()
    await user.should_see(marker="problems-none")
    assert open_project(project_dir).cases[1].restart_ref == str(solution)


async def test_generate_rechecks_files_deleted_while_the_page_was_open(user: User, ready_project):
    project_dir, project = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="problems-none")
    Path(project.mesh.path).unlink()  # deleted on disk after the page drew its checks
    user.find(marker="generate").click()
    await user.should_see(f"Mesh not found: {project.mesh.path}")
    assert not (project_dir / "configs").exists()
    await user.should_see(marker="problem-error")  # the checks were redrawn
    assert not _element(user, "generate").enabled


async def test_generate_is_the_primary_action_and_checks_are_banners(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("sweep", project_dir))
    generate = _element(user, "generate")
    assert generate.parent_slot.parent is _element(user, "page-actions")
    assert "as-btn-primary" in generate.classes
    await user.should_see(marker="problems-none")
    user.find(marker="sweep-mach").clear().type("abc").trigger("blur")
    await user.should_see("'abc' in 'abc' is not a number")


async def test_a_custom_restart_without_a_file_is_an_error_banner(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("sweep", project_dir))
    _element(user, "restart-M0p8_a2_b0").set_value("custom")
    label = _element(user, "problem-error")
    assert "as-banner-error" in label.parent_slot.parent.classes
    assert not _element(user, "generate").enabled


A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _restarts(project_dir):
    return [(case.restart, case.restart_ref) for case in open_project(project_dir).cases]


async def test_set_all_to_previous_keeps_the_first_case_fresh(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="restart-all-previous").click()
    assert _restarts(project_dir) == [("none", None), ("previous", None), ("previous", None)]
    assert _element(user, f"restart-{A4}").value == "previous"  # the table shows it at once
    await user.should_see(marker="problems-none")


async def test_set_all_to_none_clears_every_restart(user: User, ready_project):
    project_dir, project = ready_project
    for case in project.cases:
        case.restart, case.restart_ref = "custom", "/somewhere/else"
    save_project(project_dir, project)
    await _open(user, project_dir)
    user.find(marker="restart-all-none").click()
    assert _restarts(project_dir) == [("none", None)] * 3


async def test_set_all_to_custom_points_each_case_at_its_folder(user: User, ready_project, tmp_path, eventually):
    project_dir, _ = ready_project
    runs = tmp_path / "earlier_study" / "runs"
    for name in (A0, A2, A4):
        (runs / name).mkdir(parents=True)
        (runs / name / "restart_flow.dat").write_text("x")
    await _open(user, project_dir)
    user.find(marker="restart-all-custom").click()
    await user.should_see(marker="picker-choose-folder")
    user.find(marker="picker-path").type(str(runs))
    user.find(marker="picker-use").click()
    expected = [("custom", str(runs / name)) for name in (A0, A2, A4)]
    await eventually(lambda: _restarts(project_dir) == expected)  # the picker returns on a later tick
    await user.should_see(marker="problems-none")


async def test_set_all_to_custom_flags_cases_missing_from_the_folder(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    runs = tmp_path / "earlier_study" / "runs"
    (runs / A0).mkdir(parents=True)
    (runs / A0 / "restart_flow.dat").write_text("x")
    await _open(user, project_dir)
    user.find(marker="restart-all-custom").click()
    await user.should_see(marker="picker-choose-folder")
    user.find(marker="picker-path").type(str(runs))
    user.find(marker="picker-use").click()
    await user.should_see(marker="problem-error")
    assert _restarts(project_dir)[2] == ("custom", str(runs / A4))
    assert not _element(user, "generate").enabled


async def test_cancelling_set_all_custom_changes_nothing(user: User, ready_project):
    project_dir, _ = ready_project
    before = _restarts(project_dir)
    await _open(user, project_dir)
    user.find(marker="restart-all-custom").click()
    await user.should_see(marker="picker-cancel")
    user.find(marker="picker-cancel").click()
    await user.should_not_see(marker="picker-cancel")
    assert _restarts(project_dir) == before


from aerosuite.engine.editing import set_freestream


def _altitude_mode(project_dir, altitude_km=11.0):
    project = open_project(project_dir)
    set_freestream(project, mode="altitude", altitude_km=altitude_km, reynolds_length=6.0)
    save_project(project_dir, project)
    return project


async def test_altitude_mode_shows_the_derived_label_and_per_case_values(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir)
    await _open(user, project_dir)
    label = _element(user, "sweep-altitude")
    assert label.value == "11km" and "readonly" in label.props
    await user.should_see(marker="sweep-altitude-note")
    name = project.cases[0].name
    assert _element(user, f"temp-{name}").text == "216.65 K"
    assert _element(user, f"re-{name}").text == "3.48e7"


async def test_reynolds_column_follows_a_mach_edit(user: User, ready_project):
    project_dir, _ = ready_project
    _altitude_mode(project_dir)
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.6").trigger("blur")
    name = open_project(project_dir).cases[0].name
    assert _element(user, f"re-{name}").text == "2.61e7"


async def test_an_invalid_altitude_shows_dashes(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir, altitude_km=120.0)
    await _open(user, project_dir)
    assert _element(user, f"re-{project.cases[0].name}").text == "—"
    await user.should_see(marker="problem-error")


async def test_manual_mode_has_no_freestream_columns(user: User, ready_project):
    project_dir, project = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker=f"re-{project.cases[0].name}")
    assert "readonly" not in _element(user, "sweep-altitude").props

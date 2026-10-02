import asyncio
from pathlib import Path

from nicegui.testing import User

from aerosuite.engine.editing import set_freestream, set_parameter, update_sweep
from aerosuite.engine.project import PROJECT_FILE, open_project, save_project
from aerosuite.web.layout import project_url


async def _open(user, project_dir):
    await user.open(project_url("sweep", project_dir))


def _cases_tab(user):
    user.find(marker="sweep-tab-cases").click()


def _change(user, case):
    """Open the Cases tab and one case's restart choice."""
    _cases_tab(user)
    user.find(marker=f"change-{case}").click()


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_changing_mach_rebuilds_the_cases(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.6, 0.8").trigger("blur")
    project = open_project(project_dir)
    assert project.sweep.mach == [0.6, 0.8]
    assert len(project.cases) == 6
    assert _element(user, "sweep-count").text == "6" and _element(user, "sweep-formula").text == "= 2 Mach × 3 α × 1 β"
    _cases_tab(user)
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
    _cases_tab(user)
    await user.should_see(marker="case-M0p8_a0")


async def test_duplicates_block_generate(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.8, 0.8").trigger("blur")
    _cases_tab(user)
    await user.should_see(marker="dup-M0p8_a0_b0")
    await user.should_see(marker="problem-error")
    assert not _element(user, "generate").enabled


async def test_restart_choices(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="initial-restart")
    _change(user, "M0p8_a2_b0")
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
    await user.should_see(marker="badge-sweep-todo")
    user.find(marker="generate").click()
    await user.should_see("Wrote 3 configs")
    assert (project_dir / "configs" / "M0p8_a4_b0.cfg").is_file()
    await user.should_see(marker="badge-sweep-done")


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
    _change(user, "M0p8_a2_b0")
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
    _change(user, "M0p8_a2_b0")
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
    _change(user, "M0p8_a2_b0")
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
    assert "as-choice-selected" in _element(user, "restart-all-previous").classes  # the rule shows it at once
    _cases_tab(user)
    assert _element(user, f"restart-text-{A4}").text == f"continues from {A2}"
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


def _altitude_mode(project_dir, altitude_km=11.0):
    project = open_project(project_dir)
    set_freestream(project, mode="altitude", reynolds_length=6.0)
    update_sweep(project, altitudes_km=[altitude_km])
    save_project(project_dir, project)
    return project


async def test_altitude_mode_shows_the_altitudes_and_per_case_values(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir)
    await _open(user, project_dir)
    assert _element(user, "sweep-altitudes").value == "11"
    await user.should_see(marker="sweep-altitude-note")
    await user.should_not_see(marker="sweep-altitude")  # no typed label in altitude mode
    name = project.cases[0].name
    assert [label.text for label in _element(user, "sweep-summary").default_slot.children][5:] == [
        "0.8", "11 km", "216.65 K", "3.63e7", "3"]
    _cases_tab(user)
    assert _element(user, f"alt-{name}").text == "11"
    assert _element(user, f"temp-{name}").text == "216.65 K"
    assert _element(user, f"re-{name}").text == "3.63e7"


async def test_warnings_fold_into_one_row_and_errors_stay_banners(user: User, ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").write_text("MACH_NUMBER= 0.3\nAOA= 0.0\nAOA= 2.0\n")
    set_freestream(project, mode="altitude")  # no altitudes, no Reynolds length: errors
    save_project(project_dir, project)
    await _open(user, project_dir)
    group = _element(user, "problem-warning")
    assert "as-warn-group" in group.classes and not group.value
    errors = [label.text for label in user.find(marker="problem-error").elements]
    assert "Error: No altitudes in the sweep" in errors
    with user:
        group.open()
    await _open(user, project_dir)  # opened stays opened when the page is drawn again
    assert _element(user, "problem-warning").value
    with user:
        _element(user, "problem-warning").close()


async def test_editing_the_altitudes_sweeps_them(user: User, ready_project):
    project_dir, project = ready_project
    project.sweep.naming.include_altitude = True
    save_project(project_dir, project)
    _altitude_mode(project_dir)
    await _open(user, project_dir)
    user.find(marker="sweep-altitudes").clear().type("0, 11").trigger("blur")
    project = open_project(project_dir)
    assert project.sweep.altitudes_km == [0.0, 11.0] and len(project.cases) == 6
    first, fourth = project.cases[0].name, project.cases[3].name
    assert (first, fourth) == ("M0p8_0km_a0_b0", "M0p8_11km_a0_b0")
    _cases_tab(user)
    assert _element(user, f"alt-{first}").text == "0"  # the table follows at once
    assert _element(user, f"temp-{first}").text == "288.15 K"
    user.find(marker="sweep-tab-conditions").click()
    user.find(marker="restart-all-previous").click()
    assert [c.restart for c in open_project(project_dir).cases] == [
        "none", "previous", "previous", "none", "previous", "previous"]


async def test_reynolds_column_follows_a_mach_edit(user: User, ready_project):
    project_dir, _ = ready_project
    _altitude_mode(project_dir)
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.6").trigger("blur")
    name = open_project(project_dir).cases[0].name
    _cases_tab(user)
    assert _element(user, f"re-{name}").text == "2.72e7"


async def test_an_invalid_altitude_shows_dashes(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir, altitude_km=120.0)
    await _open(user, project_dir)
    _cases_tab(user)
    assert _element(user, f"re-{project.cases[0].name}").text == "—"
    await user.should_see(marker="problem-error")


async def test_manual_mode_has_no_freestream_columns(user: User, ready_project):
    project_dir, project = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker=f"re-{project.cases[0].name}")
    await user.should_not_see(marker=f"alt-{project.cases[0].name}")
    assert "readonly" not in _element(user, "sweep-altitude").props


# -- two tabs, the restart rule and the cases set differently ---------------------------------


async def test_conditions_come_first_and_cases_are_a_tab(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="sweep-mach")
    await user.should_not_see(marker=f"case-{A0}")
    assert _element(user, "sweep-tab-cases").text == "Cases 3"
    assert "as-choice-selected" in _element(user, "restart-all-none").classes
    assert _element(user, "sweep-names").text == f"Names: {A0} … {A4}"
    _cases_tab(user)
    await user.should_see(marker=f"case-{A0}")
    await user.should_not_see(marker="sweep-mach")
    assert _element(user, f"restart-text-{A2}").text == "from scratch"


async def test_a_case_set_differently_is_marked_and_the_rule_says_so(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    _change(user, A2)
    with user:
        _element(user, f"restart-{A2}").set_value("previous")
    assert _restarts(project_dir)[1] == ("previous", None)
    user.find(marker=f"change-{A2}").click()  # Done
    assert _element(user, f"restart-text-{A2}").text == f"continues from {A0}"
    await user.should_see(marker=f"differs-{A2}")
    user.find(marker="sweep-tab-conditions").click()
    assert "1 case is set differently" in _element(user, "restart-differs").text
    user.find(marker="restart-all-none").click()  # choosing the rule sets every case
    assert _restarts(project_dir) == [("none", None)] * 3
    await user.should_not_see(marker="restart-differs")


async def test_an_evenly_spaced_list_shows_as_a_range(user: User, ready_project):
    project_dir, project = ready_project
    update_sweep(project, alpha=[float(a) for a in range(-10, 22, 2)])
    save_project(project_dir, project)
    await _open(user, project_dir)
    assert _element(user, "sweep-alpha").value == "-10:20:2"
    assert _element(user, "sweep-formula").text == "= 1 Mach × 16 α × 1 β"


async def test_many_cases_fold_by_mach_on_the_cases_tab(user: User, ready_project):
    project_dir, project = ready_project
    update_sweep(project, mach=[0.6, 0.8], alpha=[float(a) for a in range(7)])
    save_project(project_dir, project)
    first = open_project(project_dir).cases[0].name
    await _open(user, project_dir)
    _cases_tab(user)
    await user.should_see(marker="sweep-group-1")
    await user.should_not_see(marker=f"case-{first}")
    user.find(marker="sweep-group-0").click()
    await user.should_see(marker=f"case-{first}")


async def test_a_base_name_that_cannot_be_a_file_name_is_refused(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-base-name").type("a/b").trigger("blur")
    await user.should_see("The base name 'a/b' can only use letters, digits")
    assert open_project(project_dir).sweep.naming.base_name == ""


async def test_a_huge_range_is_refused_at_once(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="sweep-alpha").clear().type("0:1e9:1").trigger("blur")
    await user.should_see("makes more than 1000 values")
    assert open_project(project_dir).sweep.alpha == [0.0, 2.0, 4.0]

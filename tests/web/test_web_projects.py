import sys
from pathlib import Path

import pytest
from nicegui.testing import User

from aerosuite.engine.project import PROJECT_FILE, open_project
from aerosuite.web.recent import load_recent


async def test_no_recent_projects(user: User):
    await user.open("/")
    await user.should_see(marker="recent-empty")


async def test_open_by_pasting_a_path(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open("/")
    user.find(marker="open-path").type(str(project_dir))
    user.find(marker="open-button").click()
    await user.should_see(marker="project-name")
    assert load_recent() == [project_dir.resolve()]


async def test_open_reports_a_bad_folder(user: User, tmp_path):
    await user.open("/")
    user.find(marker="open-path").type(str(tmp_path / "nowhere"))
    user.find(marker="open-button").click()
    await user.should_see("No project found")


async def test_open_with_the_picker(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    await user.open("/")
    user.find(marker="open-browse").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-study").click()
    user.find(marker="picker-choose-folder").click()
    field = next(iter(user.find(marker="open-path").elements))
    await eventually(lambda: bool(field.value))
    assert Path(field.value).resolve() == project_dir.resolve()
    user.find(marker="open-button").click()
    await user.should_see(marker="project-name")


async def test_recent_list_links_to_projects(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open("/")
    user.find(marker="open-path").type(str(project_dir))
    user.find(marker="open-button").click()
    await user.should_see(marker="project-name")
    await user.open("/")
    await user.should_see(marker="recent-study")


async def test_create_a_new_project(user: User, tmp_path):
    await user.open("/")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("fresh")
    with user:
        next(iter(user.find(marker="new-use-reference").elements)).set_value(True)
    user.find(marker="new-create").click()
    await user.should_see(marker="project-name")
    assert open_project(tmp_path / "fresh").name == "fresh"


async def test_new_project_checks_its_inputs(user: User, tmp_path):
    await user.open("/")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("a/b")
    user.find(marker="new-create").click()
    await user.should_see("Choose a plain folder name")
    user.find(marker="new-parent").clear().type(str(tmp_path / "missing"))
    user.find(marker="new-name").clear().type("ok")
    user.find(marker="new-create").click()
    await user.should_see("Parent folder not found")


NOT_PLAIN_NAMES = [
    ".",
    "..",
    "a/b",
    "a\\b",
    pytest.param("C:x", marks=pytest.mark.skipif(sys.platform != "win32", reason="drive-relative names are Windows-only")),
]


@pytest.mark.parametrize("name", NOT_PLAIN_NAMES)
async def test_new_project_name_must_stay_inside_the_parent(user: User, tmp_path, name):
    parent = tmp_path / "parent"
    parent.mkdir()
    before = sorted(tmp_path.rglob("*"))
    await user.open("/")
    user.find(marker="new-parent").type(str(parent))
    user.find(marker="new-name").type(name)
    user.find(marker="new-create").click()
    await user.should_see("Choose a plain folder name (no '.', '..', drive or separators)")
    assert sorted(tmp_path.rglob("*")) == before
    assert not (parent / name / PROJECT_FILE).exists()


from aerosuite.web.recent import add_recent  # noqa: E402


async def test_recent_rows_show_the_kind_and_the_latest_run(user: User, ready_project):
    project_dir, project = ready_project
    add_recent(project_dir)
    await user.open("/")
    await user.should_see(marker="recent-study")
    await user.should_see("sweep · 3 cases")
    await user.should_see(str(project_dir.resolve()))


async def test_create_is_the_primary_action(user: User):
    await user.open("/")
    assert "as-btn-primary" in next(iter(user.find(marker="new-create").elements)).classes


async def test_import_existing_runs(user: User, tmp_path):
    from aerosuite.engine.project import open_project

    runs = tmp_path / "old-runs"
    for name in ("M1p2_10km_vt_a0_b0", "M1p2_10km_vt_a0_b6"):
        folder = runs / name
        folder.mkdir(parents=True)
        mach = "1.25" if name.endswith("b6") else "1.2"
        (folder / f"{name}.cfg").write_text(f"MACH_NUMBER= {mach}\nAOA= 0\nSIDESLIP_ANGLE= {name[-1]}\n")
        (folder / "history.csv").write_text("Inner_Iter,CL\n" + "".join(f"{i},0.1\n" for i in range(20)))
    (runs / "notes").mkdir()  # not case-like: left out silently
    (runs / "group" / "M0p8_a2").mkdir(parents=True)
    (runs / "group" / "M0p8_a2" / "M0p8_a2.cfg").write_text("MACH_NUMBER= 0.8\nAOA= 2\n")  # no history: skipped
    await user.open("/")
    user.find(marker="import-source").type(str(runs))
    user.find(marker="import-parent").type(str(tmp_path))
    user.find(marker="import-name").type("old")
    user.find(marker="import-scan").click()
    await user.should_see("2 cases found in old-runs")
    await user.should_see(marker="import-row-M1p2_10km_vt_a0_b6")
    assert next(iter(user.find(marker="import-warnings").elements))._props["label"] == "1 warning"
    assert next(iter(user.find(marker="import-skipped").elements))._props["label"] == "1 folder skipped"
    user.find(marker="import-create").click()
    project = open_project(tmp_path / "old")
    assert [c.name for c in project.cases] == ["M1p2_10km_vt_a0_b0", "M1p2_10km_vt_a0_b6"]
    await user.should_see(marker="results-body")


async def test_import_preview_shows_the_group_folder(user: User, tmp_path):
    folder = tmp_path / "st_tail" / "M0p9_10km" / "M0p9_10km_a0_b2"
    folder.mkdir(parents=True)
    (folder / "M0p9_10km_a0_b2.cfg").write_text("MACH_NUMBER= 0.9\nAOA= 0\nSIDESLIP_ANGLE= 2\n")
    (folder / "history.csv").write_text("Inner_Iter,CL\n0,0.1\n")
    await user.open("/")
    user.find(marker="import-source").type(str(tmp_path / "st_tail"))
    user.find(marker="import-scan").click()
    await user.should_see("1 case found in st_tail")
    await user.should_see("M0p9_10km / M0p9_10km_a0_b2")


async def test_import_checks_its_inputs(user: User, tmp_path):
    await user.open("/")
    user.find(marker="import-scan").click()
    await user.should_see("Choose the runs folder")
    user.find(marker="import-source").type(str(tmp_path / "missing"))
    user.find(marker="import-scan").click()
    await user.should_see("is not a folder")

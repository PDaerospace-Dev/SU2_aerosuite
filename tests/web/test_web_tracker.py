"""The Run matrix pages: linked sheets, linking one, previewing and writing; and the automatic writer."""
from datetime import datetime, timedelta

import pytest
from nicegui.testing import User
from openpyxl import Workbook, load_workbook

from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import save_job
from aerosuite.engine.models import Project
from aerosuite.engine.project import save_project
from aerosuite.engine.tracker_links import Link, LinkedProject, find_link, load_tracker, save_link
from aerosuite.web.tracker_watch import TrackerWatch

RUN_ID = '=IF(ROW()-4>$D$14,"","RUN-"&TEXT(ROW()-4,"0000"))'


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _workbook(path, statuses):
    """Two Mach numbers x two AoA, runs from row 5 as the template lays them out."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Study"
    ws["G3"], ws["M3"], ws["N3"] = "Run ID [Auto]", "Status", "Notes"
    for row in range(5, 9):
        ws.cell(row, 7, RUN_ID)
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)", "Sideslip Beta"], 1):
        ws.cell(23, column, header)
    ws["A25"], ws["A26"], ws["B25"], ws["C25"], ws["C26"], ws["D25"] = 0.3, 0.6, 0, 0, 5, 0
    for row, text in statuses.items():
        ws.cell(row, 13, text)
    wb.save(path)
    return path


def _job(folder, job_id, cases, hours_ago=0):
    save_job(folder, JobRecord(id=job_id, backend="local", cases=list(cases), log_path=f"jobs/{job_id}.log",
                               state=JobState.DONE, created=datetime(2026, 11, 1) - timedelta(hours=hours_ago),
                               case_status=cases))


@pytest.fixture
def matrix(tmp_path):
    """A workbook (row 5 marked Converged by hand) and the project del0 beside it: M0.3 a0 unconverged (kept), M0.3 a5
    converged (to write)."""
    book = _workbook(tmp_path / "matrix.xlsx", {5: "Converged"})
    folder = tmp_path / "wing_del0"
    folder.mkdir()
    save_project(folder, Project(name="wing_del0"))
    _job(folder, "j1", {"M0p3_0km_a0": CaseState.UNCONVERGED, "M0p3_0km_a5": CaseState.CONVERGED})
    return book, folder


def _link(book, folder, **changes):
    return save_link(Link(workbook=str(book), sheet="Study", projects=[LinkedProject(path=str(folder), elevator=0)],
                          **changes))


async def test_no_links_yet(user: User):
    await user.open("/tracker")
    await user.should_see(marker="tracker-empty")
    await user.should_see("No sheets linked yet")


async def test_the_overview_shows_and_writes_a_sheet(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    await user.open("/tracker")
    await user.should_see(marker=f"tracker-sheet-{link.id}")
    assert _element(user, f"tracker-sheet-{link.id}-pending").text == "1 to write"
    assert _element(user, "tracker-kept").text == "1"
    assert _element(user, "tracker-runs").text == "4"
    user.find(marker=f"tracker-sheet-{link.id}-write").click()
    await user.should_see(marker="tracker-log")
    ws = load_workbook(book)["Study"]
    assert (ws["M5"].value, ws["M6"].value) == ("Converged", "Converged")  # the hand verdict stays
    assert load_tracker().log[0].written == 1


async def test_a_missing_workbook_is_shown_on_its_row(user: User, matrix, tmp_path):
    _, folder = matrix
    link = _link(tmp_path / "gone.xlsx", folder)
    await user.open("/tracker")
    await user.should_see(marker=f"tracker-sheet-{link.id}-error")


async def test_the_preview_takes_the_jobs_verdict_where_asked(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    await user.open(f"/tracker/preview?link={link.id}")
    await user.should_see(marker="preview-change-table")
    assert _element(user, "preview-changes").text == "1"
    assert _element(user, "preview-kept").text == "1"
    assert _element(user, "preview-write").text == "Write 1 status"
    user.find(marker="preview-kept-RUN-0001").click()
    assert _element(user, "preview-write").text == "Write 2 statuses"
    user.find(marker="preview-write").click()
    await user.should_see("Nothing to write")
    ws = load_workbook(book)["Study"]
    assert (ws["M5"].value, ws["M6"].value) == ("Not Converged", "Converged")


async def test_linking_a_sheet(user: User, matrix, eventually):
    book, folder = matrix
    await user.open("/tracker/link")
    with user:
        _element(user, "link-workbook").set_value(str(book))
    await eventually(lambda: _element(user, "link-sheet").value == "Study")
    await user.should_see(marker="link-project-wing_del0-on")
    assert _element(user, "link-project-wing_del0-elevator").value == "0"  # from the folder name
    with user:
        _element(user, "link-project-wing_del0-on").set_value(True)
        _element(user, "link-auto").set_value(False)
    await eventually(lambda: _element(user, "link-changes").text == "1")
    assert _element(user, "link-kept").text == "1"
    user.find(marker="link-save").click()
    await user.should_see(marker="tracker-preview-page")
    saved = load_tracker().links[0]
    assert (saved.sheet, saved.auto, [p.elevator for p in saved.projects]) == ("Study", False, [0.0])


async def test_a_project_without_a_deflection_must_be_given_one(user: User, matrix, eventually):
    book, _ = matrix
    other = book.parent / "baseline"
    other.mkdir()
    save_project(other, Project(name="baseline"))
    await user.open("/tracker/link")
    with user:
        _element(user, "link-workbook").set_value(str(book))
    await user.should_see(marker="link-project-baseline-on")
    assert _element(user, "link-project-baseline-elevator").value == ""
    with user:
        _element(user, "link-project-baseline-on").set_value(True)
    user.find(marker="link-save").click()
    await user.should_see("Give the elevator deflection of baseline in degrees.")


async def test_changing_and_removing_a_link(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    await user.open(f"/tracker/link?link={link.id}")
    await user.should_see(marker="link-remove")
    user.find(marker="link-remove").click()
    await user.should_see(marker="tracker-page")
    assert find_link(link.id) is None


async def test_the_writer_writes_what_changes_after_it_first_looks(matrix):
    book, folder = matrix
    _link(book, folder)
    watch = TrackerWatch()
    assert await watch.check_once() == 0  # first look: nothing is written
    assert load_workbook(book)["Study"]["M6"].value is None
    _job(folder, "j2", {"M0p6_0km_a0": CaseState.CONVERGED})
    assert await watch.check_once() == 1
    ws = load_workbook(book)["Study"]
    assert (ws["M6"].value, ws["M7"].value) == ("Converged", "Converged")
    assert load_tracker().log[0].trigger == "auto"
    assert await watch.check_once() == 0  # its own write is not a change


async def test_the_writer_leaves_links_that_do_not_write_automatically(matrix):
    book, folder = matrix
    _link(book, folder, auto=False)
    watch = TrackerWatch()
    await watch.check_once()
    _job(folder, "j2", {"M0p6_0km_a0": CaseState.CONVERGED})
    assert await watch.check_once() == 0

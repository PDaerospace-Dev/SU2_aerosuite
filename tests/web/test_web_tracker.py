"""The Run matrix pages: linked sheets, linking one, previewing and writing, a new sheet from the template; and the
automatic writer."""
import asyncio
from datetime import date, datetime, timedelta

import pytest
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction
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


def _job(folder, job_id, cases, hours_ago=0, finished=None):
    save_job(folder, JobRecord(id=job_id, backend="local", cases=list(cases), log_path=f"jobs/{job_id}.log",
                               state=JobState.DONE, created=datetime(2026, 11, 1) - timedelta(hours=hours_ago),
                               case_status=cases, finished=finished))


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
    assert "as-card-folded" in _element(user, "tracker-log").classes  # Recent writes starts folded
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


async def test_the_preview_fills_in_completed_on(user: User, tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx", {5: "Converged", 6: "Converged", 7: "Not Converged", 8: "Converged"})
    wb = load_workbook(book)
    wb["Study"]["A11"] = "Completed on"
    wb["Study"]["D11"].number_format = "mm-dd-yy"
    wb.save(book)
    folder = tmp_path / "wing_del0"
    _job(folder, "j1", {"M0p3_0km_a0": CaseState.CONVERGED, "M0p3_0km_a5": CaseState.CONVERGED,
                        "M0p6_0km_a0": CaseState.UNCONVERGED, "M0p6_0km_a5": CaseState.CONVERGED},
         finished=datetime(2026, 11, 4, 9))
    link = _link(book, folder)
    await user.open(f"/tracker/preview?link={link.id}")
    await user.should_see(marker="preview-completed")
    assert _element(user, "preview-write").text == "Write the completion date"
    user.find(marker="preview-write").click()
    await user.should_not_see(marker="preview-completed")  # written: the cell is no longer blank
    assert load_workbook(book)["Study"]["D11"].value == datetime(2026, 11, 4)


async def test_coverage_shows_the_sheet_in_three_views(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    await user.open("/tracker")
    user.find(marker="tracker-coverage").click()  # one button: the first ongoing sheet
    await user.should_see(marker="coverage-panels")
    assert "as-chip-on" in _element(user, f"coverage-sheet-{link.id}").classes
    assert "1 converged" in _element(user, "coverage-progress").text
    _element(user, "coverage-view").set_value("table")
    await user.should_see(marker="coverage-table")
    _element(user, "coverage-view").set_value("pivot")
    await user.should_see(marker="coverage-pivot")
    user.find(marker="coverage-box-0-0.3").trigger("click")  # AoA 0 (a row), Mach 0.3 (a column)
    await user.should_see(marker="coverage-detail-runs")
    assert "AoA 0° · Mach 0.3" in _element(user, "coverage-detail-title").text


async def _pick(user, ids, **flags):
    """What the page's script sends for a click (or shift-click, or drag) on runs; its handler runs as a task."""
    UserInteraction(user, {user.client.layout}, None).trigger("asCovPick", {"ids": ids, **flags})
    await asyncio.sleep(0.05)


async def _coverage(user, matrix, view="panels"):
    book, folder = matrix
    link = _link(book, folder)
    await user.open(f"/tracker/coverage?link={link.id}&view={view}")
    await user.should_see(marker=f"coverage-{view}")
    return book


async def test_a_clicked_run_is_set_by_hand(user: User, matrix):
    book = await _coverage(user, matrix)
    await _pick(user, ["RUN-0001"])  # M0.3 a0: Converged in the sheet, Not Converged by the job
    await user.should_see(marker="run-edit")
    assert _element(user, "run-edit-title").text == "RUN-0001"
    assert _element(user, "run-edit-job").text == "Not Converged"
    status = _element(user, "run-edit-status")
    assert status.value == "Converged"
    status.set_value("Diverged")
    assert "kept" in _element(user, "run-edit-hint").text
    _element(user, "run-edit-notes").set_value("blows up at 3k")
    user.find(marker="run-edit-save").click()
    await user.should_see("Saved 1 run to matrix.xlsx")
    ws = load_workbook(book)["Study"]
    assert (ws["M5"].value, ws["N5"].value) == ("Diverged", "blows up at 3k")
    await user.should_see(marker="run-edit")  # still open, as saved
    assert _element(user, "run-edit-status").value == "Diverged"


async def test_a_run_no_job_has_run_says_so(user: User, matrix):
    await _coverage(user, matrix)
    await _pick(user, ["RUN-0003"])
    await user.should_see(marker="run-edit-nojob")
    _element(user, "run-edit-status").set_value("Hold")
    assert _element(user, "run-edit-hint").text == ""


async def test_selected_runs_are_marked_together(user: User, matrix):
    book = await _coverage(user, matrix)
    await _pick(user, ["RUN-0003", "RUN-0004"], many=True)  # a drag
    await user.should_see(marker="coverage-bar")
    assert _element(user, "coverage-bar-count").text == "2 runs selected"
    await _pick(user, ["RUN-0001"], add=True)  # shift-click adds
    assert _element(user, "coverage-bar-count").text == "3 runs selected"
    await _pick(user, ["RUN-0001"], add=True)  # and takes away
    assert _element(user, "coverage-bar-count").text == "2 runs selected"
    user.find(marker="coverage-bar-hold").click()
    await user.should_see("Saved 2 runs to matrix.xlsx")
    ws = load_workbook(book)["Study"]
    assert (ws["M7"].value, ws["M8"].value) == ("Hold", "Hold")
    await user.should_not_see(marker="coverage-bar")


async def test_a_note_goes_after_the_notes_already_there(user: User, matrix):
    book, folder = matrix
    workbook = load_workbook(book)
    workbook["Study"]["N5"] = "mesh v2"
    workbook.save(book)
    await _coverage(user, matrix)
    await _pick(user, ["RUN-0001", "RUN-0002"], many=True)
    await user.should_see(marker="coverage-bar")
    user.find(marker="coverage-bar-note").click()
    await user.should_see(marker="coverage-note-dialog")
    _element(user, "coverage-note-text").set_value("rerun at CFL 5")
    user.find(marker="coverage-note-save").click()
    await user.should_see("Saved 2 runs to matrix.xlsx")
    ws = load_workbook(book)["Study"]
    assert (ws["N5"].value, ws["N6"].value) == ("mesh v2; rerun at CFL 5", "rerun at CFL 5")


async def test_a_label_selects_its_row_and_a_plain_click_edits_again(user: User, matrix):
    await _coverage(user, matrix)
    await _pick(user, ["RUN-0002"], many=True)  # the AoA 5° label of a panel holding one Mach
    await user.should_see(marker="coverage-bar")
    assert _element(user, "coverage-bar-count").text == "1 run selected"
    await _pick(user, ["RUN-0004"])  # a plain click: the selection goes, the run opens
    await user.should_see(marker="run-edit")
    await user.should_not_see(marker="coverage-bar")


async def test_sheets_are_ongoing_or_completed(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    await user.open("/tracker")
    await user.should_see(marker=f"tracker-sheet-{link.id}")
    assert (_element(user, "tracker-group-ongoing-count").text, _element(user, "tracker-group-completed-count").text) \
        == ("1", "0")
    user.find(marker=f"tracker-sheet-{link.id}-complete").click()
    await user.should_see(marker=f"tracker-sheet-{link.id}-ongoing")
    assert find_link(link.id).completed is True
    assert _element(user, "tracker-group-completed-count").text == "1"
    assert _element(user, f"tracker-sheet-{link.id}-runs").text == "4 runs · marked completed"
    user.find(marker=f"tracker-sheet-{link.id}-ongoing").click()
    await user.should_see(marker=f"tracker-sheet-{link.id}-complete")
    assert find_link(link.id).completed is False


async def test_a_sheet_with_a_verdict_on_every_run_is_completed(user: User, tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx", {5: "Converged", 6: "Not Converged", 7: "Converged", 8: "Failed"})
    link = _link(book, tmp_path / "wing_del0")
    await user.open("/tracker")
    await user.should_see(marker=f"tracker-sheet-{link.id}")
    assert _element(user, "tracker-groups").value == "completed"  # nothing ongoing
    assert _element(user, f"tracker-sheet-{link.id}-runs").text == "4 runs · every run has a verdict"


async def test_removing_a_sheet_from_its_row(user: User, matrix):
    book, folder = matrix
    link = _link(book, folder)
    before = book.read_bytes()
    await user.open("/tracker")
    await user.should_see(marker=f"tracker-sheet-{link.id}")
    user.find(marker=f"tracker-sheet-{link.id}-remove").click()
    await user.should_see(marker="tracker-remove-dialog")
    user.find(marker="tracker-remove-confirm").click()
    await user.should_see(marker="tracker-empty")
    assert find_link(link.id) is None and book.read_bytes() == before


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


def _with_template(book):
    """The matrix workbook plus a template sheet: a case name and a start date to give, rows for 10 runs."""
    wb = load_workbook(book)
    ws = wb.create_sheet("Case Template_v1")
    ws["A4"], ws["D4"] = "Case Name", "Baseline"
    ws["A10"], ws["D10"] = "Start Date", datetime(2026, 1, 1)
    ws["G3"], ws["M3"] = "Run ID [Auto]", "Status"
    for row in range(5, 15):
        ws.cell(row, 7, RUN_ID)
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)", "Sideslip Beta"], 1):
        ws.cell(23, column, header)
    wb.save(book)
    return book


async def test_a_new_sheet_from_the_template(user: User, matrix, eventually):
    book, folder = matrix
    _with_template(book)
    _link(book, folder)  # the form starts from the last linked workbook
    await user.open("/tracker")
    user.find(marker="tracker-new").click()
    await user.should_see(marker="tracker-new-page")
    await eventually(lambda: _element(user, "new-template").value == "Case Template_v1")
    await user.should_see(marker="new-detail-4")
    assert _element(user, "new-detail-4").value == "Baseline"
    assert _element(user, "new-detail-10").value == date.today().isoformat()  # a start date: today
    with user:
        _element(user, "new-project-wing_del0-on").set_value(True)
    await eventually(lambda: _element(user, "new-sweep-aoa").value == "0, 5")
    assert (_element(user, "new-sweep-mach").value, _element(user, "new-sweep-elevator").value) == ("0.3", "0")
    with user:
        _element(user, "new-name").set_value("study")
    await eventually(lambda: _element(user, "new-runs").text == "2")
    await user.should_see("The workbook already has a sheet named Study.")
    with user:
        _element(user, "new-name").set_value("Subsonic")
        _element(user, "new-detail-4").set_value("Subsonic sweep")
    user.find(marker="new-create").click()
    await user.should_see(marker="tracker-preview-page")
    ws = load_workbook(book)["Subsonic"]
    assert (ws["D4"].value, ws["A25"].value, ws["C26"].value) == ("Subsonic sweep", 0.3, 5)
    link = load_tracker().links[-1]
    assert (link.sheet, [p.elevator for p in link.projects]) == ("Subsonic", [0.0])

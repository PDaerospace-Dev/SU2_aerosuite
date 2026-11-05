"""Run-matrix workbooks: reading the matrix, the statuses jobs give, and writing them without losing the rest."""
import zipfile
from datetime import datetime, timedelta

import pytest
from openpyxl import Workbook, load_workbook

from aerosuite.engine.errors import TrackerError
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import save_job
from aerosuite.engine.tracker import (collect_statuses, elevator_of, has_tag, key, plan_changes, read_matrix,
                                      write_statuses)

RUN_ID = '=IF(ROW()-4>$D$14,"","RUN-"&TEXT(ROW()-4,"0000"))'
EXTRA_PART = "customXml/item1.xml"
EXTRA_BYTES = b"<FormTemplates>kept as it is</FormTemplates>"


def make_workbook(path, statuses=None, notes=None):
    """The template's layout: Run ID/Status/Notes headers in row 3, runs from row 5, the sweep table at A23."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Study"
    ws["G3"], ws["M3"], ws["N3"] = "Run ID [Auto]", "Status", "Notes"
    for row in range(5, 15):
        ws.cell(row, 7, RUN_ID)
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)",
                                     "Sideslip Beta (deg)"], start=1):
        ws.cell(23, column, header)
        ws.cell(24, column, f"=MAX(1,COUNTA({chr(64 + column)}25:{chr(64 + column)}124))")
    for column, values in enumerate([[0.3, 0.6], [0], [0, 5], [0, -20], []], start=1):
        for offset, value in enumerate(values):
            ws.cell(25 + offset, column, value)
    for row, text in (statuses or {}).items():
        ws.cell(row, 13, text)
    for row, text in (notes or {}).items():
        ws.cell(row, 14, text)
    wb.save(path)
    with zipfile.ZipFile(path, "a") as archive:  # a part openpyxl would drop on a save of its own
        archive.writestr(EXTRA_PART, EXTRA_BYTES)
    return path


def add_job(project_dir, job_id, cases, state=JobState.DONE, note="", age_hours=0):
    job = JobRecord(id=job_id, backend="local", cases=list(cases), log_path=f"jobs/{job_id}.log", state=state,
                    created=datetime(2026, 11, 1) - timedelta(hours=age_hours), case_status=dict(cases), note=note)
    save_job(project_dir, job)


@pytest.mark.parametrize("name, elevator", [("supersonic_del0", 0.0), ("subsonic_del20p", 20.0),
                                            ("supersonic_del30m", -30.0), ("supersonic_del_60m", -60.0),
                                            ("x_del2p5m_fine", -2.5)])
def test_elevator_from_the_folder_name(name, elevator):
    assert elevator_of(name) == elevator


def test_a_folder_name_without_a_deflection_is_an_error():
    with pytest.raises(TrackerError, match="=<degrees>"):
        elevator_of("baseline")


def test_tags_are_read_from_the_note_text():
    assert has_tag("subsonic 2nd order #2nd_order", "2nd_order")
    assert has_tag("#2ND_ORDER", "#2nd_order")
    assert not has_tag("#2nd_order_fine", "2nd_order")
    assert not has_tag("2nd_order", "2nd_order")


def test_the_matrix_follows_the_sheet_formulas(tmp_path):
    matrix = read_matrix(make_workbook(tmp_path / "m.xlsx", statuses={6: "Hold"}), "Study")
    assert matrix.status_column == "M"
    assert [row.row for row in matrix.rows] == list(range(5, 13))  # 2 Mach x 2 AoA x 2 elevator
    assert [row.key for row in matrix.rows[:4]] == [key(0.3, 0, 0, 0, 0), key(0.3, 0, 0, -20, 0),
                                                    key(0.3, 0, 5, 0, 0), key(0.3, 0, 5, -20, 0)]
    assert matrix.rows[4].key == key(0.6, 0, 0, 0, 0)
    assert matrix.rows[1].status == "Hold" and matrix.rows[1].run_id == "RUN-0002"


def test_a_missing_sheet_is_named(tmp_path):
    with pytest.raises(TrackerError, match="it has: Study"):
        read_matrix(make_workbook(tmp_path / "m.xlsx"), "Other")


def test_newest_job_wins_and_a_cancel_does_not_hide_a_result(tmp_path):
    project = tmp_path / "wing_del0"
    add_job(project, "old", {"M0p3_0km_a0": CaseState.CONVERGED, "M0p3_0km_a5": CaseState.CONVERGED}, age_hours=2)
    add_job(project, "new", {"M0p3_0km_a0": CaseState.UNCONVERGED, "M0p3_0km_a5": CaseState.CANCELLED,
                             "M0p6_0km_a0": CaseState.CANCELLED}, state=JobState.CANCELLED)
    statuses, warnings = collect_statuses([(project, 0.0)])
    assert warnings == []
    assert statuses[key(0.3, 0, 0, 0, 0)].status == "Not Converged"
    assert statuses[key(0.3, 0, 0, 0, 0)].job_id == "new"
    assert statuses[key(0.3, 0, 5, 0, 0)].status == "Converged"
    assert statuses[key(0.6, 0, 0, 0, 0)].status == "Hold"


def test_a_running_state_in_a_finished_job_is_stale(tmp_path):
    project = tmp_path / "wing_del0"
    add_job(project, "j", {"M0p3_0km_a0": CaseState.RUNNING})
    assert collect_statuses([(project, 0.0)])[0] == {}


def test_tags_choose_the_jobs(tmp_path):
    project = tmp_path / "wing_del0"
    add_job(project, "first", {"M0p3_0km_a0": CaseState.CONVERGED}, age_hours=2)
    add_job(project, "second", {"M0p3_0km_a0": CaseState.UNCONVERGED}, note="finer #2nd_order")
    case = key(0.3, 0, 0, 0, 0)
    assert collect_statuses([(project, 0.0)], tags=["2nd_order"])[0][case].job_id == "second"
    assert collect_statuses([(project, 0.0)], skip_tags=["#2nd_order"])[0][case].job_id == "first"


def test_cases_without_values_are_reported(tmp_path):
    project = tmp_path / "wing_del0"
    add_job(project, "j", {"mystery": CaseState.CONVERGED})
    statuses, warnings = collect_statuses([(project, 0.0)])
    assert statuses == {} and "mystery" in warnings[0]


def test_plan_keeps_diverged_and_lists_cases_outside_the_matrix(tmp_path):
    matrix = read_matrix(make_workbook(tmp_path / "m.xlsx", statuses={5: "Diverged", 6: "Running"}), "Study")
    project = tmp_path / "wing_del20m"
    add_job(project, "j", {"M0p3_0km_a0": CaseState.UNCONVERGED, "M3p0_0km_a0": CaseState.CONVERGED})
    add_job(tmp_path / "wing_del0", "k", {"M0p3_0km_a0": CaseState.FAILED})
    statuses, _ = collect_statuses([(tmp_path / "wing_del0", 0.0), (project, -20.0)])
    plan = plan_changes(matrix, statuses)
    assert plan.unchanged == 1  # row 5: Diverged stays, AeroSuite only knows it failed
    assert [(c.row.row, c.status) for c in plan.changes] == [(6, "Not Converged")]
    assert [entry.case for entry in plan.outside] == ["M3p0_0km_a0"]


def test_a_verdict_entered_by_hand_is_kept_unless_overwritten(tmp_path):
    matrix = read_matrix(make_workbook(tmp_path / "m.xlsx", statuses={5: "Converged", 6: "Converged",
                                                                      7: "Not Converged", 8: "Hold"}), "Study")
    project = tmp_path / "wing_del0"
    add_job(project, "old", {"M0p3_0km_a0": CaseState.UNCONVERGED, "M0p3_0km_a5": CaseState.CONVERGED,
                             "M0p6_0km_a0": CaseState.CANCELLED}, age_hours=1)
    add_job(tmp_path / "wing_del20m", "live", {"M0p3_0km_a0": CaseState.RUNNING}, state=JobState.RUNNING)
    statuses, _ = collect_statuses([(project, 0.0), (tmp_path / "wing_del20m", -20.0)], refresh=False)
    plan = plan_changes(matrix, statuses)
    # row 5 (a0, 0): Converged by hand, the job says Not Converged; row 6 (a0, -20): runs again
    # row 7 (a5, 0): Not Converged by hand, the job says Converged; row 9 (M0.6 a0, 0): only cancelled, blank
    assert [(c.row.row, c.status) for c in plan.kept] == [(5, "Not Converged"), (7, "Converged")]
    assert [(c.row.row, c.status) for c in plan.changes] == [(6, "Running"), (9, "Hold")]
    overwritten = plan_changes(matrix, statuses, overwrite=True)
    assert [(c.row.row, c.status) for c in overwritten.changes] == [(5, "Not Converged"), (6, "Running"),
                                                                    (7, "Converged"), (9, "Hold")]


def test_writing_changes_only_the_status_cells(tmp_path):
    path = make_workbook(tmp_path / "m.xlsx", statuses={5: "Hold"}, notes={5: "keep me", 7: "and me"})
    backup = write_statuses(path, "Study", "M", {5: "Converged", 7: "Not Converged & more"})
    wb = load_workbook(path)
    ws = wb["Study"]
    assert ws["M5"].value == "Converged" and ws["M7"].value == "Not Converged & more"
    assert ws["N5"].value == "keep me" and ws["N7"].value == "and me"
    assert ws["G5"].value == RUN_ID
    assert backup.name == "m.bak.xlsx" and load_workbook(backup)["Study"]["M5"].value == "Hold"
    with zipfile.ZipFile(path) as archive:
        assert archive.read(EXTRA_PART) == EXTRA_BYTES
        assert 'fullCalcOnLoad="1"' in archive.read("xl/workbook.xml").decode()
    assert read_matrix(path, "Study").rows[0].status == "Converged"


def test_a_workbook_open_in_excel_is_left_alone(tmp_path):
    path = make_workbook(tmp_path / "m.xlsx")
    (tmp_path / "~$m.xlsx").write_bytes(b"")
    before = path.read_bytes()
    with pytest.raises(TrackerError, match="open in Excel"):
        write_statuses(path, "Study", "M", {5: "Converged"})
    assert path.read_bytes() == before


def test_a_workbook_open_in_libreoffice_is_left_alone(tmp_path):
    path = make_workbook(tmp_path / "m.xlsx")
    (tmp_path / ".~lock.m.xlsx#").write_bytes(b"")
    before = path.read_bytes()
    with pytest.raises(TrackerError, match="open in LibreOffice"):
        write_statuses(path, "Study", "M", {5: "Converged"})
    assert path.read_bytes() == before

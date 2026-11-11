"""`aerosuite tracker sync`: a run-matrix sheet's Status column from the projects' jobs."""
from datetime import datetime

from openpyxl import Workbook, load_workbook
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import save_job
from aerosuite.engine.models import Project
from aerosuite.engine.project import save_project

runner = CliRunner()


def _workbook(path):
    """Two Mach numbers x two elevator deflections, runs from row 5 as the template lays them out."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Study"
    ws["G3"], ws["M3"], ws["N3"] = "Run ID [Auto]", "Status", "Notes"
    for row in range(5, 9):
        ws.cell(row, 7, '=IF(ROW()-4>$D$14,"","RUN-"&TEXT(ROW()-4,"0000"))')
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)", "Sideslip Beta"], 1):
        ws.cell(23, column, header)
    ws["A25"], ws["A26"], ws["B25"], ws["C25"], ws["D25"], ws["D26"] = 2.0, 3.0, 25, 0, 0, -30
    ws["N5"] = "a note"
    wb.save(path)
    return path


def _project(folder, cases):
    folder.mkdir()
    save_project(folder, Project(name=folder.name))
    save_job(folder, JobRecord(id="j1", backend="local", cases=list(cases), log_path="jobs/j1.log",
                               state=JobState.DONE, created=datetime(2026, 11, 1), case_status=cases))
    return folder


def test_sync_writes_the_status_column(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    del0 = _project(tmp_path / "wing_del0", {"M2p0_25km_a0": CaseState.CONVERGED})
    del30 = _project(tmp_path / "wing_del30m", {"M3p0_25km_a0": CaseState.UNCONVERGED,
                                                "M4p0_25km_a0": CaseState.CONVERGED})
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), str(del30)])
    assert result.exit_code == 0, result.output
    assert "RUN-0001" in result.output and "-> Converged" in result.output
    assert "2 run(s) to change, 0 unchanged, 2 with no job" in result.output
    assert "1 case(s) are not in the sheet's run matrix: wing_del30m/M4p0_25km_a0" in result.output
    ws = load_workbook(book)["Study"]
    assert [ws.cell(row, 13).value for row in range(5, 9)] == ["Converged", None, None, "Not Converged"]
    assert ws["N5"].value == "a note"
    assert (tmp_path / "matrix.bak.xlsx").is_file()

    again = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), str(del30)])
    assert "0 run(s) to change, 2 unchanged" in again.output
    assert "Saved" not in again.output


def test_dry_run_leaves_the_workbook_alone(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    before = book.read_bytes()
    del0 = _project(tmp_path / "wing_del0", {"M2p0_25km_a0": CaseState.CONVERGED})
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output and book.read_bytes() == before


def test_the_deflection_can_be_given_for_any_folder_name(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    folder = _project(tmp_path / "baseline", {"M2p0_25km_a0": CaseState.FAILED})
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", f"{folder}=-30"])
    assert result.exit_code == 0, result.output
    assert load_workbook(book)["Study"]["M6"].value == "Failed"


def test_errors_are_one_line(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    folder = _project(tmp_path / "baseline", {})
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(folder)])
    assert result.exit_code == 1
    assert "Error: Cannot tell the elevator deflection" in result.output
    result = runner.invoke(app, ["tracker", "sync", str(book), "Nope", f"{folder}=0"])
    assert result.exit_code == 1 and "No sheet 'Nope'" in result.output


def test_hand_verdicts_are_listed_on_a_dry_run_and_replaced_with_overwrite(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    wb = load_workbook(book)
    wb["Study"]["M5"] = "Converged"
    wb.save(book)
    del0 = _project(tmp_path / "wing_del0", {"M2p0_25km_a0": CaseState.UNCONVERGED})
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), "--dry-run"])
    assert "RUN-0001" in result.output and "Converged kept, the job says Not Converged" in result.output
    assert "1 verdict(s) entered by hand differ" in result.output
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), "--overwrite"])
    assert result.exit_code == 0, result.output
    assert load_workbook(book)["Study"]["M5"].value == "Not Converged"


def test_order_takes_only_the_cases_run_at_that_order(tmp_path):
    book = _workbook(tmp_path / "matrix.xlsx")
    del0 = _project(tmp_path / "x_del0", {"M2p0_25km_a0": CaseState.CONVERGED, "M3p0_25km_a0": CaseState.CONVERGED})
    configs = del0 / "jobs" / "j1" / "configs"
    configs.mkdir(parents=True)
    (configs / "M2p0_25km_a0.cfg").write_text("MUSCL_FLOW= NO\n")
    (configs / "M3p0_25km_a0.cfg").write_text("MUSCL_FLOW= YES\n")
    result = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), "--order", "2nd", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "M3p0_25km_a0" in result.output and "M2p0_25km_a0" not in result.output
    bad = runner.invoke(app, ["tracker", "sync", str(book), "Study", str(del0), "--order", "3rd"])
    assert bad.exit_code != 0 and "give 1st or 2nd" in bad.output


def _with_template(path):
    """The workbook with a template sheet to copy: a case name in D4, rows for 10 runs, the sweep table empty."""
    _workbook(path)
    wb = load_workbook(path)
    ws = wb.create_sheet("Case Template_v1")
    ws["A4"], ws["D4"] = "Case Name", "Baseline"
    ws["A9"] = "Notes"
    ws["G3"], ws["M3"] = "Run ID [Auto]", "Status"
    for row in range(5, 15):
        ws.cell(row, 7, '=IF(ROW()-4>$D$14,"","RUN-"&TEXT(ROW()-4,"0000"))')
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)", "Sideslip Beta"], 1):
        ws.cell(23, column, header)
    wb.save(path)
    return path


def test_new_sheet_copies_the_template_with_the_projects_sweep(tmp_path):
    book = _with_template(tmp_path / "matrix.xlsx")
    del0 = _project(tmp_path / "wing_del0", {"M2p0_25km_a0": CaseState.CONVERGED, "M3p0_25km_a0": CaseState.FAILED})
    dry = runner.invoke(app, ["tracker", "new-sheet", str(book), "Supersonic", str(del0), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Mach: 2, 3" in dry.output and "a copy of Case Template_v1, 2 runs (it has rows for 10)" in dry.output
    assert "Supersonic" not in load_workbook(book).sheetnames
    result = runner.invoke(app, ["tracker", "new-sheet", str(book), "Supersonic", str(del0), "--aoa", "0, 5",
                                 "--detail", "notes=first order", "--detail", "case=Supersonic sweep"])
    assert result.exit_code == 0, result.output
    assert "4 runs" in result.output and "Linked" in result.output
    ws = load_workbook(book)["Supersonic"]
    assert (ws["D4"].value, ws["D9"].value, ws["A25"].value, ws["C26"].value) == (
        "Supersonic sweep", "first order", 2, 5)
    synced = runner.invoke(app, ["tracker", "sync", str(book), "Supersonic", str(del0)])
    assert "2 run(s) to change" in synced.output


def test_new_sheet_refuses_a_taken_name_or_an_unknown_detail(tmp_path):
    book = _with_template(tmp_path / "matrix.xlsx")
    del0 = _project(tmp_path / "wing_del0", {"M2p0_25km_a0": CaseState.CONVERGED})
    result = runner.invoke(app, ["tracker", "new-sheet", str(book), "study", str(del0)])
    assert result.exit_code == 1 and "already has a sheet named Study" in result.output
    result = runner.invoke(app, ["tracker", "new-sheet", str(book), "New", str(del0), "--detail", "mesh=fine"])
    assert result.exit_code == 1 and "'mesh' matches 0 of Case Template_v1's details: Case Name, Notes" in result.output

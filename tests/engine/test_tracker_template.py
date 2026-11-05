"""New run-matrix sheets copied from a workbook's template sheet, inside the file, everything else kept."""
import re
import zipfile
from datetime import datetime

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from test_tracker import RUN_ID, add_job, make_workbook

from aerosuite.engine.errors import TrackerError
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.tracker import (Detail, _listed, detail_value, new_sheet, parse_values, project_levels,
                                      read_matrix, read_template, sheet_name_problem, template_sheets)

TEMPLATE = "Case Template_v1"
DRAWING = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats'
           '.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
           '<!-- the How to use text box --></xdr:wsDr>')
# the workbook's lists of sheets and parts (docProps/app.xml too, but openpyxl's has no list of sheets to add to)
INDEX_PARTS = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml"}


def make_template(path):
    """A workbook laid out as the CFD run-matrix one: an old hidden template, the template (case details in D4-D10, the
    scorecard's formula in D14, 10 run rows, the sweep table at A23, a text box) and a case sheet."""
    wb = Workbook()
    old = wb.active
    old.title = "Case Template"
    old.sheet_state = "hidden"
    ws = wb.create_sheet(TEMPLATE)
    ws["A3"] = "1. CASE CONFIGURATION"
    ws.merge_cells("A3:E3")
    for row, label, value in ((4, "Case Name", "Baseline sweep"), (7, "Reference Area S_ref (m²)", 1),
                              (9, "Notes", None), (10, "Start Date", datetime(2026, 1, 2))):
        ws.cell(row, 1, label)
        ws.cell(row, 4, value)
    ws["A14"], ws["D14"] = "Total Runs", "=IF(COUNTA(A25:E124)=0,0,A24*B24*C24*D24*E24)"
    ws["G3"], ws["M3"], ws["N3"] = "Run ID [Auto]", "Status", "Notes"
    for row in range(5, 15):
        ws.cell(row, 7, RUN_ID)
        ws.cell(row, 8, f"=IF($G{row}=\"\",\"\",'{TEMPLATE}'!$A$25)")  # a reference to itself by name
    ws["M5"] = "Pending"  # left in the template: the copy starts empty
    for column, header in enumerate(["Mach", "Altitude (km)", "AoA (deg)", "Elevator Def (deg)",
                                     "Sideslip Beta (deg)"], start=1):
        ws.cell(23, column, header)
        ws.cell(24, column, f"=MAX(1,COUNTA({chr(64 + column)}25:{chr(64 + column)}124))")
    ws["C25"] = 99  # an example value in the template, not in the new sweep
    status = DataValidation(type="list", formula1='"Pending,Running,Converged"')
    status.add("M4:M14")
    ws.add_data_validation(status)
    ws.auto_filter.ref = "G3:M3"
    make_workbook(path)
    case = load_workbook(path)["Study"]
    target = wb.create_sheet("Study")
    for row in case.iter_rows():
        for cell in row:
            target[cell.coordinate] = cell.value
    wb.save(path)
    _add_text_box(path)
    return path


def _add_text_box(path):
    """Give the template sheet a drawing part (Excel's text box), which openpyxl cannot write."""
    with zipfile.ZipFile(path) as archive:
        parts = {info.filename: archive.read(info) for info in archive.infolist()}
    sheet = "xl/worksheets/sheet2.xml"
    parts[sheet] = parts[sheet].replace(b"</worksheet>", b'<drawing r:id="rId1"/></worksheet>')
    if b'xmlns:r=' not in parts[sheet][:500]:
        parts[sheet] = parts[sheet].replace(
            b"<worksheet ", b'<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ',
            1)
    parts["xl/worksheets/_rels/sheet2.xml.rels"] = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.'
        b'org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        b'officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
    parts["xl/drawings/drawing1.xml"] = DRAWING.encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b'<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-'
                     b'officedocument.drawing+xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)


@pytest.fixture
def book(tmp_path):
    return make_template(tmp_path / "matrix.xlsx")


def _parts(path):
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def test_the_template_is_found_and_described(book):
    assert template_sheets(book) == [TEMPLATE, "Case Template"]  # the visible one first
    template = read_template(book, TEMPLATE)
    assert [(d.row, d.label) for d in template.details] == [
        (4, "Case Name"), (7, "Reference Area S_ref (m²)"), (9, "Notes"), (10, "Start Date")]  # no heading, no formula
    assert (template.sweep_row, template.runs, template.status_column, template.first_row) == (23, 10, "M", 5)


def test_a_new_sheet_is_a_filled_in_copy_and_the_rest_is_kept(book):
    before = _parts(book)
    backup = new_sheet(book, TEMPLATE, "Transonic", {4: "Transonic sweep", 7: 11.996, 10: datetime(2026, 11, 5)},
                       [[0.9, 1.1], [0.0], [0.0, 5.0], [-20.0, 0.0], [0.0]])
    assert backup.name == "matrix.bak.xlsx"
    after = _parts(book)
    assert {name for name in before if before[name] != after[name]} == INDEX_PARTS
    assert set(after) - set(before) == {"xl/worksheets/sheet4.xml", "xl/worksheets/_rels/sheet4.xml.rels",
                                        "xl/drawings/drawing2.xml"}
    assert after["xl/drawings/drawing2.xml"] == DRAWING.encode()  # the copy has its own text box
    assert b"drawing2.xml" in after["xl/worksheets/_rels/sheet4.xml.rels"]
    assert b'PartName="/xl/drawings/drawing2.xml"' in after["[Content_Types].xml"]

    wb = load_workbook(book)
    assert wb.sheetnames == ["Case Template", TEMPLATE, "Study", "Transonic"]
    ws = wb["Transonic"]
    assert (ws["D4"].value, ws["D7"].value, ws["D10"].value) == ("Transonic sweep", 11.996, datetime(2026, 11, 5))
    assert ws["D14"].value.startswith("=IF(COUNTA")  # the formulas come along
    assert ws["H5"].value == "=IF($G5=\"\",\"\",'Transonic'!$A$25)"  # its own, not the template's
    assert ws["M5"].value is None and ws["C27"].value is None  # Status empty, the template's example gone
    assert [str(v.sqref) for v in ws.data_validations.dataValidation] == ["M4:M14"]
    assert wb[TEMPLATE]["D4"].value == "Baseline sweep"  # the template itself is untouched
    matrix = read_matrix(book, "Transonic")
    assert len(matrix.rows) == 8 and matrix.levels[0] == [0.9, 1.1]

    book_xml = after["xl/workbook.xml"].decode()
    assert re.search(r"""<definedName [^>]*localSheetId="3"[^>]*>'Transonic'!\$G\$3:\$M\$3</definedName>""", book_xml)
    assert 'fullCalcOnLoad="1"' in book_xml
    sheet_xml = after["xl/worksheets/sheet4.xml"].decode()
    assert "tabSelected" not in sheet_xml


@pytest.mark.parametrize("name, problem", [("study", "already has a sheet named Study"), ("x" * 32, "at most 31"),
                                           ("a/b", "cannot contain"), ("'quoted'", "apostrophe"), ("", "a name"),
                                           ("History", "keeps the name")])
def test_names_excel_would_refuse(book, name, problem):
    assert problem in sheet_name_problem(book, name)
    with pytest.raises(TrackerError, match=problem):
        new_sheet(book, TEMPLATE, name, {}, [[0.3], [], [], [], []])


def test_a_sweep_the_template_cannot_hold_is_refused(book):
    with pytest.raises(TrackerError, match="makes 12 runs; Case Template_v1 has rows for 10"):
        new_sheet(book, TEMPLATE, "Big", {}, [[0.3, 0.6, 0.9], [0.0, 10.0], [0.0, 5.0], [], []])
    with pytest.raises(TrackerError, match="given twice"):
        new_sheet(book, TEMPLATE, "Twice", {}, [[0.3, 0.3], [], [], [], []])
    with pytest.raises(TrackerError, match="no case detail"):
        new_sheet(book, TEMPLATE, "Row", {14: "x"}, [[0.3], [], [], [], []])


def test_a_workbook_open_in_excel_gets_no_new_sheet(book):
    book.with_name("~$" + book.name).write_bytes(b"")
    with pytest.raises(TrackerError, match="open in Excel"):
        new_sheet(book, TEMPLATE, "New", {}, [[0.3], [], [], [], []])


def test_the_sweep_comes_from_the_projects_cases(tmp_path):
    folder = tmp_path / "wing_del20p"
    add_job(folder, "j1", {"M0p9_10km_a5": CaseState.CONVERGED, "M1p1_0km_a0_b2": CaseState.RUNNING})
    (folder / "configs").mkdir()
    (folder / "configs" / "cases.json").write_text('{"M0p6_0km_a5": {"mach": 0.6, "alpha": 5, "altitude_km": 0}}')
    (folder / "runs" / "M0p9_10km_a10").mkdir(parents=True)
    other = tmp_path / "wing_del0"
    add_job(other, "j2", {"M0p9_10km_a5": CaseState.CONVERGED})
    assert project_levels([(folder, 20.0), (other, 0.0)]) == [
        [0.6, 0.9, 1.1], [0.0, 10.0], [0.0, 5.0, 10.0], [0.0, 20.0], [0.0, 2.0]]


def test_details_and_sweep_values_typed_as_text():
    assert parse_values("0.3, 0.6 0.9;1.1", "Mach") == [0.3, 0.6, 0.9, 1.1]
    with pytest.raises(TrackerError, match="Mach: give numbers"):
        parse_values("0.3, fast", "Mach")
    assert detail_value(Detail(7, "S_ref", 1), " 11.996 ") == 11.996
    assert detail_value(Detail(10, "Start", datetime(2026, 1, 1)), "2026-11-05") == datetime(2026, 11, 5)
    assert detail_value(Detail(9, "Notes", None), "  ") is None
    with pytest.raises(TrackerError, match="Start: give a date"):
        detail_value(Detail(10, "Start", datetime(2026, 1, 1)), "5 Nov")


def test_the_sheet_is_added_to_the_document_properties():
    app = ('<Properties><HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Worksheets'
           '</vt:lpstr></vt:variant><vt:variant><vt:i4>2</vt:i4></vt:variant></vt:vector></HeadingPairs>'
           '<TitlesOfParts><vt:vector size="2" baseType="lpstr"><vt:lpstr>A</vt:lpstr><vt:lpstr>B</vt:lpstr>'
           '</vt:vector></TitlesOfParts></Properties>')
    listed = _listed(app, "C & D")
    assert "<vt:i4>3</vt:i4>" in listed
    assert '<vt:vector size="3" baseType="lpstr"><vt:lpstr>A</vt:lpstr><vt:lpstr>B</vt:lpstr><vt:lpstr>C &amp; D' \
           '</vt:lpstr></vt:vector>' in listed
    assert _listed("<Properties/>", "C") == "<Properties/>"

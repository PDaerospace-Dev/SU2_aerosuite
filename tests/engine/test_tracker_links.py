"""Linked run-matrix sheets: saving them, what each would write, writing it and the log."""
import pytest
from openpyxl import load_workbook
from test_tracker import add_job, make_workbook

from aerosuite.engine.errors import TrackerError
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.tracker_links import (Link, LinkedProject, candidate_projects, create_sheet, find_link,
                                            load_tracker, remove_link, report, save_link, set_auto, write_link)


def _link(tmp_path, **changes):
    book = make_workbook(tmp_path / "m.xlsx", statuses={5: "Converged"})
    add_job(tmp_path / "wing_del0", "j", {"M0p3_0km_a0": CaseState.UNCONVERGED, "M0p3_0km_a5": CaseState.CONVERGED,
                                          "M3p0_0km_a0": CaseState.CONVERGED})
    return Link(workbook=str(book), sheet="Study",
                projects=[LinkedProject(path=str(tmp_path / "wing_del0"), elevator=0)], **changes)


def test_links_are_saved_replaced_and_removed(tmp_path):
    link = save_link(_link(tmp_path))
    assert find_link(link.id) == link
    save_link(link.model_copy(update={"sheet": "Other"}))
    assert [saved.sheet for saved in load_tracker().links] == ["Other"]
    set_auto([link.id], False)
    assert find_link(link.id).auto is False
    remove_link(link.id)
    assert load_tracker().links == []


def test_the_report_counts_what_would_be_written(tmp_path):
    result = report(_link(tmp_path))
    assert result.error == ""
    assert [(c.row.row, c.status) for c in result.plan.changes] == [(7, "Converged")]
    assert [(c.row.row, c.status) for c in result.plan.kept] == [(5, "Not Converged")]
    assert [entry.case for entry in result.plan.outside] == ["M3p0_0km_a0"]
    assert result.no_job == 6 and result.sheet_counts["Converged"] == 1
    project = result.projects[0]
    assert (project.jobs_chosen, project.jobs, project.matched) == (1, 1, 2)


def test_a_missing_workbook_is_the_reports_error(tmp_path):
    link = _link(tmp_path).model_copy(update={"workbook": str(tmp_path / "gone.xlsx")})
    assert "gone.xlsx" in report(link).error


def test_writing_takes_the_changes_and_the_verdicts_the_user_accepted(tmp_path):
    link = _link(tmp_path)
    kept = report(link).plan.kept
    assert write_link(link, accepted=kept) == 2
    ws = load_workbook(link.workbook)["Study"]
    assert (ws["M5"].value, ws["M7"].value) == ("Not Converged", "Converged")
    entry = load_tracker().log[0]
    assert (entry.written, entry.trigger, entry.error) == (2, "manual", "")


def test_a_failed_write_is_logged(tmp_path):
    link = _link(tmp_path)
    (tmp_path / "~$m.xlsx").write_bytes(b"")
    with pytest.raises(TrackerError, match="open in Excel"):
        write_link(link, trigger="auto")
    assert "open in Excel" in load_tracker().log[0].error


def test_nothing_to_write_automatically_is_not_logged(tmp_path):
    link = _link(tmp_path)
    write_link(link, trigger="auto")
    assert write_link(link, trigger="auto") == 0
    assert len(load_tracker().log) == 1


def test_candidates_are_the_projects_beside_the_workbook(tmp_path):
    from aerosuite.engine.models import Project
    from aerosuite.engine.project import save_project

    for name in ("b_del0", "a_del20p"):
        (tmp_path / name).mkdir()
        save_project(tmp_path / name, Project(name=name))
    (tmp_path / "not_a_project").mkdir()
    found = candidate_projects(str(tmp_path / "m.xlsx"), extra=[str(tmp_path / "elsewhere")])
    assert [path.name for path in found] == ["a_del20p", "b_del0", "elsewhere"]


def test_a_new_sheet_is_linked_and_logged(tmp_path):
    from test_tracker_template import TEMPLATE, make_template

    book = make_template(tmp_path / "m.xlsx")
    add_job(tmp_path / "wing_del0", "j", {"M0p3_0km_a0": CaseState.CONVERGED})
    link = Link(workbook=str(book), sheet="New", projects=[LinkedProject(path=str(tmp_path / "wing_del0"), elevator=0)])
    create_sheet(link, TEMPLATE, {9: "made by a test"}, [[0.3, 0.6], [0.0], [0.0], [0.0], [0.0]])
    assert find_link(link.id) == link
    assert (load_tracker().log[0].trigger, load_tracker().log[0].sheet) == ("new-sheet", "New")
    assert [(c.row.row, c.status) for c in report(link).plan.changes] == [(5, "Converged")]
    create_sheet(link.model_copy(update={"id": "other", "sheet": "Unlinked"}), TEMPLATE, {}, [[0.3], [], [], [], []],
                 keep=False)
    assert [saved.sheet for saved in load_tracker().links] == ["New"]

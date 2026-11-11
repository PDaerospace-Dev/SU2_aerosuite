"""Linked run-matrix sheets: saving them, what each would write, writing it and the log."""
import json
from datetime import datetime

import pytest
from openpyxl import load_workbook
from test_tracker import add_job, make_workbook

from aerosuite.engine.errors import TrackerError
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.tracker import read_matrix
from aerosuite.engine.tracker_links import (Link, LinkedProject, LogEntry, RunEdit, backup_file, candidate_projects,
                                            create_sheet, edit_runs, find_link, link_stamp, load_tracker, log_write,
                                            remove_link, report, save_link, saved_links, set_auto, set_completed,
                                            tracker_file, write_link)


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


def test_closing_libreoffice_changes_the_stamp(tmp_path):
    link = _link(tmp_path)
    lock = tmp_path / ".~lock.m.xlsx#"
    lock.write_bytes(b"")
    with pytest.raises(TrackerError, match="open in LibreOffice"):
        write_link(link, trigger="auto")
    stamp = link_stamp(link)
    lock.unlink()
    assert link_stamp(link) != stamp  # the watcher tries the write again
    assert write_link(link, trigger="auto") == 1


def _every_run(tmp_path, completed=None, last=CaseState.CONVERGED):
    """A sheet with a "Completed on" detail, and jobs with a verdict for each of its 8 runs."""
    book = make_workbook(tmp_path / "m.xlsx", completed=completed)
    cases = {f"M{m}_0km_a{a}": CaseState.CONVERGED for m in ("0p3", "0p6") for a in (0, 5)}
    add_job(tmp_path / "wing_del0", "j", cases, finished=datetime(2026, 11, 3, 18))
    add_job(tmp_path / "wing_del20m", "k", cases | {"M0p6_0km_a5": last}, finished=datetime(2026, 11, 4, 9))
    return Link(workbook=str(book), sheet="Study",
                projects=[LinkedProject(path=str(tmp_path / "wing_del0"), elevator=0),
                          LinkedProject(path=str(tmp_path / "wing_del20m"), elevator=-20)])


def test_completed_on_is_the_day_the_last_job_ended(tmp_path):
    link = _every_run(tmp_path, last=CaseState.UNCONVERGED)
    assert report(link).completed_on == datetime(2026, 11, 4).date()
    assert write_link(link, trigger="auto") == 8
    assert load_workbook(link.workbook)["Study"]["D11"].value == datetime(2026, 11, 4)
    assert load_tracker().log[0].completed_on == datetime(2026, 11, 4).date()
    assert report(link).completed_on is None  # filled in: it stays as it is


def test_completed_on_waits_for_every_verdict(tmp_path):
    link = _every_run(tmp_path, last=CaseState.RUNNING)
    write_link(link)
    assert load_workbook(link.workbook)["Study"]["D11"].value is None


def test_a_completion_date_entered_by_hand_stays(tmp_path):
    link = _every_run(tmp_path, completed=datetime(2026, 11, 2))
    assert report(link).completed_on is None
    write_link(link)
    assert load_workbook(link.workbook)["Study"]["D11"].value == datetime(2026, 11, 2)


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


def test_a_sheet_is_completed_by_its_runs_or_by_hand(tmp_path):
    link = save_link(_link(tmp_path))
    assert not report(link).done  # runs without a verdict
    set_completed(link.id, True)
    assert report(find_link(link.id)).done
    set_completed(link.id, None)
    every = make_workbook(tmp_path / "all.xlsx", statuses={row: "Converged" for row in range(5, 13)})
    whole = save_link(Link(workbook=str(every), sheet="Study"))
    assert report(whole).done
    set_completed(whole.id, False)
    assert not report(find_link(whole.id)).done


def test_status_and_notes_are_set_by_hand_and_logged(tmp_path):
    link = _link(tmp_path)
    assert edit_runs(link, {"RUN-0001": RunEdit(status="Diverged", notes="  blows up at 3k  "),
                            "RUN-0002": RunEdit(notes="check the mesh"),
                            "RUN-0003": RunEdit(status="")}) == 2  # RUN-0003 is blank already
    matrix = read_matrix(link.workbook, "Study")
    assert [(row.status, row.notes) for row in matrix.rows[:3]] == [("Diverged", "blows up at 3k"),
                                                                     ("", "check the mesh"), ("", "")]
    assert matrix.notes_column == "N"
    entry = load_tracker().log[0]
    assert (entry.written, entry.trigger) == (2, "edit")
    assert load_workbook(link.workbook)["Study"]["N24"].value is None  # nothing else moved


def test_a_verdict_set_by_hand_is_kept_by_later_writes(tmp_path):
    link = _link(tmp_path)
    edit_runs(link, {"RUN-0003": RunEdit(status="Failed")})  # the job says Converged
    assert [(c.row.row, c.status) for c in report(link).plan.kept] == [(5, "Not Converged"), (7, "Converged")]
    write_link(link)
    assert load_workbook(link.workbook)["Study"]["M7"].value == "Failed"


def test_nothing_changed_is_not_logged(tmp_path):
    link = _link(tmp_path)
    assert edit_runs(link, {"RUN-0001": RunEdit(status="Converged", notes="")}) == 0
    assert load_tracker().log == []


@pytest.mark.parametrize("edit, words", [(RunEdit(status="Running"), "not a status"),
                                         (RunEdit(status="Converged"), "RUN-0099 is not a run")])
def test_a_bad_edit_is_refused(tmp_path, edit, words):
    link = _link(tmp_path)
    run_id = "RUN-0099" if "RUN-0099" in words else "RUN-0001"
    with pytest.raises(TrackerError, match=words):
        edit_runs(link, {run_id: edit})


def test_a_notes_formula_is_left_to_excel(tmp_path):
    link = _link(tmp_path)
    book = load_workbook(link.workbook)
    book["Study"]["N5"] = '=IF(M5="","",M5)'
    book.save(link.workbook)
    with pytest.raises(TrackerError, match="formula"):
        edit_runs(link, {"RUN-0001": RunEdit(notes="mine")})


def test_an_edit_waits_for_excel_to_close(tmp_path):
    link = _link(tmp_path)
    (tmp_path / "~$m.xlsx").write_bytes(b"")
    with pytest.raises(TrackerError, match="open in Excel"):
        edit_runs(link, {"RUN-0001": RunEdit(status="Diverged")})
    assert load_tracker().log[0].trigger == "edit"


def test_a_tracker_file_that_cannot_be_read_is_never_saved_over(tmp_path):
    link = save_link(_link(tmp_path))
    good = tracker_file().read_text()
    tracker_file().write_text(good[:len(good) // 2])  # cut short: a full disk, a bad copy
    with pytest.raises(TrackerError, match="cannot be read"):
        load_tracker()
    for change in (lambda: save_link(link), lambda: remove_link(link.id), lambda: set_auto([link.id], False),
                   lambda: log_write(LogEntry(link=link.id, workbook="m.xlsx", sheet="Study"))):
        with pytest.raises(TrackerError, match="tracker.json.bak"):
            change()
    assert tracker_file().read_text() == good[:len(good) // 2]  # left for repair, not replaced by an empty tracker
    assert saved_links() == [] and find_link(link.id) is None  # conveniences go without


def test_the_file_before_a_save_is_kept_as_a_backup(tmp_path):
    link = save_link(_link(tmp_path))
    before = tracker_file().read_text()
    set_auto([link.id], False)
    assert backup_file().read_text() == before and find_link(link.id).auto is False


def test_settings_a_newer_aerosuite_wrote_survive_a_save(tmp_path):
    link = save_link(_link(tmp_path))
    data = json.loads(tracker_file().read_text())
    data["links"][0]["from_the_future"] = {"a": 1}
    data["shared"] = True
    tracker_file().write_text(json.dumps(data))
    set_completed(link.id, True)
    saved = json.loads(tracker_file().read_text())
    assert saved["links"][0]["from_the_future"] == {"a": 1} and saved["shared"] is True
    assert saved["links"][0]["completed"] is True

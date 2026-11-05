"""The note on the Run page: the field, the tag list under it, the config changes line and the last job's note."""
import pytest
from nicegui import ui
from nicegui.testing import User

from aerosuite.engine import tags
from aerosuite.engine.jobs.plan import prepare_job
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import list_jobs, save_job
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


@pytest.fixture
def su2_env(monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


async def _open(user, project_dir):
    await user.open(project_url("run", project_dir))
    await user.should_see(marker="run-panel")


def _seed_tags():
    """Three projects' worth of notes: cfl-low twice, cfl-high once, fine once."""
    tags.load_index()
    for note in ("#cfl-low", "#cfl-low #fine", "#cfl-high"):
        tags.note_changed("/elsewhere", "", note)


def _earlier_job(project_dir, project, **values):
    """A finished job from yesterday whose configs are the current ones."""
    from aerosuite.engine.cfg import generate_configs

    generate_configs(project_dir, project)
    prepare_job(project_dir, project, "20261101-0900", [A0, A2, A4])
    job = JobRecord(id="20261101-0900", backend="local", cases=[A0, A2, A4], log_path="jobs/20261101-0900.log",
                    state=JobState.DONE, case_status={name: CaseState.CONVERGED for name in (A0, A2, A4)}, **values)
    save_job(project_dir, job)
    return job


async def test_the_note_field_is_one_optional_line_above_submit(user: User, ready_project, su2_env):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    note = _element(user, "run-note")
    assert note.props["placeholder"] == "Add a note…" and note.props.get("label") is None
    assert "autogrow" in note.props and "underlined" in note.props and note.value == ""
    assert _element(user, "submit").id > note.id  # drawn before the button
    assert _element(user, "submit").enabled  # a note is never required


async def test_a_typed_note_is_saved_with_the_job_and_its_tags_with_the_index(
        user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="run-note").type("coarse mesh #first-try")
    user.find(marker="submit").click()
    await eventually(lambda: bool(list_jobs(project_dir)), 15)
    assert list_jobs(project_dir)[0].note == "coarse mesh #first-try"
    assert tags.load_index()["first-try"]["count"] == 1


async def test_typing_a_hash_lists_the_tags_most_used_first_and_enter_picks_the_first(user: User, ready_project, su2_env):
    project_dir, _ = ready_project
    _seed_tags()
    await _open(user, project_dir)
    await user.should_not_see(marker="note-menu-foot")
    user.find(marker="run-note").type("try #cfl")
    await user.should_see(marker="note-tag-cfl-low")
    rows = [m for m in ("note-tag-cfl-low", "note-tag-cfl-high") if user.find(marker=m).elements]
    assert rows == ["note-tag-cfl-low", "note-tag-cfl-high"]
    assert "as-note-row-on" in _element(user, "note-tag-cfl-low").classes  # the first is highlighted
    assert "as-note-row-on" not in _element(user, "note-tag-cfl-high").classes
    row = _element(user, "note-tag-cfl-low")
    assert [c.text for c in row.default_slot.children if not isinstance(c, ui.space)] == ["#cfl-low", "all projects", "2 jobs"]
    assert _text(user, "note-menu-foot") == "Enter to pick · keep typing to create #cfl"
    user.find(marker="run-note").trigger("keydown", {"key": "ArrowDown"})
    assert "as-note-row-on" in _element(user, "note-tag-cfl-high").classes
    user.find(marker="run-note").trigger("keydown", {"key": "Enter"})
    assert _element(user, "run-note").value == "try #cfl-high "


async def test_an_unknown_tag_is_allowed_and_enter_keeps_it(user: User, ready_project, su2_env):
    project_dir, _ = ready_project
    _seed_tags()
    await _open(user, project_dir)
    user.find(marker="run-note").type("#brand-new")
    assert _text(user, "note-menu-foot") == "Enter to pick · keep typing to create #brand-new"
    user.find(marker="run-note").trigger("keydown", {"key": "Tab"})
    assert _element(user, "run-note").value == "#brand-new "
    user.find(marker="run-note").type("and more")
    await user.should_not_see(marker="note-menu-foot")  # a finished tag closes the list


async def test_the_changes_since_the_last_run_are_one_grey_line_that_opens(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _earlier_job(project_dir, project)
    await _open(user, project_dir)
    user.find(marker="select-all").click()  # everything ran: nothing is selected at first
    await user.should_not_see(marker="run-changes")  # nothing changed
    template = project_dir / "template.cfg"
    template.write_text(template.read_text() + "ITER= 500\n")
    await _open(user, project_dir)
    user.find(marker="select-all").click()
    assert _text(user, "run-changes-text") == "Note · 1 config change since last run"
    await user.should_not_see(marker="run-changes-list")
    user.find(marker="run-changes").click()
    await user.should_see(marker="run-changes-list")
    assert [c.text for c in _element(user, "run-changes-list").default_slot.children] == ["ITER= — → 500 · 3 cases"]


async def test_the_last_job_banner_quotes_its_note_and_outcome(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="last-job-note")
    _earlier_job(project_dir, project, note="lower CFL #cfl-low", outcome="converged in 900 iterations")
    await _open(user, project_dir)
    note = _element(user, "last-job-note")
    assert note.content == '“lower CFL <span class="as-hash">#cfl-low</span>” → converged in 900 iterations'
    assert "as-job-note" in note.classes


async def test_a_last_job_without_a_note_shows_no_note_line(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _earlier_job(project_dir, project)
    await _open(user, project_dir)
    await user.should_see(marker="last-job")
    await user.should_not_see(marker="last-job-note")

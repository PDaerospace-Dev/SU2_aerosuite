"""A job's note and outcome, the #tags in them, the tag index and the config changes since the last run."""
import json

from aerosuite.engine import tags
from aerosuite.engine.cfg import generate_configs, read_template
from aerosuite.engine.home import aerosuite_home
from aerosuite.engine.jobs.changes import config_changes, parameters
from aerosuite.engine.jobs.plan import prepare_job
from aerosuite.engine.jobs.rerun import rerun_changes
from aerosuite.engine.jobs.runner import JobRecord, note_tags
from aerosuite.engine.jobs.store import JOBS_DIR, list_jobs, load_job, save_job
from aerosuite.engine.project import save_project
from aerosuite.web.recent import add_recent

from slurm_helpers import A0, A2, A4, slurm_study  # noqa: F401  (fixture)


def _job(job_id="20261102-1002", **values):
    return JobRecord(id=job_id, backend="slurm", cases=[A0], log_path=f"{JOBS_DIR}/{job_id}.log", **values)


def test_a_new_record_has_an_empty_note_and_outcome(tmp_path):
    job = _job()
    assert (job.note, job.outcome, job.tags) == ("", "", [])


def test_a_record_from_before_notes_still_loads(tmp_path):
    save_job(tmp_path, _job())
    path = tmp_path / JOBS_DIR / "20261102-1002.json"
    old = json.loads(path.read_text())
    del old["note"], old["outcome"]
    path.write_text(json.dumps(old))
    job = load_job(tmp_path, "20261102-1002")
    assert (job.note, job.outcome) == ("", "")


def test_tags_are_the_hash_words_of_a_note_once_each_in_order():
    assert note_tags("fine mesh #wing-v2, retry #fine #wing-v2 and #Big #a_b #12") == ["wing-v2", "fine", "big", "a_b"]
    assert note_tags("#2nd_order run, not #1st_Order or job #3") == ["2nd_order", "1st_order"]
    assert note_tags("") == [] and note_tags("no tags # here") == []
    assert _job(note="try #cfl-low").tags == ["cfl-low"]


def test_a_submit_keeps_the_note_and_annotate_edits_it(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0], note="  lower CFL #cfl  ")
    assert job.note == "lower CFL #cfl" and load_job(project_dir, job.id).note == "lower CFL #cfl"
    fake.run("101")
    runner.refresh(project_dir, job)  # the poller saves the record under the same lock
    _before, saved = runner.annotate(project_dir, job.id, outcome="converged in 900 iterations")
    assert (saved.note, saved.outcome) == ("lower CFL #cfl", "converged in 900 iterations")
    before, saved = runner.annotate(project_dir, job.id, note="")
    assert (before, saved.note, saved.outcome) == ("lower CFL #cfl", "", "converged in 900 iterations")
    before, saved = runner.annotate(project_dir, job.id, note="second order", append=True)
    assert (before, saved.note) == ("", "second order")  # appended to nothing: just the note
    _before, saved = runner.annotate(project_dir, job.id, note="#muscl", append=True)
    assert saved.note == "second order · #muscl"
    assert load_job(project_dir, job.id).state.value == "RUNNING"  # the rest of the record is as it was


def test_the_index_counts_jobs_by_tag_and_project(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    tags.note_changed(a, "", "x")  # no index yet: built from the job files, which hold nothing
    assert tags.load_index() == {}
    tags.note_changed(a, "", "wing #fine #coarse")
    tags.note_changed(a, "", "again #fine")
    tags.note_changed(b, "", "#fine")
    index = json.loads(tags.tags_file().read_text())
    assert index["fine"] == {"count": 3, "projects": {str(a.resolve()): 2, str(b.resolve()): 1}}
    assert index["coarse"]["count"] == 1
    tags.note_changed(a, "wing #fine #coarse", "wing #fine")  # #coarse removed
    tags.note_changed(a, "again #fine", "")
    index = json.loads(tags.tags_file().read_text())
    assert "coarse" not in index and index["fine"]["count"] == 2
    assert not list(aerosuite_home().glob("*.tmp"))  # written by replacing a file


def test_matching_tags_most_used_first_with_where_they_are_used(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    tags.load_index()  # built (from no jobs); the notes below are saved after it
    for project, note in [(a, "#cfl-low"), (a, "#cfl-low #mesh"), (b, "#cfl-low"), (a, "#cfl-high"), (a, "#cfl-high")]:
        tags.note_changed(project, "", note)
    matches = tags.matching_tags("cfl", a)
    assert [(m.tag, m.count, m.scope) for m in matches] == [("cfl-low", 3, "all projects"),
                                                            ("cfl-high", 2, "this project")]
    assert [m.tag for m in tags.matching_tags("", a)] == ["cfl-low", "cfl-high", "mesh"]
    assert tags.matching_tags("zzz", a) == []


def test_a_missing_index_is_built_once_from_the_recent_projects_job_files(ready_project):
    project_dir, _project = ready_project
    save_job(project_dir, _job("20261102-1001", note="first #wing #fine"))
    save_job(project_dir, _job("20261102-1002", note="second #wing"))
    save_job(project_dir, _job("20261102-1003"))
    add_recent(project_dir)
    assert not tags.tags_file().exists()
    index = tags.load_index()
    assert {tag: entry["count"] for tag, entry in index.items()} == {"wing": 2, "fine": 1}
    assert tags.tags_file().is_file()
    save_job(project_dir, _job("20261102-1004", note="#late"))  # job files are not read again
    assert "late" not in tags.load_index()


def test_the_changes_since_the_last_run_group_cases_that_changed_alike(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    jobs = list_jobs(project_dir)
    template = read_template(project_dir, project)
    assert config_changes(project_dir, project, template, [A0, A2], jobs) == []  # nothing changed
    assert config_changes(project_dir, project, template, [A4], jobs) == []  # never ran
    lower = rerun_changes(cfl=0.5, iterations=3000)
    found = config_changes(project_dir, project, template, [A0, A2], jobs, {A0: lower, A2: lower})
    assert {(c.key, c.before, c.after) for c in found} == {("CFL_NUMBER", None, "0.5"), ("CFL_ADAPT", None, "NO"),
                                                          ("ITER", None, "3000")}
    assert all(c.cases == (A0, A2) for c in found)
    only = config_changes(project_dir, project, template, [A0, A2], jobs, {A2: lower})
    assert all(c.cases == (A2,) for c in only)
    assert next(c for c in only if c.key == "ITER").text == "ITER= — → 3000"
    assert job.id == jobs[0].id


def test_a_config_parses_into_its_lines():
    assert parameters("% a comment\nMACH_NUMBER= 0.3\n  AOA = 2.0 \nMARKER_FAR= ( farfield )\nAOA= 4\n") == {
        "MACH_NUMBER": "0.3", "AOA": "4", "MARKER_FAR": "( farfield )"}

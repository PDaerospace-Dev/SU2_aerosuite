import shutil

from aerosuite.engine.cluster import MAX_ROWS, RecordIndex, aerosuite_case, my_jobs, study_of
from aerosuite.engine.slurm import HistoryRow, QueueRow

from slurm_helpers import A0, A2, slurm_study  # noqa: F401  (fixture)

ME = "pdas-hpc1"


def _queue(job_id, folder, name, state="RUNNING", user=ME, node="hpc1"):
    return QueueRow(job_id, state, node, "1:00", node if state == "RUNNING" else "Priority", user, name, str(folder))


def _ended(job_id, folder, name, state="COMPLETED", partition="node1", submit=""):
    return HistoryRow(job_id, name, state, "0:0", "00:02:00", "hpc1", partition, "", "", str(folder), submit)


def test_aerosuite_case_and_study_of(slurm_study):
    project_dir = slurm_study[0]
    folder = project_dir / "runs" / A0
    assert aerosuite_case(str(folder), f"study/{A0}") == (project_dir, "study", A0)
    assert study_of(str(folder), f"study/{A0}") == project_dir
    assert study_of(str(folder), f"other/{A0}") is None  # the name is not this study's
    assert aerosuite_case("/home/me/bench", "su2-bench") is None  # a hand-written job
    assert aerosuite_case(str(folder), "") is None


def test_running_and_ended_cases_with_their_records(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    queue = {"101": _queue("101", project_dir / "runs" / A0, f"study/{A0}"),
             "102": _queue("102", project_dir / "runs" / A2, f"study/{A2}", state="PENDING", node=""),
             "900": _queue("900", "/home/ana", "ana/x", user="ana")}
    rows, more = my_jobs(queue, {}, ME, RecordIndex())
    assert more == 0 and [r.slurm_id for r in rows] == ["102", "101"]  # newest first; ana's job is not mine
    running = rows[1]
    assert (running.study, running.study_name, running.case, running.job_id) == (project_dir, "study", A0, job.id)
    assert (running.case_state, running.slurm_state, running.active, running.partition) == (
        "RUNNING", "RUNNING", True, "node1")


def test_a_failed_case_from_the_recent_history_is_resubmittable(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.finish("101", "OUT_OF_MEMORY", "0:125")
    runner.refresh(project_dir, job)
    recent = {"101": _ended("101", project_dir / "runs" / A0, f"study/{A0}", "OUT_OF_MEMORY")}
    [row] = my_jobs({}, recent, ME, RecordIndex())[0]
    assert (row.case_state, row.slurm_state, row.active, row.resubmittable) == (
        "FAILED", "OUT_OF_MEMORY", False, True)


def test_an_earlier_attempt_is_not_a_second_live_row(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    fake.finish("101", "NODE_FAIL")
    job = runner.refresh(project_dir, job)
    job = runner.resubmit(project_dir, project, job, [A0])  # now 102
    recent = {"101": _ended("101", project_dir / "runs" / A0, f"study/{A0}", "NODE_FAIL")}
    queue = {"102": _queue("102", project_dir / "runs" / A0, f"study/{A0}", state="PENDING", node="")}
    rows = {r.slurm_id: r for r in my_jobs(queue, recent, ME, RecordIndex())[0]}
    assert rows["101"].earlier_attempt and rows["101"].current_id == "102"
    assert rows["101"].case_state is None and not rows["101"].resubmittable
    assert not rows["102"].earlier_attempt and rows["102"].case_state == "PENDING"


def test_a_moved_study_still_lists_its_cases_without_a_link(slurm_study, tmp_path):
    project_dir, project, runner, fake = slurm_study
    runner.submit(project_dir, project, cases=[A0])
    old = project_dir / "runs" / A0
    shutil.move(str(project_dir), str(tmp_path / "moved-study"))
    [row] = my_jobs({"101": _queue("101", old, f"study/{A0}")}, {}, ME, RecordIndex())[0]
    assert (row.study, row.study_name, row.case, row.job_id, row.case_state) == (None, "study", A0, None, None)
    assert row.slurm_state == "RUNNING" and not row.resubmittable


def test_hundreds_of_jobs_are_capped_newest_first(tmp_path):
    folder = tmp_path / "s" / "runs" / "c"
    recent = {str(i): _ended(str(i), folder, "s/c") for i in range(1, MAX_ROWS + 31)}
    rows, more = my_jobs({}, recent, ME, RecordIndex())
    assert len(rows) == MAX_ROWS and more == 30 and rows[0].slurm_id == str(MAX_ROWS + 30)


def test_the_record_index_rereads_a_study_only_when_its_jobs_change(slurm_study, monkeypatch):
    from aerosuite.engine import cluster

    project_dir, project, runner, fake = slurm_study
    runner.submit(project_dir, project, cases=[A0])
    calls = []
    real = cluster.scan_jobs
    monkeypatch.setattr(cluster, "scan_jobs", lambda d: calls.append(d) or real(d))
    index = RecordIndex()
    assert index.lookup(project_dir, "101")[1] == A0
    assert index.lookup(project_dir, "101")[1] == A0
    assert len(calls) == 1
    runner.add_cases(project_dir, project, index.lookup(project_dir, "101")[0], [A2])
    assert index.lookup(project_dir, "102")[1] == A2 and len(calls) == 2
    assert index.lookup(project_dir, "999") is None


def test_study_of_reads_project_json_once_until_it_changes(slurm_study, monkeypatch):
    import os

    from aerosuite.engine import cluster

    project_dir = slurm_study[0]
    reads = []
    real = cluster.json.loads
    monkeypatch.setattr(cluster.json, "loads", lambda text: reads.append(1) or real(text))
    folder = str(project_dir / "runs" / A0)
    assert study_of(folder, f"study/{A0}") == project_dir
    assert study_of(folder, f"study/{A0}") == project_dir
    assert len(reads) == 1
    stamp = (project_dir / "project.json").stat().st_mtime_ns + 1_000_000
    os.utime(project_dir / "project.json", ns=(stamp, stamp))
    assert study_of(folder, f"study/{A0}") == project_dir and len(reads) == 2


def test_each_row_knows_when_it_was_submitted(slurm_study):
    from datetime import datetime

    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    queue = {"101": _queue("101", project_dir / "runs" / A0, f"study/{A0}")}
    [row] = my_jobs(queue, {}, ME, RecordIndex())[0]
    assert row.submitted == job.slurm[A0].submitted  # from AeroSuite's record
    elsewhere = {"7": _ended("7", "/gone/s/runs/c", "s/c", submit="2026-10-20T17:39:12")}
    [row] = my_jobs({}, elsewhere, ME, RecordIndex())[0]
    assert row.submitted == datetime(2026, 10, 20, 17, 39, 12).timestamp()  # from accounting
    unknown = {"8": _ended("8", "/gone/s/runs/c", "s/c", submit="Unknown")}
    assert my_jobs({}, unknown, ME, RecordIndex())[0][0].submitted is None


def test_a_cases_ascii_job_is_listed_as_that_case(slurm_study):
    project_dir = slurm_study[0]
    folder = project_dir / "runs" / A0
    name = f"study/{A0}-ascii"
    assert aerosuite_case(str(folder), name) == (project_dir, "study", A0)
    assert study_of(str(folder), name) == project_dir
    assert aerosuite_case(str(folder), f"study/{A0}-other") is None
    rows, _more = my_jobs({"700": _queue("700", folder, name)}, {}, ME, RecordIndex())
    assert [(r.case, r.task, r.job_id, r.active) for r in rows] == [(A0, "ASCII files", None, True)]

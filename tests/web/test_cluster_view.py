from pathlib import Path

from aerosuite.engine.cluster import MyJob
from aerosuite.engine.jobs.runner import CaseState, JobRecord, SlurmCase
from aerosuite.engine.slurm import ClusterInfo, QueueRow, Snapshot, parse_sinfo_nodes
from aerosuite.web.cluster_view import (
    can_resubmit, case_slurm_text, cluster_status, expected_ends, filter_jobs, glance, job_groups, job_state_text,
    job_studies, moved, when_text,
    node_groups, node_jobs, ordered_nodes, partition_nodes, queue_starts, queue_text, running_count, state_words,
    suggested_partition, summary_line, summary_parts,
)

NODES = ("hpc1|node1*|alloc|192/0/0/192|125000|20000|96.1|none\n"
         "hpc2|node2|drain|0/0/192/192|62000|57000|0.2|bad DIMM\n"
         "hpc3|node2|idle|0/192/0/192|62000|60000|0.0|none\n")


def _job(**slurm):
    job = JobRecord(id="j", backend="slurm", cases=list(slurm), log_path="jobs/j.log",
                    case_status={name: CaseState.PENDING for name in slurm}, state="RUNNING")
    job.slurm = {name: SlurmCase(job_id=str(100 + i), partition="node2", ntasks=48, **values)
                 for i, (name, values) in enumerate(slurm.items())}
    return job


def test_case_slurm_text():
    job = _job(a=dict(reason="Dependency"), b=dict(state="RUNNING", node="hpc1", elapsed="1:02:03"),
               c=dict(state="OUT_OF_MEMORY", exit_code="0:125"), d=dict(state="COMPLETED", exit_code="0:0"))
    assert case_slurm_text(job, "a") == "Slurm 100 · PENDING (Dependency)"
    assert case_slurm_text(job, "b") == "Slurm 101 · RUNNING on hpc1 · 1:02:03"
    assert case_slurm_text(job, "c") == "Slurm 102 · OUT_OF_MEMORY · exit 0:125"
    assert case_slurm_text(job, "d") == "Slurm 103"
    assert case_slurm_text(job, "zz") == "" and case_slurm_text(None, "a") == ""


def test_resubmit_rules():
    job = _job(a=dict(state="OUT_OF_MEMORY"), b=dict(state="NODE_FAIL"), c=dict(state="FAILED"))
    for name in "abc":
        job.case_status[name] = CaseState.FAILED
    assert [can_resubmit(job, n) for n in "abc"] == [True, True, False]
    limits = {"node1": 122880, "node2": 62000}
    assert suggested_partition(job, "a", ["node1", "node2"], limits) == "node1"  # more memory
    assert suggested_partition(job, "b", ["node1", "node2"], limits) == "node2"  # same as before


def _cluster(text=NODES, error=None):
    return ClusterInfo(nodes=parse_sinfo_nodes(text), error=error)


def test_node_groups_default_partition_first():
    groups = node_groups(_cluster("hpc2|node2|idle|0/192/0/192|62000|57000|0.2|none\n"
                                  "hpc1|node1*|mix|96/96/0/192|125000|101000|48.0|none\n"))
    assert [(name, default, [n.node for n in nodes]) for name, default, nodes in groups] == [
        ("node1", True, ["hpc1"]), ("node2", False, ["hpc2"])]
    hpc1 = groups[0][2][0]
    assert (hpc1.cpus, hpc1.busy_percent, hpc1.memory, hpc1.load) == (
        "96 / 192", 50, "99 of 122 GB free", "48.0")
    assert node_groups(None) == []


def test_cluster_status_tones():
    assert cluster_status(None, None)[0] == "grey"
    assert cluster_status(Snapshot(), _cluster(NODES))[0] == "amber"
    assert "hpc2" in cluster_status(Snapshot(), _cluster(NODES))[1] and "bad DIMM" in cluster_status(
        Snapshot(), _cluster(NODES))[1]
    assert cluster_status(Snapshot(), _cluster("hpc1|node1*|idle|0/192/0/192|1|1|0|none\n"))[0] == "green"
    assert cluster_status(Snapshot(error="Unable to contact"), _cluster())[0] == "red"


def test_running_count_and_summary_line():
    snap = Snapshot(queue={"1": QueueRow("1", "RUNNING", "hpc1", "1:00", "hpc1", "me"),
                           "2": QueueRow("2", "PENDING", "", "0:00", "Resources", "me"),
                           "3": QueueRow("3", "PENDING", "", "0:00", "Resources", "me"),
                           "4": QueueRow("4", "RUNNING", "hpc3", "1:00", "hpc3", "ana")})
    assert running_count(snap, "me") == 1
    text, bad = summary_line(_cluster(), snap, "me")
    assert text == "node1 192/192 busy · node2 1 drain, 0/384 busy · 1 of yours running, 2 queued" and bad
    text, bad = summary_line(_cluster("hpc1|node1*|idle|0/192/0/192|1|1|0|none\n"), Snapshot(), "me")
    assert (text, bad) == ("node1 free", False)
    assert summary_line(None, None, "me") == ("Asking Slurm…", False)
    assert summary_line(_cluster(), Snapshot(error="x"), "me")[1] is True


def _my_job(slurm_id, case_state="RUNNING", slurm_state="RUNNING", active=True, study="s", current=None):
    return MyJob(slurm_id, Path(f"/d/{study}"), study, "c", slurm_state, case_state, "j", "node1", "hpc1", "1:00",
                 "0:0", "", active, current or slurm_id, False)


def test_my_job_filters_and_texts():
    rows = [_my_job("5"), _my_job("4", "FAILED", "OUT_OF_MEMORY", False), _my_job("3", "CONVERGED", "COMPLETED", False, "t"),
            _my_job("2", "BLOCKED", "CANCELLED", False), _my_job("1", None, "NODE_FAIL", False, current="4")]
    assert [r.slurm_id for r in filter_jobs(rows, "active")] == ["5"]
    assert [r.slurm_id for r in filter_jobs(rows, "failed")] == ["4", "2", "1"]
    assert [r.slurm_id for r in filter_jobs(rows, "all", "t")] == ["3"]
    assert job_studies(rows) == ["s", "t"]
    assert job_state_text(rows[1]) == "Failed (OUT_OF_MEMORY)"
    assert job_state_text(rows[2]) == "Converged"
    assert job_state_text(rows[0]) == "Running"
    assert job_state_text(rows[4]) == "NODE_FAIL · earlier attempt (now 4)"


def test_a_pending_job_says_why():
    waiting = MyJob("7", Path("/d/s"), "s", "c", "PENDING", "PENDING", "j", "node1", "", "0:00", "", "Dependency",
                    True, "7", False)
    assert job_state_text(waiting) == "Pending · Dependency"
    queued = MyJob("8", Path("/d/s"), "s", "c", "PENDING", "PENDING", "j", "node1", "", "0:00", "", "None", True,
                   "8", False)
    assert job_state_text(queued) == "Pending"


def _dated(slurm_id, study, case, state, elapsed, submitted):
    return MyJob(slurm_id, Path(f"/d/{study}"), study, case, "COMPLETED", state, "j", "node1", "hpc1", elapsed,
                 "0:0", "", False, slurm_id, False, submitted)


def test_submitted_text():
    from datetime import datetime

    from aerosuite.web.cluster_view import submitted_text

    assert submitted_text(_dated("1", "s", "c", "CONVERGED", "1:00", datetime(2026, 10, 21, 9, 42).timestamp())) == (
        "21 Oct 09:42")
    assert submitted_text(_dated("1", "s", "c", "CONVERGED", "1:00", None)) == "—"


def test_sort_jobs_by_each_column():
    from aerosuite.web.cluster_view import SORT_KEYS, sort_jobs

    rows = [_dated("1", "b", "M0p8_a2", "FAILED", "10:00", 300.0), _dated("2", "a", "M0p8_a0", "CONVERGED", "1:02:00", 100.0),
            _dated("3", "c", "M0p8_a4", "UNCONVERGED", "", None)]
    ids = lambda key, descending: [r.slurm_id for r in sort_jobs(rows, key, descending)]
    assert SORT_KEYS == ("submitted", "study", "case", "state", "elapsed")
    assert ids("submitted", True) == ["1", "2", "3"]  # newest first; unknown dates last either way
    assert ids("submitted", False) == ["2", "1", "3"]
    assert ids("study", False) == ["2", "1", "3"]
    assert ids("case", True) == ["3", "1", "2"]
    assert ids("state", False) == ["2", "1", "3"]  # Converged, Failed, Unconverged
    assert ids("elapsed", True) == ["2", "1", "3"]  # 1:02:00, 10:00; no time last


def test_summary_parts_give_a_pill_per_partition_and_your_jobs():
    parts = summary_parts(_cluster("hpc1|node1*|mix|96/96/0/192|1|1|0|none\nhpc2|node2|idle|0/192/0/192|1|1|0|none\n"
                                   "hpc3|node3|drain|0/0/192/192|1|1|0|bad DIMM\n"), Snapshot(), "me")
    assert [(n[0], n[1], n[2]) for n in parts.nodes] == [("node1", "busy", "node1 50%"), ("node2", "free", "node2 free"),
                                                          ("node3", "bad", "node3 drain")]
    assert parts.bad and parts.message == "" and parts.mine == ""
    assert summary_parts(None, None, "me").message == "Asking Slurm…"
    assert summary_parts(_cluster(), Snapshot(error="x"), "me") == ("Slurm controller unreachable", True, (), "")


def test_node_jobs_are_whole_study_jobs_as_on_run():
    job = _job(a={}, b={}, c={}, d={})
    job.case_status.update(a=CaseState.CONVERGED, b=CaseState.FAILED, c=CaseState.RUNNING, d=CaseState.RUNNING)
    other = _job(x={})
    records = {("/d/s", "102"): (job, "c"), ("/d/s", "103"): (job, "d"), ("/d/t", "100"): (other, "x")}
    rows = [MyJob("103", Path("/d/s"), "s", "d", "RUNNING", "RUNNING", "j", "node1", "hpc1", "1:00", "", "", True,
                  "103", False),
            MyJob("102", Path("/d/s"), "s", "c", "RUNNING", "RUNNING", "j", "node1", "hpc1", "2:00", "", "", True,
                  "102", False),
            MyJob("100", Path("/d/t"), "t", "x", "RUNNING", "RUNNING", "k", "node2", "hpc2", "1:00", "", "", True,
                  "100", False),
            MyJob("104", Path("/d/s"), "s", "e", "PENDING", "PENDING", "j", "node1", "", "0:00", "", "", True,
                  "104", False)]
    found = node_jobs(rows, lambda study, slurm_id: records.get((str(study), slurm_id)))
    assert set(found) == {"hpc1", "hpc2"}  # a queued case is on no node
    (line,) = found["hpc1"]  # one line for the job, not one per case
    assert (line.study_name, line.job_id, line.finished, line.total, line.cases) == ("s", "j", 2, 4, ("c", "d"))
    assert line.started == job.created and line.done == 0.5
    assert line.tip == "Job j · running here: c, d"
    assert found["hpc2"][0].total == 1


def _row(slurm_id, study, case, state, partition, node="", job_id="j", **times):
    active = state in ("RUNNING", "PENDING")
    return MyJob(slurm_id, Path(study), Path(study).name, case, state, state, job_id, partition, node, "0:00", "", "",
                 active, slurm_id, False, **times)


def test_node_jobs_lists_jobs_queued_for_a_node_in_queue_order():
    from datetime import datetime, timedelta

    now = datetime(2026, 10, 28, 12, 0)
    run = _job(a=dict(elapsed="2:00:00"), b=dict(elapsed="2:00:00"), c=dict(elapsed="1:00:00"), d={})  # 2 h a case
    run.created = now - timedelta(hours=4)
    run.case_status.update(a=CaseState.CONVERGED, b=CaseState.CONVERGED, c=CaseState.RUNNING)
    split = _job(x=dict(elapsed="1:00:00"), y={}, z={})  # on hpc2, 1 h a case; one added for node1 waits there
    split.created = now - timedelta(hours=1)
    split.case_status.update(x=CaseState.CONVERGED, y=CaseState.RUNNING)
    later = _job(p={}, q={})
    records = {("/d/run", "1"): (run, "c"), ("/d/run", "2"): (run, "d"), ("/d/split", "5"): (split, "y"),
               ("/d/split", "6"): (split, "z"), ("/d/later", "9"): (later, "p"), ("/d/later", "10"): (later, "q")}
    rows = [_row("1", "/d/run", "c", "RUNNING", "node1", "hpc1"), _row("2", "/d/run", "d", "PENDING", "node1"),
            _row("5", "/d/split", "y", "RUNNING", "node2", "hpc2"), _row("6", "/d/split", "z", "PENDING", "node1"),
            _row("9", "/d/later", "p", "PENDING", "node1"), _row("10", "/d/later", "q", "PENDING", "node1")]
    nodes = {"node1": ("hpc1",), "node2": ("hpc2",)}
    board = node_jobs(rows, lambda study, slurm_id: records.get((str(study), slurm_id)), nodes, now.timestamp())
    assert [(j.study_name, j.waiting, j.cases) for j in board["hpc1"]] == [
        ("run", False, ("c",)), ("split", True, ("z",)), ("later", True, ("p", "q"))]  # run's d is its own chain
    assert board["hpc1"][1].elsewhere == "running on hpc2 · 1 / 3"
    assert board["hpc2"][0].elsewhere == "1 more queued on hpc1"
    starts = queue_starts(board["hpc1"], now)
    assert starts[0] == (3 * 3600, "run")  # split: when run's job ends (c's last hour, then d's 2 h)
    assert starts[1] == (4 * 3600, "split")  # later: + split's 1 case here at its 1 h a case
    assert queue_text(*starts[0]) == "Starts in about 3 h · after run"
    assert queue_text(None, "run") == "Starts after run" and queue_text(None, "") == "Waiting in the Slurm queue"
    assert node_jobs(rows, lambda study, slurm_id: records.get((str(study), slurm_id)))["hpc1"][0].study_name == "run"


def test_node_order_and_moving_a_card():
    groups = node_groups(_cluster())
    assert [n.node for _p, _d, n in ordered_nodes(groups)] == ["hpc1", "hpc2", "hpc3"]
    assert [n.node for _p, _d, n in ordered_nodes(groups, ["hpc3", "gone"])] == ["hpc3", "hpc1", "hpc2"]
    assert moved(["a", "b", "c"], "c", "a") == ["c", "a", "b"]  # up: before the card dropped on
    assert moved(["a", "b", "c"], "a", "b") == ["b", "a", "c"]  # down: after it
    assert moved(["a", "b"], "a", "x") == ["a", "b"]
    assert partition_nodes(groups) == {"node1": ("hpc1",), "node2": ("hpc2", "hpc3")}
    assert [state_words(s) for s in ("alloc", "mix", "idle", "drain*", "down*", "drng", "plnd")] == [
        "Full", "Partly used", "Free", "Drained", "Down", "Draining", "Plnd"]
    hpc1 = groups[0][2][0]
    assert hpc1.memory_used == (122 - 20) / 122 and round(hpc1.load_share, 2) == 0.5


def test_glance_tiles():
    nodes = ordered_nodes(node_groups(_cluster()))
    job = _job(a={}, b={}, c={})
    job.case_status.update(a=CaseState.CONVERGED, b=CaseState.RUNNING)
    rows = [_row("100", "/d/s", "b", "RUNNING", "node1", "hpc1")]
    board = node_jobs(rows, lambda study, slurm_id: (job, "b"), partition_nodes(node_groups(_cluster())))
    tiles = {tile.key: tile for tile in glance(nodes, board, rows, lambda study, slurm_id: (job, "b"))}
    assert (tiles["running"].value, tiles["running"].sub) == ("1 study", "on hpc1")
    assert (tiles["queued"].value, tiles["queued"].sub) == ("None", "nothing waits")
    assert (tiles["left"].value, tiles["left"].sub) == ("2", "of 3 · 1 finished")
    assert (tiles["cpus"].value, tiles["cpus"].sub) == ("192 / 576", "33%")
    assert (tiles["nodes"].value, tiles["nodes"].sub, tiles["nodes"].alert) == ("2 of 3 up", "hpc2 drained", True)


def test_expected_ends_follow_run_times_and_the_queue_order():
    taken = 1_000_000.0
    first = _job(a=dict(elapsed="0:30:00"), b=dict(elapsed="0:30:00"), c={}, d={}, e={})  # 30 min a case
    first.case_status.update(a=CaseState.CONVERGED, b=CaseState.UNCONVERGED, c=CaseState.RUNNING)
    second = _job(x=dict(elapsed="1:00:00"), y={}, z={})  # 1 h a case, all of it queued behind first
    second.case_status.update(x=CaseState.CONVERGED)
    fresh = _job(p={})  # nothing has run to the end: no guess
    records = {"/d/one": first, "/d/two": second, "/d/new": fresh}
    rows = [_row("3", "/d/one", "c", "RUNNING", "node1", "hpc1", started=taken - 600),
            _row("4", "/d/one", "d", "PENDING", "node1"), _row("5", "/d/one", "e", "PENDING", "node1"),
            _row("8", "/d/two", "y", "PENDING", "node1", job_id="k"),
            _row("9", "/d/two", "z", "PENDING", "node1", job_id="k"),
            _row("12", "/d/new", "p", "PENDING", "node2", job_id="m"),
            _row("1", "/d/one", "a", "COMPLETED", "node1", "hpc1", started=taken - 4200, ended=taken - 2400)]
    ends, job_ends = expected_ends(rows, lambda study, slurm_id: (records[str(study)], "c"), taken)
    assert ends["3"] == taken + 1200  # started 10 min ago, 30 min a case
    assert (ends["4"], ends["5"]) == (taken + 3000, taken + 4800)  # one at a time, as now
    assert (ends["8"], ends["9"]) == (taken + 8400, taken + 12000)  # after the first job, at its own 1 h
    assert "12" not in ends and "1" not in ends
    assert job_ends == {(Path("/d/one"), "j"): taken + 4800, (Path("/d/two"), "k"): taken + 12000}
    groups = job_groups(rows, lambda study, slurm_id: (records[str(study)], "c"), job_ends, taken)
    assert [(g.key, g.finished, g.total, g.active) for g in groups] == [
        ("one-j", 2, 5, True), ("two-k", 1, 3, True), ("new-m", 0, 1, True)]
    assert groups[0].started == taken - 4200 and groups[0].ended == taken + 4800
    assert [row.case for row in groups[0].rows] == ["c", "d", "e", "a"]


def test_when_text():
    from datetime import datetime

    today = datetime(2026, 10, 29, 10, 30)
    assert when_text(datetime(2026, 10, 29, 9, 41).timestamp(), today) == "09:41"
    assert when_text(datetime(2026, 10, 28, 22, 27).timestamp(), today) == "28 Oct 22:27"
    assert when_text(None) == "—"

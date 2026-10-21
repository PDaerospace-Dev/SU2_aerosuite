from pathlib import Path

from aerosuite.engine.cluster import MyJob
from aerosuite.engine.jobs.runner import CaseState, JobRecord, SlurmCase
from aerosuite.engine.slurm import ClusterInfo, QueueRow, Snapshot, parse_sinfo_nodes
from aerosuite.web.cluster_view import (
    can_resubmit, case_slurm_text, cluster_queue, cluster_status, filter_jobs, job_state_text, job_studies,
    node_groups, running_count, suggested_partition, summary_line,
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


def test_cluster_queue_pending_first_mine_marked():
    snap = Snapshot(queue={
        "12": QueueRow("12", "RUNNING", "hpc1", "1:00", "hpc1", "me", "s/a", "/d/s/runs/a"),
        "13": QueueRow("13", "PENDING", "", "0:00", "Resources", "ana", "x", ""),
        "9": QueueRow("9", "RUNNING", "hpc2", "9:00", "hpc2", "ana", "y", "")})
    lines = cluster_queue(snap, "me")
    assert [(l.job_id, l.own) for l in lines] == [("13", False), ("9", False), ("12", True)]
    assert cluster_queue(Snapshot(error="down"), "me") == []


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

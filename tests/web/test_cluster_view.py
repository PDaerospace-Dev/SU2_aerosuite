from aerosuite.engine.jobs.runner import CaseState, JobRecord, SlurmCase
from aerosuite.engine.slurm import ClusterInfo, NodeReason, QueueRow, Snapshot, parse_sinfo
from aerosuite.web.cluster_view import (
    can_resubmit,
    case_slurm_text,
    node_reasons,
    outage_text,
    own_jobs,
    partition_lines,
    queue_lines,
    suggested_partition,
)


def test_partition_lines_group_node_states():
    rows = parse_sinfo("node1*|up|1|mix|96/96/0/192\nnode2|up|1|drain|0/0/192/192\n")
    lines = partition_lines(rows)
    assert [(l.name, l.default, l.nodes, l.bad) for l in lines] == [
        ("node1", True, "1 mix", False), ("node2", False, "1 drain", True)]
    assert lines[0].busy_percent == 50 and lines[0].cpus == "96 / 192 CPUs busy"


def test_node_reasons():
    cluster = ClusterInfo(reasons={"hpc2": NodeReason("hpc2", "drain", "bad DIMM")})
    assert node_reasons(cluster) == ["hpc2 (drain): bad DIMM"]
    assert node_reasons(None) == []


def test_queue_lines_mark_this_studys_jobs():
    snap = Snapshot(queue={"12": QueueRow("12", "RUNNING", "hpc1", "1:00", "hpc1"),
                           "9": QueueRow("9", "PENDING", "", "0:00", "Resources")})
    lines = queue_lines(snap, {"12": "M0p8_a2"})
    assert [(l.job_id, l.what, l.own, l.reason) for l in lines] == [
        ("9", "", False, "Resources"), ("12", "M0p8_a2", True, "")]
    assert queue_lines(Snapshot(error="down"), {}) == []


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
    assert own_jobs([job]) == {"100": "a", "101": "b", "102": "c", "103": "d"}


def test_resubmit_rules():
    job = _job(a=dict(state="OUT_OF_MEMORY"), b=dict(state="NODE_FAIL"), c=dict(state="FAILED"))
    for name in "abc":
        job.case_status[name] = CaseState.FAILED
    assert [can_resubmit(job, n) for n in "abc"] == [True, True, False]
    limits = {"node1": 122880, "node2": 62000}
    assert suggested_partition(job, "a", ["node1", "node2"], limits) == "node1"  # more memory
    assert suggested_partition(job, "b", ["node1", "node2"], limits) == "node2"  # same as before


def test_outage_text():
    assert outage_text(Snapshot(), None, None) == ""
    text = outage_text(Snapshot(error="Unable to contact slurm controller"), None, 0.0)
    assert text.startswith("Slurm controller unreachable") and "last known" in text
    assert "last answer" in outage_text(Snapshot(error="x"), None, 1_800_000_000.0)
    assert outage_text(None, ClusterInfo(error="sinfo failed"), None).endswith("States shown are the last known.")

"""The Run page's Slurm rules without NiceGUI: partition rows, the queue, a case's Slurm line, the outage note."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional, Sequence

from ..engine.jobs.runner import JobRecord
from ..engine.slurm import RESUBMITTABLE, ClusterInfo, PartitionRow, Snapshot


@dataclass(frozen=True)
class PartitionLine:
    name: str
    default: bool
    nodes: str  # "1 idle", "1 mix · 1 drain"
    allocated: int
    idle: int
    total: int
    bad: bool  # a node drained, down or failing, or the partition not up
    available: str

    @property
    def busy_percent(self) -> int:
        return round(100 * self.allocated / self.total) if self.total else 0

    @property
    def cpus(self) -> str:
        return f"{self.allocated} / {self.total} CPUs busy"


def partition_lines(rows: Sequence[PartitionRow]) -> list[PartitionLine]:
    """One line per partition (sinfo gives one row per node state), in sinfo's order."""
    grouped: dict[str, list[PartitionRow]] = {}
    for row in rows:
        grouped.setdefault(row.name, []).append(row)
    lines = []
    for name, group in grouped.items():
        lines.append(PartitionLine(
            name=name, default=any(r.default for r in group),
            nodes=" · ".join(f"{r.nodes} {r.state}" for r in group),
            allocated=sum(r.allocated for r in group), idle=sum(r.idle for r in group),
            total=sum(r.total for r in group), bad=any(r.bad for r in group),
            available=group[0].available))
    return lines


def node_reasons(cluster: Optional[ClusterInfo]) -> list[str]:
    """'hpc2 (drain): bad DIMM' for each node sinfo -R lists."""
    if cluster is None:
        return []
    return [f"{r.node} ({r.state}): {r.reason}" for r in cluster.reasons.values()]


@dataclass(frozen=True)
class QueueLine:
    job_id: str
    what: str  # "<case>" for this study's jobs, "" for others
    state: str
    node: str
    time: str
    reason: str
    own: bool


def queue_lines(snapshot: Optional[Snapshot], own: Mapping[str, str]) -> list[QueueLine]:
    """Every job of `squeue --me`, oldest first; `own` maps this study's Slurm ids to case names."""
    if snapshot is None or not snapshot.ok:
        return []
    lines = []
    for job_id in sorted(snapshot.queue, key=lambda i: (len(i), i)):
        row = snapshot.queue[job_id]
        running = row.state in ("RUNNING", "COMPLETING")
        lines.append(QueueLine(job_id, own.get(job_id, ""), row.state, row.node, row.time,
                               "" if running else row.reason, job_id in own))
    return lines


def own_jobs(jobs: Iterable[JobRecord]) -> dict[str, str]:
    """{Slurm id: case} for the active Slurm jobs among `jobs`."""
    found = {}
    for job in jobs:
        if job.backend == "slurm" and job.is_active:
            for name, sc in job.slurm.items():
                found[sc.job_id] = name
    return found


def case_slurm_text(job: Optional[JobRecord], case: str) -> str:
    """'Slurm 101 · PENDING (Dependency)', '… · RUNNING on hpc1 · 1:02:03', '… · OUT_OF_MEMORY · exit 0:125'."""
    if job is None or case not in job.slurm:
        return ""
    sc = job.slurm[case]
    parts = [f"Slurm {sc.job_id}"]
    if sc.state in ("RUNNING", "COMPLETING"):
        parts.append(f"{sc.state} on {sc.node}" if sc.node else sc.state)
        if sc.elapsed:
            parts.append(sc.elapsed)
    elif sc.state in ("PENDING", "CONFIGURING", "REQUEUED") and sc.reason and sc.reason != "None":
        parts.append(f"{sc.state} ({sc.reason})")
    elif sc.state not in ("PENDING", "COMPLETED"):
        parts.append(sc.state)
    if sc.exit_code and sc.state not in ("RUNNING", "PENDING", "COMPLETING", "CANCELLED", "COMPLETED"):
        parts.append(f"exit {sc.exit_code}")
    return " · ".join(parts)


def can_resubmit(job: Optional[JobRecord], case: str) -> bool:
    return (job is not None and case in job.slurm and job.slurm[case].state in RESUBMITTABLE
            and job.case_status.get(case) is not None and job.case_status[case].value == "FAILED")


def suggested_partition(job: JobRecord, case: str, partitions: Sequence[str], limits: Mapping[str, int]) -> str:
    """Where to resubmit: the same partition, except after OUT_OF_MEMORY the one with the most memory."""
    sc = job.slurm[case]
    if sc.state == "OUT_OF_MEMORY" and limits:
        biggest = max(partitions, key=lambda name: limits.get(name, 0))
        if limits.get(biggest, 0) > limits.get(sc.partition, 0):
            return biggest
    return sc.partition


def outage_text(snapshot: Optional[Snapshot], cluster: Optional[ClusterInfo], last_ok: Optional[float]) -> str:
    """Why the Slurm panels are stale, or '' when Slurm answers."""
    error = (snapshot.error if snapshot is not None and not snapshot.ok else None) or (
        cluster.error if cluster is not None else None)
    if not error:
        return ""
    since = f" (last answer {datetime.fromtimestamp(last_ok):%H:%M:%S})" if last_ok else ""
    return f"Slurm controller unreachable{since}: {error}. States shown are the last known."

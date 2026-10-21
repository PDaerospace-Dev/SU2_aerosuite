"""The Slurm view rules without NiceGUI: a case's Slurm line and resubmit rules (Run page); nodes, everyone's
queue, my jobs, the top-bar dot and the Run summary line (Cluster page, top bar)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from ..engine.jobs.runner import JobRecord
from ..engine.cluster import MyJob, study_of
from ..engine.slurm import (FAILED_STATES, QUEUED_STATES, RESUBMITTABLE, RUNNING_STATES, ClusterInfo,
                             Snapshot, parse_duration)


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


@dataclass(frozen=True)
class NodeLine:
    node: str
    state: str
    bad: bool
    allocated: int
    total: int
    memory: str  # "101 of 122 GB free", "—" when sinfo does not say
    load: str
    reason: str

    @property
    def busy_percent(self) -> int:
        return round(100 * self.allocated / self.total) if self.total else 0

    @property
    def cpus(self) -> str:
        return f"{self.allocated} / {self.total}"


def _gb(mb: Optional[int]) -> Optional[int]:
    return None if mb is None else round(mb / 1024)


def node_groups(cluster: Optional[ClusterInfo]) -> list[tuple[str, bool, list[NodeLine]]]:
    """(partition, is the default, its nodes) — the default partition first, then in sinfo's order."""
    if cluster is None:
        return []
    groups: dict[str, tuple[bool, list[NodeLine]]] = {}
    for row in cluster.nodes:
        total, free = _gb(row.memory_mb), _gb(row.free_mb)
        memory = f"{free} of {total} GB free" if total is not None and free is not None else "—"
        line = NodeLine(row.node, row.state, row.bad, row.allocated, row.total, memory,
                        "—" if row.load is None else f"{row.load:.1f}", row.reason)
        default, lines = groups.setdefault(row.partition, (row.default, []))
        lines.append(line)
        if row.default and not default:
            groups[row.partition] = (True, lines)
    ordered = sorted(groups.items(), key=lambda item: not item[1][0])  # stable: default first
    return [(name, default, lines) for name, (default, lines) in ordered]


@dataclass(frozen=True)
class ClusterQueueLine:
    job_id: str
    user: str
    name: str
    state: str
    node: str
    time: str
    reason: str
    own: bool
    study: Optional[Path]  # an AeroSuite case's study, for the link


def cluster_queue(snapshot: Optional[Snapshot], user: str) -> list[ClusterQueueLine]:
    """Every user's jobs: pending first, then running, each in job-id order."""
    if snapshot is None or not snapshot.ok:
        return []
    rows = sorted(snapshot.queue.values(), key=lambda r: (r.state not in QUEUED_STATES, len(r.job_id), r.job_id))
    return [ClusterQueueLine(r.job_id, r.user, r.name, r.state, r.node, r.time,
                             "" if r.state in RUNNING_STATES else r.reason, r.user == user,
                             study_of(r.workdir, r.name)) for r in rows]


def cluster_status(snapshot: Optional[Snapshot], cluster: Optional[ClusterInfo]) -> tuple[str, str]:
    """The top bar's dot: red (Slurm does not answer), amber (a node is drained or down), green, grey (no answer yet)."""
    error = (snapshot.error if snapshot is not None and not snapshot.ok else None) or (
        cluster.error if cluster is not None else None)
    if error:
        return "red", f"Slurm controller unreachable: {error}"
    if cluster is None or not cluster.nodes:
        return "grey", "Asking Slurm…"
    bad = [f"{n.node} {n.state}" + (f": {n.reason}" if n.reason else "") for n in cluster.nodes if n.bad]
    if bad:
        return "amber", "; ".join(bad)
    return "green", f"All {len(cluster.nodes)} node{'' if len(cluster.nodes) == 1 else 's'} up"


def running_count(snapshot: Optional[Snapshot], user: str) -> int:
    if snapshot is None or not snapshot.ok:
        return 0
    return sum(1 for r in snapshot.queue.values() if r.user == user and r.state in RUNNING_STATES)


def summary_line(cluster: Optional[ClusterInfo], snapshot: Optional[Snapshot], user: str) -> tuple[str, bool]:
    """The Run page's one line: each partition's state, then the user's running and queued jobs."""
    status, _tip = cluster_status(snapshot, cluster)
    if status == "red":
        return "Slurm controller unreachable", True
    if status == "grey":
        return "Asking Slurm…", False
    parts = []
    for name, _default, nodes in node_groups(cluster):
        allocated, total = sum(n.allocated for n in nodes), sum(n.total for n in nodes)
        bad = [n for n in nodes if n.bad]
        if bad:
            states = ", ".join(f"{sum(1 for n in bad if n.state == s)} {s}" for s in dict.fromkeys(n.state for n in bad))
            parts.append(f"{name} {states}, {allocated}/{total} busy")
        elif allocated == 0:
            parts.append(f"{name} free")
        else:
            parts.append(f"{name} {allocated}/{total} busy")
    rows = [r for r in snapshot.queue.values() if r.user == user] if snapshot is not None else []
    running = sum(1 for r in rows if r.state in RUNNING_STATES)
    queued = sum(1 for r in rows if r.state in QUEUED_STATES)
    mine = [text for count, text in ((running, f"{running} of yours running"), (queued, f"{queued} queued")) if count]
    if mine:
        if not running:
            mine = [f"{queued} of yours queued"]
        parts.append(", ".join(mine))
    return " · ".join(parts), status == "amber"


JOB_KINDS = ("all", "active", "failed")
_FAILED_CASES = {"FAILED", "BLOCKED", "CANCELLED"}


def _failed(row: MyJob) -> bool:
    if row.case_state is not None:
        return row.case_state in _FAILED_CASES
    return row.slurm_state in FAILED_STATES or row.slurm_state == "CANCELLED"


def filter_jobs(rows: Sequence[MyJob], kind: str, study: Optional[str] = None) -> list[MyJob]:
    picked = [r for r in rows if study is None or r.study_name == study]
    if kind == "active":
        return [r for r in picked if r.active]
    if kind == "failed":
        return [r for r in picked if not r.active and _failed(r)]
    return picked


def job_studies(rows: Sequence[MyJob]) -> list[str]:
    return sorted({r.study_name for r in rows})


def job_state_text(row: MyJob) -> str:
    """'Failed (OUT_OF_MEMORY)', 'Converged', 'Pending · Dependency', 'NODE_FAIL · earlier attempt (now 4)'."""
    if row.earlier_attempt:
        return f"{row.slurm_state} · earlier attempt (now {row.current_id})"
    if row.case_state is None:
        return row.slurm_state
    text = row.case_state.capitalize()
    if row.slurm_state in QUEUED_STATES and row.reason and row.reason != "None":
        return f"{text} · {row.reason}"  # why it waits: Dependency, Resources, Priority
    plain = {"COMPLETED", "RUNNING", "PENDING", "CANCELLED", "COMPLETING"}
    return text if row.slurm_state in plain or row.slurm_state == row.case_state else f"{text} ({row.slurm_state})"


SORT_KEYS = ("submitted", "study", "case", "state", "elapsed")  # the My jobs columns that sort


def submitted_text(row: MyJob) -> str:
    """'21 Oct 09:42', or '—' when the submit time is unknown."""
    return "—" if row.submitted is None else datetime.fromtimestamp(row.submitted).strftime("%d %b %H:%M")


def _sort_value(row: MyJob, key: str):
    if key == "submitted":
        return row.submitted
    if key == "study":
        return row.study_name.lower()
    if key == "case":
        return row.case
    if key == "state":
        return job_state_text(row).lower()
    return parse_duration(row.elapsed) if row.elapsed else None  # "elapsed"


def sort_jobs(rows: Sequence[MyJob], key: str, descending: bool = False) -> list[MyJob]:
    """My jobs sorted by one column; rows without a value for it (no date, no run time) come last either way."""
    known = [row for row in rows if _sort_value(row, key) is not None]
    unknown = [row for row in rows if _sort_value(row, key) is None]
    return sorted(known, key=lambda row: _sort_value(row, key), reverse=descending) + unknown

"""The Slurm view rules without NiceGUI: a case's Slurm line and resubmit rules (Run page); nodes, my jobs, the
top-bar dot and the Run summary line (Cluster page, top bar)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, NamedTuple, Optional, Sequence

from ..engine.jobs.runner import FINAL_CASE_STATES, JobRecord
from ..engine.cluster import MyJob
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
class NodeJob:
    """A study's job with cases running on a node: how far the whole job is, as on its Run page."""
    study: Path
    study_name: str
    job_id: str
    started: datetime
    finished: int
    total: int
    cases: tuple[str, ...]  # its cases running on this node

    @property
    def done(self) -> float:
        return self.finished / self.total if self.total else 0.0

    @property
    def tip(self) -> str:
        return f"Job {self.job_id} · running here: {', '.join(self.cases)}"


def node_jobs(rows: Iterable[MyJob],
              lookup: Callable[[Path, str], Optional[tuple[JobRecord, str]]]) -> dict[str, tuple[NodeJob, ...]]:
    """Node -> the study jobs with cases running there (from My jobs' rows and the job records), by study name."""
    found: dict[tuple[str, Path, str], tuple[JobRecord, str, list[str]]] = {}
    for row in rows:
        if (row.slurm_state not in RUNNING_STATES or not row.node or row.study is None or row.job_id is None
                or row.earlier_attempt):
            continue
        record = lookup(row.study, row.slurm_id)
        if record is None:
            continue
        for node in row.node.split(","):
            found.setdefault((node, row.study, row.job_id), (record[0], row.study_name, []))[2].append(row.case)
    jobs: dict[str, list[NodeJob]] = {}
    for (node, study, job_id), (job, name, cases) in found.items():
        finished = sum(1 for name in job.cases if job.case_status.get(name) in FINAL_CASE_STATES)
        jobs.setdefault(node, []).append(NodeJob(study, name, job_id, job.created, finished, len(job.cases),
                                                 tuple(sorted(cases))))
    return {node: tuple(sorted(lines, key=lambda j: (j.study_name, j.job_id))) for node, lines in jobs.items()}


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


class SummaryParts(NamedTuple):
    message: str  # "Slurm controller unreachable" / "Asking Slurm…"; "" when the nodes are known
    bad: bool  # a drained or down node, or Slurm not answering
    nodes: tuple  # (partition, level "free" | "busy" | "bad", text, tooltip)
    mine: str  # "1 running · 15 queued" (the user's jobs), "" when none


def summary_parts(cluster: Optional[ClusterInfo], snapshot: Optional[Snapshot], user: str) -> SummaryParts:
    """The Run page's footer: one pill per partition (free, a share busy, or bad) and the user's jobs."""
    status, _tip = cluster_status(snapshot, cluster)
    if status == "red":
        return SummaryParts("Slurm controller unreachable", True, (), "")
    if status == "grey":
        return SummaryParts("Asking Slurm…", False, (), "")
    nodes = []
    for name, _default, lines in node_groups(cluster):
        allocated, total = sum(n.allocated for n in lines), sum(n.total for n in lines)
        bad = [n for n in lines if n.bad]
        tip = f"{allocated}/{total} busy"
        if bad:
            states = ", ".join(dict.fromkeys(n.state for n in bad))
            nodes.append((name, "bad", f"{name} {states}", f"{tip}; {', '.join(n.node for n in bad)} {states}"))
        elif allocated == 0:
            nodes.append((name, "free", f"{name} free", tip))
        else:
            nodes.append((name, "busy", f"{name} {round(100 * allocated / total) if total else 0}%", tip))
    rows = [r for r in snapshot.queue.values() if r.user == user] if snapshot is not None else []
    running = sum(1 for r in rows if r.state in RUNNING_STATES)
    queued = sum(1 for r in rows if r.state in QUEUED_STATES)
    mine = " · ".join(text for count, text in ((running, f"{running} running"), (queued, f"{queued} queued")) if count)
    return SummaryParts("", status == "amber", tuple(nodes), mine)


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

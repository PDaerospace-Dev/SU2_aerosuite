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
from .run_view import about_text, case_seconds, job_left


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


NODE_STATES = (("idle", "Free"), ("mix", "Partly used"), ("alloc", "Full"), ("comp", "Finishing"),
               ("drng", "Draining"), ("drain", "Drained"), ("down", "Down"))  # sinfo's short state -> in words


def state_words(state: str) -> str:
    """'alloc' -> 'Full', 'drain*' -> 'Drained'; a state not listed as Slurm writes it."""
    plain = state.rstrip("*~#!%$@^-").lower()
    return next((words for short, words in NODE_STATES if plain.startswith(short)), state.capitalize())


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
    memory_gb: Optional[int] = None
    free_gb: Optional[int] = None
    load_value: Optional[float] = None

    @property
    def busy_percent(self) -> int:
        return round(100 * self.allocated / self.total) if self.total else 0

    @property
    def cpus(self) -> str:
        return f"{self.allocated} / {self.total}"

    @property
    def memory_used(self) -> Optional[float]:
        """The share of memory in use (Linux's file cache counts as used: a busy node always looks nearly full)."""
        if not self.memory_gb or self.free_gb is None:
            return None
        return min(1.0, max(0.0, (self.memory_gb - self.free_gb) / self.memory_gb))

    @property
    def load_share(self) -> float:
        return min(1.0, self.load_value / self.total) if self.load_value is not None and self.total else 0.0

    @property
    def words(self) -> str:
        return state_words(self.state)


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
                        "—" if row.load is None else f"{row.load:.1f}", row.reason, total, free, row.load)
        default, lines = groups.setdefault(row.partition, (row.default, []))
        lines.append(line)
        if row.default and not default:
            groups[row.partition] = (True, lines)
    ordered = sorted(groups.items(), key=lambda item: not item[1][0])  # stable: default first
    return [(name, default, lines) for name, (default, lines) in ordered]


def ordered_nodes(groups: Sequence[tuple[str, bool, Sequence[NodeLine]]],
                  order: Sequence[str] = ()) -> list[tuple[str, bool, NodeLine]]:
    """(partition, is the default, node) for every node: in the user's `order` (dragged on the Cluster page), the
    nodes it does not name after them in node_groups' order."""
    nodes = [(partition, default, node) for partition, default, lines in groups for node in lines]
    place = {name: index for index, name in enumerate(order)}
    return sorted(nodes, key=lambda item: place.get(item[2].node, len(place)))  # stable: the rest keep their order


def moved(order: Sequence[str], node: str, target: str) -> list[str]:
    """`order` with `node` put where `target` is (dropped on it): before it when moving up, after it when moving
    down."""
    names = list(order)
    if node == target or node not in names or target not in names:
        return names
    down = names.index(node) < names.index(target)
    names.remove(node)
    at = names.index(target)
    names.insert(at + 1 if down else at, node)
    return names


def partition_nodes(groups: Sequence[tuple[str, bool, Sequence[NodeLine]]]) -> dict[str, tuple[str, ...]]:
    return {partition: tuple(node.node for node in lines) for partition, _default, lines in groups}


def where_text(partition: str, nodes: Mapping[str, Sequence[str]]) -> str:
    """Where a partition's queued cases will run, for people: its node when it has one, else its name."""
    members = nodes.get(partition, ())
    return members[0] if len(members) == 1 else partition


@dataclass(frozen=True)
class NodeJob:
    """A study's job on a node, as on its Run page (how far the whole job is): running, with cases running there, or
    waiting, with cases queued for the node's partition and none running there."""
    study: Path
    study_name: str
    job_id: str
    started: datetime
    finished: int
    total: int
    cases: tuple[str, ...]  # its cases running on this node (waiting: queued for it)
    waiting: bool = False
    elsewhere: str = ""  # where else the job is: "6 more queued on hpc1", "running on hpc2 · 5 / 20"
    per_case: Optional[float] = None  # its average case run time (s), once a case has run to the end
    ends: Optional[float] = None  # about when the whole job ends (time.time() seconds; see job_left)

    @property
    def done(self) -> float:
        return self.finished / self.total if self.total else 0.0

    @property
    def tip(self) -> str:
        if self.waiting:
            return f"Job {self.job_id} · {len(self.cases)} case{'' if len(self.cases) == 1 else 's'} queued here"
        return f"Job {self.job_id} · running here: {', '.join(self.cases)}"

    def left(self, now: datetime) -> Optional[float]:
        return None if self.ends is None else max(0.0, self.ends - now.timestamp())


def node_jobs(rows: Iterable[MyJob], lookup: Callable[[Path, str], Optional[tuple[JobRecord, str]]],
              nodes: Optional[Mapping[str, Sequence[str]]] = None,
              taken: float = 0.0) -> dict[str, tuple[NodeJob, ...]]:
    """Node -> the study jobs on it (from My jobs' rows and the job records): those with cases running there by
    study name, then, given each partition's nodes, those with cases queued for it and none running there, in the
    order they were submitted. `taken`: when Slurm was asked (time.time()), for when each job ends."""
    running: dict[tuple[Path, str], dict[str, list[str]]] = {}  # job -> node -> its cases running there
    queued: dict[tuple[Path, str], dict[str, list[str]]] = {}  # job -> partition -> its cases queued for it
    records: dict[tuple[Path, str], tuple[JobRecord, str]] = {}
    first: dict[tuple[Path, str], int] = {}  # job -> its lowest queued Slurm id: the queue's order
    for row in rows:
        if row.study is None or row.job_id is None or row.earlier_attempt or row.task:
            continue
        key = (row.study, row.job_id)
        if row.slurm_state in RUNNING_STATES and row.node:
            places, into = row.node.split(","), running
        elif row.slurm_state in QUEUED_STATES and row.partition and nodes is not None:
            places, into = [row.partition], queued
            first[key] = min(first.get(key, 1 << 62), int(row.slurm_id) if row.slurm_id.isdigit() else 1 << 62)
        else:
            continue
        if key not in records:
            record = lookup(row.study, row.slurm_id)
            if record is None:
                continue
            records[key] = (record[0], row.study_name)
        for place in places:
            into.setdefault(key, {}).setdefault(place, []).append(row.case)

    def line(key, cases, waiting=False, elsewhere=""):
        job, name = records[key]
        finished = sum(1 for case in job.cases if job.case_status.get(case) in FINAL_CASE_STATES)
        left = job_left(job, max(0.0, taken - job.created.timestamp()))
        return NodeJob(key[0], name, key[1], job.created, finished, len(job.cases), tuple(sorted(cases)), waiting,
                       elsewhere, case_seconds(job), None if left is None else taken + left)

    partitions = nodes or {}
    lines: dict[str, list[NodeJob]] = {}
    for key, here in running.items():
        for node, cases in here.items():
            others = [f"{len(more)} more queued on {where_text(p, partitions)}"
                      for p, more in queued.get(key, {}).items() if not set(partitions.get(p, ())) & set(here)]
            others += [f"also running on {other}" for other in sorted(here) if other != node]
            lines.setdefault(node, []).append(line(key, cases, elsewhere=" · ".join(others)))
    for node in lines:
        lines[node].sort(key=lambda j: (j.study_name, j.job_id))
    for key in sorted(queued, key=lambda k: first.get(k, 1 << 62)):
        on = sorted(running.get(key, {}))
        for partition, cases in queued[key].items():
            for node in partitions.get(partition, ()):
                if node in on:
                    continue  # queued behind its own cases there: part of the running line
                elsewhere = ""
                if on:
                    job, _name = records[key]
                    done = sum(1 for case in job.cases if job.case_status.get(case) in FINAL_CASE_STATES)
                    elsewhere = f"running on {', '.join(on)} · {done} / {len(job.cases)}"
                lines.setdefault(node, []).append(line(key, cases, True, elsewhere))
    return {node: tuple(found) for node, found in lines.items()}


def queue_starts(lines: Sequence[NodeJob], now: datetime) -> list[tuple[Optional[float], str]]:
    """For each waiting line on a node, about when it starts (seconds from now, None when not known yet) and after
    which study: the first when the first running job there ends, each next after the one before it has run its cases
    here at its job's average time per case."""
    running = [(job.left(now), job.study_name) for job in lines if not job.waiting]
    known = [item for item in running if item[0] is not None]
    if known:
        free, after = min(known)
    else:
        free, after = None, running[0][1] if running else ""
    starts = []
    for job in lines:
        if not job.waiting:
            continue
        starts.append((free, after))
        free = free + job.per_case * len(job.cases) if free is not None and job.per_case is not None else None
        after = job.study_name
    return starts


def queue_text(start: Optional[float], after: str) -> str:
    if start is not None and after:
        return f"Starts in about {about_text(start)} · after {after}"
    return f"Starts after {after}" if after else "Waiting in the Slurm queue"


@dataclass(frozen=True)
class Glance:
    """One of the Cluster page's tiles at the top."""
    key: str
    label: str
    value: str
    sub: str
    alert: bool = False


def _plural(count: int, word: str, many: str = "") -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


def glance(nodes: Sequence[tuple[str, bool, NodeLine]], board: Mapping[str, Sequence[NodeJob]],
           rows: Iterable[MyJob], lookup: Callable[[Path, str], Optional[tuple[JobRecord, str]]]) -> tuple[Glance, ...]:
    """The tiles: studies running and where, studies queued, cases to go in the active jobs, CPUs in use, nodes up."""
    running: dict[str, set[str]] = {}
    waiting: dict[tuple[Path, str], tuple[str, set[str]]] = {}  # a partition of several nodes lists it on each
    for node, lines in board.items():
        for job in lines:
            if job.waiting:
                waiting.setdefault((job.study, job.job_id), (job.study_name, set()))[1].update(job.cases)
            else:
                running.setdefault(job.study_name, set()).add(node)
    queued = sorted((name, len(cases)) for name, cases in waiting.values() if name not in running)  # nothing runs
    active: dict[tuple[Path, str], JobRecord] = {}
    for row in rows:
        if row.active and row.study is not None and row.job_id is not None and (row.study, row.job_id) not in active:
            record = lookup(row.study, row.slurm_id)
            if record is not None:
                active[(row.study, row.job_id)] = record[0]
    total = sum(len(job.cases) for job in active.values())
    finished = sum(1 for job in active.values() for case in job.cases if job.case_status.get(case) in FINAL_CASE_STATES)
    where = sorted({node for found in running.values() for node in found})
    cpus, used = sum(n.total for _p, _d, n in nodes), sum(n.allocated for _p, _d, n in nodes)
    bad = [n for _p, _d, n in nodes if n.bad]
    return (
        Glance("running", "Running", _plural(len(running), "study", "studies") if running else "None",
               f"on {', '.join(where)}" if where else "nothing of yours runs now"),
        Glance("queued", "Queued", _plural(len(queued), "study", "studies") if queued else "None",
               " · ".join(f"{name} · {_plural(count, 'case')}" if len(queued) == 1 else f"{name} {count}"
                          for name, count in queued) or "nothing waits"),
        Glance("left", "Cases to go", str(total - finished),
               f"of {total} · {finished} finished" if total else "no active job"),
        Glance("cpus", "CPUs in use", f"{used} / {cpus}", f"{round(100 * used / cpus) if cpus else 0}%"),
        Glance("nodes", "Nodes", f"{len(nodes) - len(bad)} of {len(nodes)} up",
               ", ".join(f"{n.node} {n.words.lower()}" for n in bad) or "all up", bool(bad)),
    )


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


def started_at(row: MyJob, taken: float) -> Optional[float]:
    """When a case started: Slurm accounting's time, else (running, accounting not asked yet) from its run time."""
    if row.started is not None:
        return row.started
    if row.slurm_state in RUNNING_STATES and taken:
        return taken - (parse_duration(row.elapsed) or 0.0)
    return None


def _job_key(row: MyJob) -> Optional[tuple[Path, str]]:
    if row.study is None or row.job_id is None or row.task or row.earlier_attempt:
        return None
    return row.study, row.job_id


def expected_ends(rows: Sequence[MyJob], lookup: Callable[[Path, str], Optional[tuple[JobRecord, str]]],
                  taken: float) -> tuple[dict[str, float], dict[tuple[Path, str], float]]:
    """About when each running or queued case ends (by Slurm id), and each active study job: a running case at its
    start plus its job's average case run time; then, per partition, the queued cases in the order Slurm got them
    (their job's in the order they were submitted, after the jobs before it there), as many at a time as that job
    runs there now. Left out when not known: before a case of the job has run to the end, or a job whose cases all
    wait behind someone else's."""
    per: dict[tuple[Path, str], Optional[float]] = {}
    for row in rows:
        key = _job_key(row)
        if key is not None and row.active and key not in per:
            record = lookup(row.study, row.slurm_id)
            per[key] = case_seconds(record[0]) if record is not None else None
    ends: dict[str, float] = {}
    for row in rows:
        key = _job_key(row)
        if key in per and row.slurm_state in RUNNING_STATES and per[key] is not None:
            start = started_at(row, taken)
            if start is not None:
                ends[row.slurm_id] = max(taken, start + per[key])

    def order(row: MyJob) -> int:
        return int(row.slurm_id) if row.slurm_id.isdigit() else 1 << 62

    by_partition: dict[str, dict[tuple[Path, str], list[MyJob]]] = {}
    for row in sorted(rows, key=order):
        key = _job_key(row)
        if key in per and row.active and row.partition:
            by_partition.setdefault(row.partition, {}).setdefault(key, []).append(row)
    unknown: set[tuple[Path, str]] = set()
    for jobs in by_partition.values():
        base: Optional[float] = None
        for key, found in jobs.items():  # in the order of each job's first Slurm id there
            slots = [ends.get(row.slurm_id) for row in found if row.slurm_state in RUNNING_STATES]
            if not slots:
                slots = [base]
            queued = [row for row in found if row.slurm_state not in RUNNING_STATES]
            if per[key] is None or any(slot is None for slot in slots):
                unknown.add(key)
                base = None
                continue
            for row in queued:
                at = min(range(len(slots)), key=lambda i: slots[i])
                slots[at] = ends[row.slurm_id] = slots[at] + per[key]
            base = max(slots)
    job_ends: dict[tuple[Path, str], float] = {}
    for key in per:
        mine = [row for row in rows if _job_key(row) == key and row.active]
        if key not in unknown and mine and all(row.slurm_id in ends for row in mine):
            job_ends[key] = max(ends[row.slurm_id] for row in mine)
    return ends, job_ends


@dataclass(frozen=True)
class JobGroup:
    """A study job in My jobs grouped by job: its cases' rows under a line saying how far it is and when it started
    and ended (or about when it ends)."""
    key: str  # for markers: "<study name>-<job id>", or the study name for rows of no job
    study: Optional[Path]
    study_name: str
    job_id: Optional[str]
    state: str  # the job's ("Running", "Done", ...); "" without a job record
    finished: int
    total: int
    started: Optional[float]
    ended: Optional[float]  # when it ended; while it runs, about when it ends (None: not known yet)
    active: bool
    rows: tuple[MyJob, ...]


def job_groups(rows: Sequence[MyJob], lookup: Callable[[Path, str], Optional[tuple[JobRecord, str]]],
               job_ends: Mapping[tuple[Path, str], float], taken: float) -> list[JobGroup]:
    """My jobs' rows (in their order) under their study job, the groups in the order of their first row."""
    found: dict[tuple, list[MyJob]] = {}
    for row in rows:
        found.setdefault((row.study_name, row.study, None if row.task else row.job_id), []).append(row)
    groups = []
    for (name, study, job_id), members in found.items():
        record = None
        if study is not None and job_id is not None:
            record = next((r[0] for r in (lookup(study, row.slurm_id) for row in members) if r is not None), None)
        starts = [s for s in (started_at(row, taken) for row in members) if s is not None]
        if record is None:
            groups.append(JobGroup(name, study, name, job_id, "", 0, 0, min(starts, default=None), None, False,
                                   tuple(members)))
            continue
        finished = sum(1 for case in record.cases if record.case_status.get(case) in FINAL_CASE_STATES)
        if record.is_active:
            ended = job_ends.get((study, job_id))
        else:
            ends = [row.ended for row in members if row.ended is not None]
            ended = max(ends) if ends else (record.finished.timestamp() if record.finished else None)
        groups.append(JobGroup(f"{name}-{job_id}", study, name, job_id, record.state.value.capitalize(), finished,
                               len(record.cases), min(starts, default=None), ended, record.is_active,
                               tuple(members)))
    return groups


def when_text(stamp: Optional[float], today: Optional[datetime] = None) -> str:
    """'09:41' today, '28 Oct 22:27' on another day, '—' when not known."""
    if stamp is None:
        return "—"
    moment = datetime.fromtimestamp(stamp)
    return f"{moment:%H:%M}" if moment.date() == (today or datetime.now()).date() else f"{moment:%d %b %H:%M}"


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

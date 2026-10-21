"""Slurm's commands: their arguments, parsers for their output, and running them — blocking (the CLI) or as an
asyncio subprocess (the web server, whose event loop must never wait on Slurm).

Polling makes one `squeue` call for every job and at most one `sacct` call for the jobs that have left the queue.
`sacct -X` gives each job's state, exit code, elapsed time and node; its MaxRSS is empty (memory is recorded on the
job's steps, per task), so the job's total memory comes from `seff`.
"""
from __future__ import annotations

import asyncio
import getpass
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from .errors import AeroSuiteError

TIMEOUT = 20.0
SACCT_FIELDS = "JobID,State,ExitCode,Elapsed,MaxRSS,NodeList"

QUEUED_STATES = {"PENDING", "CONFIGURING", "REQUEUED", "REQUEUE_HOLD", "REQUEUE_FED", "RESIZING", "SUSPENDED",
                 "STOPPED"}
RUNNING_STATES = {"RUNNING", "COMPLETING", "SIGNALING", "STAGE_OUT"}
FAILED_STATES = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED",
                 "REVOKED", "SPECIAL_EXIT"}
FINAL_STATES = FAILED_STATES | {"COMPLETED", "CANCELLED"}
RESUBMITTABLE = {"NODE_FAIL", "OUT_OF_MEMORY"}
BAD_NODE_STATES = ("drain", "down", "fail", "maint", "unk", "boot_fail", "inval", "no_resp", "not_resp")
NEVER_SATISFIED = "DependencyNeverSatisfied"


class SlurmUnavailable(AeroSuiteError):
    """A Slurm command is missing, timed out or failed (e.g. the controller cannot be reached)."""


# -- arguments ----------------------------------------------------------------------------------------------

def sacct_args(job_ids: Iterable[str]) -> list[str]:
    return ["sacct", "-j", ",".join(job_ids), "-P", "-n", "-X", f"--format={SACCT_FIELDS}"]


def seff_args(job_id: str) -> list[str]:
    return ["seff", job_id]


def sbatch_args(script: str) -> list[str]:
    return ["sbatch", "--parsable", script]


def scancel_args(job_ids: Iterable[str]) -> list[str]:
    return ["scancel", *job_ids]


# -- parsed output ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AcctRow:
    job_id: str
    state: str  # "CANCELLED by 1000" -> "CANCELLED"
    exit_code: str  # "0:0", "1:0", "0:125"
    elapsed: str
    max_rss: str
    node: str


@dataclass(frozen=True)
class SeffStats:
    state: str = ""
    wall_s: Optional[float] = None
    cpu_utilized_s: Optional[float] = None
    memory_gb: Optional[float] = None  # the job's total ("Memory Utilized")


def parse_sbatch(text: str) -> str:
    """The job id from `sbatch --parsable`: "123" or "123;cluster"."""
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    job_id = first.split(";")[0].strip()
    if not job_id.isdigit():
        raise SlurmUnavailable(f"sbatch did not print a job id (it printed {text.strip()!r})")
    return job_id


def _strip_reason(text: str) -> str:
    text = text.strip()
    return text[1:-1] if text.startswith("(") and text.endswith(")") else text


def parse_sacct(text: str) -> dict[str, AcctRow]:
    rows = {}
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 6 or not parts[0] or "." in parts[0]:  # steps (123.batch, 123.0) are not wanted
            continue
        job_id, state, exit_code, elapsed, max_rss, node = (part.strip() for part in parts[:6])
        rows[job_id] = AcctRow(job_id, state.split(" ")[0] if state else "", exit_code, elapsed, max_rss, node)
    return rows


_DURATION_RE = re.compile(r"^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def parse_duration(text: str) -> Optional[float]:
    """Seconds in a Slurm duration: [D-][HH:]MM:SS[.mmm], e.g. "01:12:19", "4-18:31:21", "00:02.345"."""
    match = _DURATION_RE.match(text.strip())
    if not match:
        return None
    days, hours, minutes, seconds = match.groups()
    return int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)


_UNITS = {"B": 1 / 1024 ** 3, "KB": 1 / 1024 ** 2, "K": 1 / 1024 ** 2, "MB": 1 / 1024, "M": 1 / 1024,
          "GB": 1.0, "G": 1.0, "TB": 1024.0, "T": 1024.0}


def parse_seff(text: str) -> SeffStats:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip()
    memory = None
    match = re.match(r"([\d.]+)\s*([KMGT]?B?)\b", values.get("Memory Utilized", ""))
    if match and match.group(2).upper() in _UNITS:
        memory = float(match.group(1)) * _UNITS[match.group(2).upper()]
    return SeffStats(
        state=values.get("State", "").split(" ")[0],
        wall_s=parse_duration(values.get("Job Wall-clock time", "")),
        cpu_utilized_s=parse_duration(values.get("CPU Utilized", "")),
        memory_gb=memory,
    )


SQUEUE_FORMAT = "%i|%T|%N|%M|%R|%u|%j|%Z"  # every user's jobs: id, state, node, time, reason, user, name, folder
SINFO_NODES_FORMAT = "%N|%P|%t|%C|%m|%e|%O|%E"  # per node: partition, state, CPUs, memory, free, load, reason
RECENT_DAYS = 7
RECENT_FIELDS = "JobID,JobName,State,ExitCode,Elapsed,NodeList,Partition,Start,End,WorkDir"


def squeue_args() -> list[str]:
    return ["squeue", "-h", "-o", SQUEUE_FORMAT]


def sinfo_nodes_args() -> list[str]:
    return ["sinfo", "-h", "-N", "-o", SINFO_NODES_FORMAT]


def sacct_recent_args(days: int = RECENT_DAYS) -> list[str]:
    return ["sacct", "-S", f"now-{days}days", "-X", "-n", "-P", f"--format={RECENT_FIELDS}"]


def current_user() -> str:
    """The Unix user running AeroSuite: whose jobs are "mine"."""
    return getpass.getuser()


@dataclass(frozen=True)
class QueueRow:
    job_id: str
    state: str
    node: str  # "" while pending
    time: str  # run time as squeue prints it, "0:00" while pending
    reason: str  # pending: why ("Resources", "Dependency"); running: the node list
    user: str = ""
    name: str = ""  # an AeroSuite case: "<study>/<case>"
    workdir: str = ""  # an AeroSuite case: "<study folder>/runs/<case>"; "" when Slurm does not say


def _folder(text: str) -> str:
    text = text.strip()
    return text if text.startswith("/") else ""  # "(null)", "N/A", ""


def parse_squeue(text: str) -> dict[str, QueueRow]:
    """squeue rows by job id: 8 fields (SQUEUE_FORMAT), or the 5 of the older format. A '|' inside a job name stays
    in the name: the folder is always the last field."""
    rows = {}
    for line in text.splitlines():
        parts = [part.strip() for part in line.strip().split("|")]
        if len(parts) < 5 or not parts[0]:
            continue
        job_id, state, node, run_time, reason = parts[:5]
        user, name, workdir = "", "", ""
        if len(parts) >= 8:
            user, name, workdir = parts[5], "|".join(parts[6:-1]), _folder(parts[-1])
        rows[job_id] = QueueRow(job_id, state, node, run_time, _strip_reason(reason), user, name, workdir)
    return rows


@dataclass(frozen=True)
class NodeRow:
    node: str
    partition: str
    default: bool  # the default partition (sinfo marks it '*')
    state: str  # idle, mix, alloc, drain, down*, ...
    allocated: int
    idle: int
    other: int
    total: int
    memory_mb: Optional[int]
    free_mb: Optional[int]
    load: Optional[float]
    reason: str  # why it is drained or down; "" when sinfo says "none"

    @property
    def bad(self) -> bool:
        return self.state.rstrip("*~#!%$@^-").startswith(BAD_NODE_STATES)


def _int(text: str) -> Optional[int]:
    try:
        return int(text)
    except ValueError:
        return None


def _float(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:
        return None


def parse_sinfo_nodes(text: str) -> list[NodeRow]:
    rows = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.strip().split("|", 7)]
        if len(parts) != 8 or not parts[0]:
            continue
        node, partition, state, cpus, memory, free, load, reason = parts
        counts = [_int(count) for count in cpus.split("/")]
        if len(counts) != 4 or None in counts:
            continue
        allocated, idle, other, total = counts
        rows.append(NodeRow(node, partition.rstrip("*"), partition.endswith("*"), state, allocated, idle, other,
                            total, _int(memory), _int(free), _float(load),
                            "" if reason.lower() == "none" else reason))
    return rows


@dataclass(frozen=True)
class HistoryRow:
    job_id: str
    name: str
    state: str  # "CANCELLED by 1000" -> "CANCELLED"
    exit_code: str
    elapsed: str
    node: str
    partition: str
    start: str
    end: str
    workdir: str


def parse_sacct_recent(text: str) -> dict[str, HistoryRow]:
    """RECENT_FIELDS rows by job id; a '|' inside a job name stays in the name (the other fields are counted from
    both ends)."""
    rows = {}
    for line in text.splitlines():
        parts = [part.strip() for part in line.strip().split("|")]
        if len(parts) < 10 or not parts[0] or "." in parts[0]:
            continue
        job_id, workdir = parts[0], parts[-1]
        name = "|".join(parts[1:-8])
        state, exit_code, elapsed, node, partition, start, end = parts[-8:-1]
        rows[job_id] = HistoryRow(job_id, name, state.split(" ")[0], exit_code, elapsed, node, partition, start, end,
                                  _folder(workdir))
    return rows


@dataclass(frozen=True)
class RecentJobs:
    """The user's jobs of the last RECENT_DAYS days from accounting (one sacct)."""
    taken: float = field(default_factory=time.time)
    rows: Mapping[str, HistoryRow] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass(frozen=True)
class ClusterInfo:
    """Every node (one sinfo -N)."""
    taken: float = field(default_factory=time.time)
    nodes: Sequence[NodeRow] = ()
    error: Optional[str] = None


async def recent_async(days: int = RECENT_DAYS, timeout: float = TIMEOUT) -> RecentJobs:
    taken = time.time()
    try:
        return RecentJobs(taken=taken, rows=parse_sacct_recent(await run_async(sacct_recent_args(days),
                                                                              timeout=timeout)))
    except SlurmUnavailable as exc:
        return RecentJobs(taken=taken, error=str(exc))


async def nodes_async(timeout: float = TIMEOUT) -> ClusterInfo:
    """One sinfo -N: every node with its partition, CPUs, memory, load and reason."""
    taken = time.time()
    try:
        return ClusterInfo(taken=taken, nodes=parse_sinfo_nodes(await run_async(sinfo_nodes_args(), timeout=timeout)))
    except SlurmUnavailable as exc:
        return ClusterInfo(taken=taken, error=str(exc))


# -- running them -------------------------------------------------------------------------------------------

def _missing(argv: Sequence[str], env: Optional[Mapping[str, str]]) -> Optional[str]:
    path = (env or os.environ).get("PATH", "")
    if shutil.which(argv[0], path=path) is None:
        return f"Slurm's {argv[0]} was not found on PATH; is this the cluster's controller?"
    return None


def _failure(argv: Sequence[str], code: int, stdout: str, stderr: str) -> SlurmUnavailable:
    message = (stderr.strip() or stdout.strip() or f"exit code {code}").splitlines()
    return SlurmUnavailable(f"{argv[0]} failed: {' '.join(line.strip() for line in message[-3:])}")


def run_sync(argv: Sequence[str], cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
             timeout: float = TIMEOUT) -> str:
    """The command's standard output; SlurmUnavailable when it is missing, times out or fails."""
    missing = _missing(argv, env)
    if missing:
        raise SlurmUnavailable(missing)
    try:
        done = subprocess.run(list(argv), cwd=cwd, env=dict(env) if env is not None else None, capture_output=True,
                              text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SlurmUnavailable(f"{argv[0]} did not answer within {timeout:g} s") from None
    except OSError as exc:
        raise SlurmUnavailable(f"Cannot run {argv[0]}: {exc}") from None
    if done.returncode != 0:
        raise _failure(argv, done.returncode, done.stdout, done.stderr)
    return done.stdout


async def run_async(argv: Sequence[str], cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
                    timeout: float = TIMEOUT) -> str:
    """As run_sync, without blocking the event loop."""
    missing = _missing(argv, env)
    if missing:
        raise SlurmUnavailable(missing)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=dict(env) if env is not None else None, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        raise SlurmUnavailable(f"Cannot run {argv[0]}: {exc}") from None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SlurmUnavailable(f"{argv[0]} did not answer within {timeout:g} s") from None
    stdout, stderr = out.decode(errors="replace"), err.decode(errors="replace")
    if proc.returncode != 0:
        raise _failure(argv, proc.returncode, stdout, stderr)
    return stdout


# -- one poll -----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """One poll: the queue (one squeue) and the accounting rows of watched jobs that left it (one sacct)."""
    taken: float = field(default_factory=time.time)
    queue: Mapping[str, QueueRow] = field(default_factory=dict)
    accounting: Mapping[str, AcctRow] = field(default_factory=dict)
    error: Optional[str] = None  # squeue failed: the queue is unknown, so nothing may be taken as finished
    accounting_error: Optional[str] = None  # sacct failed: finished jobs are read from their files

    @property
    def ok(self) -> bool:
        return self.error is None


def _gone(queue: Mapping[str, QueueRow], watched: Iterable[str]) -> list[str]:
    return sorted({job_id for job_id in watched if job_id not in queue}, key=lambda i: (len(i), i))


def snapshot_sync(watched: Iterable[str], timeout: float = TIMEOUT) -> Snapshot:
    taken = time.time()  # before squeue: a job submitted after this is not in it
    try:
        queue = parse_squeue(run_sync(squeue_args(), timeout=timeout))
    except SlurmUnavailable as exc:
        return Snapshot(taken=taken, error=str(exc))
    gone = _gone(queue, watched)
    if not gone:
        return Snapshot(taken=taken, queue=queue)
    try:
        return Snapshot(taken=taken, queue=queue,
                        accounting=parse_sacct(run_sync(sacct_args(gone), timeout=timeout)))
    except SlurmUnavailable as exc:
        return Snapshot(taken=taken, queue=queue, accounting_error=str(exc))


async def snapshot_async(watched: Iterable[str], timeout: float = TIMEOUT) -> Snapshot:
    taken = time.time()
    try:
        queue = parse_squeue(await run_async(squeue_args(), timeout=timeout))
    except SlurmUnavailable as exc:
        return Snapshot(taken=taken, error=str(exc))
    gone = _gone(queue, watched)
    if not gone:
        return Snapshot(taken=taken, queue=queue)
    try:
        return Snapshot(taken=taken, queue=queue,
                        accounting=parse_sacct(await run_async(sacct_args(gone), timeout=timeout)))
    except SlurmUnavailable as exc:
        return Snapshot(taken=taken, queue=queue, accounting_error=str(exc))



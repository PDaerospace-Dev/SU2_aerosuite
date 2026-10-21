# Cluster Page (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A top-level **Cluster** page (top-bar button with a status dot) showing every node, everyone's queue and the
user's AeroSuite cases on Slurm across all studies (queued, running, ended in the last 7 days) with Cancel, Resubmit
and Log; the Run page keeps a one-line cluster summary.

**Architecture:** The server's one Slurm poller (`web/slurm_watch.py`) gains an all-users `squeue`, a per-node
`sinfo -N` and a 7-day `sacct`; a new NiceGUI-free engine module (`engine/cluster.py`) maps each job's working
directory to its study and AeroSuite job record; NiceGUI-free view rules live in `web/cluster_view.py`; the page
(`web/pages/cluster.py`) only reads the poller's snapshots and the records.

**Tech Stack:** Python 3.12, pydantic v2, asyncio (engine); NiceGUI 3.17 (web); Typer (CLI); pytest + NiceGUI's
simulated `user`; `tests/fixtures/fake_slurm.py` stands in for Slurm.

**Spec:** `docs/superpowers/specs/2026-10-20-cluster-page-design.md` (binding). Base:
`docs/superpowers/specs/2026-10-19-slurm-backend-design.md`.

## Global Constraints

- Run everything from the repository root (`/data/software/templates/aerosuite/SU2_aerosuite`) with `uv run …`;
  tests: `uv run pytest -q -p no:cacheprovider`. The 4 tests in `tests/engine/test_sweep_script.py` fail on hpc1
  before and after this work (they import the real SU2 from `/opt/su2/bin`); every other test must pass after each task.
- `aerosuite/engine/` never imports NiceGUI, Typer or `aerosuite.web`/`aerosuite.cli`.
- Pages never run a Slurm command: all Slurm calls are in `web/slurm_watch.py` (async) or the engine runners
  (worker threads via `run.io_bound`).
- One `squeue` per poll for all jobs of all users; at most one batched `sacct -j` per poll; `sinfo -N` only while some
  page shows the Cluster button; the 7-day `sacct` at most every 300 s and only while a Cluster page is open (also
  right after a tracked case leaves the queue); no Slurm call while no page is open and no Slurm job is active.
- The local backend's behaviour is unchanged.
- Commit after each task; message `feat(cluster): …` / `test(cluster): …` ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push only when the user asks.
- Web tests must never reach the real Slurm on hpc1: `slurm_available()` is patched in `tests/web/conftest.py`
  (Task 7) and every test that needs Slurm uses the `fake_slurm` fixture.

**Layout (chosen by the user 2026-10-21):** **D** on the mockups canvas
(https://claude.ai/artifact/VsSeR1BSKb4SuRyXZ9uW5F, board "D · Compact node cards + collapsible queue and jobs"):
compact node cards in a grid (one per node), then **My jobs**, then **Queue**, both collapsible (open by default,
the choice remembered while the server runs).

## Review Focus

- A study moved or renamed after its cases were submitted → My jobs still lists them (study name from the job name,
  Slurm state only, no link, no Cancel/Resubmit); the page does not error. Test: Task 2.
- A resubmitted case → its earlier Slurm id (from the 7-day sacct) is shown as "earlier attempt (now <id>)", never as
  a second live row, and has no actions. Test: Task 2.
- A job name or working directory holding `|`, or Slurm printing `(null)` / `N/A` for a field → the parsers keep the
  row and leave the odd field empty. Test: Task 1.
- Hundreds of jobs in 7 days → My jobs shows the newest 500 and says how many more there are. Test: Task 2 (engine
  cap) and Task 8 (the note).
- Cancel clicked for a case that ended between the page's poll and the click → nothing is scancelled, the user is told
  it had already ended. Test: Task 3.

---

### Task 1: Slurm commands for the whole cluster

All-users `squeue` with user, job name and working directory; per-node `sinfo -N`; the 7-day `sacct`; the current
user. Additive: the per-partition `sinfo` code stays until Task 5 removes its last users.

**Files:**
- Modify: `aerosuite/engine/slurm.py`
- Modify: `tests/fixtures/fake_slurm.py`, `tests/conftest.py` (FakeSlurm)
- Test: `tests/engine/test_slurm_commands.py`

**Interfaces:**
- Produces (`aerosuite/engine/slurm.py`):
  - `SQUEUE_FORMAT = "%i|%T|%N|%M|%R|%u|%j|%Z"`; `squeue_args() -> list[str]` (no `--me`)
  - `QueueRow(job_id, state, node, time, reason, user="", name="", workdir="")`
  - `NodeRow(node, partition, default, state, allocated, idle, other, total, memory_mb, free_mb, load, reason)` with
    property `bad: bool`; `SINFO_NODES_FORMAT`; `sinfo_nodes_args() -> list[str]`;
    `parse_sinfo_nodes(text) -> list[NodeRow]`
  - `HistoryRow(job_id, name, state, exit_code, elapsed, node, partition, start, end, workdir)`; `RECENT_DAYS = 7`;
    `sacct_recent_args(days: int = RECENT_DAYS) -> list[str]`; `parse_sacct_recent(text) -> dict[str, HistoryRow]`
  - `RecentJobs(taken: float, rows: Mapping[str, HistoryRow], error: Optional[str])`;
    `async recent_async(days=RECENT_DAYS, timeout=TIMEOUT) -> RecentJobs`
  - `ClusterInfo` gains `nodes: Sequence[NodeRow] = ()`; `async nodes_async(timeout=TIMEOUT) -> ClusterInfo` (one
    `sinfo -N`, fills `nodes`, leaves `partitions` empty)
  - `current_user() -> str`
- Fake: jobs carry `user` (default: the test's user, override with env `FAKE_SLURM_USER` at sbatch time or
  `FakeSlurm.add_job`); `squeue` prints 8 fields for every user (`--me` filters); `sinfo -N` prints `state["nodes"]`;
  `sacct -S …` prints the current user's ended, accounted jobs in the recent format.
- `FakeSlurm.add_job(job_id, user="someone", state="RUNNING", node="hpc1", time="1:00", reason="None",
  name="other/job", cwd="/home/someone")`; FakeSlurm state gains
  `"nodes": ["hpc1|node1*|idle|0/192/0/192|125000|101000|7.28|none", "hpc2|node2|idle|0/192/0/192|62000|57000|3.38|none"]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/engine/test_slurm_commands.py`:

```python
from aerosuite.engine.slurm import (  # noqa: E402  (next to the other imports when tidying)
    current_user, parse_sacct_recent, parse_sinfo_nodes, recent_async, nodes_async, sacct_recent_args,
    sinfo_nodes_args, squeue_args,
)

# hpc1, 2026-10-20: sinfo -h -N -o "%N|%P|%t|%C|%m|%e|%O|%E"
SINFO_N = "hpc1|node1*|idle|0/192/0/192|125000|101081|7.28|none\nhpc2|node2|drain|0/0/192/192|62000|57125|3.38|bad DIMM\n"
# hpc1, 2026-10-20: sacct -S now-7days -X -n -P --format=JobID,JobName,State,ExitCode,Elapsed,NodeList,Partition,Start,End,WorkDir
SACCT_RECENT = ("33|test/M1p2_0km_a10|COMPLETED|0:0|00:02:56|hpc2|node2|2026-10-20T17:39:13|2026-10-20T17:42:09|"
                "/data/benchmark/x07/test/runs/M1p2_0km_a10\n"
                "20|test/M1p2_0km_a0|CANCELLED by 1000|0:0|00:01:50|hpc1|node1|2026-10-20T16:29:42|2026-10-20T16:31:32|"
                "/data/benchmark/x07/test/runs/M1p2_0km_a0\n")


def test_squeue_asks_for_every_user_with_name_and_folder():
    assert squeue_args() == ["squeue", "-h", "-o", "%i|%T|%N|%M|%R|%u|%j|%Z"]
    rows = parse_squeue("12|RUNNING|hpc1|1:00|hpc1|pdas-hpc1|test/M0p8_a0|/data/s/runs/M0p8_a0\n"
                        "13|PENDING||0:00|(Resources)|ana|my|job|(null)\n"
                        "14|PENDING||0:00|(Priority)\n")
    assert (rows["12"].user, rows["12"].name, rows["12"].workdir) == ("pdas-hpc1", "test/M0p8_a0", "/data/s/runs/M0p8_a0")
    assert (rows["13"].user, rows["13"].name, rows["13"].workdir) == ("ana", "my", "")  # '|' in a name, (null) dir
    assert (rows["14"].user, rows["14"].reason) == ("", "Priority")  # the old 5-field form still reads


def test_sinfo_nodes_from_hpc1():
    assert sinfo_nodes_args() == ["sinfo", "-h", "-N", "-o", "%N|%P|%t|%C|%m|%e|%O|%E"]
    nodes = parse_sinfo_nodes(SINFO_N)
    assert [(n.node, n.partition, n.default, n.state) for n in nodes] == [
        ("hpc1", "node1", True, "idle"), ("hpc2", "node2", False, "drain")]
    hpc1, hpc2 = nodes
    assert (hpc1.allocated, hpc1.total, hpc1.memory_mb, hpc1.free_mb, hpc1.load) == (0, 192, 125000, 101081, 7.28)
    assert hpc1.reason == "" and not hpc1.bad
    assert hpc2.reason == "bad DIMM" and hpc2.bad
    odd = parse_sinfo_nodes("hpc3|node3|down*|0/0/96/96|N/A|N/A|N/A|Not responding\n")[0]
    assert (odd.memory_mb, odd.free_mb, odd.load, odd.bad) == (None, None, None, True)


def test_sacct_recent_from_hpc1():
    assert sacct_recent_args() == ["sacct", "-S", "now-7days", "-X", "-n", "-P",
                                   "--format=JobID,JobName,State,ExitCode,Elapsed,NodeList,Partition,Start,End,WorkDir"]
    rows = parse_sacct_recent(SACCT_RECENT)
    assert rows["33"].name == "test/M1p2_0km_a10" and rows["33"].partition == "node2"
    assert rows["33"].workdir == "/data/benchmark/x07/test/runs/M1p2_0km_a10"
    assert rows["20"].state == "CANCELLED"


def test_current_user():
    import getpass

    assert current_user() == getpass.getuser()


def test_fake_queue_shows_every_user(fake_slurm, tmp_path):
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a", "-J s/a").parent))
    fake_slurm.add_job("900", user="ana", name="ana/case", cwd="/data/ana/runs/case")
    rows = parse_squeue(run_sync(squeue_args()))
    assert rows["101"].user == current_user() and rows["101"].name == "s/a"
    assert rows["101"].workdir == str(tmp_path / "a")
    assert rows["900"].user == "ana"


def test_fake_nodes_and_recent(fake_slurm, tmp_path):
    import asyncio

    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a", "-J s/a", "-p node2").parent))
    fake_slurm.finish("101", "OUT_OF_MEMORY", "0:125", node="hpc2")
    info = asyncio.run(nodes_async())
    assert [n.node for n in info.nodes] == ["hpc1", "hpc2"] and info.error is None
    recent = asyncio.run(recent_async())
    assert recent.rows["101"].state == "OUT_OF_MEMORY" and recent.rows["101"].workdir == str(tmp_path / "a")
    assert recent.rows["101"].partition == "node2"
    fake_slurm.update(accounting_down=True)
    assert asyncio.run(recent_async()).error is not None
    fake_slurm.update(controller_down=True)
    assert asyncio.run(nodes_async()).error is not None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_slurm_commands.py`
Expected: FAIL (ImportError: cannot import name 'current_user').

- [ ] **Step 3: Implement in `aerosuite/engine/slurm.py`**

Replace `SQUEUE_FORMAT`, `squeue_args`, `QueueRow` and `parse_squeue`; add the rest next to the existing parsers:

```python
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
```

Add `import getpass` at the top and `nodes: Sequence[NodeRow] = ()` to `ClusterInfo` (after `reasons`).

- [ ] **Step 4: Update the fake** — in `tests/fixtures/fake_slurm.py`:

```python
import getpass
```

In `sbatch`, add to the new job's dict: `"user": os.environ.get("FAKE_SLURM_USER") or getpass.getuser(),`.

Replace `squeue`, `sinfo` and the start of `sacct`:

```python
def squeue(state, args):
    if state.get("controller_down"):
        return fail(CONTROLLER_DOWN)
    me = getpass.getuser()
    for job_id, job in sorted(state["jobs"].items(), key=lambda item: int(item[0])):
        user = job.get("user") or me
        if not job["in_queue"] or ("--me" in args and user != me):
            continue
        reason = job["node"] if job["state"] in ("RUNNING", "COMPLETING") else "(" + job["reason"] + ")"
        fields = [job_id, job["state"], job["node"], job["time"], reason, user, job.get("name", ""),
                  job.get("cwd", "") or "(null)"]
        sys.stdout.write("|".join(fields) + "\n")
    return 0


def sinfo(state, args):
    if state.get("controller_down"):
        return fail("slurm_load_partitions: Unable to contact slurm controller (connect failure)")
    if "-N" in args:
        lines = state.get("nodes", [])
    else:
        lines = state["reasons"] if "-R" in args else state["partitions"]
    for line in lines:
        sys.stdout.write(line + "\n")
    return 0


def sacct(state, args):
    if state.get("accounting_down"):
        return fail(ACCOUNTING_DOWN)
    if "-S" in args:  # the recent history: the user's ended, accounted jobs
        me = getpass.getuser()
        for job_id, job in sorted(state["jobs"].items(), key=lambda item: int(item[0])):
            if job["in_queue"] or not job.get("accounted", True) or (job.get("user") or me) != me:
                continue
            fields = [job_id, job.get("name", ""), job["state"], job["exit_code"], job["elapsed"], job["node"],
                      job.get("partition", ""), job.get("start", ""), job.get("end", ""), job.get("cwd", "")]
            sys.stdout.write("|".join(fields) + "\n")
        return 0
    ids = args[args.index("-j") + 1].split(",")
    # ... the rest of the existing function unchanged
```

In `tests/conftest.py` `FakeSlurm.__init__`, add to the initial state:

```python
            "nodes": ["hpc1|node1*|idle|0/192/0/192|125000|101000|7.28|none",
                      "hpc2|node2|idle|0/192/0/192|62000|57000|3.38|none"],
```

and add the method:

```python
    def add_job(self, job_id: str, user: str = "someone", state: str = "RUNNING", node: str = "hpc1",
                time: str = "1:00", reason: str = "None", name: str = "other/job", cwd: str = "/home/someone") -> None:
        """A job someone else (or a hand-written script) put in the queue."""
        data = self.read()
        data["jobs"][job_id] = {"name": name, "partition": "node1", "ntasks": "4", "dependency": None, "cwd": cwd,
                                "script": "", "env_virtual_env": None, "user": user, "state": state,
                                "in_queue": True, "node": node, "time": time, "reason": reason, "exit_code": "0:0",
                                "elapsed": "00:00:00", "accounted": True, "seff": None}
        self.write(data)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_slurm_commands.py tests/engine/test_slurm_refresh.py tests/web/test_slurm_watch.py`
Expected: PASS (the snapshot code keeps using `queue.get(job_id)`, which all-users rows still satisfy).

- [ ] **Step 6: Commit**

```bash
git add aerosuite/engine/slurm.py tests/fixtures/fake_slurm.py tests/conftest.py tests/engine/test_slurm_commands.py
git commit -m "feat(cluster): Every user's queue, per-node sinfo and the 7-day sacct

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The user's AeroSuite jobs across studies

**Files:**
- Create: `aerosuite/engine/cluster.py`
- Test: `tests/engine/test_cluster.py`

**Interfaces:**
- Consumes: `QueueRow`, `HistoryRow`, `RESUBMITTABLE`, `QUEUED_STATES`, `RUNNING_STATES` (`engine/slurm.py`);
  `job_name(study, case)` (`engine/jobs/slurm.py`); `scan_jobs`, `JOBS_DIR` (`engine/jobs/store.py`).
- Produces (`aerosuite/engine/cluster.py`):
  - `aerosuite_case(workdir: str, name: str) -> Optional[tuple[Path, str, str]]` — (study folder, study name, case)
  - `study_of(workdir: str, name: str) -> Optional[Path]`
  - `RecordIndex()` with `lookup(study: Path, slurm_id: str) -> Optional[tuple[JobRecord, str]]`
  - `MyJob` (frozen dataclass): `slurm_id, study: Optional[Path], study_name, case, slurm_state,
    case_state: Optional[str], job_id: Optional[str], partition, node, elapsed, exit_code, reason, active: bool,
    current_id: Optional[str], resubmittable: bool`; property `earlier_attempt: bool`
  - `MAX_ROWS = 500`; `my_jobs(queue, recent, user, index, limit=MAX_ROWS) -> tuple[list[MyJob], int]`

- [ ] **Step 1: Write the failing tests** — `tests/engine/test_cluster.py`:

```python
import shutil

from aerosuite.engine.cluster import MAX_ROWS, RecordIndex, aerosuite_case, my_jobs, study_of
from aerosuite.engine.slurm import HistoryRow, QueueRow

from slurm_helpers import A0, A2, slurm_study  # noqa: F401  (fixture)

ME = "pdas-hpc1"


def _queue(job_id, folder, name, state="RUNNING", user=ME, node="hpc1"):
    return QueueRow(job_id, state, node, "1:00", node if state == "RUNNING" else "Priority", user, name, str(folder))


def _ended(job_id, folder, name, state="COMPLETED", partition="node1"):
    return HistoryRow(job_id, name, state, "0:0", "00:02:00", "hpc1", partition, "", "", str(folder))


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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_cluster.py`
Expected: FAIL (ModuleNotFoundError: aerosuite.engine.cluster).

- [ ] **Step 3: Implement** — `aerosuite/engine/cluster.py`:

```python
"""The user's AeroSuite cases on Slurm across every study, found from Slurm itself: an AeroSuite case's job runs in
<study>/runs/<case> and is named <study name>/<case> (the job script sets both), so a job's working directory leads to
its study and that study's job records give AeroSuite's view of it."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from .jobs.runner import CaseState, JobRecord
from .jobs.slurm import job_name
from .jobs.store import JOBS_DIR, scan_jobs
from .project import PROJECT_FILE
from .restarts import RUNS_DIR
from .slurm import QUEUED_STATES, RESUBMITTABLE, RUNNING_STATES, HistoryRow, QueueRow

MAX_ROWS = 500
ACTIVE_STATES = QUEUED_STATES | RUNNING_STATES


def aerosuite_case(workdir: str, name: str) -> Optional[tuple[Path, str, str]]:
    """(study folder, study name, case) when a job looks like an AeroSuite case, else None."""
    if not workdir or not name or "/" not in name:
        return None
    folder = Path(workdir)
    if folder.parent.name != RUNS_DIR:
        return None
    study_name, _, case = name.rpartition("/")
    if case != folder.name:
        return None
    return folder.parent.parent, study_name, folder.name


def study_of(workdir: str, name: str) -> Optional[Path]:
    """The study folder of an AeroSuite case's job, when it is still there and still that study."""
    found = aerosuite_case(workdir, name)
    if found is None:
        return None
    study, _study_name, case = found
    try:
        data = json.loads((study / PROJECT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or job_name(str(data.get("name", "")), case) != name:
        return None
    return study


class RecordIndex:
    """Slurm id -> (job record, case) per study; a study's records are read again only when its jobs/ folder
    changes (every record save replaces a file there, which changes the folder's mtime)."""

    def __init__(self) -> None:
        self._studies: dict[Path, tuple[int, dict[str, tuple[JobRecord, str]]]] = {}

    def lookup(self, study: Path, slurm_id: str) -> Optional[tuple[JobRecord, str]]:
        try:
            stamp = (Path(study) / JOBS_DIR).stat().st_mtime_ns
        except OSError:
            return None
        cached = self._studies.get(study)
        if cached is None or cached[0] != stamp:
            index: dict[str, tuple[JobRecord, str]] = {}
            jobs, _problems = scan_jobs(study)
            for job in reversed(jobs):  # oldest first, so a newer job wins
                for case, sc in job.slurm.items():
                    for seen in (*sc.attempts, sc.job_id):
                        index[seen] = (job, case)
            cached = (stamp, index)
            self._studies[study] = cached
        return cached[1].get(slurm_id)


@dataclass(frozen=True)
class MyJob:
    slurm_id: str
    study: Optional[Path]  # None: the study folder is gone, moved or no longer this study
    study_name: str
    case: str
    slurm_state: str
    case_state: Optional[str]  # AeroSuite's (a CaseState value) for the case's current attempt; None without one
    job_id: Optional[str]  # the AeroSuite job holding it
    partition: str
    node: str
    elapsed: str
    exit_code: str
    reason: str
    active: bool
    current_id: Optional[str]  # the case's current Slurm id (differs for an earlier attempt)
    resubmittable: bool

    @property
    def earlier_attempt(self) -> bool:
        return self.current_id is not None and self.current_id != self.slurm_id


def my_jobs(queue: Mapping[str, QueueRow], recent: Mapping[str, HistoryRow], user: str, index: RecordIndex,
            limit: int = MAX_ROWS) -> tuple[list[MyJob], int]:
    """The user's AeroSuite cases in the queue and in the recent history, newest first, at most `limit`, and how many
    more there were. Hand-written jobs (not in a study's runs/ folder under its study/case name) are left out."""
    seen: dict[str, tuple] = {}
    for job_id, row in recent.items():
        seen[job_id] = (row.name, row.workdir, row.state, row.partition, row.node, row.elapsed, row.exit_code, "")
    for job_id, row in queue.items():  # the queue is newer than accounting
        if row.user == user:
            seen[job_id] = (row.name, row.workdir, row.state, "", row.node, row.time, "", row.reason)
    rows = []
    for job_id, (name, workdir, state, partition, node, elapsed, exit_code, reason) in seen.items():
        found = aerosuite_case(workdir, name)
        if found is None:
            continue
        _folder, study_name, case = found
        study = study_of(workdir, name)
        record = index.lookup(study, job_id) if study is not None else None
        case_state = job = current = None
        resubmittable = False
        if record is not None:
            job, case = record[0], record[1]
            sc = job.slurm[case]
            current = sc.job_id
            partition = partition or sc.partition
            if sc.job_id == job_id:
                status = job.case_status.get(case)
                case_state = status.value if status is not None else None
                resubmittable = status is CaseState.FAILED and sc.state in RESUBMITTABLE
        rows.append(MyJob(job_id, study, study_name, case, state, case_state, job.id if job else None, partition,
                          node, elapsed, exit_code, reason, state in ACTIVE_STATES, current, resubmittable))
    rows.sort(key=lambda row: (len(row.slurm_id), row.slurm_id), reverse=True)
    return rows[:limit], max(0, len(rows) - limit)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_cluster.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/cluster.py tests/engine/test_cluster.py
git commit -m "feat(cluster): The user's AeroSuite cases across studies, found from Slurm

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Cancel one case

**Files:**
- Modify: `aerosuite/engine/jobs/slurm.py` (`cancel_case`, `_final_state`; use `_final_state` wherever a job ends after
  its last case)
- Modify: `aerosuite/web/jobs.py` (`JobWatcher.cancel_case`)
- Modify: `aerosuite/cli/run_cmds.py` (`aerosuite cancel --case`)
- Test: `tests/engine/test_slurm_cancel_resubmit.py`, `tests/engine/test_slurm_refresh.py` (one expectation),
  `tests/cli/test_cli_run_slurm.py`

**Interfaces:**
- Produces: `SlurmRunner.cancel_case(project_dir: Path, job: JobRecord, case: str) -> JobRecord` (raises `JobError` when
  `case` is not one of the job's Slurm cases or scancel fails; returns the job unchanged when the case already ended);
  `JobWatcher.cancel_case(project_dir: Path, project: Project, job_id: str, case: str) -> JobRecord`.
- Job end rule (all ends after the last case, `_final_state(job) -> JobState`): DONE when every case is CONVERGED or
  UNCONVERGED; else FAILED when some case is FAILED; else CANCELLED.

- [ ] **Step 1: Write the failing tests** — append to `tests/engine/test_slurm_cancel_resubmit.py`:

```python
def test_cancel_one_case_lets_the_others_run(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project)
    fake.run("101")
    job = runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, job, A2)
    assert fake.calls("scancel") == [["scancel", "102"]]
    assert job.case_status == {A0: CaseState.RUNNING, A2: CaseState.CANCELLED, A4: CaseState.PENDING}
    assert job.failure_tail[A2] == "Cancelled from the Cluster page."
    assert job.is_active and active_lock(project_dir)["job_id"] == job.id


def test_cancel_a_case_others_restart_from_blocks_them(slurm_study):
    project_dir, project, runner, fake = slurm_study
    for case in project.cases[1:]:
        case.restart = "previous"
    save_project(project_dir, project)
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    job = runner.cancel_case(project_dir, runner.refresh(project_dir, job), A0)
    fake.finish("102", "CANCELLED", elapsed="00:00:00")  # Slurm: --kill-on-invalid-dep
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.CANCELLED, A2: CaseState.BLOCKED}
    assert job.state is JobState.CANCELLED and active_lock(project_dir) is None


def test_cancelling_the_last_case_ends_the_job(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101")
    job = runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, job, A2)
    assert job.state is JobState.CANCELLED and job.finished is not None
    assert active_lock(project_dir) is None


def test_cancel_a_case_that_already_ended_does_nothing(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0, A2])
    fake.finish("101", "FAILED", "1:0")
    stale = job  # the page's copy, from before the case ended
    runner.refresh(project_dir, job)
    job = runner.cancel_case(project_dir, stale, A0)
    assert fake.calls("scancel") == [] and job.case_status[A0] is CaseState.FAILED


def test_cancel_case_errors(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = runner.submit(project_dir, project, cases=[A0])
    with pytest.raises(JobError, match="not a Slurm case of job"):
        runner.cancel_case(project_dir, job, A2)
    fake.update(controller_down=True)
    with pytest.raises(JobError, match="Cannot cancel M0p8_a0_b0"):
        runner.cancel_case(project_dir, job, A0)
    assert load_job(project_dir, job.id).case_status[A0] is CaseState.PENDING
```

In `tests/engine/test_slurm_refresh.py::test_cancelled_outside_aerosuite`, the job's end state changes with the new
rule (only a cancelled case, none failed); change its last line to:

```python
    assert job.case_status[A0] is CaseState.CANCELLED and job.state is JobState.CANCELLED
```

Append to `tests/cli/test_cli_run_slurm.py`:

```python
def test_cancel_one_case_from_the_cli(study):
    project_dir, fake = study
    runner.invoke(app, ["run", str(project_dir), "--backend", "slurm"])
    result = runner.invoke(app, ["cancel", str(project_dir), "--case", A2])
    assert result.exit_code == 0, result.output
    assert f"Cancelled {A2} (Slurm job 102)" in result.output
    assert fake.calls("scancel") == [["scancel", "102"]]
    result = runner.invoke(app, ["cancel", str(project_dir), "--case", "nope"])
    assert result.exit_code == 1 and "not a Slurm case" in result.output
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_slurm_cancel_resubmit.py tests/engine/test_slurm_refresh.py tests/cli/test_cli_run_slurm.py`
Expected: FAIL (AttributeError: 'SlurmRunner' object has no attribute 'cancel_case'; the changed expectation).

- [ ] **Step 3: Implement** — in `aerosuite/engine/jobs/slurm.py` add (beside `cancel`):

```python
    def _final_state(self, job: JobRecord) -> JobState:
        """How a job whose cases all ended ends: DONE when every case ran to the end, FAILED when one failed, else
        CANCELLED (cases cancelled, or blocked by a cancelled one)."""
        states = [job.case_status[name] for name in job.cases]
        if all(state in OK_STATES for state in states):
            return JobState.DONE
        return JobState.FAILED if CaseState.FAILED in states else JobState.CANCELLED

    @_serialized
    def cancel_case(self, project_dir: Path, job: JobRecord, case: str) -> JobRecord:
        """scancel one case; the job's other cases go on. Nothing happens when the case has already ended."""
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        sc = job.slurm.get(case)
        if sc is None:
            raise JobError(f"{case} is not a Slurm case of job {job.id}")
        if not job.is_active or job.case_status.get(case) in FINAL_CASE_STATES:
            return job
        try:
            sl.run_sync(sl.scancel_args([sc.job_id]))
        except sl.SlurmUnavailable as exc:
            raise JobError(f"Cannot cancel {case} (Slurm job {sc.job_id}): {exc}") from exc
        job.case_status[case] = CaseState.CANCELLED
        sc.state = "CANCELLED"
        job.failure_tail[case] = "Cancelled from the Cluster page."
        self._log(project_dir, job, f"{case} ({sc.job_id}) cancelled: scancel {sc.job_id}")
        if all(job.case_status.get(name) in FINAL_CASE_STATES for name in job.cases):
            self._end(project_dir, job, self._final_state(job))
        else:
            save_job(project_dir, job)
        return job
```

Replace the two places that compute the end state from `ok = all(...)` (in `apply_snapshot` and in
`_abandon_batch`) with `self._end(project_dir, job, self._final_state(job))`.

In `aerosuite/web/jobs.py` add after `add_cases`:

```python
    def cancel_case(self, project_dir: Path, project: Project, job_id: str, case: str) -> JobRecord:
        """Stop one case of a Slurm job (see SlurmRunner.cancel_case)."""
        directory = Path(project_dir).resolve()
        job = next((job for job in self._view(directory, project).overview.jobs if job.id == job_id), None)
        if job is None or job.backend != "slurm":
            raise JobError(f"No Slurm job {job_id} in this project")
        return self.slurm_runner.cancel_case(directory, job, case)
```

In `aerosuite/cli/run_cmds.py`, the `cancel` command gains an option and a branch before the whole-job cancel:

```python
    case: Annotated[Optional[str], typer.Option(
        "--case", help="Slurm: cancel only this case of the job; the others go on")] = None,
```

```python
    if case is not None:
        if job.backend != "slurm":
            typer.echo("Error: --case is for Slurm jobs; a local sweep is cancelled as a whole.", err=True)
            raise typer.Exit(1)
        job = runner_of(job).cancel_case(directory, job, case)
        typer.echo(f"Cancelled {case} (Slurm job {job.slurm[case].job_id})."
                   if job.case_status[case].value == "CANCELLED" else f"{case} had already ended.")
        _echo_job(job)
        return
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/engine/test_slurm_cancel_resubmit.py tests/engine/test_slurm_refresh.py tests/engine/test_slurm_add_cases.py tests/cli`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/jobs/slurm.py aerosuite/web/jobs.py aerosuite/cli/run_cmds.py tests/engine/test_slurm_cancel_resubmit.py tests/engine/test_slurm_refresh.py tests/cli/test_cli_run_slurm.py
git commit -m "feat(cluster): Cancel one case of a Slurm job (and aerosuite cancel --case)

A job whose cases all ended is DONE when every case ran to the end, FAILED
when one failed, else CANCELLED.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: View rules for nodes, queue, my jobs, the dot and the summary

NiceGUI-free; additive (the per-partition rules stay until Task 5).

**Files:**
- Modify: `aerosuite/web/cluster_view.py`
- Test: `tests/web/test_cluster_view.py`

**Interfaces:**
- Consumes: `NodeRow`, `ClusterInfo.nodes`, `Snapshot`, `QueueRow` (Task 1); `MyJob`, `study_of` (Task 2).
- Produces (`aerosuite/web/cluster_view.py`):
  - `NodeLine(node, state, bad, allocated, total, memory, load, reason)` with `busy_percent`, `cpus` properties;
    `node_groups(cluster) -> list[tuple[str, bool, list[NodeLine]]]` — (partition, is default, its nodes), default first
  - `ClusterQueueLine(job_id, user, name, state, node, time, reason, own, study: Optional[Path])`;
    `cluster_queue(snapshot, user) -> list[ClusterQueueLine]` — pending first, then running, each by id
  - `cluster_status(snapshot, cluster) -> tuple[str, str]` — tone `green|amber|red|grey`, tooltip
  - `running_count(snapshot, user) -> int`
  - `summary_line(cluster, snapshot, user) -> tuple[str, bool]` — text, whether it is bad news
  - `JOB_KINDS = ("all", "active", "failed")`; `filter_jobs(rows, kind, study=None) -> list[MyJob]`;
    `job_studies(rows) -> list[str]`; `job_state_text(row) -> str`

- [ ] **Step 1: Write the failing tests** — append to `tests/web/test_cluster_view.py`:

```python
from pathlib import Path

from aerosuite.engine.cluster import MyJob
from aerosuite.engine.slurm import parse_sinfo_nodes
from aerosuite.web.cluster_view import (
    cluster_queue, cluster_status, filter_jobs, job_state_text, job_studies, node_groups, running_count,
    summary_line,
)

NODES = ("hpc1|node1*|alloc|192/0/0/192|125000|20000|96.1|none\n"
         "hpc2|node2|drain|0/0/192/192|62000|57000|0.2|bad DIMM\n"
         "hpc3|node2|idle|0/192/0/192|62000|60000|0.0|none\n")


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


def _job(slurm_id, case_state="RUNNING", slurm_state="RUNNING", active=True, study="s", current=None):
    return MyJob(slurm_id, Path(f"/d/{study}"), study, "c", slurm_state, case_state, "j", "node1", "hpc1", "1:00",
                 "0:0", "", active, current or slurm_id, False)


def test_my_job_filters_and_texts():
    rows = [_job("5"), _job("4", "FAILED", "OUT_OF_MEMORY", False), _job("3", "CONVERGED", "COMPLETED", False, "t"),
            _job("2", "BLOCKED", "CANCELLED", False), _job("1", None, "NODE_FAIL", False, current="4")]
    assert [r.slurm_id for r in filter_jobs(rows, "active")] == ["5"]
    assert [r.slurm_id for r in filter_jobs(rows, "failed")] == ["4", "2", "1"]
    assert [r.slurm_id for r in filter_jobs(rows, "all", "t")] == ["3"]
    assert job_studies(rows) == ["s", "t"]
    assert job_state_text(rows[1]) == "Failed (OUT_OF_MEMORY)"
    assert job_state_text(rows[2]) == "Converged"
    assert job_state_text(rows[0]) == "Running"
    assert job_state_text(rows[4]) == "NODE_FAIL · earlier attempt (now 4)"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_cluster_view.py`
Expected: FAIL (ImportError: cannot import name 'cluster_queue').

- [ ] **Step 3: Implement** — append to `aerosuite/web/cluster_view.py` (and import `Path`, `MyJob`, `study_of`,
  `QUEUED_STATES`, `RUNNING_STATES`, `FAILED_STATES` at the top):

```python
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
    """'Failed (OUT_OF_MEMORY)', 'Converged', 'NODE_FAIL · earlier attempt (now 4)'."""
    if row.earlier_attempt:
        return f"{row.slurm_state} · earlier attempt (now {row.current_id})"
    if row.case_state is None:
        return row.slurm_state
    text = row.case_state.capitalize()
    plain = {"COMPLETED", "RUNNING", "PENDING", "CANCELLED", "COMPLETING"}
    return text if row.slurm_state in plain or row.slurm_state == row.case_state else f"{text} ({row.slurm_state})"
```

In `summary_line`, the "1 drain" text comes from counting each bad state; the test pins
`node2 1 drain, 0/384 busy` for one drained and one idle node (busy counts every node of the partition).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_cluster_view.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/web/cluster_view.py tests/web/test_cluster_view.py
git commit -m "feat(cluster): View rules for nodes, everyone's queue, my jobs, the status dot and the Run summary

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The poller goes per node; the Run page gets its summary line

The poller reads `sinfo -N` (not per-partition) and, with a Cluster page open, the 7-day `sacct`; the Run page's
*Cluster* and *Queue* parts become one summary line. The per-partition code then has no users and is removed.

**Files:**
- Modify: `aerosuite/web/slurm_watch.py`, `aerosuite/web/pages/run.py`, `aerosuite/web/cluster_view.py`,
  `aerosuite/engine/slurm.py`, `tests/fixtures/fake_slurm.py`, `tests/conftest.py`, `tests/web/conftest.py`
- Test: `tests/web/test_slurm_watch.py`, `tests/web/test_web_run_slurm.py`, `tests/web/test_cluster_view.py`,
  `tests/engine/test_slurm_commands.py`

**Interfaces:**
- Consumes: `nodes_async`, `recent_async`, `current_user` (Task 1); `summary_line` (Task 4).
- Produces (`SlurmWatch`): `show_cluster()` / `hide_cluster()` (a page shows the Cluster button: read `sinfo -N`);
  `show_page()` / `hide_page()` (a Cluster page is open: read the 7-day `sacct`); attributes `cluster: ClusterInfo`
  (with `nodes`), `recent: Optional[RecentJobs]`, `user: str`, `pages: int` (property); `RECENT_SECONDS = 300`.
- Removed: `PartitionRow`, `NodeReason`, `parse_sinfo`, `parse_sinfo_reasons`, `sinfo_args`, `sinfo_reason_args`,
  `SINFO_FORMAT`, `SINFO_REASON_FORMAT`, `cluster_async`, `ClusterInfo.partitions`, `ClusterInfo.reasons`
  (`engine/slurm.py`); `PartitionLine`, `partition_lines`, `node_reasons`, `QueueLine`, `queue_lines`, `own_jobs`,
  `outage_text` (`web/cluster_view.py`); the fake's `partitions`/`reasons` state and `sinfo -R`.

- [ ] **Step 1: Rewrite the poller tests** — in `tests/web/test_slurm_watch.py` replace
  `test_sinfo_only_while_a_page_shows_the_cluster` and `test_controller_down_keeps_the_states` with:

```python
async def test_sinfo_per_node_only_while_the_cluster_button_is_shown(two_studies):
    _studies, _runner, watch, fake = two_studies
    watch.show_cluster()
    await watch.poll_once()
    assert [call[0:3] for call in fake.calls()] == [["squeue", "-h", "-o"], ["sinfo", "-h", "-N"]]
    assert [n.node for n in watch.cluster.nodes] == ["hpc1", "hpc2"]
    fake.update(nodes=["hpc1|node1*|idle|0/192/0/192|125000|101000|7.28|none",
                       "hpc2|node2|drain|0/0/192/192|62000|57000|3.38|bad DIMM"])
    await watch.poll_once()
    assert watch.cluster.nodes[1].reason == "bad DIMM"
    watch.hide_cluster()
    fake.clear_calls()
    await watch.poll_once()
    assert fake.calls() == []


async def test_recent_sacct_only_with_a_cluster_page_and_at_most_every_5_minutes(two_studies, monkeypatch):
    from aerosuite.web import slurm_watch

    _studies, _runner, watch, fake = two_studies
    watch.show_page()
    await watch.poll_once()
    assert [call for call in fake.calls() if call[0] == "sacct" and "-S" in call]
    fake.clear_calls()
    await watch.poll_once()
    assert not [call for call in fake.calls() if call[0] == "sacct"]  # within 300 s: not again
    monkeypatch.setattr(slurm_watch, "RECENT_SECONDS", 0.0)
    await watch.poll_once()
    assert [call for call in fake.calls() if call[0] == "sacct" and "-S" in call]
    watch.hide_page()
    fake.clear_calls()
    await watch.poll_once()
    assert fake.calls() == []


async def test_a_case_leaving_the_queue_refreshes_the_recent_history(two_studies):
    studies, runner, watch, fake = two_studies
    directory, project = studies[0]
    job = runner.submit(directory, project, cases=[A0])
    watch.track(directory, job.id)
    watch.show_page()
    await watch.poll_once()
    fake.clear_calls()
    fake.finish("101")
    await watch.poll_once()
    assert [call for call in fake.calls() if call[0] == "sacct" and "-S" in call]
    assert watch.recent.rows["101"].state == "COMPLETED"


async def test_controller_down_keeps_the_states(two_studies):
    studies, runner, watch, fake = two_studies
    directory, project = studies[0]
    job = runner.submit(directory, project, cases=[A0])
    watch.track(directory, job.id)
    watch.show_cluster()
    fake.run("101")
    await watch.poll_once()
    ok_time = watch.last_ok
    fake.update(controller_down=True)
    await watch.poll_once()
    assert not watch.snapshot.ok and "Unable to contact" in watch.snapshot.error
    assert watch.cluster.error is not None and watch.last_ok == ok_time
    assert load_job(directory, job.id).case_status[A0] is CaseState.RUNNING
```

In `tests/web/test_web_run_slurm.py` replace `test_slurm_mode_shows_the_cluster_and_the_slurm_fields` and
`test_drained_node_and_controller_down` with:

```python
async def test_slurm_mode_shows_a_cluster_summary_and_the_slurm_fields(user: User, slurm_project):
    project_dir, _project, fake = slurm_project
    fake.update(nodes=["hpc1|node1*|mix|96/96/0/192|125000|101000|48.0|none",
                       "hpc2|node2|idle|0/192/0/192|62000|57000|0.2|none"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    await _open(user, project_dir)
    await user.should_not_see(marker="run-machine")
    await user.should_not_see(marker="run-partitions")
    assert _text(user, "run-cluster-summary") == "node1 96/192 busy · node2 free"
    assert _element(user, "run-cluster-link").props["href"] == "/cluster"
    assert _element(user, "run-backend").value == "slurm"
    assert _element(user, "run-partition").value == "node1"
    assert _element(user, "run-ntasks").value == "96"
    assert _text(user, "submit") == "Submit 3 cases to Slurm"


async def test_the_summary_turns_red_for_a_drained_node_or_an_outage(user: User, slurm_project, eventually):
    project_dir, _project, fake = slurm_project
    fake.update(nodes=["hpc1|node1*|idle|0/192/0/192|125000|101000|0.0|none",
                       "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    await _open(user, project_dir)
    summary = _element(user, "run-cluster-summary")
    assert summary.text == "node1 free · node2 1 drain, 0/192 busy" and "as-error-text" in summary.classes
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: _text(user, "run-cluster-summary") == "Slurm controller unreachable", 5)
```

In `tests/web/test_web_run_slurm.py::test_the_backend_toggle_is_saved_with_the_project`, replace
`await user.should_see("Cluster")` (twice is once — after switching to Slurm) with
`await user.should_see(marker="run-cluster-summary")`, and drop the final `assert WATCH.viewers == 0`.

In `tests/web/conftest.py` `fresh_slurm_watch`, also reset the new attributes (before and after the test):

```python
    WATCH._tracked.clear()
    WATCH._viewers = 0
    WATCH._pages = 0
    WATCH.snapshot = WATCH.cluster = WATCH.recent = WATCH.last_ok = None
```

In `tests/web/test_cluster_view.py` delete `test_partition_lines_group_node_states`, `test_node_reasons`,
`test_queue_lines_mark_this_studys_jobs`, the `own_jobs` assert in `test_case_slurm_text` and `test_outage_text`, and
their imports. In `tests/engine/test_slurm_commands.py` delete `test_sinfo_rows`, `test_sinfo_reasons`, and in
`test_fake_scancel_and_sinfo` replace the sinfo part with
`assert [n.node for n in parse_sinfo_nodes(run_sync(slurm.sinfo_nodes_args()))] == ["hpc1", "hpc2"]`
(drop the `sinfo -R` lines and the `parse_sinfo`, `parse_sinfo_reasons` imports).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_slurm_watch.py tests/web/test_web_run_slurm.py`
Expected: FAIL (AttributeError: 'SlurmWatch' object has no attribute 'show_page'; marker run-cluster-summary missing).

- [ ] **Step 3: Implement the poller** — in `aerosuite/web/slurm_watch.py`:

```python
RECENT_SECONDS = 300.0  # the 7-day sacct: at most this often, and only while a Cluster page is open
```

In `__init__` add:

```python
        self._pages = 0
        self._recent_due = False
        self.recent: Optional[sl.RecentJobs] = None
        self.user = sl.current_user()
```

Replace the `show_cluster` docstring with `"""A page shows the Cluster button (top bar): read sinfo -N too."""`, and
add:

```python
    def show_page(self) -> None:
        """A Cluster page is open: read the recent history (sacct) too, until hide_page."""
        self._pages += 1
        self._recent_due = True
        self._poke()

    def hide_page(self) -> None:
        self._pages = max(0, self._pages - 1)

    @property
    def pages(self) -> int:
        return self._pages
```

Replace `poll_once`:

```python
    async def poll_once(self) -> None:
        records = self._records()
        active = [(directory, job) for directory, job in records if job.is_active]
        runner = self._runner()
        if active or self._viewers or self._pages:
            watched = [slurm_id for _directory, job in active for slurm_id in runner.watched_ids(job)]
            snapshot = await sl.snapshot_async(watched)
            self.snapshot = snapshot
            self.polls += 1
            if snapshot.ok:
                self.last_ok = snapshot.taken
                if any(slurm_id not in snapshot.queue for slurm_id in watched):
                    self._recent_due = True  # a case left the queue: the history has something new
            for directory, job in active:
                await asyncio.to_thread(runner.apply_snapshot, directory, job, snapshot)
        if self._viewers or self._pages:
            self.cluster = await sl.nodes_async()
        if self._pages and (self._recent_due or self.recent is None
                            or time.time() - self.recent.taken >= RECENT_SECONDS):
            self.recent = await sl.recent_async()
            self._recent_due = False
        await self._fetch_seff(runner)
```

- [ ] **Step 4: Implement the Run summary** — in `aerosuite/web/pages/run.py`:

Delete the methods `_show_cluster`, `_hide_cluster`, `_cluster`, `_cluster_values`, the attributes
`showing_cluster`, `cluster_shown`, the `ui.context.client.on_disconnect(self._hide_cluster)` line, the call
`self._show_cluster(self.slurm)` in `render`, and in `poll()` replace `self._cluster_values()` with
`self._summary_values()`. In `_machine_values` replace the Slurm branch's `self._cluster_values()` with
`self._summary_values()`. In `render`, replace

```python
                        if self.slurm:
                            ui.label("Cluster").classes("as-run-head")
                            self._cluster(view)
```

with

```python
                        if self.slurm:
                            ui.label("Cluster").classes("as-run-head")
                            self._cluster_summary()
```

and add:

```python
    def _cluster_summary(self) -> None:
        """One line on the cluster (partitions, your jobs) and a link to the Cluster page; kept current by poll()."""
        with ui.row().classes("items-baseline w-full no-wrap gap-2"):
            self.summary_label = ui.label("").classes("as-muted").mark("run-cluster-summary")
            ui.space()
            ui.link("Cluster →", "/cluster").classes("no-wrap").mark("run-cluster-link")
        self._summary_values()

    def _summary_values(self) -> None:
        label = getattr(self, "summary_label", None)
        if label is None or label.is_deleted:
            return
        watch = WATCHER.slurm_watch
        text, bad = summary_line(watch.cluster, watch.snapshot, watch.user)
        label.text = text
        label.classes(replace="as-error-text" if bad else "as-muted")
```

Update the imports from `..cluster_view` to
`can_resubmit, case_slurm_text, suggested_partition, summary_line`, and the module docstring's
"the cluster and the queue" to "a one-line cluster summary".

- [ ] **Step 5: Remove the per-partition code** — in `aerosuite/engine/slurm.py` delete `SINFO_FORMAT`,
  `SINFO_REASON_FORMAT`, `sinfo_args`, `sinfo_reason_args`, `PartitionRow`, `NodeReason`, `parse_sinfo`,
  `parse_sinfo_reasons`, `cluster_async`, and make `ClusterInfo`:

```python
@dataclass(frozen=True)
class ClusterInfo:
    """Every node (one sinfo -N)."""
    taken: float = field(default_factory=time.time)
    nodes: Sequence[NodeRow] = ()
    error: Optional[str] = None
```

In `aerosuite/web/cluster_view.py` delete `PartitionLine`, `partition_lines`, `node_reasons`, `QueueLine`,
`queue_lines`, `own_jobs`, `outage_text` and the `PartitionRow` import. In `tests/fixtures/fake_slurm.py` `sinfo`, keep
only the `-N` branch (`lines = state.get("nodes", [])`); in `tests/conftest.py` `FakeSlurm.__init__` drop
`"partitions"` and `"reasons"`. Then `grep -rn "partitions=\|reasons=\|PartitionRow\|parse_sinfo\b\|sinfo_args\|queue_lines\|own_jobs\|outage_text" aerosuite tests`
must print nothing except `settings.slurm.partitions` uses.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/web tests/engine/test_slurm_commands.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A aerosuite tests
git commit -m "feat(cluster): The poller reads every node and the recent history; Run shows a summary line

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: One resubmit dialog for the Run and Cluster pages

**Files:**
- Create: `aerosuite/web/resubmit_dialog.py`
- Modify: `aerosuite/web/pages/run.py` (`confirm_resubmit` uses it)
- Test: `tests/web/test_web_run_slurm.py::test_resubmit_out_of_memory_proposes_more_memory` (unchanged, must pass)

**Interfaces:**
- Consumes: `WATCHER.resubmit`, `slurm_options`, `preflight`, `suggested_partition`, `load_settings`.
- Produces: `async resubmit_case(directory: Path, project: Project, job: JobRecord, case: str) -> Optional[JobRecord]`
  — shows the dialog (markers `resubmit-suggestion`, `resubmit-partition`, `resubmit-keep`, `resubmit-confirm`), checks,
  resubmits in a worker thread, notifies; returns the updated job or None (kept failed, blocked by a check, or failed).

- [ ] **Step 1: Run the existing test as the safety net**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_run_slurm.py -k resubmit`
Expected: PASS (before the move).

- [ ] **Step 2: Move the dialog** — `aerosuite/web/resubmit_dialog.py`:

```python
"""The Resubmit dialog for a NODE_FAIL / OUT_OF_MEMORY case: where to run it again (another partition is proposed
after OUT_OF_MEMORY), the pre-submit checks, then the resubmit in a worker thread. Used by the Run and Cluster pages."""
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.executors import slurm_options
from ..engine.jobs.runner import JobRecord
from ..engine.models import Project
from ..engine.preflight import preflight
from ..engine.settings import load_settings
from .cluster_view import suggested_partition
from .jobs import WATCHER
from .ui_kit import hint, primary_button, secondary_button


def _answer(dialog: ui.dialog, value: bool) -> None:
    dialog.submit(value)
    dialog.delete()


async def resubmit_case(directory: Path, project: Project, job: JobRecord, case: str) -> Optional[JobRecord]:
    settings, _warnings = load_settings()
    partitions = [p.name for p in settings.slurm.partitions]
    limits = {p.name: p.memory_limit_mb for p in settings.slurm.partitions}
    sc = job.slurm[case]
    chosen = {"partition": suggested_partition(job, case, partitions, limits)}
    with ui.dialog() as dialog, ui.card().classes("gap-3"):
        ui.label(f"Resubmit {case}?").classes("as-strong")
        why = "It ran out of memory" if sc.state == "OUT_OF_MEMORY" else "Its node failed"
        ui.label(f"{why} on {sc.partition} (Slurm job {sc.job_id}). It runs again in the same job, with the cases "
                 "waiting for its solution.").classes("as-muted")
        if chosen["partition"] != sc.partition:
            hint(f"Suggested: {chosen['partition']}, which has more memory.").mark("resubmit-suggestion")
        ui.select(partitions, value=chosen["partition"], label="Partition",
                  on_change=lambda e: chosen.update(partition=e.value)).classes("w-full").mark("resubmit-partition")
        with ui.row().classes("w-full justify-end gap-2"):
            secondary_button("Keep it failed", on_click=lambda: _answer(dialog, False)).mark("resubmit-keep")
            primary_button("Resubmit", on_click=lambda: _answer(dialog, True)).mark("resubmit-confirm")
    if not await dialog:
        return None
    partition = chosen["partition"]
    options = slurm_options(project, settings, partition=partition,
                            ntasks=sc.ntasks if partition == sc.partition else None, time_limit=sc.time_limit)
    errors = [p for p in preflight(directory, project, "run", cases=[case], options=options, settings=settings)
              if p.severity == "error" and not p.message.startswith(f"Job {job.id} ")]
    if errors:
        ui.notify(errors[0].message, type="negative")
        return None
    try:
        updated = await run.io_bound(WATCHER.resubmit, directory, project, job.id, [case], options)
    except AeroSuiteError as exc:
        ui.notify(str(exc), type="negative")
        return None
    ui.notify(f"Resubmitted {case} to {partition}", type="positive")
    return updated
```

In `aerosuite/web/pages/run.py` replace the body of `confirm_resubmit` with:

```python
    async def confirm_resubmit(self, job, case: str) -> None:
        """NODE_FAIL / OUT_OF_MEMORY: submit the case again (and the cases blocked behind it) in the same job."""
        self.dialogs_open += 1
        try:
            await resubmit_case(self.directory, self.project, job, case)
        finally:
            self.dialogs_open -= 1
        if not self.holder.is_deleted:
            self.frame.refresh()
            self.render()
```

and import `from ..resubmit_dialog import resubmit_case`; drop `suggested_partition` from the `cluster_view` import if
no longer used.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_run_slurm.py`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add aerosuite/web/resubmit_dialog.py aerosuite/web/pages/run.py
git commit -m "refactor(cluster): One Resubmit dialog for the Run and Cluster pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The top-bar Cluster button

**Files:**
- Modify: `aerosuite/web/slurm_watch.py` (`slurm_available`), `aerosuite/web/layout.py`, `aerosuite/web/theme.py`,
  `tests/web/conftest.py`
- Test: `tests/web/test_web_cluster_button.py`

**Interfaces:**
- Consumes: `WATCH.show_cluster/hide_cluster`, `WATCH.snapshot`, `WATCH.cluster`, `WATCH.user` (Task 5);
  `cluster_status`, `running_count` (Task 4).
- Produces: `slurm_available() -> bool` (`sinfo` on PATH); `_cluster_button()` in both top bars — markers `cluster`,
  `cluster-dot` (classes `as-dot-green|amber|red|grey`, prop `title`), `cluster-count`.

- [ ] **Step 1: Keep web tests off the real Slurm** — in `tests/web/conftest.py` add:

```python
@pytest.fixture(autouse=True)
def no_real_slurm(monkeypatch):
    """hpc1 has the real sinfo on PATH: the Cluster button (and its polling) appears only with the fake Slurm."""
    import os

    from aerosuite.web import slurm_watch

    monkeypatch.setattr(slurm_watch, "slurm_available", lambda: "FAKE_SLURM_STATE" in os.environ)
```

- [ ] **Step 2: Write the failing tests** — `tests/web/test_web_cluster_button.py`:

```python
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url
from aerosuite.web.slurm_watch import WATCH


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_no_button_without_slurm(user: User):
    await user.open("/")
    await user.should_not_see(marker="cluster")


async def test_the_button_dot_and_count(user: User, fake_slurm, ready_project, tmp_path, eventually):
    project_dir, project = ready_project
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)))
    project.run.backend = "slurm"
    generate_configs(project_dir, project)
    runner_for("slurm").submit(project_dir, project)
    fake_slurm.run("101")
    fake_slurm.run("102", node="hpc2")
    await user.open(project_url("run", project_dir))
    await user.should_see(marker="cluster")
    assert WATCH.viewers >= 1  # the button asks the poller for sinfo -N
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-green" in _element(user, "cluster-dot").classes, 5)
    assert _element(user, "cluster-count").text == "· 2"
    fake_slurm.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|101000|96.0|none",
                             "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-amber" in _element(user, "cluster-dot").classes, 5)
    assert "hpc2 drain: bad DIMM" in _element(user, "cluster-dot").props["title"]
    fake_slurm.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-red" in _element(user, "cluster-dot").classes, 5)
    user.find(marker="cluster").click()
    await user.should_see(marker="cluster-page")
```

(`cluster-page` exists after Task 8; until then end this test at the red dot and add the last two lines in Task 8.)

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_cluster_button.py`
Expected: FAIL (marker `cluster` not found).

- [ ] **Step 4: Implement** — `aerosuite/web/slurm_watch.py`:

```python
import shutil


def slurm_available() -> bool:
    """Slurm's commands are installed here (the Cluster button and page are shown only then)."""
    return shutil.which("sinfo") is not None
```

`aerosuite/web/layout.py` — add, and call `_cluster_button()` just before `_calculators_button(...)` in `header()` and
in `ProjectFrame._top_bar`:

```python
def _cluster_button() -> None:
    """The top bar's Cluster button: a dot for the cluster's health and the number of your running jobs."""
    from . import slurm_watch
    from .cluster_view import cluster_status, running_count

    if not slurm_watch.slurm_available():
        return
    watch = slurm_watch.WATCH
    with ui.button(color=None, on_click=lambda: ui.navigate.to("/cluster")).props("flat dense no-caps").classes(
            "as-topbar-icon as-topbar-labelled").mark("cluster"):
        dot = ui.element("span").classes("as-cluster-dot as-dot-grey").mark("cluster-dot")
        ui.label("Cluster")
        count = ui.label("").classes("as-cluster-count").mark("cluster-count")
    watch.show_cluster()
    ui.context.client.on_disconnect(watch.hide_cluster)

    def update() -> None:
        if dot.is_deleted:
            return
        tone, tip = cluster_status(watch.snapshot, watch.cluster)
        dot.classes(replace=f"as-cluster-dot as-dot-{tone}")
        dot.props["title"] = tip
        dot.update()
        running = running_count(watch.snapshot, watch.user)
        count.text = f"· {running}" if running else ""

    update()
    ui.timer(2.0, update)
```

`aerosuite/web/theme.py` — beside the other top-bar rules:

```css
.as-cluster-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 7px; }
.as-dot-green { background: #2da44e; } .as-dot-amber { background: #d4a72c; }
.as-dot-red { background: #cf222e; } .as-dot-grey { background: #8c959f; }
.as-cluster-count { margin-left: 4px; color: #9fb0c8; }
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_cluster_button.py tests/web/test_web_topbar.py tests/web/test_web_shell.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/slurm_watch.py aerosuite/web/layout.py aerosuite/web/theme.py tests/web/conftest.py tests/web/test_web_cluster_button.py
git commit -m "feat(cluster): Cluster button in the top bar with a health dot and your running jobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The Cluster page

**Files:**
- Create: `aerosuite/web/pages/cluster.py`
- Modify: `aerosuite/web/app.py` (register), `aerosuite/web/theme.py` (own-row highlight)
- Test: `tests/web/test_web_cluster.py`; finish `tests/web/test_web_cluster_button.py` (the click)

**Interfaces:**
- Consumes: `WATCH.show_page/hide_page`, `WATCH.snapshot/cluster/recent/user/last_ok`, `WATCH.track` (Task 5);
  `my_jobs`, `RecordIndex` (Task 2); `node_groups`, `cluster_queue`, `cluster_status`, `filter_jobs`, `job_studies`,
  `job_state_text`, `JOB_KINDS` (Task 4); `WATCHER.cancel_case` (Task 3); `resubmit_case` (Task 6);
  `slurm_available` (Task 7).
- Produces: page `/cluster` (layout D); markers `cluster-page`, `cluster-outage`, `nodes-card`, `nodes-summary`,
  `node-card-<n>`, `node-<n>`, `node-<n>-state`, `jobs-card-toggle`, `queue-card-toggle`,
  `node-<n>-cpus`, `node-<n>-memory`, `node-<n>-note`, `queue-card`, `q-<id>`, `q-<id>-user`, `q-<id>-link`,
  `queue-empty`, `jobs-card`, `jobs-filter-<kind>`, `jobs-study`, `job-<id>`, `job-<id>-state`, `cancel-<id>`,
  `cancel-confirm`, `cancel-keep`, `resubmit-<id>`, `log-<id>`, `log-dialog-text`, `jobs-more`, `jobs-accounting`,
  `jobs-none`.

- [ ] **Step 1: Write the failing tests** — `tests/web/test_web_cluster.py`:

```python
import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import save_project
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.slurm_watch import WATCH

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


@pytest.fixture
def cluster_study(ready_project, tmp_path, fake_slurm):
    project_dir, project = ready_project
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)))
    project.run.backend = "slurm"
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    return project_dir, project, fake_slurm


async def _open(user):
    await user.open("/cluster")
    await user.should_see(marker="cluster-page")
    await WATCH.poll_once()  # the page asked for nodes and the recent history


async def test_nodes_queue_and_my_jobs(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101", node="hpc1")
    fake.add_job("900", user="ana", state="PENDING", node="", reason="Resources", name="ana/x")
    fake.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|20000|96.0|none",
                       "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    await _open(user)
    assert WATCH.pages == 1
    await eventually(lambda: _text(user, "node-hpc2-note") == "bad DIMM", 5)
    assert _text(user, "node-hpc1-cpus") == "192 / 192" and _text(user, "node-hpc1-memory") == "20 of 122 GB free"
    assert "as-node-bad" in _element(user, "node-card-hpc2").classes
    assert _text(user, "q-900-user") == "ana"
    assert _element(user, "q-101-link").props["href"].startswith("/run?project=")
    assert _text(user, "job-101-state") == "Running" and _text(user, "job-102-state").startswith("Pending")
    await user.should_not_see(marker="job-900")  # someone else's


async def test_filters(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    fake.finish("102", "OUT_OF_MEMORY", "0:125")
    WATCH.track(project_dir, job.id)
    await _open(user)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="job-102").elements), 5)
    user.find(marker="jobs-filter-active").click()
    await user.should_not_see(marker="job-102")
    await user.should_see(marker="job-101")
    user.find(marker="jobs-filter-failed").click()
    await user.should_see(marker="job-102")
    await user.should_not_see(marker="job-101")


async def test_cancel_one_case(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="cancel-102").elements), 5)
    user.find(marker="cancel-102").click()
    await eventually(lambda: bool(user.find(marker="cancel-confirm").elements))
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].case_status[A2] is CaseState.CANCELLED, 10)
    assert fake.calls("scancel") == [["scancel", "102"]]
    assert list_jobs(project_dir)[0].case_status[A0] is CaseState.RUNNING


async def test_resubmit_from_the_cluster_page(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    project.run.slurm.partition = "node2"
    save_project(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.finish("101", "OUT_OF_MEMORY", "0:125", node="hpc2")
    WATCH.track(project_dir, job.id)
    await _open(user)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="resubmit-101").elements), 5)
    user.find(marker="resubmit-101").click()
    await eventually(lambda: bool(user.find(marker="resubmit-confirm").elements))
    assert _element(user, "resubmit-partition").value == "node1"
    user.find(marker="resubmit-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].slurm[A0].attempts == ["101"], 10)


async def test_log_dialog(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    (project_dir / "runs" / A0 / "slurm-101.out").write_text("AeroSuite: Slurm job 101\n|   12|  -4.1|\n")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="log-101").elements), 5)
    user.find(marker="log-101").click()
    await eventually(lambda: "|   12|  -4.1|" in _text(user, "log-dialog-text"), 5)


async def test_controller_down_shows_stale_data_and_disables_actions(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="cancel-101").elements), 5)
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="cluster-outage").elements), 5)
    assert "Slurm controller unreachable" in _text(user, "cluster-outage")
    assert not _element(user, "cancel-101").enabled


async def test_accounting_down_lists_active_cases_only(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    fake.update(accounting_down=True)
    await _open(user)
    await eventually(lambda: bool(user.find(marker="jobs-accounting").elements), 5)
    await user.should_see(marker="job-101")


async def test_my_jobs_and_queue_fold_and_stay_folded(user: User, cluster_study, eventually):
    from aerosuite.web.pages import cluster as cluster_page

    cluster_page._COLLAPSED.clear()
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-101").elements), 5)
    user.find(marker="jobs-card-toggle").click()
    await user.should_not_see(marker="job-101")
    user.find(marker="queue-card-toggle").click()
    await user.should_not_see(marker="q-101")
    await user.open("/cluster")  # a new page: the sections stay folded
    await user.should_see(marker="jobs-card-toggle")
    await user.should_not_see(marker="job-101")
    user.find(marker="jobs-card-toggle").click()
    await eventually(lambda: bool(user.find(marker="job-101").elements), 5)
    cluster_page._COLLAPSED.clear()


async def test_more_than_the_cap_says_so(user: User, cluster_study, monkeypatch, eventually):
    from aerosuite.web.pages import cluster as cluster_page

    project_dir, project, fake = cluster_study
    monkeypatch.setattr(cluster_page, "MAX_ROWS", 1)
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    await _open(user)
    await eventually(lambda: _text(user, "jobs-more") == "1 older job not shown", 5)
```

Append the last two lines to `tests/web/test_web_cluster_button.py::test_the_button_dot_and_count`:

```python
    user.find(marker="cluster").click()
    await user.should_see(marker="cluster-page")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_cluster.py`
Expected: FAIL (no page at /cluster).

- [ ] **Step 3: Implement** — `aerosuite/web/pages/cluster.py`:

```python
"""Cluster: every node (sinfo -N), everyone's queue (squeue) and the user's AeroSuite cases on Slurm across every
study — queued, running, or ended in the last 7 days — with Cancel (one case), Resubmit and Log. Everything comes
from the server's Slurm poller and the job records; the page never runs a Slurm command itself."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ...engine.cluster import MAX_ROWS, RecordIndex, my_jobs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.store import load_job
from ...engine.project import open_project
from ..cluster_view import (JOB_KINDS, cluster_queue, cluster_status, filter_jobs, job_state_text, job_studies,
                            node_groups)
from ..jobs import WATCHER
from ..layout import header, project_url
from ..resubmit_dialog import resubmit_case
from ..slurm_watch import WATCH, slurm_available
from ..ui_kit import banner, chip_button, danger_button, flat_button, hint, pill, secondary_button, table, td, td_box, th

POLL_SECONDS = 2.0
LOG_LINES = 200
INDEX = RecordIndex()  # shared by every Cluster page: a study's records are read once per change
KIND_LABELS = {"all": "All", "active": "Active", "failed": "Failed"}
_COLLAPSED: set[str] = set()  # "jobs", "queue": sections the user folded, kept while the server runs


def register() -> None:
    @ui.page("/cluster")
    def cluster_page() -> None:
        header()
        with ui.column().classes("as-page w-full").mark("cluster-page"):
            with ui.row().classes("as-crumbs w-full"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Cluster").classes("as-crumb-current").mark("crumb-page")
            if not slurm_available():
                banner("info", "Slurm is not installed on this machine.").mark("cluster-none")
                return
            ClusterPage()


def _answer(dialog: ui.dialog, value: bool) -> None:
    dialog.submit(value)
    dialog.delete()


def _time(stamp: Optional[float]) -> str:
    return f"{datetime.fromtimestamp(stamp):%H:%M:%S}" if stamp else "—"


class ClusterPage:
    def __init__(self) -> None:
        self.kind = "all"
        self.study: Optional[str] = None
        self.dialogs_open = 0
        self.shown: Optional[tuple] = None
        WATCH.show_page()
        ui.context.client.on_disconnect(WATCH.hide_page)
        self.holder = ui.column().classes("w-full gap-4")
        self.poll()
        ui.timer(POLL_SECONDS, self.poll)

    def _data(self) -> tuple:
        snapshot, cluster, recent = WATCH.snapshot, WATCH.cluster, WATCH.recent
        queue = snapshot.queue if snapshot is not None and snapshot.ok else {}
        rows, more = my_jobs(queue, recent.rows if recent is not None else {}, WATCH.user, INDEX, MAX_ROWS)
        for row in rows:  # a study never opened here: the poller keeps its record current from now on
            if row.active and row.study is not None and row.job_id is not None:
                WATCH.track(row.study, row.job_id)
        return (cluster.taken if cluster else None, snapshot.taken if snapshot else None,
                recent.taken if recent else None, tuple(rows), more, self.kind, self.study)

    def poll(self) -> None:
        if self.dialogs_open:
            return
        data = self._data()
        if data != self.shown:
            self.shown = data
            self.render(data[3], data[4])

    def render(self, rows: tuple, more: int) -> None:
        snapshot, cluster, recent = WATCH.snapshot, WATCH.cluster, WATCH.recent
        tone, tip = cluster_status(snapshot, cluster)
        self.down = tone == "red"
        self.holder.clear()
        with self.holder:
            if self.down:
                banner("error", f"{tip}. Showing the last known state, as of {_time(WATCH.last_ok)}.").mark(
                    "cluster-outage")
            self._nodes(cluster)
            self._jobs(list(rows), more, recent)
            self._queue(snapshot)

    # -- nodes ------------------------------------------------------------------------------------------------

    def _nodes(self, cluster) -> None:
        """One compact card per node, the default partition's first; a drained or down node is tinted red."""
        groups = node_groups(cluster)
        with ui.row().classes("items-baseline w-full gap-2").mark("nodes-card"):
            total = sum(n.total for _p, _d, nodes in groups for n in nodes)
            used = sum(n.allocated for _p, _d, nodes in groups for n in nodes)
            count = sum(len(nodes) for _p, _d, nodes in groups)
            ui.label("Nodes").classes("as-card-title")
            ui.label(f"{count} node{'' if count == 1 else 's'} · {used} / {total} CPUs in use · updated "
                     f"{_time(cluster.taken if cluster else None)}" if groups else "Asking Slurm…").classes(
                "as-muted").mark("nodes-summary")
        with ui.element("div").classes("as-node-grid w-full"):
            for partition, default, nodes in groups:
                for node in nodes:
                    with ui.column().classes("as-node-card" + (" as-node-bad" if node.bad else "")).mark(
                            f"node-card-{node.node}"):
                        with ui.row().classes("items-center w-full no-wrap gap-2"):
                            ui.label(node.node).classes("as-mono as-strong").mark(f"node-{node.node}")
                            ui.label(partition + (" · default" if default else "")).classes("as-muted as-small")
                            ui.space()
                            pill(node.state.upper() if node.bad else node.state).classes("as-pill-small").mark(
                                f"node-{node.node}-state")
                        with ui.row().classes("items-center w-full no-wrap gap-2"):
                            ui.linear_progress(node.busy_percent / 100, show_value=False).props(
                                "rounded size=6px").classes("grow")
                            ui.label(node.cpus).classes("as-mono as-small").mark(f"node-{node.node}-cpus")
                        with ui.row().classes("items-baseline w-full no-wrap gap-2 as-small"):
                            ui.label(node.memory).classes("as-muted").mark(f"node-{node.node}-memory")
                            ui.label(f"· load {node.load}").classes("as-muted")
                            ui.space()
                            ui.label(node.reason).classes("as-error-text").mark(f"node-{node.node}-note")

    @contextmanager
    def _section(self, key: str, title: str, subtitle: str, mark: str):
        """A card whose title row folds it (open by default; the choice kept while the server runs). Yields
        (header row for extra controls, whether the body is shown)."""
        opened = key not in _COLLAPSED
        with ui.column().classes("as-card as-card-flush w-full gap-0").mark(mark):
            with ui.row().classes("items-center w-full no-wrap gap-2 pr-3") as head:
                with ui.button(on_click=lambda: self._toggle(key), color=None).props(
                        f'flat no-caps align=left aria-expanded={"true" if opened else "false"}').classes(
                        "as-section-toggle grow").mark(f"{mark}-toggle"):
                    ui.icon("expand_more" if opened else "chevron_right")
                    ui.label(title).classes("as-card-title")
                    ui.label(subtitle).classes("as-muted as-small")
            yield head, opened

    def _toggle(self, key: str) -> None:
        (_COLLAPSED.discard if key in _COLLAPSED else _COLLAPSED.add)(key)
        self.shown = None
        self.poll()

    # -- queue ------------------------------------------------------------------------------------------------

    def _queue(self, snapshot) -> None:
        lines = cluster_queue(snapshot, WATCH.user)
        mine = sum(1 for line in lines if line.own)
        subtitle = f"{len(lines)} job{'' if len(lines) == 1 else 's'}, all users · {mine} yours · yours highlighted"
        with self._section("queue", "Queue", subtitle, "queue-card") as (_head, opened):
            if not opened:
                return
            if not lines:
                hint("Queue empty").classes("px-4 pb-4").mark("queue-empty")
                return
            with table("auto minmax(5rem, .6fr) minmax(10rem, 1.6fr) minmax(7rem, .8fr) minmax(4rem, .5fr) "
                       "auto minmax(8rem, 1fr)").classes("as-table-compact w-full"):
                for heading in ("Job", "User", "Name", "State", "Node", "Time", "Reason"):
                    th(heading)
                for line in lines:
                    own = " as-own" if line.own else ""
                    td(line.job_id, mono=True).classes(own).mark(f"q-{line.job_id}")
                    td(line.user).classes(own).mark(f"q-{line.job_id}-user")
                    with td_box() as cell:
                        cell.classes(own)
                        if line.study is not None:
                            ui.link(line.name, project_url("run", line.study)).classes("as-mono").mark(
                                f"q-{line.job_id}-link")
                        else:
                            ui.label(line.name).classes("as-mono")
                    td(line.state).classes(own)
                    td(line.node or "—").classes(own)
                    td(line.time, mono=True).classes(own)
                    td(line.reason).classes(own)

    # -- my jobs ----------------------------------------------------------------------------------------------

    def _jobs(self, rows: list, more: int, recent) -> None:
        failed = len(filter_jobs(rows, "failed"))
        subtitle = (f"{len(rows)} · all studies · queued, running or ended in the last 7 days"
                    + (f" · {failed} failed" if failed else ""))
        with self._section("jobs", "My jobs", subtitle, "jobs-card") as (head, opened):
            if not opened:
                return
            with head:
                for kind in JOB_KINDS:
                    chip = chip_button(KIND_LABELS[kind], on_click=lambda k=kind: self._set_kind(k)).mark(
                        f"jobs-filter-{kind}")
                    if kind == self.kind:
                        chip.classes("as-chip-on")
                studies = job_studies(rows)
                if len(studies) > 1:
                    ui.select({None: "All studies", **{s: s for s in studies}}, value=self.study,
                              on_change=lambda e: self._set_study(e.value)).props("dense").mark("jobs-study")
            if recent is not None and recent.error:
                hint("Ended jobs need Slurm accounting, which does not answer; showing active cases only.").classes(
                    "as-hint-warning px-4").mark("jobs-accounting")
            shown = filter_jobs(rows, self.kind, self.study)
            if not shown:
                hint("No jobs").classes("px-4 pb-4").mark("jobs-none")
                return
            with table("minmax(7rem, .8fr) minmax(9rem, 1.2fr) auto minmax(10rem, 1.4fr) minmax(8rem, 1fr) auto "
                       "auto minmax(11rem, auto)").classes("as-table-compact w-full"):
                for heading in ("Study", "Case", "Slurm job", "State", "Partition · node", "Elapsed", "Exit", ""):
                    th(heading)
                for row in shown:
                    self._job_row(row)
            if more:
                hint(f"{more} older job{'' if more == 1 else 's'} not shown").classes("px-4 pb-4").mark("jobs-more")

    def _job_row(self, row) -> None:
        with td_box():
            if row.study is not None:
                ui.link(row.study_name, project_url("run", row.study)).mark(f"job-{row.slurm_id}-study")
            else:
                ui.label(row.study_name).classes("as-muted")
        td(row.case, mono=True).mark(f"job-{row.slurm_id}")
        td(row.slurm_id, mono=True)
        td(job_state_text(row)).mark(f"job-{row.slurm_id}-state")
        td(" · ".join(part for part in (row.partition, row.node) if part) or "—")
        td(row.elapsed or "—", mono=True)
        td(row.exit_code or "—", mono=True)
        with td_box() as cell:
            cell.classes("gap-1 no-wrap")
            live = row.study is not None and row.job_id is not None and not row.earlier_attempt
            if live and row.active:
                button = danger_button("Cancel", on_click=lambda r=row: self.confirm_cancel(r)).props("dense")
                button.mark(f"cancel-{row.slurm_id}").set_enabled(not self.down)
            if live and row.resubmittable:
                button = secondary_button("Resubmit", on_click=lambda r=row: self.resubmit(r)).props("dense")
                button.mark(f"resubmit-{row.slurm_id}").set_enabled(not self.down)
            if row.study is not None:
                flat_button("Log", on_click=lambda r=row: self.show_log(r), icon="terminal").props("dense").mark(
                    f"log-{row.slurm_id}")

    def _set_kind(self, kind: str) -> None:
        self.kind = kind
        self.shown = None
        self.poll()

    def _set_study(self, study: Optional[str]) -> None:
        self.study = study
        self.shown = None
        self.poll()

    # -- actions ----------------------------------------------------------------------------------------------

    async def confirm_cancel(self, row) -> None:
        self.dialogs_open += 1
        try:
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Cancel {row.case} (Slurm job {row.slurm_id}) of {row.study_name}? Cases that restart "
                         "from its solution become Blocked; the job's other cases go on.")
                with ui.row().classes("w-full justify-end gap-2"):
                    secondary_button("Keep it", on_click=lambda: _answer(dialog, False)).mark("cancel-keep")
                    danger_button("Cancel the case", on_click=lambda: _answer(dialog, True)).mark("cancel-confirm")
            confirmed = await dialog
        finally:
            self.dialogs_open -= 1
        if not confirmed:
            return
        try:
            project = open_project(row.study)
            job = await run.io_bound(WATCHER.cancel_case, row.study, project, row.job_id, row.case)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
        else:
            cancelled = job.case_status.get(row.case) is not None and job.case_status[row.case].value == "CANCELLED"
            ui.notify(f"Cancelled {row.case}" if cancelled else f"{row.case} had already ended", type="info")
        self.shown = None
        self.poll()

    async def resubmit(self, row) -> None:
        self.dialogs_open += 1
        try:
            project = open_project(row.study)
            job = load_job(row.study, row.job_id)
            await resubmit_case(row.study, project, job, row.case)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
        finally:
            self.dialogs_open -= 1
        self.shown = None
        self.poll()

    def show_log(self, row) -> None:
        path = Path(row.study) / "runs" / row.case / f"slurm-{row.slurm_id}.out"
        with ui.dialog().props("maximized=false") as dialog, ui.card().classes("w-[60rem] max-w-full"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"{row.study_name} / {row.case} · {path.name}").classes("as-dialog-title grow")
                ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense")
            with ui.scroll_area().classes("as-log-body").style("height: 60vh") as scroll:
                text = ui.label("").classes("as-log-text").mark("log-dialog-text")

        def update() -> None:
            text.text = _tail(path)
            scroll.scroll_to(percent=1.0)

        update()
        timer = ui.timer(POLL_SECONDS, update)
        dialog.on("hide", lambda: (timer.cancel(), dialog.delete()))
        dialog.open()


def _tail(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 256 * 1024))
            data = fh.read()
    except OSError:
        return f"(no output yet: {path.name} does not exist)"
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]) or "(nothing written yet)"
```

In `aerosuite/web/app.py` import `cluster` with the other pages and call `cluster.register()`.
In `aerosuite/web/theme.py` add the node cards and section toggles (layout D):

```css
.as-node-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.as-node-card { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 12px;
  gap: 6px; }
.as-node-bad { background: #fff8f7; border-color: #f0b9b3; }
.as-pill-small { font-size: 11.5px; padding: 1px 7px; }
.as-section-toggle { min-height: 48px; justify-content: flex-start; gap: 10px; padding: 0 16px; }
```

and `.as-table-compact .as-own { background: var(--as-accent-tint); }` and
`.as-chip-on { background: var(--as-accent); color: #fff; }` (skip the latter if `chip_button` already has an "on"
style — check `ui_kit.chip_button` first and reuse its class).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q -p no:cacheprovider tests/web/test_web_cluster.py tests/web/test_web_cluster_button.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/web/pages/cluster.py aerosuite/web/app.py aerosuite/web/theme.py tests/web/test_web_cluster.py tests/web/test_web_cluster_button.py
git commit -m "feat(cluster): The Cluster page: nodes, everyone's queue and my jobs across studies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Docs, the full suite and screenshots

**Files:**
- Modify: `README.md` (Running on the Slurm cluster), `docs/HANDOVER.md` (hpc1 section),
  `docs/superpowers/specs/2026-10-20-cluster-page-design.md` (Status: Implemented)

- [ ] **Step 1: README** — in "Running on the Slurm cluster", replace the bullet starting "The Run page shows the
  cluster" with:

```markdown
- The **Cluster** page (top bar; its dot is green, amber for a drained or down node, red when Slurm does not answer)
  shows every node, everyone's queue and your AeroSuite cases on Slurm from every study — queued, running or ended in
  the last 7 days — with Cancel (one case), Resubmit and Log. The Run page keeps a one-line summary. The Results page
  adds a **Cost** group per case (elapsed, s/iter, peak memory and CPU use from `sacct`/`seff`) and the study's
  node-hours.
```

and add `aerosuite cancel ./study --case M0p8_a2   # one case; the others go on` to the command block.

- [ ] **Step 2: HANDOVER** — in "hpc1 and the Slurm backend", add one bullet: "Cluster page (phase 1, spec
  `2026-10-20-cluster-page-design.md`): next phases are usage history (sacct over a period) and admin actions
  (drain/resume need Slurm Operator rights for pdas-hpc1, not granted as of 2026-10-20)."

- [ ] **Step 3: Full suite**

Run: `uv run pytest -q -p no:cacheprovider`
Expected: everything passes except the 4 known `tests/engine/test_sweep_script.py` failures.

- [ ] **Step 4: Screenshots** — start the demo on the fake cluster (scratchpad `demo/`, port 8093, its own
  `AEROSUITE_HOME`, `PATH` with the fake shims, as in earlier sessions), take headless-Firefox screenshots of `/cluster`
  and of a study's Run page, check them, send them to the user, stop the demo server (by its port's pid).

- [ ] **Step 5: Commit**

```bash
git add README.md docs/HANDOVER.md docs/superpowers/specs/2026-10-20-cluster-page-design.md
git commit -m "docs(cluster): Cluster page in the README and handover

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

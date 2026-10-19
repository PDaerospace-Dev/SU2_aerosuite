# AeroSuite — Slurm execution backend — Design Spec

**Date:** 2026-10-19
**Status:** Draft for review
**Builds on:** `2026-09-21-aerosuite-web-architecture-design.md` and `2026-09-25-web-run-monitor-design.md` (jobs, the
Run and Monitor pages). Branch `feat/slurm-backend`, from `main` at `39c5135`.

---

## 1. Why and scope

AeroSuite now runs on **hpc1**, the Slurm controller of a two-node cluster. Today a submit runs the whole sweep on
this machine through `aoa_sweep_v8.py` and `mpirun` (`LocalRunner`). This adds a **slurm** backend beside it: each
case becomes one Slurm batch job, submitted from its own case folder, watched from one batched `squeue` call, with
its final state, exit code and cost taken from accounting.

**The cluster (given by the user; checked on hpc1 on 2026-10-19 where marked ✓):**
- Slurm 26.05.4; `sbatch`, `squeue`, `sinfo`, `scancel`, `scontrol`, `sacct`, `seff` are local commands (✓ all in
  `/usr/bin`). Jobs run as the user running AeroSuite.
- Partitions `node1` (hpc1, default) and `node2` (hpc2): 2× EPYC 7642 each, **192 CPUs per node in Slurm** (96 cores
  × 2 threads; ✓ `sinfo %C` = `0/192/0/192`), `SelectTypeParameters = CR_CORE_MEMORY,CR_ONE_TASK_PER_CORE` (✓).
- 1 GbE between nodes: every job is `-N 1`. Multi-node is never offered.
- Defaults: one job per node with `--exclusive`; node1 → 96 tasks, node2 → 48 tasks (no gain beyond ~32–48 there).
- Memory: about 3.9 GB per million cells. Limits: node1 640 MB per allocated CPU (an `--exclusive` job gets all 192
  CPUs = 120 GB), node2 62,000 MB per job. Over the limit → `OUT_OF_MEMORY`. Nodes can fail → `NODE_FAIL`.
- Cases must live under `/data` (NFS, mounted on hpc2). `/scratch` is never used for cases.
- SU2 8.5.0 in `/opt/su2/bin`; `module load mpi/openmpi-x86_64`; in a job: `srun --mpi=pmix SU2_CFD <cfg>`; scripts
  start with `#!/bin/bash -l`. Reference: `/data/software/templates/su2_job.sh`.
- Accounting on (cluster `pdas-cfd`, account `pdas`).
- `DependencyParameters` is unset (✓), so Slurm does **not** cancel a job whose dependency can never be met: it would
  stay `PENDING (DependencyNeverSatisfied)` forever unless the job asks for `--kill-on-invalid-dep=yes` (§4.3).

**Two findings from hpc1's accounting that shape §6 (✓ on jobs 8–11):**
- `sacct -X … MaxRSS` is **empty**: MaxRSS is recorded on the steps (`<id>.batch`, `<id>.0`), and there it is the
  largest *single task* (770 MB on job 11), not the job's total. `seff` reports the job's total ("Memory Utilized:
  61.95 GB" on job 11). So **peak memory comes from `seff`**; the batched `sacct -X` call gives state, exit code,
  elapsed and node.
- `seff`'s "CPU Efficiency" is against all 192 allocated CPUs, so a 96-rank job tops out at 50% (job 11: 49.49%).
  AeroSuite shows **CPU use per rank** instead: CPU Utilized ÷ (wall time × ntasks).

**Out of scope:** multi-node jobs, job arrays, slurmrestd, several users, spreading one submit over both partitions,
cancelling single cases of a Slurm job (Cancel stops the whole job, as for local).

**Unchanged:** the local backend. `LocalRunner`, `sweep_wrapper.py`, `aoa_sweep_v8.py`, the local lock file and every
local test stay as they are; a project with no backend set and server settings left at their defaults behaves
exactly as today.

## 2. Settings

### 2.1 Server settings — new `engine/settings.py`

Stored in `$AEROSUITE_HOME/settings.json` (default `~/.aerosuite/settings.json`, beside `recent.json`, profiles and
packages). Missing file → defaults; an unreadable file → defaults plus a warning shown on the Settings page and by
the CLI (never a crash). Written atomically (tmp + `os.replace`).

```
AppSettings
  backend: "local" | "slurm" = "local"          # the default for projects that don't choose
  slurm: SlurmSettings
    shared_root: str = "/data"
    partitions: list[PartitionSettings] =
      [ {name: "node1", default_ntasks: 96, memory_limit_mb: 122880, ntasks_warn_above: null, block_over_memory: false},
        {name: "node2", default_ntasks: 48, memory_limit_mb: 62000,  ntasks_warn_above: 48,   block_over_memory: true} ]
    default_partition: str = "node1"
    exclusive: bool = true
    gb_per_million_cells: float = 3.9
    module_line: str = "module load mpi/openmpi-x86_64"
    su2_bin: str = "/opt/su2/bin"
    srun_command: str = "srun --mpi=pmix SU2_CFD"
    poll_seconds: float = 12 (5…120)
    default_time_limit: str = ""                 # "" = no -t; else Slurm syntax, e.g. "12:00:00", "2-00:00:00"
    account: str = "pdas"                        # "" = no -A
```

These defaults are this cluster's facts; nothing in the code refers to `node1`, `/data` or the paths directly.
`memory_limit_mb` is the limit an `--exclusive` job gets (node1: 640 MB × 192 CPUs). Validation: partition names
unique and non-empty, `default_partition` one of them, `default_ntasks ≥ 1`, `shared_root` absolute, the time limit
matches Slurm's formats (`MM`, `MM:SS`, `HH:MM:SS`, `D-HH`, `D-HH:MM`, `D-HH:MM:SS`).

**Editing:** a new **Settings** page (`/settings`, gear in the top bar) with an *Execution* card: backend, the Slurm
fields, and the partitions as a small editable table. The CLI gets `aerosuite settings` (prints the file's path and
values) and `aerosuite settings set <dotted.key> <value>` (e.g. `slurm.poll_seconds 15`,
`slurm.partitions.node2.default_ntasks 32`), validated like the page.

### 2.2 Per project / per run — schema 8

`RunSettings` gains (migration 7→8 adds the defaults, nothing else changes):

```
backend: Optional["local" | "slurm"] = None    # None = the server default
slurm: SlurmRun
  partition: Optional[str] = None              # None = default_partition
  ntasks: Optional[int] = None                 # None = that partition's default_ntasks
  time_limit: Optional[str] = None             # None = default_time_limit; "" = none
```

The Run page and `aerosuite run` set these (and save them, as `-n` / *Cores per case* do today), so a project
remembers how it was last run. `partitions` stays the local backend's MPI count.

## 3. Executor abstraction

The existing `Runner` protocol in `engine/jobs/runner.py` is the common interface; it already has
`submit` / `refresh` (= poll; returns the updated record, which carries the status) / `cancel`. Changes:

- New `engine/jobs/executors.py`: `runner_for(backend) -> Runner` (one `LocalRunner`, one `SlurmRunner` per process),
  `backend_of(project, settings) -> str` (project choice, else server default) and `runner_of(job)` (by
  `job.backend`, so a job is always refreshed and cancelled by the backend that started it, whatever the settings
  say now).
- `started_cases(project_dir, job)` becomes part of the protocol (Monitor and the log panel use it). Slurm: the cases
  whose job has reached RUNNING or later.
- `case_log(project_dir, job, case) -> Optional[Path]`: the file holding that case's solver output. Local: the job
  log (Monitor keeps cutting it at the banners as today). Slurm: `runs/<case>/slurm-<jobid>.out`.
- `CaseState.BLOCKED` (new, final): never ran because a case it restarts from did not succeed. Only Slurm produces it.
  Shown as "Blocked" (amber), counted with Failed for the job's outcome, offered by the Failed selector.

### 3.1 Job records

One AeroSuite job per submit, as today (`jobs/<id>.json`, `jobs/<id>.log`, `jobs/<id>/configs/`), with
`backend="slurm"`. Each case is one Slurm job; `JobRecord` gains:

```
slurm: dict[str, SlurmCase] = {}     # by case name; empty for local jobs
SlurmCase
  job_id: str                         # the current attempt
  attempts: list[str] = []            # earlier Slurm job ids of this case (resubmits), oldest first
  partition: str; ntasks: int; time_limit: str
  depends_on: Optional[str]           # the case it waits for (afterok), if any
  state: str = "PENDING"              # the last Slurm state seen (PENDING, RUNNING, ..., NODE_FAIL)
  node: str = ""; reason: str = ""; elapsed: str = ""
  exit_code: Optional[str] = None     # "0:0", "1:0", "0:125" as sacct gives it
  checks: int = 0                     # polls since it left the queue without an accounting row (§5.2)
```

`backend_ref` holds the submit's settings (`partition`, `ntasks`, `time_limit`, `exclusive`, `account`).

### 3.2 One active job per project

Kept as today. The lock file stays the local mechanism, unchanged. For Slurm `submit` writes the lock with
`"backend": "slurm"`; `store.active_lock` treats such a lock as active while its job record is active (no PID check)
and clears it otherwise. Preflight's "Job … is still running" therefore covers both backends.

## 4. Submission — new `engine/jobs/slurm.py`: `SlurmRunner`

### 4.1 What a submit does

1. `prepare_job` as today (it writes `jobs/<id>/configs/`, plans restarts and sets aside solutions that are about to
   be deleted). Its `ControlLine`s say which case restarts from which.
2. For each case, in case order: empty `runs/<case>/` (as the sweep script does when a case starts — here it happens
   at submit, so a queued case's old results are gone while it waits), then write into it:
   - `<case>.cfg`: the job's copy, with `SOLUTION_FILENAME` set to the absolute restart file when the case restarts
     (the case's own restart file name for `previous` / `from_case` targets: `runs/<target>/<RESTART_FILENAME>`;
     the set-aside or custom file otherwise) and `RESTART_SOL` as planned. Output names stay relative, so SU2
     writes `history.csv`, the restart and the volume/surface files into the case folder, as locally.
   - `su2_job.sh` (§4.2).
3. `sbatch --parsable su2_job.sh` with the case folder as working directory (so `-o slurm-%j.out` and
   `$SLURM_SUBMIT_DIR` are the case folder) and AeroSuite's own venv stripped from the environment
   (`sweep_environment()`). The output `123` or `123;pdas-cfd` → job id `123`. Each case is submitted after the one
   it depends on, so the dependency's id is known.
4. Save the record after every successful `sbatch`, and log each submit to `jobs/<id>.log`
   (`case M0p8_a2 → Slurm job 123 on node1, 96 tasks, after 122`).
5. **A failed `sbatch` part-way** (non-zero exit, unparsable output, timeout): `scancel` the ones already submitted
   (one call), mark the job FAILED with the error in its log and in each case's failure text, remove the lock, and
   raise `JobError` with sbatch's message. Nothing is left queued or half-recorded.

### 4.2 The job script

Self-contained, so the folder records exactly how the case ran and can be resubmitted by hand with
`sbatch su2_job.sh` (after removing the dependency line):

```bash
#!/bin/bash -l
#SBATCH -J X07_cruise/M0p8_a2
#SBATCH -p node1
#SBATCH -N 1
#SBATCH -n 96
#SBATCH --exclusive
#SBATCH -A pdas
#SBATCH -t 12:00:00
#SBATCH -o slurm-%j.out
#SBATCH --dependency=afterok:122
#SBATCH --kill-on-invalid-dep=yes
# Written by AeroSuite for job 20261019-1412, case M0p8_a2 (restarts from M0p8_a0).
module load mpi/openmpi-x86_64
export PATH=/opt/su2/bin:$PATH
cd "$SLURM_SUBMIT_DIR"
echo "AeroSuite: Slurm job $SLURM_JOB_ID on $(hostname), $SLURM_NTASKS ranks, start $(date -Is)"
srun --mpi=pmix SU2_CFD M0p8_a2.cfg
code=$?
echo "AEROSUITE_EXIT $code $(date -Is)"
exit $code
```

Job name = `<study name>/<case>`; `-A`, `-t`, `--exclusive` and the two dependency lines only when they apply. Every
value comes from §2. Values put into the script are checked (no newlines; partition/account/time limit match
`[A-Za-z0-9_.:-]+`), and the cfg name is quoted.

### 4.3 Restart dependencies

A case whose control line is `previous` or `from_case` (it restarts from a case running earlier in the same job) gets
`--dependency=afterok:<that case's job id>` and `--kill-on-invalid-dep=yes`. If the earlier case fails, Slurm
cancels the dependent job instead of leaving it pending forever; AeroSuite then shows it **Blocked** ("Not run:
M0p8_a0 ended OUT_OF_MEMORY"), and so on down a chain. As a second guard, a job seen `PENDING` with reason
`DependencyNeverSatisfied` is cancelled by AeroSuite and marked Blocked the same way.

*Difference from local, intended:* locally a `previous` case after a failed one starts from scratch; on Slurm it is
Blocked, because a restart from a solution that never came is not what was asked for.

Cases restarting from a solution outside this job (`custom`, a continued case) have no dependency; their file is
checked before submit (preflight, as today).

## 5. Polling

### 5.1 Commands — new `engine/slurm.py`

Argument builders and **pure parsers** (unit-tested on captured output), and two ways to run them: `run_sync`
(`subprocess.run`, for the CLI) and `run_async` (`asyncio.create_subprocess_exec`, for the web), both with a timeout
(default 20 s). Missing command, timeout, or a non-zero exit become `SlurmUnavailable(message)` with Slurm's own
stderr (e.g. "slurm_load_jobs error: Unable to contact slurm controller (connect failure)").

| Call | When | Parsed into |
|---|---|---|
| `squeue --me -h -o "%i\|%T\|%N\|%M\|%R"` | once per poll, all jobs | `{id: QueueRow(state, node, time, reason)}` |
| `sacct -j <id1,id2,…> -P -n -X --format=JobID,State,ExitCode,Elapsed,MaxRSS,NodeList` | once per poll, only for tracked jobs that left the queue and have no final state yet | `{id: AcctRow}`; `CANCELLED by 1000` → `CANCELLED` |
| `sinfo -h -o "%P\|%a\|%D\|%t\|%C"` | once per poll while a Run page shows the cluster | partition rows (a trailing `*` = default) |
| `sinfo -R -h -o "%n\|%t\|%E"` | only when some node is drained/down/failing | node → reason |
| `seff <id>` | once per case, when it reaches a final state | elapsed, CPU utilized, memory utilized |
| `sbatch --parsable`, `scancel <ids…>` | submit, cancel, resubmit | job id |

### 5.2 State mapping (`SlurmRunner.refresh`)

`refresh(project_dir, job, snapshot=None)`: the web passes the poller's latest snapshot (no subprocess on the event
loop); the CLI passes none and the runner makes the calls itself (one `squeue`, at most one `sacct`).

- In the queue: `PENDING` (and `CONFIGURING`, `REQUEUED`, `SUSPENDED`) → case PENDING, with the reason shown
  (`Resources`, `Priority`, `Dependency`); `RUNNING`, `COMPLETING` → case RUNNING, with node and run time.
- Left the queue → its `sacct` row:
  - `COMPLETED` → convergence from `history.csv` as locally (CONVERGED / UNCONVERGED; FAILED when no history).
  - `FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `BOOT_FAIL`, `DEADLINE`, `PREEMPTED` → FAILED. The failure
    text names the Slurm state and exit code ("OUT_OF_MEMORY (exit 0:125) on hpc2") and then the last lines of
    `slurm-<id>.out`, as locally.
  - `CANCELLED` → BLOCKED when the case depends on one that did not succeed, else CANCELLED.
  - No row yet (slurmdbd lags a moment behind) → unchanged, `checks += 1`.
- **Accounting unreachable** (`sacct` fails), or still no row after 10 polls → the file fallback: `slurm-<id>.out`
  ending in `AEROSUITE_EXIT 0` or holding SU2's "Exit Success" → treated as COMPLETED; `AEROSUITE_EXIT <n>` → FAILED
  (exit n); neither → FAILED, "ended without a result; accounting is unreachable, so the reason (out of memory, node
  failure, time limit) is unknown". Files cannot tell OUT_OF_MEMORY or NODE_FAIL apart, which the text says.
- **Controller unreachable** (`squeue` fails): **nothing changes state**. A job missing from a failed `squeue` is
  never taken as finished. The error is shown (§5.4) and the next poll tries again.
- The job ends when every case is final: DONE if all are CONVERGED/UNCONVERGED, else FAILED. Then the lock is
  cleared and `jobs/<id>/restart/` removed, as locally.

### 5.3 The poller — `web/slurm_watch.py`

One asyncio task for the whole server, started on app startup. Each `poll_seconds` it runs **one** `squeue`, then
(if needed) **one** `sacct` for every tracked Slurm job across all projects that has left the queue, then `sinfo`
while some client shows a Slurm Run page, and stores the result as an immutable `ClusterSnapshot` (time, queue rows,
accounting rows, partitions, node reasons, error). It idles (no calls) when there is no active Slurm job and no Slurm
Run page open. `seff` for newly finished cases runs here too, a few at a time, and its result goes to the case's
stats file (§8).

`JobWatcher.state()` (still called from the pages' 2 s timers) refreshes a Slurm job from the latest snapshot,
which costs a dict lookup and a record save only when something changed. Projects are tracked from the moment
their job is submitted or first shown; a job started from the CLI is picked up when its project is opened.

### 5.4 Errors

- `sbatch` missing → preflight error "Slurm's sbatch was not found on PATH; is this the cluster's controller?"
  (Submit stays disabled, `aerosuite run` exits 1 with it).
- Controller down at submit → `JobError` with Slurm's message: a red banner on the Run page, an error line in the CLI;
  nothing recorded as running.
- Controller down while polling → the cluster panel shows "Slurm controller unreachable since 14:02: <message>" and
  keeps the last known states (marked as stale); one line goes to each active job's log when the outage starts and
  one when it ends (not one per poll). Never an exception in the event loop: the poller catches everything, logs it
  with the traceback to the server log, and carries on.

## 6. Pre-submit checks — new `engine/slurm_checks.py`

Run by `preflight(..., "submit"/"run")` when the backend is Slurm, **instead of** the local environment checks
(`SU2_RUN`, the sweep's Python), which a Slurm job does not use. All problems at once, as today:

| Check | Severity |
|---|---|
| `sbatch` on PATH | error |
| the project folder resolves under `shared_root` | error: "Case folders must be under /data so hpc2 can see them (this project is in /home/…)" |
| each selected case's `configs/<case>.cfg` exists | error |
| its `MESH_FILENAME` is absolute and the file exists | error |
| the mesh / custom restart files are under `shared_root` | warning: "hpc2 cannot see /home/…/mesh.su2" |
| the partition exists in the settings; `ntasks ≥ 1`; time limit format | error |
| `ntasks > ntasks_warn_above` (node2: 48) | warning: "node2 gains nothing above about 48 tasks; 96 asked" |
| estimated memory > `memory_limit_mb` | warning, or **error** when `block_over_memory` (node2) |

**Memory estimate:** `NELEM` from the `.su2` header, reading at most the first 64 lines (never the whole file; a
15M-cell mesh is GBs). The estimate is `NELEM / 1e6 × gb_per_million_cells`, shown in the Checks panel either way
("≈ 58 GB of 120 GB on node1"). For a non-`.su2` mesh (CGNS) or no `NELEM` in the header there is no estimate, and a
note says so. With `--exclusive` off the limit for node1 would be per allocated CPU; this phase always compares
with the exclusive limit, and says so in the settings help.

## 7. Cancel and resubmit

- **Cancel** = one `scancel <every non-final job id of the job>`; cases still PENDING or RUNNING become CANCELLED, the
  job CANCELLED, the lock cleared. It returns at once (no 20 s wait as locally); the next poll confirms. A failing
  `scancel` raises `JobError` and changes nothing.
- **Resubmit** (one click in the case row, for cases whose Slurm state is `NODE_FAIL` or `OUT_OF_MEMORY`): a dialog
  with the partition and ntasks pre-filled (for OUT_OF_MEMORY on node2 it proposes node1 and says why). It submits
  that case again **inside the same AeroSuite job** (its old id goes to `attempts`; earlier `slurm-<id>.out` files
  stay in the folder), together with the cases Blocked behind it, each with `afterok` on the new id. The job becomes
  active again. Blocked by preflight like a submit (memory, partition). Only when no other job of the project is
  active.

## 8. Results: cost per case

When a case reaches a final state the poller (or the CLI's refresh) writes `runs/<case>/slurm_stats.json`:

```
{job_id, partition, node, ntasks, state, exit_code, elapsed_s, iterations, s_per_iter,
 peak_memory_gb, cpu_use_per_rank, attempts}
```

- `elapsed_s` from sacct; `iterations` = last minus first iteration in `history.csv`, plus one; `s_per_iter` =
  elapsed / iterations (wall time including mesh reading and partitioning, said in the column's tooltip).
- `peak_memory_gb` = seff "Memory Utilized"; `cpu_use_per_rank` = CPU Utilized / (elapsed × ntasks). When `seff` is
  missing or fails, these two are empty and the rest still written.

The **Results** page reads these files with the histories (no Slurm call) and adds a **Cost** group to the results
table: Elapsed, s/iter, Peak memory, CPU use, Node, Tasks, plus a study total of node-hours. The group is not shown
when no case has a stats file (local studies look as today). `summary.csv` is unchanged; the CSV export from the page
includes the Cost columns.

## 9. Run page in Slurm mode

- **Launch panel:** a Local / Slurm toggle (the project's choice; first value the server default). Slurm shows
  Partition (select), Tasks (pre-filled from the partition, edited per project), Time limit, and "1 node, exclusive"
  as text. *Cores per case* is shown for Local only.
- **Checks:** the §6 problems and the memory estimate.
- **Cluster** (replaces *Machine*): one row per partition from `sinfo`: name, availability, node state, CPUs
  allocated / idle / total as a bar. A drained / down / failing node is a red row with its `sinfo -R` reason. When
  the controller is unreachable: the error and the time of the last good poll.
- **Queue:** every job of `squeue --me` (not only this study's): id, name, state, node, run time, pending reason,
  this study's highlighted.
- **Case rows** also show the Slurm job id, the Slurm state when it says more than ours ("PENDING · Dependency",
  "OUT_OF_MEMORY"), node and exit code; NODE_FAIL / OUT_OF_MEMORY rows get **Resubmit**.
- **Cancel** stops all of the job's Slurm jobs (§7).
- **Monitor** and the **log panel** follow a Slurm case through its `slurm-<id>.out`; the log panel's job entry shows
  `jobs/<id>.log` (submits, state changes, errors).

## 10. CLI

```
aerosuite run DIR [--backend local|slurm] [--partition node2] [--ntasks 48] [--time 12:00:00] [-n N]
aerosuite status DIR [--watch]          # Slurm: one squeue + at most one sacct per refresh; shows id/node/reason
aerosuite cancel DIR [JOB_ID]           # by the job's own backend
aerosuite resubmit DIR [CASE ...] [--partition P] [--ntasks N]   # default: every NODE_FAIL / OUT_OF_MEMORY case
aerosuite settings [set KEY VALUE]
```

`--backend`, `--partition`, `--ntasks`, `--time` are saved to the project like `-n`. `--ntasks` with the local backend
and `-n` with Slurm are errors that say which option to use.

## 11. Tests

Unit tests with **fake Slurm commands**: `tests/fixtures/fake_slurm.py` plus a fixture that writes `sbatch`, `squeue`,
`sinfo`, `scancel`, `sacct`, `seff` shims into a temp `bin/` placed first on `PATH`. The fake keeps its queue in a
JSON file (`FAKE_SLURM_STATE`); tests move jobs through states by editing it, can switch the controller or
accounting "down", and read back every call made (to assert one `squeue` per poll and one batched `sacct`). POSIX
only (skipped on Windows); no Slurm, SU2 or MPI.

Covered: submit + id parse (`123` and `123;pdas-cfd`), the written script, state mapping, a job leaving the queue as
COMPLETED / FAILED / OUT_OF_MEMORY / NODE_FAIL via sacct, the file fallback when sacct is down, sacct lagging, cancel,
the dependency chain (afterok ids in the scripts; A fails → B and C Blocked), DependencyNeverSatisfied guard,
controller down at submit and while polling (no state change), partial-submit rollback, the memory pre-check (NELEM
read from a header only; warn on node1, block on node2), shared-root check, resubmit, settings load/validate, schema
7→8, the poller (one squeue per interval for two projects; async; idle when nothing to watch), the Run page in Slurm
mode (simulated user), Results Cost group, CLI options. Every existing local test keeps passing unchanged.

The manual test plan for the cluster is in `2026-10-19-slurm-manual-test-plan.md`.

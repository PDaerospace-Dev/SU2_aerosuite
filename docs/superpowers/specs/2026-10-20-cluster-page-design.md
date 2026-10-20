# AeroSuite — Cluster page (phase 1) — Design Spec

**Date:** 2026-10-20
**Status:** Draft for review
**Builds on:** `2026-10-19-slurm-backend-design.md` (the Slurm backend, its poller and job records). Branch
`feat/slurm-backend`.

---

## 1. Why and scope

The Run page's right-hand panel holds the cluster (partitions, drained nodes) and the queue next to the study's own
launch controls, checks and last job. Those two parts belong to the whole cluster, not to one study, and they do not
scale: more nodes need a row each and more simulations make a long queue, neither of which fits a 340 px column.
They move to their own **Cluster** page, reached from the top bar, which also shows something no page shows today:
**every AeroSuite case on Slurm across all studies**.

**Decided with the user (2026-10-20):**
- The page **watches nodes and the queue** and lets the user **manage their jobs**. Usage history and admin actions
  were also wanted; they come as later phases (§9).
- The queue shows **everyone's jobs**, the user's own highlighted (colleagues will submit too).
- "My jobs" lists AeroSuite cases that are **queued, running, or ended in the last 7 days**, from every study.
- The jobs are found **from Slurm itself** (each job's working directory leads to its study), so cases started from
  the CLI, in studies never opened in the browser, are found too.
- The Run page keeps a **one-line cluster summary** that links to the page.

**Out of scope (later phases):** history beyond 7 days, charts of usage (phase 2); drain/resume nodes, hold/release
jobs (phase 3 — needs Slurm Operator rights, which `pdas-hpc1` does not have: admin level `None`, checked
2026-10-20); multi-node jobs over InfiniBand (its own spec when the hardware is there). The page must show any
number of nodes cleanly so that adding nodes needs no redesign.

## 2. Navigation

- A **Cluster** button in the top bar of every page (inside a study and outside, like Calculators), shown only when
  Slurm is installed (`sinfo` on PATH). It carries:
  - a **status dot**: green — Slurm answers and every node is up; amber — a node is drained, down or failing;
    red — the controller does not answer (the dot's tooltip says which node and why, or the error);
  - the number of the user's **running** Slurm jobs, when there are any ("Cluster · 3").
- It opens **`/cluster`**, a full page (breadcrumb Projects › Cluster).
- **Run page, Slurm mode:** the *Cluster* and *Queue* parts of the panel are replaced by one line, e.g.
  `node1 192/192 busy · node2 free · 3 of yours queued` and a **Cluster →** link. Red text when a node is
  drained/down or Slurm is unreachable. The case rows keep their Slurm details and Resubmit button as now.

## 3. The page

Three cards, top to bottom; each can be folded (the existing card fold, remembered while the server runs).

### 3.1 Nodes

One row per node from `sinfo -N`, grouped under its partition (default partition first, marked "default"):

| Node | State | CPUs | Memory | Load | Note |
|---|---|---|---|---|---|
| hpc1 | idle | bar 0 / 192 | 101 of 125 GB free | 7.3 | |
| hpc2 | drain | bar 0 / 192 | 57 of 62 GB free | 3.4 | **bad DIMM** (red) |

- State as Slurm names it (idle, mix, alloc, drain, down, …), red for drained/down/failing/not responding.
- CPUs: allocated / total as a bar; Memory: `%e` free of `%m` total, in GB; Load: `%O`; Note: `%E` (the reason a node
  is drained or down), red.
- Under the card: "Updated hh:mm:ss" (the poll time).

### 3.2 Queue

Every job in `squeue` (all users): pending jobs first, then running ones, each in job-id order:

| Job | User | Name | State | Node | Time | Reason |
|---|---|---|---|---|---|---|

The user's own jobs are highlighted; a job of an AeroSuite study shows its name as `study/case` with a link to the
study's Run page. "Queue empty" when there is nothing.

### 3.3 My jobs

The user's AeroSuite cases — queued, running, or ended in the last 7 days — from every study, newest first:

| Study | Case | Slurm job | State | Partition · node | Elapsed | Exit | |
|---|---|---|---|---|---|---|---|
| test (link) | M1p2_0km_a10 | 33 | Unconverged (COMPLETED) | node2 · hpc2 | 2:56 | 0:0 | Log |

- **State** is AeroSuite's case state from the job record (Converged, Failed, Blocked, …) with Slurm's state beside it
  when it says more (OUT_OF_MEMORY, PENDING · Dependency). Without a readable record (the study moved, the record is
  gone) the row shows Slurm's state only, and no actions except Log.
- **Actions per row:**
  - **Cancel** (queued or running): scancels that one case (§5). A confirmation dialog names the case and says that
    cases waiting for its solution become Blocked.
  - **Resubmit** (NODE_FAIL / OUT_OF_MEMORY): the Run page's resubmit dialog (partition proposal included).
  - **Log**: a dialog with the last 200 lines of the case's `slurm-<id>.out`, refreshed every 2 s while open,
    "Follow" as in the log panel.
- Filter chips above the table: *All · Active · Failed* (Failed includes Blocked and Cancelled), and a study filter
  (select) when the jobs come from more than one study.
- Jobs the user submitted by hand (not in an AeroSuite study) are not listed here; they are in the Queue card.

## 4. Data

All Slurm calls stay in the server's one poller (`web/slurm_watch.py`); pages read its snapshot. Changes:

| Call | When | Change |
|---|---|---|
| `squeue -h -o "%i\|%T\|%N\|%M\|%R\|%u\|%j\|%Z"` | every poll (as now) | **all users** instead of `--me`; adds user, name, working directory. Still one call. |
| `sinfo -h -N -o "%N\|%P\|%t\|%C\|%m\|%e\|%O\|%E"` | every poll while any page shows the Cluster button | per node, replaces the per-partition `sinfo` (the Run summary and the top-bar dot are computed from it) |
| `sinfo -R` | dropped | `%E` in `sinfo -N` already gives each node's reason |
| `sacct -S now-7days -X -n -P --format=JobID,JobName,State,ExitCode,Elapsed,NodeList,Partition,Start,End,WorkDir` | at most every 5 min, only while a Cluster page is open; also right after a case ends | one call, the user's own jobs (sacct's default) |

- **The user** is the Unix user running AeroSuite (`getpass.getuser()`); "mine" means `%u` equals it.
- **Finding a job's study:** working directory `…/<study>/runs/<case>` → `<study>` when `<study>/project.json`
  exists and the job's name is `<study name>/<case>` (as the job script writes it). The case's AeroSuite record is the
  job record in `<study>/jobs/` whose `slurm[case].job_id` or `attempts` holds that Slurm id; found records are cached
  per study until its `jobs/` folder changes (mtime), so a poll does not re-read every record.
- **Live states** of active cases still come from the job records the poller already keeps current (one squeue, at
  most one batched sacct); the 7-day `sacct` only adds the cases that ended and are no longer tracked.
- Idle rule as now: no Slurm call while no page is open and no Slurm job is active.

## 5. Cancelling one case

New: `SlurmRunner.cancel_case(project_dir, job, case)` — `scancel <that case's id>`; the case becomes CANCELLED
(failure text "Cancelled from the Cluster page"); the job's other cases go on. Cases that wait for it (afterok) are
cancelled by Slurm (`--kill-on-invalid-dep`) and shown Blocked by the existing rules. When it was the last active case
the job ends: CANCELLED when none of its cases failed (FAILED, or Blocked by a failure), else FAILED. A failing `scancel`
raises `JobError` and changes nothing. The Run page's **Cancel job** stays as it is (the whole job).

## 6. Errors

- Controller unreachable: the dot turns red; the page shows a banner "Slurm controller unreachable since hh:mm:ss:
  <message>" and the last known nodes, queue and jobs, greyed and marked "as of hh:mm:ss"; Cancel and Resubmit are
  disabled (they would fail).
- Accounting unreachable (the 7-day sacct fails): My jobs shows active cases only, with a note "ended jobs need
  Slurm accounting, which does not answer".
- A study folder that cannot be read: its jobs show with Slurm's state only (§3.3); never an error page.
- Nothing raised in the poller escapes it (as now).

## 7. Files

| File | Change |
|---|---|
| `engine/slurm.py` | `QueueRow` gains `user`, `name`, `workdir`; all-users `squeue_args()`; `NodeRow`, `sinfo_nodes_args()`, `parse_sinfo_nodes()`; `HistoryRow`, `sacct_recent_args(days)`, `parse_sacct_recent()`; `current_user()` |
| `engine/cluster.py` (new) | `study_of(workdir, name)`, `MyJob` rows from queue + recent sacct + job records, the record cache |
| `engine/jobs/slurm.py` | `cancel_case()` |
| `web/slurm_watch.py` | all-users queue, per-node sinfo, the 5-minute recent sacct while a Cluster page is open; viewer counts for "Cluster button shown" and "Cluster page open" |
| `web/cluster_view.py` | node rows, queue rows (all users), my-job rows and filters, the status dot, the Run summary line (NiceGUI-free, unit-tested) |
| `web/pages/cluster.py` (new) | the page |
| `web/layout.py` | the top-bar Cluster button with dot and count |
| `web/pages/run.py` | the summary line replaces the Cluster and Queue parts |
| `web/jobs.py` | `cancel_case()`; resubmit by study folder for the Cluster page |
| `cli/run_cmds.py` | `aerosuite cancel <study> --case <name>` (one case), for parity |

## 8. Testing

Test-first, POSIX, no real Slurm:
- The fake Slurm gains all-users `squeue` (jobs with a user field; other users' jobs), `sinfo -N` rows, and
  `sacct -S` listing jobs with WorkDir.
- Engine: parsers on hpc1's real output (captured 2026-10-20); `study_of` (real study, moved study, hand-submitted
  job, name mismatch); my-jobs from queue + sacct + records (active, ended, attempts, unreadable record);
  `cancel_case` (case cancelled, others go on, dependent Blocked, last case ends the job, scancel failing).
- Poller: one squeue per poll with two projects; sinfo -N only while the button is shown; recent sacct at most every
  5 min and only with the page open; idle with nothing open.
- Pages (simulated user): the top-bar button and dot (green / amber with reason / red), hidden without `sinfo`;
  the page's three cards and filters; Cancel one case with its dialog; Resubmit; the Log dialog; the Run summary line
  and its link; stale banner when the controller is down.
- Every existing test keeps passing; the Run page's Slurm tests change only where the Cluster/Queue parts moved.
- Screenshots of the page on the fake cluster for the user before merging.

## 9. Later phases

- **Phase 2 — usage history:** `sacct` over a chosen period; node-hours per day, per study and per partition;
  failures by kind (OOM, NODE_FAIL, TIMEOUT); export.
- **Phase 3 — admin actions:** hold/release own jobs (possible today); drain/resume nodes once the user's Slurm
  account has Operator rights (`sacctmgr modify user pdas-hpc1 set adminlevel=Operator`, run once by an admin) —
  a decision for the user/IT, since anyone who can open AeroSuite could then do it.
- **Multi-node jobs (InfiniBand):** node count per job, partitions spanning nodes, MPI launch and memory rules — its
  own spec when the hardware is in.

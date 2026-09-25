# AeroSuite Web UI — Run and Monitor (Phase 3b) — Design Spec

**Date:** 2026-09-25
**Status:** Draft for review
**Builds on:** `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md` (the base spec; its §6 and §7 apply unless changed here) and `docs/superpowers/specs/2026-09-23-web-config-modes-design.md`. Branch `feat/web-run-monitor`, stacked on `feat/web-phase-3a`.

---

## 1. Why and scope

After Phase 3a and the config modes, a study can be set up in the browser but not run or watched there; that still needs the CLI or the PyQt5 app. Phase 3b adds the **Run** and **Monitor** pages so a study goes from setup to running and converging without leaving the browser.

**Decided with the user:**
- **Reruns of selected cases.** When a sweep ends with FAILED or UNCONVERGED cases, the user reruns just those cases, choosing per rerun whether each continues from its own last solution.
- **Monitor shows one case at a time:** residuals and coefficients against iteration, the convergence verdict and the live solver log. Overlaying several cases is not in 3b.
- **Results stays a placeholder** (greyed in the sidebar). Its design is a separate discussion.
- **No startup token in 3b** (see §7).

**Out of scope:** Results page; overlaying cases on Monitor; subset reruns from the CLI (the engine API makes `aerosuite run --case … --continue` a small follow-up); Slurm; authentication; ParaView button (Phase 4).

## 2. Engine changes

All in `aerosuite/engine/`, no NiceGUI, unit-tested with the fake sweep script.

### 2.1 Restart file of a case — `restart_file(project_dir, case_name) -> Path | None`

The case's restart file from its last run: read `RESTART_FILENAME` from the `.cfg` the sweep script copied into `runs/<case>/` (default `restart_flow` when the line is missing), then look in `runs/<case>/` for that name as written, then with `.dat`, then with `.csv`. Returns the first file that exists, or `None` (no run yet, the run failed before writing one, or the folder is gone). `None` means the case cannot be continued.

### 2.2 Job inputs — new `jobs/plan.py`: `prepare_job(project_dir, project, job_id, cases, continue_cases) -> Path`

Writes the job's own inputs to `jobs/<id>/configs/` and returns that folder. Used for every submit (a full run is the subset "all cases"), so there is one code path.

- `cases`: case names to run, in the project's case order. Unknown names or an empty list raise `JobError`.
- For each selected case, its generated `configs/<case>.cfg` is copied in. A missing generated config raises `JobError` ("Generate configs first").
- A `run_control.txt` for the selected cases only, one line per case, derived from each case's restart option:
  - `none`, `initial`, `custom`: written as today.
  - `from_case X`: kept as `from_case X.cfg` when X is also selected and runs earlier in this job; otherwise rewritten to `custom <restart_file(X)>`; when X has no restart file, `none` and a warning (see §4).
  - `previous`: means "the case before it in the project's case list" and is treated exactly as `from_case <that case>` (so it never silently refers to a different case in a subset). The first case's `previous` is `none`, as today.
- **Continue** (case in `continue_cases`): the restart file from `restart_file(case)` is copied to `jobs/<id>/restart/<case>/<original file name>` **before anything runs** (the script deletes `runs/<case>/` when the case starts). The control line becomes `custom <absolute path of the copy>` and the job's copy of `<case>.cfg` gets `RESTART_SOL= YES`. A continued case with no restart file raises `JobError` naming the cases.
- `RESTART_SOL` is changed only in the job's copy; `template.cfg` and `configs/` are never modified.
- On any error the partly written `jobs/<id>/` folder is removed and nothing is left behind.

### 2.3 Submitting a subset — `LocalRunner.submit(project_dir, project, cases=None, continue_cases=())`

`cases=None` means all cases (today's behaviour). The runner calls `prepare_job`, then launches the sweep script with `-d jobs/<id>/configs -c jobs/<id>/configs/run_control.txt`; everything else is unchanged (working directory `runs/`, detached, log `jobs/<id>.log`, `.lock`, one job per project). `JobRecord.cases` and `case_status` list only the selected cases. Cases not selected are untouched: their `runs/<case>/` folders and their statuses from earlier jobs stay as they are.

### 2.4 Case overview — `case_overview(project_dir, project) -> CaseOverview`

For each case in the project: its status from the **newest job that included it** (`created` order) together with that job's id, the job's failure tail for the case, or `NOT_RUN` when no job included it. Also returns the problems found while reading jobs (below). The Run table and the Run badge read this.

### 2.5 Unreadable job records

`list_jobs` currently raises when any `jobs/*.json` is unreadable, which would break the Run page. A new `scan_jobs(project_dir) -> (jobs, problems)` skips unreadable records and reports each as a warning ("Job record jobs/<file> can't be read; ignored"). `case_overview` and the web layer use it; `list_jobs` keeps its strict behaviour for the CLI.

## 3. Web

### 3.1 Shared job watcher — new `aerosuite/web/jobs.py` (no NiceGUI)

One `JobWatcher` per server process, holding the server's single `LocalRunner` (the runner keeps the processes it started so it can reap them; separate instances per page would disagree).

- `state(project_dir) -> JobView`: the latest job, the active job (if any) and the case overview. An active job is refreshed through the runner at most once every 2 s per project, however many tabs ask; within that interval the cached state is returned. After a server restart the watcher starts empty; the first `state()` loads jobs from disk and refreshes the active one, and the runner's pid-plus-start-time check picks up a sweep that is still running.
- `submit(project_dir, project, cases, continue_cases)` and `cancel(project_dir)`: call the runner and drop the cached state so the next `state()` is fresh.
- `history(project_dir, job_id, case) -> DataFrame`: the whole history of that case in that job so far, read incrementally with one `HistoryReader` per `(job id, case)`. A rerun is a new job, so a recreated `history.csv` never reuses an old byte offset.
- `log_tail(project_dir, job_id, lines=40) -> str`.

### 3.2 Run page — `pages/run.py`

- **Checks:** `preflight(..., "run")` problems at the top; errors disable Submit, warnings do not.
- **Case table:** tick box, case name, status (from `case_overview`), the job it last ran in, and for FAILED cases the failure tail (expandable). Quick selectors: All, Failed, Unconverged, Not run, None.
- **Continue from each case's last solution:** a checkbox under the table. Default: on when every ticked case is UNCONVERGED and has a restart file; otherwise off. Ticked cases without a restart file are named beside it and the checkbox is disabled while any are ticked.
- **Submit** (disabled while a job is active, preflight has errors or nothing is ticked): runs Generate first (so a run always uses the current settings), then `watcher.submit`. Generation errors are shown and nothing starts.
- **Cancel** (only while a job is active): confirmation dialog, then `watcher.cancel`.
- **Job history:** newest first — id, created, state, number of cases, finished.
- While a job is active the page refreshes on a 2 s timer; otherwise it does not poll.

### 3.3 Monitor page — `pages/monitor.py`

- **Case select**, one case. Default: the case running now; otherwise the case that ran most recently. The data shown is from the newest job that included the case.
- **Residuals chart:** every `rms[...]` column against the iteration column (`Inner_Iter`, else `Outer_Iter`, else the row number), log y-axis.
- **Coefficients chart:** a multi-select of the other history columns, default `CL`, `CD`, `CMy` (those present), against iteration.
- **Convergence verdict:** the message from `check_convergence` for the data so far.
- **Log tail:** the last 40 lines of that job's log.
- Charts use NiceGUI's built-in ECharts (`ui.echart`); no new dependency. While the selected case is RUNNING the page updates every 2 s; otherwise it does not poll.

### 3.4 Sidebar

- **Run** becomes a link. Badge: ○ never run; a running indicator while a job is active; ● when the latest status of any case is FAILED, UNCONVERGED or CANCELLED; ✓ when every case's latest status is CONVERGED.
- **Monitor** becomes a link, no badge.
- **Results** stays greyed.

## 4. Error handling

Engine functions raise `AeroSuiteError` subclasses with a user-facing message; pages show the message and never crash.

- Preflight errors for `run` (`SU2_RUN` not set, sweep script or sweep Python not found, a job already running, a restart reference missing) disable Submit and are listed. Warnings are shown and do not block.
- `from_case`/`previous` resolving to a case with no restart file: the case runs from scratch and the Run page shows a warning naming it before Submit.
- A continued case whose restart file disappeared after the page loaded: `prepare_job` fails with a message naming the cases; nothing is launched and no job record is left.
- Two tabs submitting at once: the `.lock` lets one through; the other shows "A job is already running for this project".
- The sweep dying at once (wrong Python, SU2 import error): `refresh` marks the cases FAILED with the log tail, shown under each case.
- Cancel of a job that already ended reports its real outcome (existing engine behaviour).
- Monitor: "No history yet for this case" when the file does not exist; malformed lines are skipped (existing `HistoryReader` behaviour); "Log not available" when the log cannot be read.
- The 2 s outside-change watcher still reloads a page when `project.json` changes; job state is not stored in `project.json` and is unaffected.

## 5. Testing

No SU2, MPI, display or real browser; everything passes on Windows and Linux.

- **Engine:** `restart_file` (found as written, with `.dat`, with `.csv`, missing, custom `RESTART_FILENAME`); `prepare_job` (only selected cfgs and control lines; Continue copies the restart file, writes `custom` and sets `RESTART_SOL= YES` in the job copy only; `from_case` and `previous` outside the subset become `custom`, or `none` without a restart file; errors leave no `jobs/<id>/`); `case_overview` (newest job wins, `NOT_RUN`, a corrupt job file skipped with a warning); subset submit through the fake sweep (only ticked cases run; other `runs/<case>/` folders untouched).
- **`web/jobs.py`:** at most one refresh per 2 s across repeated `state()` calls; pickup by a new watcher of a job that is still running; history reader per `(job, case)`; log tail.
- **Pages (simulated user, fake sweep):** Run — preflight errors disable Submit; submit all → RUNNING → CONVERGED; the Failed selector plus Continue reruns only those cases; cancel with confirmation; job history; failure tails. Monitor — defaults to the running case; residual (log axis) and coefficient series; verdict text; log tail; "No history yet". Sidebar — Run and Monitor links, Run badge states, Results greyed.
- **Visual click-through** in the browser pane with screenshots, as the plan's last task.
- **Workstation check (user):** one real continued rerun on the SU2 workstation, confirming SU2 reads the copied restart file through the `custom` path with `RESTART_SOL= YES` (the fake sweep cannot prove SU2's file-name handling).

## 6. Files

| File | Change |
|---|---|
| `aerosuite/engine/jobs/plan.py` | new: `restart_file`, `prepare_job` |
| `aerosuite/engine/jobs/local.py` | `submit` takes `cases`, `continue_cases`; runs from the job's configs |
| `aerosuite/engine/jobs/store.py` | `scan_jobs` |
| `aerosuite/engine/jobs/overview.py` | new: `case_overview`, `NOT_RUN` |
| `aerosuite/web/jobs.py` | new: `JobWatcher` |
| `aerosuite/web/pages/run.py`, `pages/monitor.py` | new pages |
| `aerosuite/web/status.py`, `layout.py`, `app.py` | Run/Monitor links and Run badge |
| `README.md` | Run and Monitor pages |

## 7. Access and security

No startup token in 3b (user decision, 2026-09-25). The server keeps binding to `127.0.0.1` and rejecting non-local `Host` headers (base spec §6). **Known risk:** from 3b the web UI can launch and cancel jobs, and on a workstation shared by several accounts any local account can reach the port. The token (Jupyter-style) is deferred to a later phase and must be added before AeroSuite is used on a shared machine.

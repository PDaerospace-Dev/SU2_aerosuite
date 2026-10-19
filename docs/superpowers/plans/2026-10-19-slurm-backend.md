# Slurm backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development).
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `slurm` execution backend beside the unchanged `local` one: one Slurm batch job per case with a job
script in its case folder, restart dependencies (`afterok`), one batched `squeue` / `sacct` per poll from an async
poller, a cluster panel and queue on the Run page, pre-submit checks with a memory estimate, cancel and resubmit, cost
per case on the Results page, and the same options in the CLI.

**Spec:** `docs/superpowers/specs/2026-10-19-slurm-backend-design.md` (binding). Manual tests:
`docs/superpowers/specs/2026-10-19-slurm-manual-test-plan.md`.

**Tech:** Python 3.12, pydantic v2, asyncio (engine, no NiceGUI); NiceGUI 3.17 (web); Typer (CLI); pytest with the
simulated `user` fixture; `tests/fixtures/fake_slurm.py` stands in for Slurm.

## Global constraints

- Run everything from the repository root with `uv run …`; tests: `uv run pytest -q -p no:cacheprovider`.
- **Local unchanged:** no edit to `engine/jobs/local.py` behaviour, `sweep_wrapper.py`, `aoa_sweep_v8.py`; the full
  existing suite passes after every task.
- **Import boundaries** as before: `engine/` has no NiceGUI/Typer/web imports; `web/` has no pandas.
- **Never block the event loop:** web code never calls `subprocess.run` for Slurm; only `engine.slurm.run_async`
  from the poller task.
- **One `squeue` per poll for all jobs; at most one `sacct` per poll.** Tests assert the call counts.
- **A failed `squeue` never changes a case's state.**
- **No hard-coded cluster facts** outside `engine/settings.py` defaults.
- Commit after each task (small commits, message `feat(slurm): …` / `test(slurm): …`), ending with the
  Co-Authored-By line. Push only when the user asks.

## Review focus

- `squeue` fails (controller down) while a case is RUNNING → the case stays RUNNING, an outage line is logged once.
  Task 6.
- Case finishes between polls and slurmdbd has no row yet → unchanged until it has; after 10 polls the file fallback.
  Task 6.
- `sbatch` fails on case 2 of 3 → case 1's job is scancelled, the job FAILED with the message, lock cleared. Task 5.
- A fails → B (afterok on A) and C (afterok on B) both Blocked, none left pending. Task 6.
- 15 GB `.su2` mesh → the NELEM reader reads ≤ 64 lines. Task 4.
- Two projects with active Slurm jobs → still one `squeue` per poll. Task 9.

---

### Task 1: Server settings

**Files:** create `aerosuite/engine/settings.py`, `aerosuite/cli/settings_cmds.py`; modify `aerosuite/cli/app.py`
(register); tests `tests/engine/test_settings.py`, `tests/cli/test_cli_settings.py`.

**Interfaces:** `AppSettings`, `SlurmSettings`, `PartitionSettings` (spec §2.1); `settings_path() -> Path`;
`load_settings() -> tuple[AppSettings, list[str]]` (warnings); `save_settings(s)`; `set_value(s, dotted_key, text)
-> AppSettings` (raises `SettingsError`); `PartitionSettings` lookup `s.slurm.partition(name)`;
`valid_time_limit(text) -> bool`.

- [ ] Tests: defaults when missing; unreadable/invalid JSON → defaults + warning; round trip; validation (duplicate
  partitions, unknown default partition, relative shared root, bad time limits `1:2:3:4`, `abc`; good ones
  `30`, `12:00:00`, `2-00:00:00`); `set_value` on `slurm.poll_seconds` and `slurm.partitions.node2.default_ntasks`;
  `AEROSUITE_HOME` respected.
- [ ] Implement; `aerosuite settings` / `settings set`. Run tests; commit.

### Task 2: Data model — schema 8, BLOCKED, Slurm case records, executors, lock

**Files:** modify `engine/models.py`, `engine/project.py` (migration 7→8), `engine/jobs/runner.py`
(`CaseState.BLOCKED`, `SlurmCase`, `JobRecord.slurm`, protocol gains `started_cases`, `case_log`),
`engine/jobs/store.py` (`write_lock(..., backend=...)`, `active_lock` for slurm locks), `engine/jobs/local.py`
(only `case_log` added, returning the job log), `web/run_view.py` + `web/status.py` + `web/ui_kit.py` (Blocked in
STATUS_ORDER, pill tone, Failed selector), `cli/run_cmds.py` (prints BLOCKED); create `engine/jobs/executors.py`.
Tests: `tests/engine/test_models.py`, `test_project.py` (7→8), `test_jobs_store.py` (slurm lock active while record
active, cleared when not; local lock unchanged), new `tests/engine/test_executors.py`, `tests/web/test_run_view.py`.

- [ ] Tests first, then implement; full suite green; commit.

### Task 3: Slurm commands and the fake

**Files:** create `aerosuite/engine/slurm.py`, `tests/fixtures/fake_slurm.py`, fixture `fake_slurm` in
`tests/conftest.py`; tests `tests/engine/test_slurm_commands.py`.

**Interfaces:** `SlurmUnavailable(Exception)`; dataclasses `QueueRow`, `AcctRow`, `PartitionRow`, `SeffStats`;
parsers `parse_sbatch(text) -> str`, `parse_squeue`, `parse_sacct`, `parse_sinfo`, `parse_sinfo_reasons`,
`parse_seff`; argv builders `squeue_args()`, `sacct_args(ids)`, `sinfo_args()`, `sinfo_reason_args()`,
`seff_args(id)`, `sbatch_args(script)`, `scancel_args(ids)`; `run_sync(argv, cwd=None, timeout=20) -> str`;
`async run_async(argv, timeout=20) -> str`; `query_sync(ids_left_queue) -> Snapshot` (one squeue, ≤ one sacct).

- [ ] Fake: one Python script dispatched on the shim's name; state JSON (`jobs`, `next_id`, `controller_down`,
  `accounting_down`, `partitions`, `reasons`, `calls`); `sbatch --parsable` parses `#SBATCH` lines incl.
  `--dependency`, appends a PENDING job, prints the id (optionally `;pdas-cfd`); `scancel` marks CANCELLED and
  removes from the queue; `squeue/sacct/sinfo/seff` print from the state; down → stderr + exit 1.
- [ ] Parser tests on captured real output (hpc1 job 11's `seff`, `sacct` with `CANCELLED by 1000`, `0:125`,
  `sinfo` with `node1*`, drained rows); runner tests: missing command, timeout, non-zero exit → `SlurmUnavailable`
  with stderr; `run_async` under `asyncio.run`. Commit.

### Task 4: Pre-submit checks and the memory estimate

**Files:** create `aerosuite/engine/slurm_checks.py`; modify `engine/preflight.py` (`preflight(..., backend=None,
run=None, settings=None)`: Slurm replaces `_environment_problems`; local path unchanged); tests
`tests/engine/test_slurm_checks.py`, `tests/engine/test_preflight.py` (local unchanged).

**Interfaces:** `mesh_elements(path) -> Optional[int]` (≤ 64 lines); `memory_estimate_gb(nelem, factor)`;
`slurm_problems(project_dir, project, cases, partition, ntasks, time_limit, settings) -> list[Problem]`;
`memory_note(...) -> Optional[str]` for the Checks panel.

- [ ] Tests: NELEM found after comments/NDIME; not found; CGNS → None; reader stops early (a file with a huge tail
  of garbage — assert lines read via a counting wrapper); outside shared root → error; mesh not absolute / missing →
  error; mesh outside root → warning; ntasks > 48 on node2 → warning only; estimate > limit → warning on node1,
  error on node2; unknown partition / bad time limit → error; sbatch not on PATH → error. Commit.

### Task 5: SlurmRunner.submit and the job script

**Files:** create `aerosuite/engine/jobs/slurm.py`; tests `tests/engine/test_slurm_submit.py`.

**Interfaces:** `job_script(study, case, cfg_name, options, settings, job_id, depends_on_id, note) -> str`;
`SlurmRunner(settings_loader=load_settings)` with `submit(project_dir, project, cases=None, continue_cases=(),
partition=None, ntasks=None, time_limit=None) -> JobRecord`.

- [ ] Tests: script text matches spec §4.2 (with and without `-A`, `-t`, dependency); case folder gets cfg with
  `SOLUTION_FILENAME` (previous / from_case / custom / continued) and `RESTART_SOL`; `sbatch` called from the case
  folder, ids `123` and `123;pdas-cfd` parsed; record saved with `SlurmCase`s and the lock; dependency ids chain in
  order; partial failure on case 2 → case 1 scancelled, job FAILED, lock cleared, `JobError`; controller down at
  submit → `JobError`, no active record; script values with a newline rejected; the env passed to sbatch has no
  `VIRTUAL_ENV`. Commit.

### Task 6: refresh — state mapping, accounting, fallback, Blocked, stats

**Files:** `engine/jobs/slurm.py` (`refresh(project_dir, job, snapshot=None)`, `started_cases`, `case_log`,
`write_case_stats`), tests `tests/engine/test_slurm_refresh.py`.

- [ ] Tests (each through the fake): PENDING (reason) / RUNNING (node, time) / COMPLETING; left queue →
  COMPLETED + converged history → CONVERGED, unconverged → UNCONVERGED, no history → FAILED; FAILED / TIMEOUT /
  OUT_OF_MEMORY / NODE_FAIL → FAILED with state, exit code and the out-file tail; CANCELLED → CANCELLED; dependency
  failed → dependents (chain of 2) BLOCKED; `DependencyNeverSatisfied` → scancel + BLOCKED; sacct no row → unchanged
  then fallback after 10; sacct down → `AEROSUITE_EXIT 0` / "Exit Success" / `AEROSUITE_EXIT 1` / nothing; squeue
  down → no change and one log line per outage start/end; one squeue + one sacct per refresh for many cases; job end
  → DONE/FAILED, lock cleared, restart copies removed; stats file content (s/iter, peak memory and CPU per rank from
  seff, seff failing → those empty). Commit.

### Task 7: cancel and resubmit

**Files:** `engine/jobs/slurm.py` (`cancel`, `resubmit(project_dir, project, job, cases, partition=None,
ntasks=None)`, `resubmittable(job) -> list[str]`), tests `tests/engine/test_slurm_cancel_resubmit.py`.

- [ ] Tests: one scancel with all non-final ids; states CANCELLED; scancel failing → JobError, nothing changed;
  resubmit NODE_FAIL case → new id, old in `attempts`, job active, Blocked dependents resubmitted with afterok on
  the new id; OOM resubmit to another partition rewrites the script; resubmit refused for other states and while
  another job is active; preflight memory block applies. Commit.

### Task 8: CLI

**Files:** `cli/run_cmds.py` (`run` options, `status`/`cancel` via `runner_of(job)`, `resubmit`), tests
`tests/cli/test_cli_run_slurm.py`.

- [ ] Tests: `run --backend slurm --partition node2 --ntasks 48 --time 1:00:00` submits and saves the choices;
  `--ntasks` with local / `-n` with slurm → clear error; preflight errors exit 1; `status` prints job ids, nodes,
  reasons and exits non-zero with the message when the controller is down; `cancel`; `resubmit` default set.
  Existing CLI tests unchanged. Commit.

### Task 9: The poller and JobWatcher

**Files:** create `aerosuite/web/slurm_watch.py`; modify `web/jobs.py` (dispatch by `job.backend`, pass the snapshot,
`case_log`), `web/server.py` / `web/app.py` (start/stop the task on app startup/shutdown); tests
`tests/web/test_slurm_watch.py`, `tests/web/test_jobs.py`.

**Interfaces:** `ClusterSnapshot`; `SlurmWatch.track(project_dir, job_id)`, `.show_cluster()` / `.hide_cluster()`
(viewer count), `.snapshot`, `async .poll_once()`, `.start()` / `.stop()`.

- [ ] Tests: `poll_once` with two projects' jobs → one squeue, one sacct; idle (no calls) with nothing tracked and no
  viewer; sinfo only with a viewer, `sinfo -R` only when a node is drained; controller down → snapshot.error set,
  previous rows kept; exceptions never escape the loop; seff once per finished case; `JobWatcher.state()` makes no
  subprocess call for a Slurm job (assert via the fake's call log). Commit.

### Task 10: Run page in Slurm mode

**Files:** `web/pages/run.py` (backend toggle, Slurm launch fields, Cluster and Queue parts, case-row Slurm details,
Resubmit dialog, Cancel via the runner), new `web/cluster_view.py` (NiceGUI-free formatting: CPU bars, state tones,
reasons), CSS in `web/theme.py`; tests `tests/web/test_cluster_view.py`, `tests/web/test_web_run_slurm.py`.

- [ ] Tests (simulated user, fake Slurm): toggle saves `run.backend`; partition select pre-fills tasks; memory note
  and node2 warning in Checks; shared-root error disables Submit; Submit → rows PENDING with ids; snapshot change →
  RUNNING with node; drained node row and reason; controller-down banner; Cancel; Resubmit dialog for OOM proposes
  node1; Local mode still shows Machine (existing `test_web_run.py` unchanged). Screenshots for the user. Commit.

### Task 11: Settings page

**Files:** create `web/pages/settings.py`; modify `web/layout.py` (gear in the top bar), `web/app.py` (register);
tests `tests/web/test_web_settings.py`.

- [ ] Tests: shows defaults; edits saved to `settings.json`; invalid values rejected with the message; partition
  rows add/remove; unreadable file → warning banner. Screenshots. Commit.

### Task 12: Monitor and log panel for Slurm cases

**Files:** `web/pages/monitor.py`, `web/log_panel.py` (use `case_log` / `started_cases` of the job's runner); tests
in `tests/web/test_web_monitor.py`, `tests/web/test_web_log_panel.py`.

- [ ] Tests: Monitor shows a running Slurm case's `slurm-<id>.out` tail and history; log panel lists the job and shows
  `jobs/<id>.log`; local behaviour unchanged. Commit.

### Task 13: Results — Cost group

**Files:** `engine/study_results.py` (read `slurm_stats.json` per case into a `cost` frame), `web/results_view.py`,
`web/pages/results.py`; tests `tests/engine/test_study_results.py`, `tests/web/test_web_results.py`.

- [ ] Tests: Cost columns present only when some case has stats; values and units; node-hours total; CSV export
  includes them; `summary.csv` unchanged. Commit.

### Task 14: Docs and the cluster check

- [ ] README: a short "Running on the cluster" section; `docs/HANDOVER.md`: hpc1, the branch, the decisions here.
- [ ] Full suite; then the manual test plan on the cluster with the user (`2026-10-19-slurm-manual-test-plan.md`).

# Slurm backend — manual test plan on the cluster

For `feat/slurm-backend` (spec: `2026-10-19-slurm-backend-design.md`). Run on hpc1 as `pdas-hpc1`, AeroSuite started
with `aerosuite serve`. Each test says what to do and what to see; tick it and note the job ids.

## 0. Preparation

- A small test study under `/data` (e.g. `/data/tests/aerosuite-slurm/`), mesh under `/data`. Use a coarse mesh for
  §2–§5 so they take minutes; the X07 15M-cell case only for §1's timing check and §6.
- Template `ITER= 50`, `HISTORY_WRT_FREQ_INNER= 1`.
- Before each test: `squeue --me` is empty, `sinfo` shows node1 and node2 `idle`.
- Settings page: backend Slurm, defaults as in the spec (§2.1). `aerosuite settings` prints the same.

## 1. One 50-iteration case on node1, then on node2

1. Single-case study. Run page → Slurm, partition node1 (Tasks shows 96), Submit.
   - Checks show "≈ N GB of 120 GB on node1" and nothing red.
   - `runs/<case>/su2_job.sh` exists; compare with `/data/software/templates/su2_job.sh`: `-J <study>/<case>`,
     `-p node1`, `-N 1`, `-n 96`, `--exclusive`, `-A pdas`, `-o slurm-%j.out`, `module load …`, `srun --mpi=pmix`.
   - The case shows PENDING then RUNNING on hpc1 with a run time ticking at the poll interval (~12 s); `squeue --me`
     agrees. The Queue panel lists the job; the Cluster panel shows node1's CPUs allocated.
   - Monitor follows the residuals; the log panel shows `slurm-<id>.out`.
   - At the end: CONVERGED or UNCONVERGED, exit code 0:0. `sacct -j <id> -X` says COMPLETED.
   - Results → Cost group: Elapsed matches sacct, s/iter ≈ elapsed / 50, Peak memory matches `seff <id>` "Memory
     Utilized", CPU use per rank close to 100% (not seff's ~50%).
2. Same on node2: Tasks pre-fills 48. Set 96 → a warning about node2 above 48 tasks, Submit still allowed. Set back
   to 48 and submit. Runs on hpc2, same checks as above.
3. CLI: `aerosuite run <study> --backend slurm --partition node2 --ntasks 48` then
   `aerosuite status <study> --watch` until it finishes; the Run page shows the same job.
4. (X07 only, optional) one case on node1 at 96 tasks: s/iter ≈ 2.26 s plus start-up; peak memory ≈ 58 GB.

## 2. Cancel

1. Submit a 3-case sweep on node1 with `ITER= 2000`. When case 1 is RUNNING and 2–3 PENDING: Cancel → confirm.
   - The Run page answers at once; within one poll all three cases are CANCELLED and the job CANCELLED.
   - `squeue --me` is empty; `sacct` shows CANCELLED for all three; nothing SU2 left on hpc1 (`pgrep SU2_CFD`).
2. `aerosuite cancel <study>` on a fresh submit: same result from the CLI.

## 3. A 3-case sweep

1. α = 0, 2, 4, restart `none`, node1. Submit.
   - Three Slurm jobs, one per case folder; with `--exclusive` they run one after another (the others PENDING,
     reason Resources). The Queue panel shows the reasons.
   - All three end CONVERGED/UNCONVERGED; Results shows the curve and a Cost row per case and the node-hours total.
2. Same sweep split by hand: case 1–2 on node1, then rerun case 3 on node2 (ticked alone). Both nodes are used; the
   Cluster panel shows both busy.

## 4. A restart-dependency pair

1. Two cases, B restarts `previous` from A. Submit on node1.
   - `runs/B/su2_job.sh` has `--dependency=afterok:<A's id>` and `--kill-on-invalid-dep=yes`; B shows
     "PENDING · Dependency" while A runs, then runs and restarts from `runs/A/restart_flow.dat` (its log says so).
2. Failure path: set A's `ITER` very small and give A a broken setting (e.g. a wrong marker in an override) so SU2
   fails, or `scancel` A by hand while it runs.
   - A ends FAILED (or CANCELLED); within one or two polls B is **Blocked** with "Not run: A ended …"; B is not left
     pending; `squeue --me` is empty.

## 5. Failure handling

1. **OUT_OF_MEMORY:** in Settings, temporarily set node2's `memory_limit_mb` very high so the check does not block,
   then run the X07 mesh on node2 (or any case that needs > 62 GB). It ends FAILED "OUT_OF_MEMORY"; the row offers
   Resubmit, proposing node1. Resubmit → runs on node1 inside the same job; `attempts` lists the first id.
   Set the setting back.
2. **Memory pre-check:** X07 mesh on node2 with the setting back: Submit is blocked with the estimate and the limit.
   On node1: allowed, estimate shown.
3. **Shared root:** a study under `/home/pdas-hpc1/`: Submit blocked, message names `/data`.
4. **Controller down:** `sudo systemctl stop slurmctld` while a job is running (or block it in the firewall).
   - The Cluster panel shows "controller unreachable since …"; case states stay as they were (nothing marked
     failed); one line in the job's log. `aerosuite status` prints the error and exits non-zero.
   - Submit now: a red banner with Slurm's message, nothing recorded.
   - `sudo systemctl start slurmctld`: within one poll everything updates; one "reachable again" line in the log.
5. **Accounting down:** `sudo systemctl stop slurmdbd` while a short case finishes. It is still classified
   (CONVERGED/FAILED from `slurm-<id>.out`'s `AEROSUITE_EXIT` line), with a note that the Slurm state is unknown.
   Start slurmdbd again.
6. **Drained node:** `sudo scontrol update nodename=hpc2 state=drain reason="test"`: node2's row turns red with
   "test". `… state=resume` clears it.
7. **NODE_FAIL** cannot be caused safely; covered by the unit tests.

## 6. Server restart and local backend

1. Submit a 3-case sweep, stop `aerosuite serve` while case 1 runs, start it again 1 min later: the Run page shows the
   true states (sacct for any case that finished meanwhile).
2. Switch the study back to Local and run one short case with `mpirun` as before: everything behaves as before this
   branch (Machine panel, free cores, Cancel).

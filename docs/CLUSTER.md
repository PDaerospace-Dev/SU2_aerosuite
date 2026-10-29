# Running on the Slurm cluster

On the cluster's controller (hpc1) AeroSuite can submit each case as its own Slurm batch job instead of running the
sweep on this machine. Choose **Slurm** in the Run page's toggle (saved with the study), or make it the default for
every study on the **Settings** page (bottom left) or with `aerosuite settings set backend slurm`.

```bash
aerosuite run ./study --backend slurm --partition node1 --case M0p8_a0 --case M0p8_a2
aerosuite run ./study --add --partition node2 --ntasks 48   # more cases into the running job, on node2
aerosuite status ./study --watch     # Slurm job ids, nodes, pending reasons; one squeue per poll interval
aerosuite cancel ./study             # scancel every unfinished case of the job
aerosuite cancel ./study --case M0p8_a2   # one case; the others go on
aerosuite resubmit ./study           # the cases that ended NODE_FAIL or OUT_OF_MEMORY, in the same job
aerosuite settings                   # partitions, default tasks, memory limits, module line, SU2 path, ...
```

- Every case gets `runs/<case>/su2_job.sh` (one node, `--exclusive`, `srun --mpi=pmix SU2_CFD <case>.cfg`) and its
  output in `runs/<case>/slurm-<jobid>.out`; the folder records exactly how it ran (`sbatch su2_job.sh` there
  reruns it by hand, after removing a `--dependency` line).
- While a Slurm job runs, the Run page's **Add cases** sends more ticked cases into it, e.g. to the other node; the
  time limit for every job is set on the Settings page (`--time` overrides it for one run).
- A case that restarts from another case of the same submit waits for it to end, however it ends
  (`--dependency=afterany`). It restarts from that case's solution only if the case exited 0 and the solution file
  exists; otherwise (failed, cancelled, killed) its script sets `RESTART_SOL= NO` and it starts from scratch, as a
  local sweep does. Its `slurm-<id>.out` and the job log say so. (Jobs submitted before this used `afterok`: there a
  failed case's dependents show **Blocked**.)
- **Resubmit** (a NODE_FAIL or OUT_OF_MEMORY case, with the cases blocked behind it) prepares the case folder again
  as a submit does: its run so far is kept as an earlier attempt, its config is written afresh from the job's, and
  the earlier `slurm-<id>.out` stays beside the new one. A case whose solution to restart from is gone starts from
  scratch, and the job log says so.
- A case run again inside the same job (Add cases) keeps only one earlier attempt with its volume files until the
  job ends; older ones lose them at once.
- The server watches every running AeroSuite job it finds in Slurm (the queue and the last 7 days) from its start,
  so a job that ends while no page shows its study is still recorded, its lock released and its files tidied.
- Studies must live under the shared root (`/data`): the other node cannot see anything else. Before submitting,
  AeroSuite estimates the memory from the mesh header (`NELEM` × 3.9 GB per million cells, configurable), warns when
  it is over the partition's limit and refuses on partitions set to block (node2).
- The **Cluster** page (top bar; its dot is green, amber for a drained or down node, red when Slurm does not answer)
  shows tiles at a glance and a card per node (what runs there and what is queued for it), then your AeroSuite cases
  on Slurm from every study — queued, running or ended in the last 7 days, with when each started and ended — with
  Cancel (one case), Resubmit and Log; the list folds. The Run page keeps
  a one-line summary. The Results page adds a **Cost** group per case (elapsed, s/iter, peak memory and CPU use from
  `sacct`/`seff`) and the study's node-hours.
- **node0 (hpc0, the Ubuntu workstation)** is a partition like the others, but its job script does not use
  `srun --mpi=pmix` (the nodes have PMIx 4, the workstation PMIx 5). It runs `mpirun --bind-to core -np
  "$SLURM_NTASKS" SU2_CFD <case>.cfg` under plain `#!/bin/bash`, with `PATH=/usr/local/bin:/usr/bin:/bin` and
  `LD_LIBRARY_PATH` unset, no `--exclusive`, and never `--export=NONE` (uid 1000 is `pdas` there and `pdas-hpc1` on
  the nodes). The launch command, module line, PATH, unset variables and job environment are per-partition settings
  (Settings → *Partitions* → node0, or `aerosuite settings set slurm.partitions.node0.launch_command ...`); a
  partition whose launch command is empty keeps the Slurm-wide ones. Its reference script is
  `/data/software/templates/su2_job_ws.sh`.
- The local backend (`mpirun` through the sweep script) is unchanged and stays the default.

# AeroSuite roadmap

Planned work that is not started yet. Each item says why it matters, what it takes and what has to be true first.

## One case on several nodes (InfiniBand)

**Status:** planned, starts when the InfiniBand network is in (written 28 Oct 2026).

**Goal:** run one SU2 case across 2 or 4 identical nodes as one MPI job, e.g. 4 × 192 = 768 ranks, chosen per
study or per added batch the way a partition is chosen today.

### Why

One node per case gives the most cases per day: every node runs at full efficiency. Several nodes per case is
worth it when:

1. **The mesh does not fit one node's memory.** A del50m case peaks around 89 GB; over 2 nodes it needs about
   45 GB on each.
2. **One case is wanted back soon**, e.g. a check case before a sweep is sent.
3. **The tail of a sweep:** when fewer cases are left than nodes, idle nodes can speed up the ones still running.

SU2 slows down once each rank holds too few cells, so 4 nodes give a case perhaps 3–3.5×, not 4×. The speedup
for our meshes on our network has to be measured (step 3 below), not assumed.

### Before AeroSuite: the cluster

None of this is AeroSuite's job, but nothing below works without it.

- [ ] OpenMPI and PMIx built with UCX, so MPI runs over InfiniBand and not Ethernet. Check with `ucx_info -d` and an
      MPI bandwidth test between two nodes.
- [ ] SU2 built against that MPI (`SU2_CFD`, `SU2_SOL`).
- [ ] A Slurm partition holding only the identical nodes. hpc0 (64 cores) and hpc2 (61 GB) stay out: in a
      multi-node job the slowest node sets the pace.
- [ ] Storage: every rank's output goes to the shared `/data`. A large write there has already hung a case once;
      NFS over RDMA (on the InfiniBand) or a node-local scratch that is copied back would help.

### In AeroSuite

**1. Engine basics**

- [ ] `nodes` on a partition in Settings → Slurm (default 1), and on `SlurmOptions`
      (`aerosuite/engine/jobs/executors.py`).
- [ ] `script_head` writes `#SBATCH -N <nodes>` and `--ntasks-per-node` in place of the fixed `-N 1`
      (`aerosuite/engine/jobs/slurm.py`); a multi-node case always gets `--exclusive`.
- [ ] Read Slurm's compact node lists (`hpc[1-4]`, `hpc[1,3]`) into node names wherever a job's node is read:
      squeue/sacct rows in `aerosuite/engine/slurm.py`, `SlurmCase.node`, `node_jobs` in
      `aerosuite/web/cluster_view.py` (today it only splits at commas) and `job_nodes` in `aerosuite/web/jobs.py`.
- [ ] The memory check per node: the mesh's estimate divided by the nodes, against each node's memory
      (`aerosuite/engine/slurm_checks.py`).
- [ ] The ASCII export (`aerosuite/engine/ascii_export.py`) keeps `-N 1`: SU2_SOL is short and does not need more.

**2. Web UI**

- [ ] Run page: a 1 / 2 / 4 node choice beside the partition and its cores per case, for a submit and for Add cases.
- [ ] Cluster page: a case on several nodes shows on each of their cards, marked "spans hpc1 + hpc2 · 384 cores",
      so it reads as one case.
- [ ] Run's job bar and the Projects list: one node pill per node the case runs on.

**3. Scaling test**

- [ ] Run one case for about 50 iterations on 1, 2 and 4 nodes and read the time per iteration from its history.
- [ ] Keep the result per mesh and show it: "2 nodes: 1.9×, 4 nodes: 3.4×".
- [ ] From it, compare layouts for the sweep before it is sent: "48 cases, 1 node each: about 22 h · 2 nodes each:
      about 25 h".

**4. Later: AeroSuite picks the layout**

- [ ] One node per case while there are more cases than nodes; the last cases get the free nodes.

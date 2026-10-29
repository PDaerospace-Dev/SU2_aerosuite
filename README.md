# AeroSuite

AeroSuite is a web application for preparing, running and reviewing SU2 CFD studies. This includes:
- Mesh and config (CFG) setup
- Parametric sweeps over Mach, angle of attack, sideslip and altitude
- Runs on this machine or on a Slurm cluster
- Live convergence monitoring
- Results with plots, derived values.

**Cluster:** Slurm nodes and your jobs management
**Calculators:** (ISA atmosphere and y+)
**ParaView:** Open your cases in Paraview

It runs as a service on the workstation and opens in any browser; everything it does is also available as the `aerosuite` command.

>The original PyQt5 desktop app is still in the repository: see [Legacy desktop app](#legacy-desktop-app-pyqt5).

## Quick start
One-time setup (no admin rights needed; Python 3.12 in its own environment, managed by [uv](https://docs.astral.sh/uv/)):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /path/to/SU2_aerosuite
uv sync
uv run aerosuite service install --root /data   # starts at boot, listens on 127.0.0.1:8080
```

Then open http://localhost:8080 on the workstation, or from your PC with the launcher the Settings page offers
(see *Getting started* in [docs/WEB_UI.md](docs/WEB_UI.md)). To try it in a terminal instead: `uv run aerosuite serve --root /data`.

## Workflow
1. **Projects** — open, create or import a study (a *General case* or an *Aircraft study* from a profile such as X07).
2. **Setup** — choose the mesh and template, the run settings and the sweep on/off switch.
3. **Aircraft** or **CFG setup** — the case's flight conditions, solver, boundaries, reference values and start;
   or a plain config editor for a general case.
4. **Sweep** — Mach, α, β and altitude lists, case names and how each case restarts.
5. **Run** — check the configs with SU2, submit cases (locally or on cluster), rerun the ones that fail.
6. **Monitor** — residuals and coefficients while a case runs.
7. **Results** — parameters averaged over the last iterations, as plots, tables and CSV.

Alongside: **Cluster** (Slurm nodes and your jobs), **Calculators** (ISA atmosphere, y+), **ParaView**,
**Settings** and **Profiles**. Each is described in the [web UI guide](docs/WEB_UI.md); the **?** in the top bar opens it on the
page you are on.

## Project structure
```
run_aerosuite.py             Entry point of the legacy PyQt5 app
pyproject.toml, uv.lock      Environment (Python 3.12 via uv)
aerosuite/
├── web/                     The web UI (NiceGUI): pages/, theme, Run board, Cluster view, help guide
├── cli/                     The `aerosuite` command (new, set, generate, run, status, serve, service, settings, ...)
├── engine/                  All logic, no UI imports
│   ├── models.py            Project model (project.json)
│   ├── project.py, study.py Create / open / save study folders
│   ├── naming.py            Case names <-> Mach/alpha/beta/altitude
│   ├── cfg.py, config_*.py  Template rendering, config generation and editing
│   ├── preflight.py, su2_check.py   Checks before generate / run (including SU2's own dry run)
│   ├── results.py, packages.py, formula.py   History reading, convergence, derived values, result packages
│   ├── settings.py          Server-wide settings (backend, Slurm, partitions)
│   ├── slurm.py, cluster.py Slurm queries and the node view
│   ├── atmosphere/          ISA and y+ calculators
│   └── jobs/                Job records, local and Slurm executors, rerun, sweep wrapper
├── core/, ui/, utils/, main.py   Legacy desktop app (see below)
└── resources/
    ├── config_template.cfg  Bundled default reference config
    ├── aoa_sweep_v8.py      Sweep script (runs under the system Python that imports SU2)
    └── profiles/, packages/ Bundled aircraft profiles and result packages
tests/                       pytest suite; tests/fixtures/fake_sweep.py stands in for SU2
docs/                        WEB_UI.md (the in-app guide), CLUSTER.md (Slurm), ROADMAP.md, HANDOVER.md, superpowers/
```

## Installation
AeroSuite runs on **Python 3.12** in its own uv environment. The system Python (3.7.6 on the workstation) is not
touched; the sweep script keeps running under it, because that is the Python that can import SU2. `SU2_RUN` must be
set in the shell that starts a run, and the sweep script is launched under the Python named by
`AEROSUITE_SWEEP_PYTHON` (default: the first `python3` on `PATH` outside AeroSuite's own environment). Set it when
SU2 lives under a different interpreter:

```bash
export AEROSUITE_SWEEP_PYTHON=/usr/bin/python3
```

The install steps are under *Quick start* above.

### Tests
```bash
uv run pytest
```

## Documentation
- [docs/WEB_UI.md](docs/WEB_UI.md): the web UI page by page. The **?** in the top bar shows this file.
- [docs/CLUSTER.md](docs/CLUSTER.md): running on Slurm: job scripts, restarts, memory limits and the node0 partition.

## Command line
The same workflow without the GUI — handy over SSH and for scripting (run inside the uv environment, or `uv run aerosuite ...`):

```bash
aerosuite new ./study --template master.cfg --mesh wing.su2
aerosuite set ./study --mach 0.6,0.8,0.85 --alpha=-4:12:2 --beta 0 --partitions 64
aerosuite set ./study --key CFL_NUMBER=5 --key MARKER_PLOTTING=none
aerosuite set ./study --freestream altitude --altitude-km 0,5,11 --reynolds-length 6   # sweep altitudes; per-case Re
aerosuite show ./study
aerosuite edit ./study          # anything else (restart per case, numerics) in $EDITOR
aerosuite generate ./study
aerosuite run ./study           # returns at once; the sweep keeps running after logout
aerosuite status ./study --watch
aerosuite cancel ./study
aerosuite import ./old-runs ./old-study   # read existing SU2 case folders into a read-only study
aerosuite summarize ./study    # the Results page's parameters, derived and characteristic values → results/*.csv
```

`aerosuite <command> --help` lists every option. Set `run.sweep_python` (`aerosuite set ./study --sweep-python /path/to/python3`) if the Python that imports SU2 is not the first `python3` on your PATH.

Submitting to Slurm (`--backend slurm`, `--partition`, `resubmit`) is in [docs/CLUSTER.md](docs/CLUSTER.md).

### Over SSH
- From any folder, run `uv run --project /path/to/SU2_aerosuite aerosuite ...`, or add an alias: `alias aerosuite='uv run --project /path/to/SU2_aerosuite aerosuite'`.
- `SU2_RUN` must be set in the shell that runs `aerosuite run`; the sweep inherits it.
- If the sweep dies when you log out, systemd is killing your processes (`KillUserProcesses`); run `loginctl enable-linger $USER` once.
- `aerosuite edit` waits for the editor to exit, so a GUI editor needs its wait flag, e.g. `EDITOR="code --wait"`.

## Future Plans
See [docs/ROADMAP.md](docs/ROADMAP.md). Next:

- **One case on several nodes:** run a case across 2 or 4 identical nodes over InfiniBand, with a scaling test
  that measures how much faster it gets.

## Legacy desktop app (PyQt5)
The original desktop version is still in the repository (`run_aerosuite.py`, `aerosuite/main.py`, `ui/`, `core/`,
`utils/`). New work happens in the web UI and the `aerosuite` command.

```bash
uv run python run_aerosuite.py
alias su2aero2='uv run --project /path/to/SU2_aerosuite python /path/to/SU2_aerosuite/run_aerosuite.py'
```

Its pages follow the same order as the web UI: Calculators, Directory, Mesh, CFG (*Aircraft Aero* or *General*),
Sweep, Control File (scan the configs into `run_control.txt`), Run (launches `aoa_sweep_v8.py` and streams its
output), Monitor (live residuals) and Results (summary CSV and plots). **Profiles → Save / Load SU2 Profile**
(Ctrl+S / Ctrl+O) keeps its settings in a JSON file; the web UI's Profiles page replaces that.

## Contributors
Thanks to the following contributors for their work on this project:
1. Midhun
2. Martino
3. Daniel

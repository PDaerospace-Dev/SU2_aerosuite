# AeroSuite Pro V2

AeroSuite Pro is a desktop application for preparing, running, and reviewing SU2 CFD studies. From mesh loading through config (CFG) generation, parametric sweeps, execution, convergence monitoring, and results analysis.

## Layout

```
+--------------------------------------------------------------------+
| Menu   Toolbar                                      Project Name   |
+---------------+----------------------------------------------------+
| Workflow Tree |                                                    |
|               |                                                    |
| Calculators   |                Content Pane                        |
|  ISA Calc     |         (the page for whatever's selected          |
|  y+ Calc      |          in the tree on the left)                  |
| Project       |                                                    |
|  Directory    |                                                    |
|  Mesh         |                                                    |
|  CFG          |                                                    |
|   Aircraft    |                                                    |
|   General     |                                                    |
|  Sweep        |                                                    |
|  Control File |                                                    |
|  Run          |                                                    |
|  Monitor      |                                                    |
|  Results      |                                                    |
+---------------+----------------------------------------------------+
| Console / Log                                                      |
+--------------------------------------------------------------------+
```
## Workflow
The tree runs top to bottom in execution order:

1. **Calculators**
   - **ISA Calculator** — Standard atmosphere properties at any altitude up to 100 km.
   - **y+ Calculator** — First-cell height for a target y+, feeding into mesh sizing.

*The **"Update SU2 Parameters"** button pushes altitude/temperature/Reynolds straight into the Sweep and CFG pages.*

2. **Directory** — Working directory + output run-folder name. Everything downstream (Mesh, Sweep, Control File) reads its default paths from here.

3. **Mesh** — Load a mesh file. 
For `.su2` meshes, marker tags (e.g. `airfoil`, `farfield`) are auto-extracted and surfaced on the CFG page.

4. **CFG**

   - **Aircraft Aero** (Designed for X07) - Load a `.cfg` template and set freestream, toggle markers, set physical/reference properties and numerics, and generate a single config file. Also includes a live preview of cfg file.

   - **General** — load any `.cfg` file and edit its raw text directly, with the reference panel at the side. 

*Reference- https://github.com/su2code/SU2/blob/master/config_template.cfg (config_template.cfg) for checking or copying marker blocks.*

5. **Sweep** — Load a base `.cfg` file and generate the full Mach × Alpha × Beta parametric sweep from it.

6. **Control File** — Scan a folder of generated `.cfg` files (defaults to the Directory page's working directory) into a per-case restart-configuration table, and write `run_control.txt` from it.
- *Includes a collapsible "What is a control file?" explainer.*

7. **Run** — Launches the sweep script (`aoa_sweep_v8.py` or compatible) as a subprocess and streams its output live.

8. **Monitor** — Live-refreshing residual plots read from SU2 history files.

9. **Results** — Consolidates a batch run's history files into a summary CSV and auto-plots CL/CD/moment.
## Project Structure
```
run_aerosuite.py             Entry point (legacy PyQt5 app)
diagnose.py                  Startup diagnostics
pyproject.toml, uv.lock      Environment (Python 3.12 via uv)
aerosuite/
├── main.py                  Legacy main window
├── engine/                  All logic, no UI imports — the future of AeroSuite
│   ├── models.py            Project model (project.json)
│   ├── project.py           Create / open / save project folders
│   ├── naming.py            Case names <-> Mach/alpha/beta
│   ├── cfg.py               Template rendering, config generation
│   ├── results.py           History reading, convergence, summaries
│   ├── preflight.py         Checks before generate / run
│   ├── atmosphere/          ISA and y+ calculators
│   └── jobs/                Job records, LocalRunner, lock
├── core/                    Legacy API, now delegating to engine/
├── ui/                      Legacy PyQt5 pages (retired in Phase 5)
├── utils/                   Legacy file / validation helpers
└── resources/
    ├── config_template.cfg  Bundled default reference config
    └── aoa_sweep_v8.py      Sweep script (runs under the system Python that imports SU2)
tests/                       pytest suite; tests/fixtures/fake_sweep.py stands in for SU2
docs/superpowers/            Design spec and implementation plans
```
## Installation
AeroSuite runs on **Python 3.12** in its own environment, managed by [uv](https://docs.astral.sh/uv/).
The system Python (3.7.6 on the workstation) is not touched; the sweep script keeps running under it,
because that is the Python that can import SU2.

One-time setup (no admin rights needed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /path/to/SU2_aerosuite
uv sync
```

### Running
```bash
uv run python run_aerosuite.py
```

The **Run** page launches the sweep script under the Python named by `AEROSUITE_SWEEP_PYTHON`
(default: the first `python3` on `PATH` outside AeroSuite's own environment — normally the system
Python that imports SU2). Set it when SU2 lives under a different interpreter:
```bash
export AEROSUITE_SWEEP_PYTHON=/usr/bin/python3
```

On the workstation, point the `su2aero2` alias at the new environment:
```bash
alias su2aero2='uv run --project /path/to/SU2_aerosuite python /path/to/SU2_aerosuite/run_aerosuite.py'
```

### Tests
```bash
uv run pytest
```

## Command line
The same workflow without the GUI — handy over SSH and for scripting (run inside the uv environment, or `uv run aerosuite ...`):

```bash
aerosuite new ./study --template master.cfg --mesh wing.su2
aerosuite set ./study --mach 0.6,0.8,0.85 --alpha=-4:12:2 --beta 0 --partitions 64
aerosuite set ./study --key CFL_NUMBER=5 --key MARKER_PLOTTING=none
aerosuite show ./study
aerosuite edit ./study          # anything else (restart per case, numerics) in $EDITOR
aerosuite generate ./study
aerosuite run ./study           # returns at once; the sweep keeps running after logout
aerosuite status ./study --watch
aerosuite cancel ./study
aerosuite summarize ./study --last 100
```

`aerosuite <command> --help` lists every option. Set `run.sweep_python` (`aerosuite set ./study --sweep-python /path/to/python3`) if the Python that imports SU2 is not the first `python3` on your PATH.

## Typical Workflow
*Calculator*
1. **ISA and Y+ Calculator** — enter altitude and Mach, click Transfer → values land in SU2 tab.

*SU2 Project*
1. Set a project directory and select the mesh.
2. Open **CFG** and complete the **General** or **Aircraft Aero** settings.
3. Generate one or more SU2 configuration files.
4. In **Control File**, scan the configuration folder and write `run_control.txt`.
5. In **Run**, choose the sweep script, configuration directory, and control file; load the plan and run it.
4. **Convergence Monitor** — select a history file while the sweep is running; plot auto-refreshes
5. **Results Analysis** — point at the run directory, select columns, consolidate and plot

## Profile Save / Load
Use **Profiles → Save SU2 Profile** (Ctrl+S) to save all SU2 Generator settings to a JSON file.  
Use **Profiles → Load SU2 Profile** (Ctrl+O) to restore them.

## Future Plans
- 

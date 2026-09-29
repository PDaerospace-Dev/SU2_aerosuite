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

## Web UI
Start it on the workstation (inside the uv environment):

```bash
aerosuite serve --root ~/cfd        # file picker starts in ~/cfd; listens on 127.0.0.1:8080
aerosuite serve --port 8765         # another port, e.g. when 8080 is taken
```

- At the workstation: open http://localhost:8080
- From your own PC: `ssh -L 8080:127.0.0.1:8080 you@workstation`, then open http://localhost:8080 (with `--port`, use that port on the workstation side of `-L`)

Pages:
- **Projects**: recent, open, and **new project**. First choose a *General case* (one config, no sweep) or an *Aircraft study* (pick a profile such as X07; sweep on).
- **Setup**: mesh, template (the chosen files are shown in green, with the mesh's markers; the template is copied into the project under its own name), run settings (MPI partitions; the sweep Python and script are under *Advanced*, which opens by itself when the sweep would run under AeroSuite's own Python). The **aircraft profile** is chosen here, with *Apply profile defaults* and *Save as profile…* (this saves your template, settings, mesh path, sweep and run settings for the next study of that aircraft; *Manage profiles* opens the Profiles page). The **sweep on/off** switch is here too.
- **CFG setup** (general cases): your template in an editor with line numbers (saved a second after you stop typing, when you leave it, or on Ctrl+S). Warnings fold into one row (*3 warnings*); click it to read them. On the right, two tabs: **Preview** (the config a case gets) and **SU2 reference**: search any option, then click *Insert*, or use *Find* in the full file. *Sweep | Single case* at the top switches the sweep on or off, as on Setup; with the sweep off, *Generate configs* is here.
- **Aircraft** (with a profile, in place of CFG setup): the Aircraft Aero form (dropdowns for scheme, MUSCL and turbulence; the four marker lines; placeholders). On the right: **Preview**, **Template** (the template in an editor with line numbers; it saves a second after you stop typing, when you leave it, or on Ctrl+S) and **SU2 reference**. *Sweep | Single case* is at the top; with the sweep off, *Generate configs* is too. **Freestream** starts with the **Mach number**: with the sweep on it shows the Sweep page's Mach values; for a single case you set it here (it is the template's `MACH_NUMBER`). The rest is *Set by hand* (one temperature and Reynolds number for every case) or *From altitude*: give a Reynolds length, and each case gets the ISA temperature of its altitude (0–100 km) and its own Reynolds number from its altitude and Mach. With the sweep on, the altitudes are a list on the Sweep page (shown here); for a single case you set its one altitude here. The Sweep page then shows each case's altitude, temperature and Reynolds number, and each case name carries its altitude label (11 km → `11km`).
- **Sweep** (sweep on): Mach/α/β ranges, naming, restarts, checks, Generate. With the freestream *From altitude*, **Altitudes (km)** sweeps altitude too (`0, 5, 11` or `0:12:3`): each altitude is a block of the whole Mach/α/β sweep, and *Set all → Previous* starts each block fresh. Each case restarts from `none` (a fresh start), `previous` (the case before it) or `custom` (a restart file, or a case folder such as another study's `runs/M0p8_a2_b0/` — the restart file inside is found for you). A `previous` or `custom` case gets `RESTART_SOL= YES` in the job's own copy of its config automatically (a `none` case gets `NO`); the template and `configs/` are left as they are. A `previous` case whose predecessor fails in the same job has nothing to restart from, so it starts fresh instead (the sweep script sets `RESTART_SOL= NO` for it), and the cases after it continue from it.
- **Run**: checks, every case's latest status, and **Submit** for all or selected cases (*Failed*, *Unconverged*, *Not run* select them for you). Click a case's *Failed* status to see why it failed. *Continue from each case's last solution* reruns a case from where it stopped (on by default for unconverged cases). **Cancel** stops a running job. **Job history** is the second tab; each job's *Log* button opens its log. The sweep keeps running when you close the browser or stop the server.
- **Monitor**: pick a case, or **Open file…** any history file, to plot residuals and coefficients against iteration — tick columns on or off, **Normalize**, **Stop**/**Start** live updating. Updates live while the case runs.
- **Log** (the button at the bottom right of every project page, or click *Running 3/32* in the top bar): the sweep's output as it runs, along the bottom of the page. It follows the running job (else the newest); pick any earlier job from its list. Jobs are named by date and minute (`20260928-1358`, then `-2` for a second job in the same minute).
- **Profiles** (Projects page, Setup, or the project menu at the top right): every profile, and what a new study of it starts from: template, mesh, reference dimensions, sweep, partitions. Change them there. The Aircraft form's other values are shown; change those in a study and *Save as profile…* with the same id. Changing a bundled profile (X07) saves your own copy; *Reset to bundled* brings the original back.
- **Calculators** (the *Calculators* button in the top bar, on any page; it opens over the page from the right): **ISA atmosphere** (temperature, pressure, density, viscosity, airspeed, Reynolds number from altitude, Mach and length) and **y+ first cell height** (wall spacing for a target y+, with a note when the Reynolds number is outside the skin-friction formula's range). Inside a project, ISA's *Apply to project* sets an aircraft project's Freestream to *From altitude*, or writes the freestream lines of a single-case general template (at the template's Mach); it lists every change and asks first. *Send to y+* copies the flow into the y+ calculator.

Every field saves as soon as you leave it; invalid values are shown in red and not saved. Results arrive later; until then use `aerosuite summarize`.

The bundled X07 profile has the desktop app's form defaults but no template or mesh. On the workstation, open **Profiles → X07** and set its template, mesh, sweep and partitions there (this saves your own copy of X07); or set up an X07 study and use *Save as profile…* with the id `x07`.

The web UI has no login, so it only listens on the workstation itself unless you pass `--host` together with `--i-understand-no-auth`.

Because the web UI can start and cancel jobs, anyone with an account on the workstation can reach it at 127.0.0.1 while it runs; a login token is planned before AeroSuite is used on a shared machine.

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
aerosuite summarize ./study --last 100
```

`aerosuite <command> --help` lists every option. Set `run.sweep_python` (`aerosuite set ./study --sweep-python /path/to/python3`) if the Python that imports SU2 is not the first `python3` on your PATH.

### Over SSH
- From any folder, run `uv run --project /path/to/SU2_aerosuite aerosuite ...`, or add an alias: `alias aerosuite='uv run --project /path/to/SU2_aerosuite aerosuite'`.
- `SU2_RUN` must be set in the shell that runs `aerosuite run`; the sweep inherits it.
- If the sweep dies when you log out, systemd is killing your processes (`KillUserProcesses`); run `loginctl enable-linger $USER` once.
- `aerosuite edit` waits for the editor to exit, so a GUI editor needs its wait flag, e.g. `EDITOR="code --wait"`.

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

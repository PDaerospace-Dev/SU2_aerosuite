# AeroSuite V4

AeroSuite Pro is a desktop and web application for preparing, running, and reviewing SU2 CFD studies. 
From mesh loading through config (CFG) generation, parametric sweeps, execution, convergence monitoring, and results analysis.

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
Run the following python script in the terminal from the folder
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
su2aero
```

## Web UI
The browser version of AeroSuite: the whole study, from mesh to results, in one place. The **?** in the top bar
opens this guide on the page you are on.

### Getting started
**Once, on the workstation** (inside the uv environment), install it as an always-on service. It starts at boot,
restarts after a crash and keeps running when you log out, so no terminal or tmux is needed:

```bash
uv run aerosuite service install --root /data   # file picker starts in /data; listens on 127.0.0.1:8080
aerosuite service status                        # running? and how to open it
aerosuite service restart                       # after updating AeroSuite; sweeps and Slurm jobs go on
aerosuite service logs                          # its latest output
aerosuite service stop / uninstall
```

It also links `~/.local/bin/aerosuite` to this environment, so `aerosuite` works in any terminal without `uv run`
(a file already there is left alone). It runs through a login shell, so it sees the same PATH and modules as a
terminal. If logging out stops it, lingering could not be enabled for you: ask an admin for
`sudo loginctl enable-linger <user>`.

#### Opening it
| From | How |
|---|---|
| The workstation | http://localhost:8080 |
| Your PC | **Aerosuite Settings → Open from your PC → download the launcher** (`AeroSuite.bat` for Windows, `aerosuite.command` for Mac or Linux), copy it to the PC and double-click it. It opens the SSH tunnel, then AeroSuite in your browser; closing its window disconnects. |
| Your PC, by hand | `ssh -N -L 8080:127.0.0.1:8080 user@workstation`, then http://localhost:8080 |

- Set *SSH address of this machine* on the Settings page first if your PC reaches it by another name (e.g. its
  Tailscale IP). `aerosuite service launcher --for windows -o AeroSuite.bat` writes the same launcher from the
  command line.
- To run it in a terminal instead (it stops with the terminal): `aerosuite serve --root /data` (`--port 8765` when
  8080 is taken). It prints the tunnel command for your PC.

#### No login
The web UI has no login, so it only listens on the workstation itself unless you pass `--host` together with
`--i-understand-no-auth`. Because it can start and cancel jobs, anyone with an account on the workstation can reach
it at 127.0.0.1 while it runs; a login token is planned before AeroSuite is used on a shared machine.

### Finding your way
- **Top bar**: *Projects* (the AeroSuite logo), and in a project the job indicator (*Running 3/32*), **ParaView**,
  **Cluster**, **Calculators**, **↻ Refresh**, **? Help** and the project switcher (recent projects, *All projects*,
  *Profiles*).
- **Sidebar** (in a project): the workflow's steps in order, each with a dot for where it stands. The **«** button
  next to the logo folds it to icons. **Settings** is at its bottom left; on pages without a sidebar it is the
  button in the bottom left corner.
- **Log**: the button at the bottom right of every project page.
- **Saving**: every field saves as soon as you leave it; an invalid value is shown in red and not saved. Editors
  save a second after you stop typing, when you leave them, or on Ctrl+S.
- **Refresh** (↻) rebuilds the page from what is on disk now, as the browser's reload does. A page follows changes
  to the project itself on its own; use it after a change it does not watch, such as a template edited in another
  program.
- **Addresses**: every page names its study in the address (`/run?project=/data/…/study`), so a bookmark opens it
  directly. Some also open a tab: `?tab=solver` on Aircraft, `?tab=board|list|history&case=<name>` on Run.

### Projects
Your recent projects, *Open* (choose or paste a folder), **New project** and **Import SU2 runs**.

- A new project is a **General case** (one config, no sweep) or an **Aircraft study** (pick a profile such as X07;
  the sweep is on).
- **Import SU2 runs** reads runs made outside AeroSuite: see its own section.

### Setup
The study's files and how it runs.

- **Mesh** and **template**: the chosen files are shown in green, with the mesh's markers. The template is copied
  into the project under its own name.
- **Run settings**: MPI partitions. The sweep Python and script are under *Advanced*, which opens by itself when
  the sweep would run under AeroSuite's own Python.
- **Aircraft profile**: chosen here, with *Apply profile defaults* and *Save as profile…* (this saves your template,
  settings, mesh path, sweep and run settings for the next study of that aircraft). *Manage profiles* opens the
  Profiles page.
- The **sweep on/off** switch.

### CFG setup
For general cases: your template in an editor with line numbers.

- Warnings fold into one row (*3 warnings*); click it to read them.
- On the right, two tabs: **Preview** (the config a case gets) and **SU2 reference** (search any option, then click
  *Insert*, or use *Find* in the full file).
- *Sweep | Single case* at the top switches the sweep on or off, as on Setup. With the sweep off, *Generate configs*
  is here, and a **Restart** card under the template sets how the one case starts (see Aircraft → Start).

### Aircraft
For studies with a profile, in place of CFG setup: the study's whole setup on one page.

#### Across the top
- At the top right: *Sweep | Single case*, the problems as badges (*1 error*, *4 warnings*; click one to read them)
  and *Generate configs* (*Generate 20 configs* with the sweep on).
- Under the breadcrumbs, the **case strip**: the case's name (with the sweep on, *20 cases*) and what it runs at
  (Mach, α, β, altitude, Reynolds number, how it starts).

#### Case names
- A single case is named like a sweep case (e.g. `M1p5_0km_a0_b0`), so its cfg, run folder and force breakdown file
  carry that name, and the name follows every change. A general study's single case keeps the project's name.
- Click the name to choose what goes into it (the same options as on the Sweep page): a base name, the altitude
  label (*Set by hand*), and *Name cases with* Mach, altitude, α, β and the base name, e.g. untick β for
  `M1p5_0km_a0`. Each case keeps its restart when its name changes.
- If the template's Mach, AoA or β is edited outside AeroSuite, opening the Aircraft page (or `aerosuite
  generate`/`run`) renames the case; until then Generate refuses, rather than writing configs under the old name.

#### The form's six tabs
- **Flight & air**: Mach, **AoA α** and **sideslip β**. For a single case they are the template's `MACH_NUMBER`,
  `AOA` and `SIDESLIP_ANGLE`; with the sweep on they are the sweep's lists (`0.6, 0.8` or `-4:12:2`), with what they
  make (each altitude and Mach's temperature, pressure, Reynolds number and cases). Then the air:
  - *Set by hand*: one temperature and Reynolds number for every case.
  - *From altitude*: give a Reynolds length, and each case gets the ISA temperature and pressure of its altitude
    (0–100 km) and its own Reynolds number from its altitude and Mach, with either `INIT_OPTION` (`REYNOLDS` or
    `TD_CONDITIONS`). A single case has one altitude; a sweep has a list, and each case name carries its altitude
    label (11 km → `11km`).
- **Solver**: scheme (convective, MUSCL, turbulence), iterations, the CFL number and *Adaptive CFL*. With it on,
  `CFL_ADAPT_PARAM`'s numbers each have a box: factor down, factor up, min and max CFL, and under *More* the linear
  solver tolerance and start iteration. The template's numbers (else SU2's default) show until you change one;
  *Use the template's* goes back.
- **Boundaries**: the mesh's markers, and the `MARKER_` lines (`MARKER_HEATFLUX`, `MARKER_FAR`, `MARKER_PLOTTING`,
  `MARKER_MONITORING` and any other the study sets). Type a value to write the line into every config, leave it
  empty for the template's line, or untick it to remove the line.
- **Reference**: reference length and area, moment origin.
- **Start** (*Restarts* with the sweep on). For a single case: *Fresh start*, or *From a solution*: one of this
  project's runs that left a restart file (newest first, with its outcome), or *Another file or folder…* (a case
  folder is enough; the restart file inside is found). The choice stays when a new Mach, AoA or β renames the case,
  so a Mach 1.5 case can start from the Mach 1.2 run. With the sweep on, the rule every case follows (from scratch,
  from the previous case, from a folder); set a case differently on the Sweep page.
- **Extra options**: any other SU2 option, written into every config (the count is on the tab). *Insert* in the SU2
  reference adds one here (a `MARKER_` option goes to Boundaries).

> To carry on the same case from where it stopped, use *Continue from the last solution* on the Run page.

#### Config and SU2 reference (on the right)
- **Config** opens on *Written lines*: only the lines AeroSuite writes over the template, in config order, coloured
  by where each comes from (the form, the altitude, the boundaries, extra options, the case itself), with what the
  template had (*template: 15.0*). The stretches of template between them fold (*… 41 template lines*). Click a
  line to open the tab that sets it.
- *Whole config* is all of it, editable. Each changed line goes back where it came from: into the template, in
  place, or into the form field or option that writes it (e.g. `REF_AREA`, `CFL_NUMBER`), which the form then
  shows. A line set per case (the sweep's Mach, α and β, the mesh, the breakdown file, the freestream from the
  altitude) goes back as it was, with a note saying where to change it.
- With the sweep on, pick the case to show; edits apply to every case.

### Sweep
With the sweep on: Mach/α/β ranges, naming, restarts, checks, Generate.

- **Altitudes (km)** (with the freestream *From altitude*) sweeps altitude too (`0, 5, 11` or `0:12:3`): each
  altitude is a block of the whole Mach/α/β sweep, and *Set all → Previous* starts each block fresh.
- **Restarts**: each case starts from

  | Restart | Starts from |
  |---|---|
  | `none` | scratch (a fresh start) |
  | `previous` | the case before it |
  | `custom` | a restart file, or a case folder such as another study's `runs/M0p8_a2_b0/` (the restart file inside is found for you) |

- A `previous` or `custom` case gets `RESTART_SOL= YES` in the job's own copy of its config automatically (a `none`
  case gets `NO`); the template and `configs/` are left as they are.
- A `previous` case whose predecessor fails in the same job has nothing to restart from, so it starts fresh instead
  (the sweep script sets `RESTART_SOL= NO` for it), and the cases after it continue from it.

### Checks before a run
*Generate* and *Submit* first put each case's config through SU2 itself: `SU2_CFD -d`, a dry run of SU2's own checks
on a dummy geometry, without loading the mesh (about 2 s per config, up to 8 at once; an unchanged config is not
checked again).

- A config SU2 rejects stops the submit, with SU2's message and where to change it, e.g. *SU2 rejects the config:
  CFL adaption factor down should be less than 1.0. (CFL_ADAPT_PARAM, template line 120)*.
- The Aircraft page's Config tab shows SU2's verdict under the config after each save.
- AeroSuite also checks what the dry run cannot see: a mesh marker with no boundary condition is an error (SU2 stops
  on it when it reads the mesh). It warns of an adaptive CFL whose minimum is above `CFL_NUMBER`, `REF_AREA` /
  `REF_LENGTH` left at 1 in an aircraft study, and a `HISTORY_OUTPUT` without `AERO_COEFF`.
- *Settings → Check each case's config with SU2* turns the SU2 check off; so does
  `aerosuite settings set check_with_su2 false`.

### Run
Submit cases, follow the job, and fix the ones that fail. The sweep keeps running when you close the browser or stop
the server.

#### The job bar
Across the top: the running job (*6 of 20 cases done*, a progress bar, the case running now, elapsed and about how
long is left) with **Monitor**, **Log** and **Cancel**. With none running, how the last one ended (*Done · job
20261024-1151 · 40 cases · 2 converged · 38 unconverged*) with its **Log** and **Job history**.

#### Board, List and Job history
The cases are in three tabs (`?tab=board|list|history` in the address opens one, `&case=<name>` a case's details).

- **Board** (when the cases make a grid): a grid per altitude (and per β when β is swept), Mach down and α across,
  one coloured tile per case: running, queued (with its place, *#3*), converged (*✓ 812 it*), unconverged
  (*1500 it*), failed (*! failed*, red border) or not run. *Large* / *Compact* sizes the tiles (compact from 40
  cases). An altitude folds to one line with its counts, and opens by itself while something runs, waits or failed
  there.
- **List**: the cases by state: *Running now*, *Queued* (with the next one), *Needs a look* (failed first, then
  unconverged and cancelled), *Not run yet* and *Done*, each with *Select all*; a long Queued or Done folds.
- **Job history**: every job, each with a *Log* button for its log.
- Cases a running job still has that the sweep no longer makes (it changed after they were submitted) are on the
  board and in the list too, marked as the job's; they cannot be selected.

#### Choosing cases
- Click a tile for the case's details on the right. Ctrl+click it, or click a row (Mach) or column (α) name, to
  select.
- *Select* above the cases (*Failed*, *Unconverged*, *Not run*, *All*, *None*) picks cases in one click. When
  nothing has run yet every case is selected, else the cases not run yet. A bar under the cases counts the
  selection.

#### On the right: details and Submit
- A case's **details**, when one is clicked: where it stands, its iterations and the Results page's values, its
  Slurm job, why it failed and what to try, what it ran with, **Monitor**, **Continue it**, **Rerun with changes…**,
  *Selected for the next run*, and its earlier attempts.
- **Run N selected cases**: where (this machine or Slurm, partition, tasks), *Continue from each case's last
  solution* (on by default for unconverged cases), the checks, and **Submit**. While a Slurm job runs it is **Add N
  cases to the running job**, on a partition of your choice. Then the cluster or the machine.
- A single case is a card instead.

#### When a case fails
- It says why in words under its name: *Diverged at iteration 592 (SU2 found NaN)*, *SU2 rejected the config: …*,
  *Stopped at the time limit …*, *Ran out of memory*, *SU2 didn't start: …*. The Cluster page, the job log and
  `aerosuite status` give the same reason.
- Its details say what to try, with a button where one helps (open the config, Setup or Settings; continue from its
  last solution after a time limit; Monitor), the residuals before a divergence, and the output's last lines.

#### Rerun with changes
On a failed case, and on an unconverged single case: rerun just that case with, for that job only,

- a CFL (fixed; half the current one after a divergence),
- a first-order start (`MUSCL_FLOW` / `MUSCL_TURB` off),
- a number of iterations,
- *from its last solution* or *from scratch*.

The changes go into that job's own copy of the config, so the template and the other cases stay as they are. The job
log says what the case ran with, and the case shows it (*ran with CFL 0.5 (fixed), first order*) with **Keep**,
which writes those settings into the config (the template, or the form field or placeholder that writes the line).
With a Slurm job running, the rerun is added to it.

> When a case that started from a solution does not finish (failed, cancelled), the solution it started from is kept
> in its job's folder, and *Rerun with changes…* offers it first: a failed second-order continuation can start again
> from the first-order solution. It is deleted once the case finishes with a solution of its own.

#### Earlier attempts
- Before a rerun empties a case's run folder, its run is kept in `attempts/<case>/<n>-<job>/` with its restart
  solution, history, config, surface files and Slurm output (its volume `flow.*` files are dropped when the job
  ends). The last 3 attempts of each case are kept.
- A case with attempts shows *N earlier attempts*: how each ended, what it ran with and its iterations, with
  **Restart from this** (the rerun dialog, starting from that solution) and **Make current** (it becomes the case's
  run again, and the current run an attempt).
- A case a job never reached (cancelled or failed before it started) gets its run back when the job ends.
- Monitor draws the earlier attempts before the current run on one iteration axis, with a dashed line where each
  starts (*Earlier attempts before it*, on by default).

### Monitor
Residuals and coefficients against iteration, live while a case runs.

- Pick a case, or **Open file…** any history file. Tick columns on or off, **Normalize**, and **Stop** / **Start**
  live updating.
- **Parameters** tab: plots of any columns of the history file. *Add plot* lists every column (grouped, with a
  search box); the columns ticked together share one plot, and each plot has its own value axis.
- Zoom a plot with the mouse wheel, drag to move, or use the bar under it. The zoom is kept while new iterations
  arrive; the four-arrows button shows the whole run again.
- The **Values** block on the left gives each plotted column's mean over the last N iterations (N is the box at the
  top right, 100 to start with), with the latest value and the range below it. It works on a case and on an opened
  file.
- The plots and N are kept while the server runs; they are not saved in the project.

### Results
Every case's chosen parameters, averaged over the last N iterations, as plots and tables.

- A strip at the top shows the shown cases' conditions (Mach, altitude, T, α, β, Config) with the case and
  convergence counts. The controls sit in an icon strip at the left (**Designs**, **Filters**, **Params**,
  **Average**, **Packages**), each opening a panel over the plots.
- **Choose parameters…** opens every column the history files hold, searchable and grouped: total coefficients, one
  group per marker (such as `CL(Wing)` or `Avg_Massflow(outlet)`), flow, and, folded, convergence monitors, solver
  and residuals. Convergence is judged on the chosen parameters.
- **+ Derived…** adds, with a live preview,
  - a formula per case: `L/D = CL / CD`, `1 - {Avg_TotalPress(outlet)} / {Avg_TotalPress(inlet)}`, forces with
    `q_inf` and `S_ref`;
  - a *characteristic value* per curve: `slope(CL, Alpha, -2, 6)`, `at(Alpha, CL, 0)`, `max({L/D})`,
    `argmax({L/D}, Alpha)`.
- **Packages** bundle parameters, formulas and plots. *Aerodynamic characteristics* (CL–α, CD–α, CMy–α, CL–CD, L/D,
  CLα, α₀, CD₀, (L/D)max, CMα) switches on by itself when the history has CL, CD and CMy; *Save as package…* keeps
  your own for any study.
- **+ Add plot**: any X (α, Mach, β, altitude or a parameter) against one or more Y. One line per Mach (or whatever
  varies), each in its own colour; unconverged points are hollow; a click on a point opens that case in Monitor.
- **+ Add design…** draws another study over this one (each design one colour).
- **Copy table** pastes into a spreadsheet; **Export CSV** writes `results/summary.csv` and
  `results/characteristics.csv` and downloads the summary.
- Plots, Characteristic values and Results fold; the page remembers everything per study. On Slurm, a **Cost** group
  per case (elapsed, s/iter, peak memory and CPU use) and the study's node-hours are added.

### Import SU2 runs
On the Projects page: read runs made outside AeroSuite, one folder per case with its `.cfg` and history file, also
inside group folders up to four levels down (`st_tail/M0p9_10km/M0p9_10km_a0_b2/`).

- Each case's Mach, α, β and temperature come from its `.cfg` (`MACH_NUMBER`, `AOA`, `SIDESLIP_ANGLE`,
  `FREESTREAM_TEMPERATURE`) and from its folder name, read part by part:

  | Part | Means | Examples |
  |---|---|---|
  | `M…` | Mach | `M2p5` |
  | `…km`, `…m`, `sl` | altitude | `30km`, `11000m`, `sl` |
  | `a…` | α | `a50`, `an4`, `a2p5` |
  | `b…` | β | `b6` |
  | `T…K` | temperature | `T200K` |
  | anything else | the **Config** | `M1p2_10km_vt_a0_b6` → config `vt` |

- Where both give a value the cfg wins. **Scan** lists every disagreement (identical ones grouped) and each
  case-like folder it could not read (empty and unrelated folders are left out).
- Two cases with the same folder name in different groups are named `group/folder` and take the group as their
  Config.
- **Import** creates a read-only study holding only `project.json` (nothing is copied or changed). It shows Results
  and Monitor, and **Rescan** on Results picks up new, removed or changed case folders. On the Results page, Config
  and Temperature filter, tabulate and split lines like the sweep values.

### Profiles
From the Projects page, Setup, or the project switcher: every profile, and what a new study of it starts from
(template, mesh, reference dimensions, sweep, partitions). Change them there.

- The Aircraft form's other values are shown; change those in a study and *Save as profile…* with the same id.
- Changing a bundled profile (X07) saves your own copy; *Reset to bundled* brings the original back.

> The bundled X07 profile has the desktop app's form defaults but no template or mesh. On the workstation, open
> **Profiles → X07** and set its template, mesh, sweep and partitions there (this saves your own copy of X07); or set
> up an X07 study and use *Save as profile…* with the id `x07`.

### Cluster
The **Cluster** button in the top bar, when Slurm is there. Its dot is green, amber for a drained or down node, red
when Slurm does not answer; the number next to it is your running jobs.

- Every node as a compact card.
- **My jobs**: your AeroSuite cases on Slurm from every study (queued, running, or ended in the last 7 days) with
  Cancel (one case), Resubmit and Log. It folds.
- The Run page keeps a one-line summary. How jobs are submitted: the README's *Running on the Slurm cluster*.

### Calculators
The **Calculators** button in the top bar, on any page; it opens over the page from the right.

- **ISA atmosphere**: temperature, pressure, density, viscosity, airspeed and Reynolds number from altitude, Mach and
  length.
- **y+ first cell height**: wall spacing for a target y+, with a note when the Reynolds number is outside the
  skin-friction formula's range.
- Inside a project, ISA's *Apply to project* sets an aircraft project's freestream to *From altitude*, or writes the
  freestream lines of a single-case general template (at the template's Mach). It lists every change and asks
  first. *Send to y+* copies the flow into the y+ calculator.

### ParaView
The **ParaView** button in the top bar of a project lists the cases that have flow files (`.vtu`, `.vtk`, `.vtm` in
the case folder), newest first.

- A case opens its surface and volume files in ParaView on the workstation's screen; *All cases* opens every case's
  surface files in one session.
- From a browser on another PC, a case copies its folder path instead.
- `AEROSUITE_PARAVIEW` names another executable than `paraview`.

### Log
The **Log** button at the bottom right of every project page (or click *Running 3/32* in the top bar): the sweep's
output as it runs, along the bottom of the page.

- It follows the running job (else the newest); pick any earlier job from its list.
- Jobs are named by date and minute (`20260928-1358`, then `-2` for a second job in the same minute).

### Settings
At the bottom left of every page. Server-wide settings, saved for every study; the same as `aerosuite settings`.

- **Execution**: where jobs run by default (this machine with mpirun, or Slurm; each study can choose on its Run
  page), and *Check each case's config with SU2* (see *Checks before a run*).
- **Slurm**: the default partition, one job per node (`--exclusive`), the shared root, module line, SU2 bin folder,
  launch command, job environment, account, default time limit, memory per million cells and the poll interval.
- **Partitions**: each partition's limits, including the memory an `--exclusive` job may use before Slurm kills it,
  and whether to block a submit over it.
- **Job script per partition**: a partition with its own launch command (e.g. `mpirun` on the workstation) gets
  only its own environment.
- **Open from your PC**: the SSH address of this machine, the launchers and the tunnel command (see *Getting
  started*).

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

### Running on the Slurm cluster
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
- Studies must live under the shared root (`/data`): the other node cannot see anything else. Before submitting,
  AeroSuite estimates the memory from the mesh header (`NELEM` × 3.9 GB per million cells, configurable), warns when
  it is over the partition's limit and refuses on partitions set to block (node2).
- The **Cluster** page (top bar; its dot is green, amber for a drained or down node, red when Slurm does not answer)
  shows every node as a compact card, then your AeroSuite cases on Slurm from every study — queued, running or ended in
  the last 7 days — with Cancel (one case), Resubmit and Log; the list folds. The Run page keeps
  a one-line summary. The Results page adds a **Cost** group per case (elapsed, s/iter, peak memory and CPU use from
  `sacct`/`seff`) and the study's node-hours.
- **node0 (hpc0, the Ubuntu workstation)** is a partition like the others, but its job script does not use
  `srun --mpi=pmix` (the nodes have PMIx 4, the workstation PMIx 5). It runs `mpirun --bind-to core -np
  "$SLURM_NTASKS" SU2_CFD <case>.cfg` under plain `#!/bin/bash`, with `PATH=/usr/local/bin:/usr/bin:/bin` and
  `LD_LIBRARY_PATH` unset, no `--exclusive`, and never `--export=NONE` (uid 1000 is `pdas` there and `pdas-hpc1` on
  the nodes). The launch command, module line, PATH, unset variables and job environment are per-partition settings
  (Settings → *Job script per partition*, or `aerosuite settings set slurm.partitions.node0.launch_command ...`); a
  partition whose launch command is empty keeps the Slurm-wide ones. Its reference script is
  `/data/software/templates/su2_job_ws.sh`.
- The local backend (`mpirun` through the sweep script) is unchanged and stays the default.

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

## Contributors
Thanks to the following contributors for their work on this project:
1. Midhun
2. Martino
3. Daniel

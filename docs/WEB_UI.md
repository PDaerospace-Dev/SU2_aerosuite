# AeroSuite web UI guide

AeroSuite runs SU2 studies from your browser: set up a mesh and a config, sweep Mach, α, β and altitude, run the
cases on this machine or on the Slurm cluster, watch them converge and compare the results. The **?** in the top
bar opens this guide on the page you are on; the box above the list searches it.

## Start here

### Getting started
**Open AeroSuite**

| From | How |
|---|---|
| Locally | http://localhost:8080 |
| SSH remote (launcher) | Use the launcher from **Settings → Open from your PC** (`AeroSuite.bat` on Windows, `aerosuite.command` on Mac or Linux). Double-click it: it connects to the workstation and opens AeroSuite in your browser. Closing its window disconnects. |
| SSH remote (command)  | `ssh -N -L 8080:127.0.0.1:8080 user@workstation`, then http://localhost:8080 |

If AeroSuite does not answer at all, it is not running on the workstation: see *Command line → Keep it running*.

**Your first study, in six steps**

1. **Projects → New.** Pick *Aircraft study* (with a profile such as X07) or *General case* (one config).
2. **Setup.** Choose the mesh and the template config.
3. **Aircraft** (or **CFG setup**). Set the flow, solver, boundaries and reference values.
4. **Sweep.** Enter the Mach, α, β and altitude lists, check *What this makes* and *Your choices*, then
   **Generate configs**.
5. **Run.** Choose the cases, where they run and what they start from, then **Submit**.
6. **Monitor** and **Results.** Watch the residuals, then compare coefficients across the cases.

> Everything saves as you go: there is no Save button. You can close the browser while a sweep runs; it keeps going.

### Finding your way
- **Sidebar**: the steps of a study in order (Setup, Aircraft or CFG setup, Sweep, Run, Monitor, Results). The dot
  next to each says where it stands: green done, amber needs a look, blue running, grey not yet. The **«** button
  folds it to icons. **Settings** is at its bottom.
- **Top bar**: the AeroSuite logo goes back to *Projects*. In a project you also see the running job
  (*Running 3/32*, click it for the log), **ParaView**, **Cluster**, **Calculators**, **↻ Refresh**, **? Help** and
  the project switcher (recent projects, *All projects*, *Profiles*). On a narrow window the buttons shrink to icons;
  hover one for its name.
- **Log**: the button at the bottom right of every project page.
- **Saving**: a field saves when you leave it. A value that is not valid turns red and is not saved. Editors save a
  second after you stop typing, when you leave them, or on Ctrl+S.
- **Refresh (↻)** redraws the page from the files on disk. Pages follow changes to the project by themselves; use it
  after changing something outside AeroSuite, such as a template edited in another program.
- **Bookmarks**: every page has the study in its address (`/run?project=/data/…/study`), so a bookmark opens it
  directly. `?tab=solver` opens a tab on Aircraft, `?tab=board|list|history&case=<name>` on Run.

### Frequently Asked Questions (FAQ)
#### Q1. How do I restart cases that failed?
**A.** On **Run**, click **Failed** above the board, choose **Starts from → Each case's own last solution**, open *What
each starts from* to check, then **Submit** (or **Add N cases** while a job runs). A failed case that started from a
solution starts from that same solution again (*kept*).

#### Q2. How do I carry on unconverged cases for more iterations?
**A.** **Run → Unconverged**, then **Starts from → Each case's own last solution** and **Submit**. To give them more
iterations, change *Iterations* on Aircraft → Solver first.

#### Q3. How do I rerun one case with a lower CFL or first order?
**A.** Click its tile on **Run**, then **Rerun with changes…**. The change is for that run only; **Keep** afterwards writes
it into the config. See *Run → Rerun with changes*.

#### Q4. How do I add an altitude or a Mach number?
**A.** Add it to the list on **Sweep**, **Generate configs**, then on **Run** pick **Not run** and **Submit**. The cases
that already ran keep their results.

#### Q5. How do I see where a case stands?
**A.** Click its tile on **Run** for its details, or open **Monitor** for its residuals.

#### Q6. How do I compare cases or export numbers?
**A.** **Results**: plots and tables of the averaged coefficients, **Copy table** for a spreadsheet, **Export CSV**.

#### Q7. How do I look at the flow field?
**A.** **ParaView** in the top bar opens a case's files on the workstation. *Write ASCII from restart…* rebuilds them from
the restart file.

#### Q8. How do I use AeroSuite from my own PC?
**A.** **Settings → Open from your PC → download the launcher**, copy it to your PC and double-click it.

#### Q9. How do I work without the browser?
**A.** Every main step has a command: see *Command line*.

## Your study, step by step

### Projects
Your recent projects, and three tabs: **New** (a new study), **Open** (choose or paste a folder) and **Import SU2
runs**.

- Each recent project shows its kind (*sweep · 40 cases*) and how its latest job is doing: a blue node pill
  (*hpc2*) while a case runs there, a dashed one (*node2 · 20 queued*) where its cases wait, grey once the job has
  ended, *this PC* for a run on the workstation.
- A new project is a **General case** (one config, no sweep) or an **Aircraft study** (pick a profile such as X07;
  the sweep is on).
- **Import SU2 runs** reads runs made outside AeroSuite: see *Import SU2 runs*.

### Setup
The study's files and how it runs.

- **Mesh** and **template**: the chosen files show in green, with the mesh's markers. The template is copied into the
  project under its own name.
- **Run settings**: MPI partitions. The sweep's Python and script are under *Advanced*, which opens by itself when the
  sweep would run with AeroSuite's own Python.
- **Aircraft profile**: pick one, then *Apply profile defaults*, or *Save as profile…* to keep this study's template,
  settings, mesh, sweep and run settings for the next study of that aircraft. *Manage profiles* opens Profiles.
- The **sweep on/off** switch.

### CFG setup
For general cases: your template in an editor with line numbers.

- Warnings fold into one row (*3 warnings*); click it to read them.
- On the right: **Preview** (the config a case gets) and **SU2 reference** (search any option, then *Insert*, or
  *Find* in the full file).
- *Sweep | Single case* at the top switches the sweep on or off. With the sweep off, *Generate configs* is here, and
  the **Restart** card under the template sets how the one case starts.

### Aircraft
For studies with a profile: the whole setup on one page.

**Across the top**: *Sweep | Single case*, the problems as badges (*1 error*, *4 warnings*; click to read them) and
*Generate configs*. Under the breadcrumbs, the **case strip** shows the case's name (with the sweep on, *20 cases*)
and what it runs at.

**The form's tabs**

- **Flight & air**: Mach, **α** and **β**. For a single case they are the template's `MACH_NUMBER`, `AOA` and
  `SIDESLIP_ANGLE`; with the sweep on they are lists (`0.6, 0.8` or `-4:12:2`, meaning from −4 to 12 in steps of 2).
  Then the air:
  - *Set by hand*: one temperature and Reynolds number for every case.
  - *From altitude*: give a Reynolds length, and each case gets the standard-atmosphere (ISA) temperature and
    pressure of its altitude (0–100 km) and its own Reynolds number.
- **Solver**: convective scheme, MUSCL (second order), turbulence model, iterations, CFL and *Adaptive CFL* (its four
  numbers: factor down, factor up, min and max). The template's value shows until you change one; *Use the
  template's* goes back.
- **Boundaries**: the mesh's markers and the `MARKER_` lines. Type a value to write the line into every config, leave
  it empty for the template's line, or untick it to remove the line.
- **Reference**: reference length and area, moment origin.
- **Start** (*Restarts* with the sweep on): *Fresh start*, or *From a solution* (one of this project's runs, or
  *Another file or folder…*; a case folder is enough). With the sweep on, the rule every case follows.
- **Extra options**: any other SU2 option, written into every config.

**Config and SU2 reference (on the right)**

- **Written lines** shows only what AeroSuite writes over the template, coloured by where each line comes from, with
  the template's value next to it. Click a line to open the tab that sets it.
- **Whole config** is all of it, editable. A changed line goes back where it came from: the template, or the form
  field that writes it.
- With the sweep on, pick which case to show; edits apply to every case.

**Case names**: a case is named from its values, e.g. `M1p5_0km_a0_b0` (Mach 1.5, 0 km, α 0, β 0). Click the name to
choose what goes into it: a base name, the altitude label, and Mach, altitude, α, β. Untick β for `M1p5_0km_a0`.

### Sweep
The Mach, α, β (and altitude) lists, what they make, and the restart rule. Two tabs: **Conditions** and **Cases**.

**Conditions**

- **Flight conditions**: one list each, `0.6, 0.8` or `-4:12:2`. With the freestream *From altitude*, **Altitudes
  (km)** sweeps altitude too (`0, 5, 11`).
- **Name cases with**: what goes into the case names.
- **Restarts**: how each case starts. *Every case starts from scratch*, *Each case continues from the previous one*
  (the first of each altitude starts from scratch), or *All continue from a folder of solutions* (e.g. another
  study's `runs/`).
- **What this makes**: the number of cases (*10 cases = 2 Mach × 1 altitude × 5 α × 1 β*), their names, and per Mach
  and altitude the temperature, pressure and Reynolds number.
- **Your choices**: what every case will run with, in one look: mesh, solver, scheme (1st or 2nd order), CFL,
  iterations, freestream, reference values and hand-set keys. Click a tile to open the page that sets it.
  - A blue dot means your project changes that value from the template.
  - An amber tile, and *N changed since the cases last ran* next to the title, means it differs from what the cases
    last ran with. Worth a look before a restart: the restarted cases will run with the new value.
  - The arrow folds the card to one line.

**Cases**: every case and how it restarts. Click **Change** on a case to set it differently from the rule; it is
then marked *differs*. A sweep with many cases folds by Mach and altitude.

> "Previous" follows the case order, which runs across Mach numbers at one altitude: M0.6 α0 continues from M0.3 α20.
> A case whose predecessor fails in the same job starts fresh instead.

### Checks before a run
Before *Generate* and *Submit*, each case's config goes through SU2's own check (`SU2_CFD -d`, a dry run without the
mesh, about 2 s per config).

- A config SU2 rejects stops the submit, with SU2's message and where to change it, e.g. *SU2 rejects the config:
  CFL adaption factor down should be less than 1.0. (CFL_ADAPT_PARAM, template line 120)*.
- AeroSuite also checks what the dry run cannot see: a mesh marker with no boundary condition is an error. It warns of
  an adaptive CFL whose minimum is above `CFL_NUMBER`, `REF_AREA` / `REF_LENGTH` left at 1, and a `HISTORY_OUTPUT`
  without `AERO_COEFF`.
- *Settings → Check each case's config with SU2* turns the SU2 check off.

### Run
Submit cases, follow the job, and fix the ones that fail. A sweep keeps running when you close the browser.

**The job bar** (across the top): the running job with its progress (*6 of 20 cases done*), the case running now,
elapsed time and about how long is left, and **Monitor**, **Log** and **Cancel**. Pills name the nodes its cases run
on; a dashed one shows where cases wait (*hpc1 · 6 queued*). With nothing running, it says how the last job ended.

**The cases**, in tabs:

- **Board**: a grid per altitude, Mach down and α across. Each tile is one case; the coloured dot says how it stands:

  | Dot | Means |
  |---|---|
  | green | converged |
  | amber | unconverged (ran out of iterations) |
  | blue, blue edge | running (iterations so far) |
  | red, red edge | failed (*! failed*) |
  | grey ring, dashed edge | queued (*#3*, its place) or not run yet |

  Tiles are compact at first; the two icons next to the status bar switch to large tiles with the status in words.
  An altitude's heading names its failed cases and folds the grid to one line.
- **List**: the cases by state: *Running now*, *Queued*, *Needs a look* (failed, unconverged, cancelled), *Not run
  yet* and *Done*.
- **Earlier**: cases from earlier sweeps that the sweep no longer makes (e.g. 0 km after the altitudes became 20 km).
  Their results stay in Results and Monitor. **Add to sweep** brings an altitude back.
- **Job history**: every job, each with its log.

The bar above the cases counts every status at a glance; hover a part for its name.

**Choosing cases**

- Click a tile for its details on the right. Ctrl+click (⌘ on a Mac) or Shift+click to select several; click a Mach
  or α heading to select its row or column.
- **Select** picks in one click: *All*, *Failed*, *Unconverged*, *Not run*, *None*.

**Starts from**: one choice for the cases you submit.

| Choice | Each case starts from |
|---|---|
| *As the sweep says* | the Sweep page's restart rule (scratch, the previous case, or a folder) |
| *Each case's own last solution* | its run folder's solution, or, for a case whose run failed, the solution that run started from |
| *From scratch* | no solution, whatever the sweep says |

Under it, **What each starts from** lists every selected case's start; folded it counts them (*6 cases · 6 kept*).
The tags say: *own* (its own last solution), *kept* (the solution a failed run started from), *from case* (another
case's), *after it runs* (a case earlier in this batch), *waits* (a case still running), *scratch*, and *none yet*.
A case with *none yet* has nothing to start from: Submit stays off until you choose another start.

**Submit**: the panel on the right says where the cases run (this machine or Slurm, partition, tasks per case, memory
per case), then **Submit N cases**. While a Slurm job runs it is **Add N cases** to that job, on a partition of your
choice.

**A case's details** (click its tile): where it stands, iterations, its Results values, its Slurm job, what it ran
with, **Monitor**, **Continue it** (from its own last solution), **Run again from where it started** (a failed case
whose run started from a solution), **Rerun with changes…**, and its earlier attempts.

**When a case fails**

- It says why in words: *Diverged at iteration 592 (SU2 found NaN)*, *SU2 rejected the config: …*, *Stopped at the
  time limit*, *Ran out of memory*, *SU2 didn't start: …*.
- Its details say what to try, with a button where one helps, the residuals before a divergence and the output's last
  lines.

**Rerun with changes**: on a failed case (and an unconverged single case), rerun just that case with, for that run
only, a lower CFL (half after a divergence), a first-order start (`MUSCL_FLOW` / `MUSCL_TURB` off), other iterations,
and where it **Starts from** (the same three choices, each naming the solution it means, plus any earlier attempt).
The template and the other cases stay as they are. Afterwards the case shows what it ran with (*ran with CFL 0.5
(fixed), first order*) and **Keep** writes that into the config.

> When a case that started from a solution fails, that solution is kept in its job's folder, so a failed
> second-order restart can start again from the first-order solution. It is deleted once the case finishes with a
> solution of its own.

**Earlier attempts**: before a rerun clears a case's folder, its run is kept in `attempts/<case>/` (the last 3).
A case with attempts lists them, each with **Restart from this** and **Make current**. Monitor draws them before the
current run on one iteration axis.

### Monitor
Residuals and coefficients against iteration, live while a case runs.

- Pick a case (type to search), or **Open file…** any history file. Tick columns on or off, **Normalize**, and
  **Stop** / **Start** live updating.
- **Parameters**: plots of any history columns. *Add plot* lists every column; columns ticked together share a plot.
- Zoom with the mouse wheel, drag to move; the four-arrows button shows the whole run again.
- **Values** on the left: each plotted column's mean over the last N iterations (N at the top right), with the
  latest value and the range.

### Results
Every case's chosen parameters, averaged over the last N iterations, as plots and tables.

- The strip at the top shows the conditions of the cases shown, with how many converged. The icons on the left open
  **Designs**, **Filters**, **Params**, **Average** and **Packages**.
- **Choose parameters…**: every column of the history files, searchable and grouped (totals, per marker such as
  `CL(Wing)`, flow, convergence). Convergence is judged on the chosen parameters.
- **+ Derived…**: a formula per case (`L/D = CL / CD`), or a value per curve (`slope(CL, Alpha, -2, 6)`,
  `max({L/D})`), with a live preview.
- **Packages** bundle parameters, formulas and plots. *Aerodynamic characteristics* (CL–α, CD–α, CMy–α, L/D, CLα,
  CD₀, (L/D)max…) switches on by itself when the history has CL, CD and CMy.
- **+ Add plot**: any X (α, Mach, β, altitude or a parameter) against one or more Y, one line per Mach. Hollow points
  are unconverged; click a point to open that case in Monitor.
- **+ Add design…** draws another study over this one.
- **Copy table** pastes into a spreadsheet; **Export CSV** writes `results/summary.csv` and downloads it.

## More tools

### Import SU2 runs
On Projects: read runs made outside AeroSuite (one folder per case with its `.cfg` and history), also inside group
folders up to four levels down.

- Mach, α, β and temperature come from the `.cfg` and from the folder name, part by part:

  | Part | Means | Examples |
  |---|---|---|
  | `M…` | Mach | `M2p5` |
  | `…km`, `…m`, `sl` | altitude | `30km`, `11000m`, `sl` |
  | `a…` | α | `a50`, `an4` (−4), `a2p5` |
  | `b…` | β | `b6` |
  | `T…K` | temperature | `T200K` |
  | anything else | the **Config** | `M1p2_10km_vt_a0_b6` → config `vt` |

- Where both give a value, the cfg wins. **Scan** lists every disagreement and each folder it could not read.
- **Import** makes a read-only study (only `project.json`; nothing is copied or changed) with Results and Monitor.
  **Rescan** on Results picks up new or changed folders.

### Profiles
What a new study of an aircraft starts from: template, mesh, reference values, sweep and partitions.

- Change a bundled profile (X07) and your own copy is saved; *Reset to bundled* brings the original back.
- From a study, *Save as profile…* (on Setup) keeps its whole setup.

> The bundled X07 profile has no template or mesh. Set them once in **Profiles → X07**.

### Cluster
The **Cluster** button in the top bar, when Slurm is there. Its dot is green, amber when a node is drained or down,
red when Slurm does not answer; the number is your running jobs.

- **Tiles**: studies running and where, studies queued, cases still to go, CPUs in use, nodes up.
- **A card per node**: CPU, memory and load, its state in words (*Full*, *Partly used*, *Free*, *Drained*), the study
  jobs running there and those queued next, with about when they start. Click a line for that study's Run page;
  drag a card to reorder.
- **My jobs**: your AeroSuite cases on Slurm from every study (last 7 days), with **Cancel**, **Resubmit** and **Log**,
  grouped by job.

### Calculators
The **Calculators** button in the top bar opens over any page.

- **ISA atmosphere**: temperature, pressure, density, viscosity, speed and Reynolds number from altitude, Mach and
  length. In a project, *Apply to project* sets the freestream (it lists every change and asks first).
- **y+ first cell height**: the wall spacing for a target y+. *Send to y+* copies the flow from ISA.

### ParaView
The **ParaView** button lists the cases with flow files (`.vtu`, `.vtk`, `.vtm`), newest first.

- Click a case to open its surface and volume files in ParaView on the workstation; *All cases* opens every case's
  surface. From another PC, it copies the folder path instead.
- **Write ASCII from restart…** rebuilds a case's `flow.vtk` and `surface_flow.vtk` from its restart file with
  SU2_SOL: handy when the sweep writes binary `.vtu` or no volume file. On Slurm it runs as a short job (its output in
  `to_ascii-<job id>.out`). A case still running is refused.

### Log
The **Log** button at the bottom right of every project page (or click *Running 3/32* in the top bar) shows the
sweep's output along the bottom of the page. It follows the running job; pick an earlier job from its list. Jobs are
named by date and minute (`20260928-1358`).

### Settings
Server-wide settings, for every study. Hover a field's ⓘ for what it does.

- **General**: where jobs run by default (this machine or Slurm; a study can choose on its Run page) and *Check each
  case's config with SU2*.
- **Slurm**: the default partition, shared folder, account, time limit, the job script (modules, SU2 folder, launch
  command) and polling.
- **Partitions**: a card per partition with its tasks per case and memory limit. Click one for all its settings,
  including its own launch command and job script.
- **Open from your PC**: this machine's SSH address, the launchers and the tunnel command.

## Reference

### Command line
Everything the main steps do can also be done in a terminal on the workstation, e.g. in a script. Each command takes
the study's folder; add `--help` to any command for all its options.

**Keep it running** (once, on the workstation)

```
uv run aerosuite service install --root /data   # start it, now and at every boot
aerosuite service status                        # running? how to open it
aerosuite service restart                       # after an update; jobs go on
aerosuite service logs -n 100                   # its latest output
aerosuite service stop                          # until the next restart or boot
aerosuite service uninstall
aerosuite service launcher --for windows -o AeroSuite.bat   # --for mac too
```

`service install` also links `~/.local/bin/aerosuite`, so `aerosuite` works in any terminal without `uv run`. If it
stops when you log out, ask an admin for `sudo loginctl enable-linger <user>`. To run it in a terminal instead (it
stops with the terminal): `aerosuite serve --root /data` (`--port 8765` when 8080 is taken).

**A study from start to results**

```
aerosuite new /data/me/wing --template wing.cfg --mesh wing.su2
aerosuite set /data/me/wing --mach 0.6,0.8 --alpha -4:12:2 --beta 0
aerosuite set /data/me/wing --freestream altitude --altitude-km 0,5,11 --reynolds-length 2.49
aerosuite set /data/me/wing --key CFL_NUMBER=2 --key ITER=1500
aerosuite generate /data/me/wing
aerosuite run /data/me/wing --backend slurm --partition node2
aerosuite status /data/me/wing --watch
aerosuite summarize /data/me/wing --last 200
```

| Command | Does |
|---|---|
| `new DIR` | Make a study folder (`--template`, `--mesh`, `--name`) |
| `show DIR` | Print its settings, sweep and cases |
| `set DIR` | Change the sweep (`--mach`, `--alpha`, `--beta`, `--altitude-km`), files (`--template`, `--mesh`), freestream, or any SU2 option (`--key KEY=VALUE`; `--unset KEY` goes back to the template's) |
| `edit DIR` | Edit `project.json` in your editor; saved only if valid |
| `generate DIR` | Check the study, then write the configs |
| `run DIR` | Start the sweep: `--backend local` (this machine) or `slurm`; `--partition`, `--ntasks`, `--time 12:00:00`; `--case NAME` (repeatable) for some cases; `--add` to add them to the running Slurm job |
| `status DIR` | The latest job and each case's state (`--watch` to follow it) |
| `cancel DIR [JOB]` | Stop the running job (`--case NAME` on Slurm stops just that case) |
| `resubmit DIR [CASES]` | Submit again the cases that ended NODE_FAIL or OUT_OF_MEMORY (`--partition`, `--ntasks`) |
| `summarize DIR` | Average each case's history into `results/summary.csv` and print it (`--last N`, `--columns CL,CD`) |
| `import SOURCE DIR` | Make a read-only study from existing SU2 runs |
| `settings` | Print the server-wide settings |
| `settings set KEY VALUE` | Change one, e.g. `backend slurm`, `check_with_su2 false`, `slurm.partitions.node2.default_ntasks 48` |

> The web UI and the command line share the same files: a study set up in one opens in the other, and a job started
> from the terminal shows on the Run page.

### Troubleshooting
| You see | Try |
|---|---|
| The page does not open | Is AeroSuite running? `aerosuite service status` on the workstation. From a PC, is the launcher's window open? |
| *SU2 rejects the config* | The message names the option and the template line: fix it on Aircraft or CFG setup. |
| *Diverged at iteration …* | **Rerun with changes…** with a lower CFL and a first-order start, then continue at second order from that solution. |
| *Stopped at the time limit* | **Continue it**: the case starts from its last solution. Raise the limit in Settings → Slurm. |
| *Ran out of memory* | Pick a partition with more memory per case, or fewer tasks per node. **Resubmit** on Cluster → My jobs. |
| A restart has *none yet* | That case has no solution: choose *As the sweep says* or *From scratch* for it. |
| Restarted cases behave differently | Look at **Sweep → Your choices** for amber tiles: something changed since they last ran. |
| A page looks out of date | **↻ Refresh** in the top bar. |
| Slurm does not answer | The Cluster dot is red: wait a moment, or ask the cluster admin. Running jobs go on. |

### Words used here
- **Study / project**: one folder with `project.json`, the template, `configs/`, `runs/` and `jobs/`.
- **Case**: one SU2 run at one Mach, α, β and altitude, in `runs/<case>/`.
- **Sweep**: every combination of the Mach, α, β and altitude lists.
- **Job**: one submit of some cases. On Slurm, each case is a batch job of its own.
- **Template**: your SU2 config; each case's config is the template with its own values written in.
- **Restart / solution**: SU2's restart file a case can start from instead of a fresh flow.
- **Converged / unconverged**: the chosen coefficients settled / the case ran all its iterations without settling.
- **Partition**: a group of cluster nodes, e.g. `node2`.

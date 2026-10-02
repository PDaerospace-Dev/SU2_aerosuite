# Handover: continuing AeroSuite on the workstation

Started 2026-09-28 when development moved from the Windows dev PC to the Linux workstation; last updated
2026-09-30. It holds what the code and git history do not: the machine setup, where the branch stands, the
decisions taken along the way and what is still open. Read it first in a new session; keep it current or fold it
into a CLAUDE.md.

## The workstation

- `pdas@pdas-Super-Server`, Ubuntu (glibc 2.39), 64 cores; on the user's Tailscale network as
  `pdas-super-server` / `100.111.93.91`. Other machines share that network, so the web UI stays on 127.0.0.1.
- `python3` is conda base **Python 3.7.6**, which imports SU2 (`SU2_RUN=/usr/local/bin`, `PYTHONPATH` set in
  `~/.bashrc`, interactive shells only). SU2's QuickStart case is in `~/SU2/QuickStart` (useful for real runs).
- AeroSuite runs in its own **uv-managed Python 3.12** environment (`uv sync`, then `uv run …`). The sweep
  script `aerosuite/resources/aoa_sweep_v8.py` must keep running under conda 3.7.6: keep it Python 3.7
  compatible and never resolve the sweep interpreter inside AeroSuite's venv (`AEROSUITE_SWEEP_PYTHON`, or
  *Setup → Advanced → Python for the sweep script*).
- **Starting the web UI:** `aeroweb` (a function in `~/.bash_aliases`) runs `aerosuite serve` from any folder with
  the conda sweep Python set; port 8080 on 127.0.0.1. Inside `tmux new -s aero` it survives logging out.
- **From the Windows PC:** an SSH tunnel with Windows' own OpenSSH, `ssh -N -L 8080:127.0.0.1:8080
  pdas@100.111.93.91` (the user has an `AeroSuite.bat` for it), then http://localhost:8080. The user stopped
  using MobaXterm. The Claude app opens a short SSH connection per operation; with a passphrase key it asks each
  time unless the Windows `ssh-agent` service runs and the key is added (`ssh-add`) — advised, not confirmed.
- User profiles in `~/.aerosuite/profiles/`, user packages in `~/.aerosuite/packages/` (`AEROSUITE_HOME`
  overrides; the tests do).
- No GitHub login is stored for git and `gh` is not installed: **the user pushes** (`git push origin
  feat/web-ui-refresh`) and opens pull requests in the browser.

## How the user works

- The user maintains the code; Claude writes most of it. Work goes phase by phase with approval gates: propose
  (with screenshots of a working prototype when it is UI: the user asks "show screenshots"), get a yes, write a
  spec and plan in `docs/superpowers/`, then build test-first in small commits.
- The user tests on the workstation with real data and sends back comments. Answer each with an opinion and a
  recommendation first; ask only where the choice is theirs.
- Commit as part of an agreed batch; push only when asked (and the user does the push, see above).
- The user writes briefly and wants short, plain summaries with what to try next.
- Studies are not only external aerodynamics (ducts, internal flow): nothing may assume CL/CD exist.

## Branch

Everything is on **`feat/web-ui-refresh`**, stacked on `feat/engine-phase-0-1` → `feat/cli-phase-2` →
`feat/web-phase-3a` → `feat/web-run-monitor`. `origin/main` was merged into it on 2026-09-29 (`3417955`: main's
V3 README; its committed `.pyc` files and `aerosuite.egg-info/` were then removed, `8532620`). The user chose a
**pull request into `main`**: https://github.com/PDaerospace-Dev/SU2_aerosuite/compare/main...feat/web-ui-refresh
— not opened yet as far as this session knows. On 2026-09-30 the branch was **22 commits ahead** of the copy of
it GitHub last showed this workstation; the user needs to push before the PR shows them.

Specs and plans per phase: `docs/superpowers/specs/`, `docs/superpowers/plans/`; architecture:
`docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md`.

## What exists (short)

- `aerosuite/engine/`: all logic, no UI imports. Projects (`project.json`, **schema 7**), config generation,
  sweeps (Mach, α, β, altitude) and naming, restarts, profiles, ISA / y+, job running (`jobs/`: LocalRunner
  through `sweep_wrapper.py`, job records `jobs/<id>.json`, logs, per-job configs), results (`results.py`,
  `study_results.py`, `formula.py`, `packages.py`) and imported runs (`imported.py`).
- `aerosuite/cli/`: `aerosuite new/show/set/edit/generate/run/status/cancel/summarize/serve/import`.
- `aerosuite/web/`: the NiceGUI web UI. Pages: Projects (open, **Import SU2 runs**, new), Profiles, Setup, CFG setup
  (general cases) or Aircraft (aircraft studies), Sweep, Run, Monitor, **Results**, Calculators (also a panel
  from the right). A log panel opens from the bottom of project pages. Look in `theme.py`, building blocks in
  `ui_kit.py`; NiceGUI-free rules beside the pages (`results_view.py`, `results_charts.py`, `calculators/*_rules.py`).
- The legacy PyQt5 app (`aerosuite/main.py`, `ui/`, `core/`) still runs (`uv run python run_aerosuite.py`); it
  is retired in a later phase.
- Tests: `uv run pytest -q -p no:cacheprovider` — **955 passed, 1 Windows-only skip** (2026-10-02, ~4 min; up to
  7 min when the workstation is busy with other jobs). Web tests use NiceGUI's simulated user;
  `tests/fixtures/fake_sweep.py` stands in for SU2. A fake sweep still running when its test ends fails that
  test (see the working notes).

## Checked on the workstation

- Rounds one and two of the user's feedback (2026-09-28), the altitude sweep: the user confirmed them.
- With real SU2 (QuickStart NACA 0012, 2 ranks), by Claude: the sweep's exit code (a killed sweep fails the case it
  was running, "killed by signal 9"); Cancel from the Run page ("Cancelling…", other pages answer within 0.35 s,
  nothing left running).
- In headless Chrome, by Claude: the line-numbered template editor (saving after a pause, on Ctrl+S, on leaving),
  folded warnings, the Freestream card, the Results page on demo data, an imported demo folder. Still for the user:
  clicking into the editor's text with the mouse in a real window.

## Not yet checked by the user

- **Results page** (spec `2026-09-29-results-design.md`, commits `e31a474`..`5214edd`): open Results on a finished
  real study, choose parameters (the picker), add a derived value (e.g. `CL / CD`, or a force with `q_inf * S_ref`)
  and a plot, compare a second study (+ Add design), Copy table, Export CSV, Save as package.
- **Import SU2 runs** (spec `2026-09-30-import-runs-design.md`, commits `af6a0c9`..`ab1288e`): import a real folder
  of old runs (Projects page card, or `aerosuite import`), check the scan's values and warnings, look at it on
  Results and Monitor, Rescan after adding a folder.

- **Cancel right after Run on a real job** (fix `d9ffccb`, 2026-10-02): press Cancel within a second of Submit
  and check with `ps` that no `mpirun` / `SU2_CFD` is left. Tested only on Linux with the fake sweep, not with
  real `mpirun` and not on Windows.

- **ParaView menu in the top bar** (2026-10-02; `engine/paraview.py`, `web/paraview_menu.py`): on the workstation's
  own browser, open a case and *All cases* and check ParaView really starts and shows the files. Only the menu
  and the "No display" error were seen for real (the server was started from a shell without a desktop session);
  the launch itself is tested with `Popen` replaced. From another PC a case copies its folder path instead.

## Decisions worth knowing

- No login in the web UI (spec §7 known risk); it listens on 127.0.0.1 unless `--host … --i-understand-no-auth`.
  Keep it behind the SSH tunnel: the Tailscale network is shared.
- ISA uses the US76/SU2 Sutherland constants (viscosity and Reynolds number ~4% off the old PyQt app, which was
  wrong).
- Altitude sweeps only in *From altitude* mode; a sweep's altitudes are `sweep.altitudes_km`, a single case's is
  `freestream.altitude_km`; neither is copied into the other.
- Restart options are only `none` / `previous` / `custom`; each job's own cfg copy gets `RESTART_SOL`; the
  template and `configs/` are never changed by a run.
- The bundled `resources/config_template.cfg` is SU2's original reference setup: never edit it.
- Jobs run through `engine/jobs/sweep_wrapper.py` (AeroSuite's Python, `-I`), which records the exit code in
  `jobs/<id>.exit` (kept as `exit_code`); the web cancels in a worker thread (`run.io_bound`).
- `store.kill_tree` **suspends each process before listing its children**, then terminates and resumes it
  (2026-10-02). Listing first and signalling after let a child started in between live on with no parent: a
  Cancel right after Run killed the wrapper and left the sweep (SU2) running. Keep that order.
- **Results:** parameters are history columns (grouped from SU2 names in `results.group_of`), chosen per study
  (`project.results`; `None` = not chosen yet, `[]` = cleared on purpose). Derived values and characteristic values
  are formulas read by `engine/formula.py` (an `ast` reader with an allowed list; **never `eval`**); derived values
  use averaged values (ratio of averages); a characteristic value's curve runs along its curve function's X (α by
  default). Convergence is judged on the chosen history parameters (none → "not judged"). Packages combine at read
  time (`packages.effective`), so switching one off removes what it brought; the bundled *aero* package
  (`resources/packages/aero.json`) switches on by itself when the history has CL, CD and CMy. Compared studies are
  read with the current study's definitions.
- **Imported runs:** one folder per case (`.cfg` + history), found up to 4 levels down (group folders; study and
  hidden folders left out; only case-like folders reported as skipped); clashing folder names → `group/folder`,
  Config = group;
  values from the cfg (`MACH_NUMBER`, `AOA`, `SIDESLIP_ANGLE`, `FREESTREAM_TEMPERATURE`), else the folder name read
  part by part (`M2p5`, `30km`/`11000m`/`sl`, `a50`/`an4`/`a5m`, `b6`, `T200K`, the rest = Config). **The cfg wins**;
  identical disagreements are grouped. The study holds only `project.json` and never writes the source; it shows
  only Results and Monitor. Reading only: re-running imported cases was deferred by the user.
- **Layouts (2026-09-30, user's choices):** Results = conditions strip + icon strip whose panels open over
  full-width plots ("F"; no hover box, no per-case list); with one study each plot line has its own colour.
  Projects = recent list with a filter + one card with New / Open / Import tabs ("B"). Mockups in
  `docs/superpowers/specs/assets/2026-09-30-layout/`.
- **Run page (2026-10-02, the user's choice "B"):** cases on the left by study size (`web/run_view.py`: a case
  card for one case, a plain list, or the list folded by Mach and altitude from 13 cases with more than one group),
  a panel on the right that stays in view: ticked cases, cores per case, Submit — or the running job with elapsed
  and a rough time left, Cancel — then checks (warnings folded), the machine (`engine/machine.py`: cores, free now,
  memory, who uses the cores) and the last job. No small convergence plot on the case card (Monitor link instead).
- **Setup and Sweep (2026-10-02, the user's choices "A" and "D"):** Setup is four steps in one card (the path box
  opens with Change…) and a panel with the project, what is ready and the next page. Sweep has two tabs: Conditions
  (lists shown as `from:to:step` when evenly spaced, one restart rule, "What this makes") and Cases (restart in
  words, Change per row, folded by Mach and altitude from 13 cases). The restart rule is not stored: it is the one
  the most cases follow (`web/sweep_view.detect_rule`), the others are "set differently"; choosing a rule sets
  every case. Aircraft cards fold (`ui_kit.fold_button`, remembered while the server runs).
- On the Results page **Config** (a label: filters, columns, splits lines, never an X axis) and **Temperature** (a
  number) are case variables for every study. A variable fixed by the other splitting ones does not split lines.

- Sweep input is bounded and checked (2026-10-02, after a review of the whole web UI): a value list takes at most
  1000 finite numbers (`editing.MAX_LIST_VALUES`), a sweep makes at most 10000 cases (`cfg.MAX_CASES`), and the
  base name and altitude label can only use letters, digits, `.`, `-` and `_` (they become file names;
  `naming.name_part_problem`). A project.json that already holds an unsafe case name gets a Sweep error.
  Setup's "Apply profile defaults" saves the template's new name and redraws the page.

- Monitor follows the running job to its next case ("Follow the running case", on unless the link names a case;
  picking a case or opening a file switches it off). The status is the pill only; the line beside it is case and job.
- Hover texts are set with `ui_kit.titled`, never as a `title="…"` props string (a double quote in the text broke it).

- Monitor has two tabs (2026-10-02; mock and screenshots in `specs/assets/2026-10-02-monitor-parameters/`).
  *Parameters* (`web/monitor_params.py`): plots of any history columns, one value axis per plot, each zoomed on its
  own (the zoom is held server-side per page as iterations, `Window`, and re-applied at every update: a window that
  ends on the newest iteration follows it). The *Values* block shows the mean of the last N iterations in bold with
  the latest value and range below. By the user's choice: plots and N live in `monitor_params._STATES` (per project,
  while the server runs), not in project.json; no Normalize on this tab; no shading or mean line on the plots.

## Open items and next steps

Next, in the order recommended to the user on 2026-09-30:

1. The user checks Results and Import on real data (above) and sends comments.
2. The user pushes and opens the PR into `main`.
3. Candidate features the user has mentioned or been offered: re-running imported cases (deferred); experimental
   or reference data from a CSV as a Results overlay; a PDF report of the plots and tables; recording more per
   imported case (mesh, other cfg values); retiring the PyQt5 app.

Known smaller items (from reviews; none blocking):

- `BREAKDOWN_FILENAME` is relative (files land in `runs/`); an all-NaN history column counts as converged;
  `write_lock` creates the file before writing it.
- CLI `show`/`set` don't surface the profile or sweep-off state of AeroSuite studies.
- AeroSuite studies in altitude mode do not record each case's temperature in `cases.json`, so their Results page
  has no Temperature column (imported studies do).
- With many unrelated sweeps in one study (e.g. an imported folder mixing a β sweep and an α sweep), plots get many
  single-point lines and a paged legend; filters help.
- On Windows the test `test_losing_the_lock_race_leaves_nothing_behind` flaked once (before the `kill_tree` fix
  of 2026-10-02, which may have been the cause; not rerun on Windows since).
- `kill_tree` can still miss a child that a process starts from its own SIGTERM handler after it is resumed.

## Working notes for Claude

- NiceGUI 3.17: `refreshable.refresh()` is fire-and-forget, so pages that tests read right after a change rebuild
  synchronously (`box.clear()` then redraw) instead.
- Tests that open dialogs must `await user.should_see(marker=…)` before clicking inside them.
- `ui.navigate.to` called while a page is being built never reaches a real browser (the simulated user does get
  it): issue it from `ui.timer(0, …, once=True)`.
- NiceGUI's simulated `ui.download.file(path)` fetches the path as a URL; use `ui.download.content(bytes, name)`
  and check it with `await user.download.next()`.
- Checking in a real browser: headless Chrome's `--screenshot` flag can capture a page before a client-side
  navigation; drive Chrome over the DevTools protocol instead (a script with `websockets` + `httpx`, both in the
  venv) and read `location.pathname`. The Claude-in-Chrome extension was not connected in this setup.
- A test server for screenshots on port 8093 (`uv run aerosuite serve --port 8093 --root <scratch>`) keeps port
  8080 free for the user's own `aeroweb`.
- **Leaked fake sweeps:** `ready_project` kills the jobs in the project's records, then any `fake_sweep.py`
  whose command line is under the test's temp folder, and fails the test if it found one; a session fixture
  (`no_fake_sweep_outlives_the_session` in `tests/conftest.py`) does the same for the session's temp folder.
  Other pytest sessions' sweeps are never touched. `ps -eo pid,etimes,args | grep "fixtures/fake_swee[p].py"`
  should print nothing when no suite is running (57 left by earlier runs were killed on 2026-10-02). Such a
  failure means a kill or cancel missed a process: look at the engine, not at the fixture.
- The workstation is shared and often busy (load ~60): the suite's time varies; don't read slowness as a bug
  without checking `uptime`.

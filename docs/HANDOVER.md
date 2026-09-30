# Handover: continuing AeroSuite on the workstation

Written 2026-09-28 when development moved from the Windows dev PC to the Linux workstation. It holds
what the code and git history do not: the machine setup, where each branch stands, the decisions taken
along the way and what is still open. Read it first in a new session; keep it current or fold it into
a CLAUDE.md.

## The workstation

- `pdas@pdas-Super-Server`, Ubuntu (glibc 2.39).
- `python3` is conda base **Python 3.7.6**, which imports SU2; `SU2_RUN=/usr/local/bin`.
- AeroSuite itself runs in its own **uv-managed Python 3.12** environment (`uv sync`, then `uv run …`).
  The sweep script `aerosuite/resources/aoa_sweep_v8.py` must keep running under the conda 3.7.6
  interpreter: keep it Python 3.7 compatible, and never resolve the sweep interpreter inside
  AeroSuite's own venv. Set `export AEROSUITE_SWEEP_PYTHON="$(which python3)"` in a shell where conda
  base is active, or set *Setup → Advanced → Python for the sweep script*.
- The user reaches it from Windows with MobaXterm. The web UI (`uv run aerosuite serve`; `--root` only sets where the
  file picker starts, default home)
  listens on 127.0.0.1:8080 only; from the PC it needs an SSH tunnel
  (`ssh -L 8080:127.0.0.1:8080 pdas@<workstation>`, or MobaXterm's Tunneling tool), then
  http://localhost:8080.
- `aeroweb` (a function in `~/.bash_aliases`) starts the web UI from any folder with the conda sweep
  Python set; the user reaches it through a saved MobaXterm tunnel on port 8080.
- User profiles live in `~/.aerosuite/profiles/` (override with `AEROSUITE_HOME`; the tests do).

## How the user works

- The user maintains the code; Claude writes most of it. Work goes phase by phase with approval
  gates: propose, get a yes, then build test-first, commit in small logical commits.
- The user tests on the workstation with real meshes and templates and sends back a list of comments.
  Answer each with an opinion and a recommendation first; ask only where the choice is theirs.
- Only commit when asked or as part of an agreed batch; push only when asked.
- The user writes briefly; they appreciate short, plain summaries with what to try next.

## Branches

All work is stacked, newest last; none is merged into `main`:

`feat/engine-phase-0-1` → `feat/cli-phase-2` → `feat/web-phase-3a` → `feat/web-run-monitor` →
**`feat/web-ui-refresh`** (current; contains everything below).

The user decided to keep the branches as they are for now; the merge into `main` is still to be
decided. Specs and implementation plans for each phase are in `docs/superpowers/specs/` and
`docs/superpowers/plans/`; the architecture is in
`docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md`.

## What exists (short)

- `aerosuite/engine/`: all logic, no UI imports. Projects (`project.json`, schema 4), config
  generation, sweeps and naming, restarts, profiles, ISA / y+, job running (`jobs/`: LocalRunner,
  job records in `jobs/<id>.json`, log `jobs/<id>.log`, per-job configs in `jobs/<id>/configs`).
- `aerosuite/cli/`: `aerosuite new/show/set/edit/generate/run/status/cancel/summarize/serve`.
- `aerosuite/web/`: the NiceGUI web UI. Pages: Projects, Profiles, Setup, CFG setup (general cases),
  Aircraft (aircraft studies; has Preview | Template | SU2 reference tabs), Sweep, Run (Cases | Job
  history tabs), Monitor, Calculators (also a panel from the right on every page). A log panel opens
  from the bottom of every project page. Look lives in `theme.py`; building blocks in `ui_kit.py`.
- The legacy PyQt5 app (`aerosuite/main.py`, `ui/`, `core/`) still runs (`uv run python
  run_aerosuite.py`); it is retired in a later phase.
- Tests: `uv run pytest` (918 passing, 1 Windows-only skip, on the workstation 2026-09-29). Web tests use NiceGUI's simulated
  user; `tests/fixtures/fake_sweep.py` stands in for SU2; `tests/engine/test_sweep_script.py` runs the
  real sweep script against a stand-in `SU2` package.

## Workstation feedback already done

First round (2026-09-28): the restart fix in `aoa_sweep_v8.py` (a `previous` case after a failed one
starts fresh with `RESTART_SOL= NO`), Setup highlights the chosen mesh/template, partitions first with
the rest under Advanced, Mach in Freestream, Preview/Reference tabs, sweep switch on the config page,
no Configs step, collapsible failure details on Run. The user confirmed all of it works.

Second round (2026-09-28, commits `e5299a0`..`414b14e`; the user confirmed it all works on the workstation
2026-09-29):

- the template copy keeps its file name; the previous copy is removed;
- job names are `YYYYMMDD-HHMM` (then `-2`, `-3` in the same minute). Because names are unique only
  within a project, `LocalRunner` keys its caches by (project folder, job id);
- Config page renamed **CFG setup**; aircraft studies don't show it (Aircraft has a Template tab,
  the sweep switch and Generate);
- log panel at the bottom (Log button; the top bar's "Running 3/32" opens it); Run's Job history tab;
- Calculators as a panel from the right;
- profiles also store the mesh path, sweep and run settings; `/profiles` page to edit them (editing
  a bundled profile saves the user's copy; Reset restores the bundled one).

Altitude sweep (2026-09-29, commit `4326026`, spec `docs/superpowers/specs/2026-09-29-altitude-sweep-design.md`;
the user confirmed it works on the workstation 2026-09-29): in *From altitude* mode the Sweep page has an
**Altitudes (km)** list next to Mach, α, β; altitude is the outermost loop; each case gets its own label,
temperature and Reynolds number; Set all → Previous starts each altitude block fresh; schema 5 moves the one
altitude into the list. A single case keeps one altitude on the Aircraft page.

## Decisions worth knowing

- No login/token in the web UI yet (spec §7 known risk); it listens on 127.0.0.1 unless
  `--host … --i-understand-no-auth`.
- ISA uses the US76/SU2 Sutherland constants, so its viscosity and Reynolds number differ ~4% from the
  old PyQt app (the old app was wrong).
- Altitude sweeps only in *From altitude* mode (in *Set by hand* the altitude is just a name label). A sweep's
  altitudes are `sweep.altitudes_km`, a single case's is `freestream.altitude_km` (like Mach: sweep list vs
  template); neither is copied into the other.
- Restart options are only `none` / `previous` / `custom`; the job's own copy of each cfg gets
  `RESTART_SOL` set from its line; the template and `configs/` are never changed by a run.
- The bundled `aerosuite/resources/config_template.cfg` is SU2's original reference setup: never edit it
  (e.g. its two `FREESTREAM_TEMPERATURE` lines, flow and solid zone, stay; AeroSuite sets both and warns).
- Jobs run through `engine/jobs/sweep_wrapper.py` (AeroSuite's Python, `-I`), which records the sweep
  script's exit code in `jobs/<id>.exit` (kept as `exit_code` in the job record); an abnormal end fails the
  case that was running. The web cancels in a worker thread (`run.io_bound`).
- Results page (spec `docs/superpowers/specs/2026-09-29-results-design.md`): parameters from the history
  files, derived values via `engine/formula.py` (an ast reader with an allowed list, never `eval`), packages
  (bundled `resources/packages/aero.json`, user ones in `~/.aerosuite/packages/`), overlays read with the
  current study's definitions, settings in `project.json` `results` (schema 6). `aerosuite summarize` uses them.

## Open items

Done 2026-09-29 and checked on the workstation with real SU2 (QuickStart NACA 0012, 2 ranks):
- the sweep's exit code is recorded (`f7987a4`): the sweep script and SU2 killed mid-case (SIGKILL) gave
  that case Failed "The sweep stopped during this case (killed by signal 9)", the rest "stopped before this
  case started", exit code -9, no SU2 left;
- Cancel from the Run page (`46abec2`): "Cancelling…" shown, other pages answered within 0.35 s meanwhile,
  job and cases Cancelled, no SU2 or lock left (this cancel took 1.4 s);
- `ed2882c` (line-numbered template editor, folded warnings, Freestream card): checked in headless Chrome
  (saving after a pause, on Ctrl+S and on leaving; warnings row; mode toggle). Still for the user: clicking
  into the editor text with the mouse in a real window.

Results page (2026-09-29, commits `e31a474`..`8fb1319`, **not yet checked on the workstation**): ask the user
to open Results on a finished real study, choose parameters, add a derived value and a plot, compare a second
study, and export.

Import SU2 runs (2026-09-30, spec `docs/superpowers/specs/2026-09-30-import-runs-design.md`, **not yet checked on
the workstation**): the Projects page's *Import SU2 runs* card and `aerosuite import` read existing case folders
(.cfg + history; values from the cfg, else the folder name) into a read-only study (schema 7, `project.imported`).
Ask the user to import a real folder of old runs and look at it on Results.

Known smaller items (from reviews; none blocking):

- Monitor shows the status twice; the job indicator, project switcher and study-kind tiles are not
  keyboard-reachable.
- `BREAKDOWN_FILENAME` is relative (files land in `runs/`); an all-NaN history column counts as converged;
  `write_lock` creates the file before writing it.
- CLI `show`/`set` don't surface the profile or sweep-off state.
- On Windows the test `test_losing_the_lock_race_leaves_nothing_behind` flaked once.

## Working notes for Claude

- NiceGUI 3.17: `refreshable.refresh()` is fire-and-forget, so pages that tests read right after a
  change rebuild synchronously (`box.clear()` then redraw) instead.
- Tests that open dialogs must `await user.should_see(marker=…)` before clicking inside them.
- On Windows, git checks files out with CRLF; that won't matter on Linux.

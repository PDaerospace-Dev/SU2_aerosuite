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
- The user reaches it from Windows with MobaXterm. The web UI (`uv run aerosuite serve --root ~/cfd`)
  listens on 127.0.0.1:8080 only; from the PC it needs an SSH tunnel
  (`ssh -L 8080:127.0.0.1:8080 pdas@<workstation>`, or MobaXterm's Tunneling tool), then
  http://localhost:8080.
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
- Tests: `uv run pytest` (728 passing on 2026-09-28, on Windows). Web tests use NiceGUI's simulated
  user; `tests/fixtures/fake_sweep.py` stands in for SU2; `tests/engine/test_sweep_script.py` runs the
  real sweep script against a stand-in `SU2` package.

## Workstation feedback already done

First round (2026-09-28): the restart fix in `aoa_sweep_v8.py` (a `previous` case after a failed one
starts fresh with `RESTART_SOL= NO`), Setup highlights the chosen mesh/template, partitions first with
the rest under Advanced, Mach in Freestream, Preview/Reference tabs, sweep switch on the config page,
no Configs step, collapsible failure details on Run. The user confirmed all of it works.

Second round (2026-09-28, commits `e5299a0`..`414b14e`, **not yet checked on the workstation**):

- the template copy keeps its file name; the previous copy is removed;
- job names are `YYYYMMDD-HHMM` (then `-2`, `-3` in the same minute). Because names are unique only
  within a project, `LocalRunner` keys its caches by (project folder, job id);
- Config page renamed **CFG setup**; aircraft studies don't show it (Aircraft has a Template tab,
  the sweep switch and Generate);
- log panel at the bottom (Log button; the top bar's "Running 3/32" opens it); Run's Job history tab;
- Calculators as a panel from the right;
- profiles also store the mesh path, sweep and run settings; `/profiles` page to edit them (editing
  a bundled profile saves the user's copy; Reset restores the bundled one).

Ask the user to try: set up **Profiles → X07** (template, mesh, sweep, partitions), make a new X07
study from it, run a sweep and watch the Log panel with real SU2 output (it shows the last 500 lines).

## Decisions worth knowing

- No login/token in the web UI yet (spec §7 known risk); it listens on 127.0.0.1 unless
  `--host … --i-understand-no-auth`.
- ISA uses the US76/SU2 Sutherland constants, so its viscosity and Reynolds number differ ~4% from the
  old PyQt app (the old app was wrong).
- Restart options are only `none` / `previous` / `custom`; the job's own copy of each cfg gets
  `RESTART_SOL` set from its line; the template and `configs/` are never changed by a run.
- Results page is a separate, later design; until then `aerosuite summarize`.

## Open items

Next, agreed but deferred by the user:

- **Altitude sweep**: altitude as a fourth sweep dimension (with Mach, α, β), each case's ISA
  temperature and Reynolds number from its own altitude and Mach. Open questions: how `previous`
  restarts chain across altitudes; altitude sweeps only in "From altitude" mode.

Known smaller items (from reviews; none blocking):

- Monitor shows the status twice; the job indicator, project switcher and study-kind tiles are not
  keyboard-reachable.
- `LocalRunner` ignores the sweep script's exit code; `BREAKDOWN_FILENAME` is relative (files land in
  `runs/`); an all-NaN history column counts as converged; `write_lock` creates the file before
  writing it.
- Run's Cancel can block the web server's event loop for up to ~20 s; `cancel()` doesn't reload the
  job record first.
- The bundled `config_template.cfg` has `FREESTREAM_TEMPERATURE` twice (both lines are replaced).
- CLI `show`/`set` don't surface the profile or sweep-off state.
- `.claude/launch.json` (the dev-server preview config) points `--root` at a Windows temp folder;
  change it on Linux.
- On Windows the test `test_losing_the_lock_race_leaves_nothing_behind` flaked once.

## Working notes for Claude

- NiceGUI 3.17: `refreshable.refresh()` is fire-and-forget, so pages that tests read right after a
  change rebuild synchronously (`box.clear()` then redraw) instead.
- Tests that open dialogs must `await user.should_see(marker=…)` before clicking inside them.
- On Windows, git checks files out with CRLF; that won't matter on Linux.

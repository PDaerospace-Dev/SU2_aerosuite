# AeroSuite Web Architecture — Design Spec

**Date:** 2026-09-21
**Status:** Draft for review
**Scope:** Replace the PyQt5 desktop UI with a Python engine + CLI + NiceGUI web UI, migrated in phases. The first implementation plan covers Phases 0–1 only.

---

## 1. Context and goals

AeroSuite today is a PyQt5 desktop app (~7.9k lines) that prepares, runs and post-processes SU2 sweeps. `aerosuite/core/` is already Qt-free, but application state lives inside widgets: pages read each other's fields directly, cross-page updates are hand-wired signals in `main.py`, and profile save/load (`main.py:645`) copies selected widget values by hand and misses most CFG settings.

Known correctness bugs (fixed as part of Phase 1):

- Sweep writes `MACH_NUMBER`/`AOA`/`SIDESLIP_ANGLE` with `:.1f` — Mach 0.85 becomes 0.8, AoA 2.25 becomes 2.2 (`ui/sweep_setup_tab.py:222`).
- Case filenames keep one decimal of Mach and round angles, so 0.78/0.8/0.82/0.85 all map to `M0p8` and α 1.5/2.5 both map to `a2`; files overwrite each other silently. `validate_config` does not detect this.
- Results parsing ignores beta, requires names to start with `M`, and its `_A<n>[mp]` branch would misread `a2p5` as +2.
- A case is reported `SUCCESS` when its output folder exists, regardless of convergence.
- On Windows, Stop kills only the Python wrapper, leaving `mpirun`/SU2 running.

**Deployment context:** one Linux workstation today (SU2 runs there); remote access from users' PCs and HPC (Slurm) submission later. Visualisation needs are 2D only; 3D stays in ParaView.

**Maintainer context:** code is written mostly by Claude and reviewed/maintained by a Python-literate CFD engineer. The stack must be Python-only — no JavaScript/TypeScript build chain.

**Goals**

1. A single project model that is the source of truth for every setting.
2. An execution layer whose state survives UI restarts and can gain an HPC backend without UI rewrites.
3. A browser UI reachable locally now and over SSH tunnel later.
4. Engine correctness covered by automated tests that run without SU2, MPI or a browser.
5. A working tool at every migration step.

**Non-goals (this spec)**

- Slurm backend and authentication (interface shaped for them, not built).
- Replacing `aoa_sweep_v8.py` as the execution backend.
- 3D visualisation.

## 2. Decision: NiceGUI web app over a UI-free engine

Considered:

| Option | Verdict |
|---|---|
| **NiceGUI web app** (FastAPI + Quasar, all Python) | **Chosen.** Only option that reaches remote/HPC use without a second UI rewrite; Python-only; good fit for long-running jobs and live updates. |
| PySide6 (Qt6) desktop | Smallest migration and LGPL licence, but remote use limited to VNC/X forwarding; multi-user HPC would force a later server + UI rewrite. |
| FastAPI + React/TypeScript | Most polished, but two languages and a JS toolchain conflict with the maintainer context. |
| Streamlit / Dash | Rejected: rerun-whole-script model fits multi-page stateful workflows with background jobs poorly. |

Risk: NiceGUI's community is smaller than Qt's. Mitigation: the UI layer is thin and depends only on the engine, so it is replaceable.

## 3. Architecture

Three layers; each depends only on the one below.

```
aerosuite/
├── engine/                 pure Python, no UI imports
│   ├── models.py           pydantic models (section 4)
│   ├── project.py          create / open / save project folders; schema migration
│   ├── atmosphere.py       ISA + y+           (from core/isa_calculator, core/yplus_calculator)
│   ├── cfg.py              render_case, marker extraction, case naming (from core/su2_generator)
│   ├── results.py          history reading, convergence, summary (from core/monitor, core/aerosummary)
│   ├── preflight.py        pre-run validation returning a list of problems
│   ├── errors.py           AeroSuiteError hierarchy
│   └── jobs/
│       ├── runner.py       Runner protocol + JobRecord
│       ├── local.py        LocalRunner (runs aoa_sweep_v8.py)
│       └── store.py        read/write jobs/<id>.json, project lock
├── cli.py                  `aerosuite` command (Typer)
├── web/                    NiceGUI app; one module per page (section 7)
├── resources/              config_template.cfg, aoa_sweep_v8.py, presets/*.json
└── ui/, main.py            legacy PyQt5 app — kept until Phase 5
```

Rules:

- `web/` and `cli.py` never read/write project files or manage processes directly; they call engine functions.
- A new feature = an engine function (tested) + a page or CLI command.
- `aerosuite/core/` is moved into `engine/` in Phase 1; `core/` remains as thin re-export shims until the PyQt5 app is retired.

### Project folder

A project is a directory; the directory is the source of truth.

```
<project>/
├── project.json            all settings (section 4)
├── template.cfg            copy of the master template taken at selection time
├── configs/                generated *.cfg, run_control.txt, cases.json
├── runs/<case>/            SU2 output per case (as aoa_sweep_v8.py produces today)
├── jobs/<job_id>.json      job records
├── jobs/<job_id>.log       sweep log
├── .lock                   present while a local job is active
└── results/                summary CSV and exported plots
```

The mesh is referenced by path, not copied (meshes are large).

## 4. Project model

Pydantic v2 models serialised to `project.json`. `schema_version` is an integer starting at 1; `project.py` holds an ordered list of migration functions applied on load.

```
Project
  schema_version: int
  name: str
  created, modified: datetime
  mesh: Mesh
      path: str
      markers: list[str]          # read from MARKER_TAG= lines of .su2 meshes
  template: str                   # relative path, normally "template.cfg"
  preset: str | None              # name of the preset last applied (informational)
  settings: Settings
      freestream: temperature_K, reynolds, reynolds_length
      reference:  origin_x, origin_y, origin_z, ref_length, ref_area
      numerics:   turb_model, cfl, iter, conv_method, muscl
      markers:    dict[str, str]  # e.g. {"MARKER_FAR": "( FarField )"}; key absent = line removed
      overrides:  dict[str, str]  # any SU2 key; replaces "custom placeholders"
  sweep: SweepSpec
      mach: list[float], alpha: list[float], beta: list[float]
      altitude: str
      naming: include_mach, include_alpha, include_beta, include_altitude, include_base, base_name
  cases: list[Case]
      name: str                   # filename stem
      mach, alpha, beta: float
      restart: none | previous | initial | custom | from_case
      restart_ref: str | None     # path (custom/initial) or case name (from_case)
  run: RunSettings
      partitions: int
      sweep_script: str           # default: bundled resources/aoa_sweep_v8.py
      sweep_python: str           # interpreter able to import SU2; default: "python3" on PATH
```

Numeric settings are stored as numbers, not strings; `Settings` fields left as `None` are not written, so the template value stands.

**Presets:** JSON files in `resources/presets/` holding partial `Settings`. "X07 Aircraft Aero" is the first preset, capturing today's form defaults. Applying a preset overwrites the fields it defines.

### Case naming (fixes filename collisions)

- Mach: `M` + value with `.` replaced by `p`, all significant digits kept: 0.85 → `M0p85`, 0.8 → `M0p8`, 1.5 → `M1p5`.
- Angles: `a`/`b` prefix, `n` for negative, `p` for decimal point, all significant digits kept: 5 → `a5`, −5 → `an5`, 2.5 → `a2p5`, −0.5 → `an0p5`.
- Whole numbers produce the same names as today, so existing run folders remain valid.
- Values are formatted with `format(v, "g")` then normalised; the same formatting is used for values written into the `.cfg`, so file content and name never disagree.
- Generation fails with a list of duplicates if any two cases would produce the same name.

## 5. Data flow

1. **Edit** — a page updates the in-memory `Project`, which is saved to `project.json` (debounced ~0.5 s). All open pages observe the same object.
2. **Render** — `render_case(project, case) -> str` layers: template → `settings` → `overrides` → case Mach/α/β (+ `MESH_FILENAME`, `BREAKDOWN_FILENAME`). Later layers win. Keys missing from the template are appended; marker keys absent from `settings.markers` are removed. The Settings-page preview calls the same function.
3. **Generate** — runs preflight, then writes `configs/<case>.cfg` for every case, `configs/run_control.txt` from `cases[].restart`, and `configs/cases.json` (`{name: {mach, alpha, beta}}`).
4. **Run** — `runner.submit(project, cases, partitions)` → `JobRecord`.
5. **Monitor** — background poller reads new log and history bytes (section 6).
6. **Results** — averages the last N iterations of each `runs/<case>/history.csv` and joins with `cases.json` for Mach/α/β. Folder-name parsing is used only when `cases.json` is absent (legacy runs), and the fixed parser handles `p` decimals, `n` negatives and beta.

## 6. Jobs, monitoring and errors

### Runner protocol

```
submit(project, cases, partitions) -> JobRecord
refresh(job) -> JobRecord        # derives state from disk and the OS
cancel(job) -> JobRecord
```

`JobRecord` (saved as `jobs/<id>.json`): `id`, `backend` (`"local"`), `backend_ref` (dict; `{"pid", "pgid"}` for local, later `{"slurm_id"}`), `cases`, `log_path`, `created`, `finished`, `state` (`QUEUED | RUNNING | DONE | FAILED | CANCELLED`), `case_status` (`{name: PENDING | RUNNING | CONVERGED | UNCONVERGED | FAILED | CANCELLED}`), `failure_tail` (`{name: last ~50 log lines}`).

### LocalRunner

- Launches `sweep_python sweep_script -d . -c run_control.txt -n <partitions>` from `configs/`, detached (`start_new_session=True`), stdout/stderr to `jobs/<id>.log`. Answers the script's confirmation prompt on stdin as today.
- Creates `.lock` on submit; `submit` refuses if a lock exists and its pid is alive; a stale lock (dead pid) is removed.
- `refresh` never trusts memory: pid liveness (`os.kill(pid, 0)`), the log's `Running Case i/n: <cfg>` banners, and per case `runs/<case>/error.log` (→ FAILED) or `history.csv` + convergence check (→ CONVERGED/UNCONVERGED).
- `cancel` sends SIGTERM to the process group, waits 5 s, then SIGKILL. On Windows it uses `taskkill /T /F /PID <pid>`.
- The convergence check is today's `AeroSummary.check_convergence` (std/mean of CL/CD/CMy over the last 10%), moved into `engine/results.py`.

### Monitoring

A single asyncio task in the web server refreshes active jobs every 2 s. History and log readers keep a per-file byte offset and parse only appended lines. Updates are pushed to all connected browsers.

### Preflight

`preflight(project, action) -> list[Problem]` where `Problem` has `severity` (`error` / `warning`) and `message`. Checks: template exists; mesh exists; case-name collisions; markers referenced in `settings.markers` but absent from `mesh.markers` (warning); `SU2_RUN` set and `sweep_script` exists (run only); project lock held by a live job (run only); `custom`/`initial`/`from_case` restarts have a valid reference. Errors block the action; warnings are shown and can be acknowledged.

### Errors

Engine functions raise `AeroSuiteError` subclasses (`ProjectError`, `TemplateError`, `GenerationError`, `JobError`) with user-facing messages. The UI and CLI display them. No `print`-and-continue in the engine.

### Access and security

The server binds to `127.0.0.1:8080` by default. Remote use is via `ssh -L 8080:localhost:8080 <workstation>`. There is no authentication; binding to a non-local address requires adding authentication first, and the server refuses a non-local bind unless `--i-understand-no-auth` is passed.

## 7. Web UI

Left sidebar in workflow order with status badges (✓ complete, ● needs attention, ○ not started); header shows the open project and a switcher.

| Page | Contents |
|---|---|
| Projects | New / open / recent; import legacy profile JSON |
| Calculators | ISA and y+; "Apply to project" writes `settings.freestream` |
| Setup | Mesh (markers auto-read), master template, preset |
| Settings | Freestream / reference / numerics / markers / overrides form beside live `.cfg` preview |
| Sweep | Ranges, naming options, resulting case table with live collision highlighting, Generate |
| Run | Restart-plan table, preflight results, partitions, Submit / Cancel, job history, per-case status |
| Monitor | Case multi-select, live Plotly residual and coefficient plots, overlay |
| Results | Summary table, polars (CL–α, CD–CL, CM–α), CSV export, "Open in ParaView" (launches `paraview` on the workstation display; disabled with a tooltip when the browser is not local) |

Each page module targets ≤ ~200 lines and calls only engine functions.

Launch: `aerosuite serve [--port 8080]`.

## 8. CLI

Typer app installed as the `aerosuite` command:

- `aerosuite new <dir> --template <cfg> --mesh <su2>`
- `aerosuite generate <dir>` — preflight + write configs
- `aerosuite run <dir> [-n N]` — submit via LocalRunner
- `aerosuite status <dir>` — refresh and print jobs and case states
- `aerosuite cancel <dir> [job_id]`
- `aerosuite summarize <dir> [--last N]`
- `aerosuite serve [--port]`

## 9. Environment

- The workstation's Python is 3.7.6, which is below the minimum for NiceGUI, pydantic v2 and current pandas. AeroSuite therefore runs on **Python 3.12 in its own user-level environment**, created with `uv` (single binary, no root needed: `uv python install 3.12`, `uv venv`). Miniforge (conda) is the fallback if `uv` cannot be used. The system Python 3.7.6 is not modified.
- The sweep script keeps running under the existing Python 3.7.6 that already imports SU2's modules: `run.sweep_python` defaults to `python3` on `PATH`, not to AeroSuite's own interpreter. SU2's Python modules are never installed into the AeroSuite environment.
- `aoa_sweep_v8.py` must stay compatible with Python 3.7 (no syntax newer than 3.7 in that file).
- A launcher script `bin/su2aero` activates the AeroSuite environment and runs `aerosuite serve`; the existing `su2aero2` alias keeps launching the PyQt5 app until Phase 5.
- Dependencies (pinned in `requirements.txt`): `nicegui`, `pydantic>=2`, `typer`, `pandas`, `plotly`; dev: `pytest`.
- PyQt5, matplotlib and qtawesome stay in requirements until Phase 5.

## 10. Testing

- **Engine unit tests (pytest):** naming encode/decode round-trips and collision detection; backward-compatible names for whole numbers; exact values written to `.cfg`; `render_case` layer precedence, marker removal, append of unknown keys; restart plan → `run_control.txt`; convergence check; results join with `cases.json` and legacy name parsing (including beta, `p` decimals, `n` negatives); schema migration.
- **Runner integration tests:** a fake sweep script in `tests/fixtures/` emits `Running Case` banners, writes `history.csv` (converging or not) and `error.log` on demand, and sleeps so cancel can be exercised. Tests cover submit, refresh after a simulated server restart, cancel, lock refusal and stale-lock recovery. No SU2 or MPI required.
- **CLI smoke tests** via Typer's `CliRunner`.
- **Web tests:** NiceGUI's `User` fixture for open project → generate → submit (with the fake script).
- Tests must pass on Linux and Windows.

## 11. Migration phases

Each phase gets its own implementation plan; the app is usable at the end of each.

| Phase | Delivers |
|---|---|
| 0. Housekeeping | `.gitignore`; remove committed `__pycache__`; commit `aoa_sweep_v8.py`; `tests/` scaffold with pytest; fix `test_imports.py`; documented `uv` setup for the Python 3.12 environment |
| 1. Engine | `engine/` models, project store, `render_case`, naming fixes, results fixes, preflight, LocalRunner + job store, full tests; `core/` becomes re-export shims; PyQt5 sweep and results pages call the engine for naming, value formatting and results parsing; the PyQt5 Run page keeps the existing `SweepRunner` until Phase 3 |
| 2. CLI | Commands in section 8 (except `serve`) |
| 3. Web core | `serve`; Projects, Setup, Settings, Sweep, Run, Monitor, Results pages |
| 4. Parity | Calculators, presets UI, ParaView button, legacy profile import |
| 5. Retire PyQt5 | Delete `ui/`, `main.py` Qt code, `su2_tab.py`, `core/` shims; drop Qt deps; update README |
| Later | SlurmRunner; authentication |

**First implementation plan:** Phases 0–1.

## 12. Resolved decisions

- Workstation Python is 3.7.6 → AeroSuite uses its own Python 3.12 via `uv` (section 9).
- The workstation has internet access → packages and Python are installed online; no offline install path is needed.

# AeroSuite Web UI — Config Modes, Reference Panel and Aircraft Profiles — Design Spec

**Date:** 2026-09-23
**Status:** Draft for review
**Builds on:** `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md` (the base spec; its §3, §6 and §7.1 still apply unless changed here). Branch `feat/web-config-modes`, stacked on `feat/web-phase-3a`.

---

## 1. Why

The desktop app deliberately had two ways of working, and the Phase 3a web UI lost both:

- **General** — most studies are not aircraft sweeps. You build one `.cfg` by editing a template as text, with SU2's reference `config_template.cfg` beside it (with Find) to look up and copy option blocks.
- **Aircraft Aero** — for an aircraft, the common parameters are a form with dropdowns and the aircraft's known values as hints; anything else is looked up in the reference and added as a custom placeholder; then a Mach/α/β sweep.

Phase 3a forced every project through the sweep, had no reference panel and flattened the Aircraft Aero form into generic text boxes.

**Decision (chosen by the user):** one project type built in layers (option B), with a two-card start screen when creating a project (from option C). A study is not locked into a mode: a profile and the sweep can be switched on or off later.

**Also decided:**
- General projects are runnable (single case, same Run/Monitor/Results as a sweep — Phase 3b).
- Aircraft support is multi-aircraft through **profiles**; X07 ships first. The X07 master template is only on the workstation, so the bundled X07 profile has settings and hints but no template; the user adds the template later with "Save as profile".

## 2. Project model changes

`schema_version` goes from 1 to 2. Migration 1→2 adds `profile = None` and `sweep.enabled = True`, so every existing project behaves exactly as before.

```
Project
  profile: str | None          # profile id, e.g. "x07"; None = general project
  sweep: SweepSpec
      enabled: bool            # False → the project is a single case
      ...                      # (mach, alpha, beta, altitude, naming unchanged)
```

### Single-case projects (`sweep.enabled = False`)

- Exactly one case, named after the project folder (e.g. `nozzle_study` → `configs/nozzle_study.cfg`, `runs/nozzle_study/`). `build_cases` returns this case; its restart option is kept across rebuilds like any other case.
- **Rendering writes the template as the user wrote it.** `MACH_NUMBER`, `AOA`, `SIDESLIP_ANGLE` and `BREAKDOWN_FILENAME` are NOT injected. Still applied: project settings, markers, overrides (in the same order as today) and the absolute `MESH_FILENAME` when a mesh is set.
- The case's `mach`, `alpha` and `beta` are read from the template's `MACH_NUMBER`, `AOA` and `SIDESLIP_ANGLE` lines (0.0 when a line is missing or not a number), so `cases.json` and `summary.csv` still carry them.
- `run_control.txt`, `LocalRunner`, `summarize` and the CLI work unchanged (a job with one case).
- Preflight: "No Mach numbers in the sweep" applies only when the sweep is enabled. The other checks are unchanged.

### Editing the template text

- `engine.project.set_template_text(project_dir, project, text) -> list[str]` writes `template.cfg` (atomic write, `OSError` → `TemplateError`) and returns warnings:
  - lines that are neither blank, a comment (`%`), nor `KEY= value`: `Line 12 is not an option or a comment: "..."`
  - an option set more than once: `FREESTREAM_TEMPERATURE is set on lines 246 and 357; both will be changed together`
- `engine.project.read_template_text(project_dir, project) -> str` (`TemplateError` if missing).

## 3. Reference panel (`engine/reference.py`)

- `load_reference(path: Path | None = None) -> list[RefOption]`: parses SU2's `config_template.cfg` (default: the bundled `aerosuite/resources/config_template.cfg`).
  - `RefOption(key, line, description, section, line_no)`. `line` is the full default line (`MARKER_EULER= ( airfoil )`); `description` is the comment block directly above it (leading `%` stripped, joined with spaces); `section` comes from the latest `% --- … ---` banner.
  - An option appearing more than once keeps every occurrence, each with its own description and section.
  - Unreadable file → `ProjectError`; the web panel then keeps showing the bundled reference.
- `search(options, query, limit=50) -> list[RefOption]`: case-insensitive; options whose key contains the query first, then options whose description contains it; empty query returns nothing.
- `keys_in(text: str) -> set[str]`: option keys set in a config text (used for the "In config" badge).

## 4. Profiles (`engine/profiles.py`)

```
<profiles dir>/<id>/
├── profile.json     {"id", "name", "description",
│                     "settings": <partial Settings>,   # applied as defaults
│                     "hints":    {<field or MARKER_ key>: "<text>"},  # grey hint text only
│                     "naming":   <partial Naming>}
└── template.cfg     optional — the aircraft's master template
```

- Two locations: bundled `aerosuite/resources/profiles/` and the user's `$AEROSUITE_HOME/profiles/` (default `~/.aerosuite/profiles/`). A user profile with the same id replaces the bundled one.
- `list_profiles() -> list[Profile]`, `load_profile(id) -> Profile` (`ProjectError` if unknown or invalid).
- `apply_profile(project_dir, project, profile)`: sets `project.profile`; copies the profile's template when it has one; overwrites the settings fields and naming flags the profile defines; leaves every other field alone.
- `save_profile(project_dir, project, id, name, description="", overwrite=False) -> Profile`: the id must be a plain folder name (letters, digits, `-`, `_`); an existing user profile is replaced only with `overwrite=True`; copies `template.cfg` and the project's settings and naming. It never copies the mesh path, sweep values, cases or restarts.
- **Bundled X07 profile** (`resources/profiles/x07/profile.json`, no template):
  - settings: reference length 6, reference area 16.213, moment origin 5.16 / 0 / 0, Reynolds length 1; numerics: convective ROE, MUSCL YES, turbulence SST, CFL 1.0, iterations 1500 (the desktop app's form defaults).
  - hints (grey text only, not written): the four marker fields `MARKER_HEATFLUX` / `MARKER_PLOTTING` / `MARKER_MONITORING` → `( Fuselage, Wing, VT, HT )`, `MARKER_FAR` → `( FarField )`, as in the app.

## 5. Pages and navigation

**Sidebar** shows only what the project uses: `Setup · Config · [Aircraft] · [Sweep] · Run · Monitor · Results` — Aircraft when `profile` is set, Sweep when `sweep.enabled`; Run/Monitor/Results stay greyed until Phase 3b. Badges: Config ✓ when the template exists and has no parse warnings (● with warnings); Aircraft ✓ when the template exists; Sweep as in §7.1 of the base spec; Configs as today.

**New project** (Projects page) — three steps:
1. Two cards: **General case** (profile none, sweep off) or **Aircraft study** (profile dropdown: bundled and user profiles; sweep on).
2. Parent folder + name; template (General: pick one, or "Start from SU2's config_template.cfg"; Aircraft: the profile's template if it has one, otherwise pick one — required); mesh (optional).
3. Create → `create_project` + `apply_profile` (Aircraft) + `set_template` + `set_mesh`; land on Setup.

**Setup** — as in 3a, plus:
- **Profile** dropdown (None / bundled / user) → sets `project.profile` only; the **Apply profile defaults** button (confirm dialog) calls `apply_profile`.
- **Save as profile…** dialog (id, name, description; confirm before replacing).
- **Sweep** switch (on/off) → `sweep.enabled`; cases are rebuilt.

**Config** (every project):
- Left: the template as editable monospace text. Saves on blur through `set_template_text`; warnings listed under the editor. A **Preview** toggle shows the rendered config of a selected case. When the sweep is off: the checks panel and **Generate config** live here.
- Right: the **reference panel** — search box; results list (default line, description, section) with **Insert**, or an "In config" badge; **Show full file** (read-only view with Find next and highlight, as in the app); **Load another reference…** (picker, `.cfg`).
- Insert on Config: when the key is already in the text, the editor scrolls to and highlights that line instead of adding a duplicate; otherwise the option's default line is appended at the end under `% --- added from reference ---` (the heading is added once).

**Aircraft** (only with a profile) — replaces 3a's Settings page:
- Left, laid out like the app's Aircraft Aero form: Freestream (temperature, Reynolds number, Reynolds length); Physical & reference (reference length, area, moment origin x/y/z); Numerics (Convective: ROE/JST/AUSM; MUSCL: YES/NO; Turbulence: SST/SA; CFL; iterations); Markers (HEATFLUX, FAR, PLOTTING, MONITORING — each with an include tick and a value; unticked = line removed, as in the app); Placeholders (key/value rows = `settings.overrides`, add/delete). Empty fields show the profile's value or hint as grey text.
- Right: the same reference panel; **Insert** here adds a placeholder row with the option's default value (or focuses the existing row). Preview toggle as on Config.
- Dropdown values are fixed lists in the page; a template value not in the list is shown as an extra option so nothing is lost.

**Sweep** — unchanged, shown only when the sweep is on.

**Page background** — every page sets an explicit background and text colour so it stays readable in browsers that paint a dark canvas.

## 6. Error handling

- All writes go through `ProjectFrame.save`/`ProjectSession.apply` or the engine functions above (stale-save refusal and invalid-file refusal from 3a still apply).
- Template text warnings never block saving; they are shown and listed in preflight as warnings.
- A broken profile file: the profile is left out of dropdowns and a warning is shown on the Projects page; applying it raises `ProjectError`.
- A reference file that cannot be read: an error under the panel; the bundled reference stays loaded.

## 7. Testing

- Engine: reference parsing of the bundled file (e.g. `MARKER_EULER` found with its description and section; duplicate keys kept); search ordering and limit; `keys_in`; migration 1→2; single-case rendering (no Mach/AoA/β/breakdown injection; mesh, settings, overrides applied) and Mach/α/β read from the template; single-case run through the fake sweep and `summarize`; `set_template_text` warnings and atomic write; profiles list/load/apply/save (bundled vs user precedence, overwrite refusal, never copying mesh/sweep/cases).
- Pages (simulated browser): start screen (both kinds; aircraft without a profile template requires a template); sidebar shows/hides Aircraft and Sweep; Config save-on-blur, warnings, Insert (append and jump-to-existing), Show full file + Find next, single-case Generate; Aircraft dropdowns, marker ticks, placeholders, Insert into placeholders, profile hints; Setup profile dropdown, Apply defaults, Save as profile, sweep switch.
- Visual click-through in the browser pane with screenshots after the last task.

## 8. Out of scope

- Run / Monitor / Results pages (Phase 3b), calculators (Phase 4 unless moved), a startup token (decided before 3b).
- Restyling the whole UI to the desktop app's look (beyond the explicit page background).
- New CLI flags for profiles or the sweep switch. The CLI already works with single-case and profile projects (`generate`, `run`, `status`, `summarize`), and `aerosuite edit` can change `profile` and `sweep.enabled` by hand.

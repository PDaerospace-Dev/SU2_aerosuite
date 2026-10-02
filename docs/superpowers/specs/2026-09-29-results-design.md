# Results Page: Design Spec

**Date:** 2026-09-29
**Status:** Agreed with the user (chat, 2026-09-29)
**Builds on:** `2026-09-21-aerosuite-web-architecture-design.md` §6 and the Results row of its page table (summary
table, polars, CSV export). Branch: `feat/web-ui-refresh`.
**Mockups** (a working prototype on synthetic data): `docs/superpowers/specs/assets/2026-09-29-results/`:
- `compare-aero.png`: two designs overlaid, the Aerodynamic characteristics package, characteristic values
- `internal-flow.png`: a duct study, own parameters, derived Pt loss, own plots
- `parameter-picker.png`, `folded-sections.png`: a study with 72 history parameters
- `derived-dialog.png`, `add-plot-dialog.png`

---

## 1. Why and scope

After a sweep the user post-processes: the aerodynamic characteristics (CL–α, CD–α, CM–α, CL–CD), numbers read off
those curves, and comparisons between designs. Today that is `aerosuite summarize` → `summary.csv` and plots made by
hand. The page must also serve studies that are **not external aerodynamics** (ducts, intakes, heat transfer): nothing
may assume CL and CD exist.

**Decided with the user:**
- **Parameters come from the history files.** Any `history.csv` column can be chosen; the page shows only the chosen
  ones, and a searchable, grouped picker holds all of them (a full SU2 output has 70–200 columns).
- **Derived parameters:** per-case formulas of averaged values (L/D, total-pressure loss, forces from coefficients).
- **Characteristic values:** numbers read off a curve (CLα, α₀, CD₀, (L/D)max and its α, CMα).
- **Packages:** *Aerodynamic characteristics* is a built-in package of parameters, derived values, characteristic
  values and plots, switched on with one click. The user saves their own packages (e.g. "Duct performance") and uses
  them in any study.
- **Own plots:** any X (a sweep variable or a parameter) against **one or more** Y parameters.
- **Overlay designs:** other studies drawn on the same plots and listed in the same tables, each design one colour.
- **Convergence is judged on the chosen parameters**, not on fixed CL/CD/CMy.
- **Sections fold:** Plots, Characteristic values and Results fold shut; the state is kept per study.

**Out of scope (later):** experimental/reference data from a CSV as an overlay; a PDF report; ParaView (files can be
downloaded from a case folder instead); per-iteration derived values (formulas use averages only).

## 2. The page, top to bottom (see the mockups)

1. **Designs and flight condition** (one card)
   - Design chips: this study (always first) and each overlaid study, a colour swatch each, ✕ removes an overlay (the
     other study is never changed). **+ Add design…** picks a project folder (the file picker, projects only).
   - Filter chips for each sweep variable that varies (Mach, α not shown as it is the usual X, β, altitude); a chip
     toggles a value. With one design every value is shown; with overlays only the first Mach at first.
   - **Average last N iterations** (default 100, as `summarize`).
2. **Parameters**: the chosen ones as chips with ✕, "6 of 73 chosen", and **Choose parameters…**
3. **Tiles**: cases shown · converged · unconverged (red when > 0) · designs.
4. **Plots** (folds): package chips (✓ Aerodynamic characteristics, own packages; a package whose parameters the
   study lacks is disabled with the reason as a tooltip), **+ Add plot**, the package's plots, then "My plots".
   Each plot: a title, ✕ (own plots), a PNG download. Unconverged points are hollow. Hover: case, X and Y.
   **Clicking a point opens that case in Monitor.**
5. **Characteristic values** (folds; only when a package or the user defines some): one row per design and curve.
6. **Results** (folds): Design, Case, the varying sweep variables, the chosen parameters (derived marked ƒ), Status.
   Many columns scroll sideways with Design and Case pinned.
7. Page actions: **Copy table** (tab-separated, pastes into Excel), **Export CSV**, **Save as package…**

### 2.1 Choose parameters (a panel from the right, like Calculators)

Search box; "N chosen · Clear all"; groups built from SU2's column names, each with its count, the number chosen and a
tick for the whole group:

| Group | Columns |
|---|---|
| Derived (ƒ) | the study's formulas, with **+ Derived…** |
| Total coefficients | `C` + 1–4 letters: CL, CD, CSF, CMx…, CFx…, CEff |
| Marker: *name* | `Anything(name)`: CL(Wing), Avg_Massflow(outlet), one group per marker |
| Flow & other | everything else |
| Convergence monitors | `Cauchy…` (folded) |
| Solver | `LinSol…`, `…CFL` (folded) |
| Residuals | `rms[…]`, `max[…]`, `bgs[…]` (folded) |

Iteration counters (`Time_Iter`, `Outer_Iter`, `Inner_Iter`, `Cur_Time`) are never offered. Groups holding chosen
parameters open; the rest start folded. The columns are read from the study's history files (the union over cases).

### 2.2 Add plot

- **X**: one dropdown: the varying sweep variables first, then parameters. **Y**: a multi-select of parameters.
  Both are searchable over *all* history columns; picking an unchosen one also chooses it.
- **Lines** (shown in words under the dropdowns, changeable): one line per value of the varying sweep variables
  that are not on the X axis; when X is a parameter (CL vs CD), points are joined along α. Colour = design; line style
  = the splitting value (solid, dashed, dotted, then dash-dot); with several Y, marker shape = Y parameter.
- Axis names: sweep variables with units (α (deg), Altitude (km)); a parameter's unit when a derived one has one.

### 2.3 Derived parameter

Name, optional unit, formula, clickable names (History, Sweep, Study constants), the allowed operators and functions,
and a live preview of the first cases (or the error, e.g. "`{Avg_Mass}` is not a column").

## 3. Formulas (engine, `engine/formula.py`)

A small reader built on Python's `ast`, **never `eval`**: only these node types are accepted, anything else is an error.

- Numbers; `+ - * / ^ ( )` (`^` is power); unary minus.
- Names: history columns (bare when a Python identifier, else in braces: `{Avg_TotalPress(outlet)}`), the sweep
  variables `Mach`, `Alpha`, `Beta`, `Altitude`, study constants (below), and other derived names defined earlier.
- Functions: `sqrt abs log exp sin cos tan` (angles in degrees) `min max`.
- Division by zero or a value outside a function's domain gives an empty cell with the reason on hover, not an error.
- Evaluated on the **averaged** values of one case (ratio of averages).

**Study constants:** `S_ref`, `L_ref` (the project's reference settings, else the template's `REF_AREA` /
`REF_LENGTH`); with the freestream from altitude, per case from ISA at its altitude and Mach: `rho_inf`, `p_inf`,
`T_inf`, `V_inf`, `q_inf`. Unavailable constants make the formula's cells empty with "q_inf needs the freestream from
altitude" (manual mode) rather than a wrong number.

**Characteristic values** use the same reader with curve functions, evaluated per design and curve (a curve = one
value of each splitting sweep variable, along α):
`slope(Y, X, from, to)` (least-squares line), `at(Y, X, value)` (Y where X = value, linear interpolation; also inverse,
e.g. `at(Alpha, CL, 0)` = α₀), `max(Y)`, `min(Y)`, `argmax(Y, X)`, `argmin(Y, X)`. A curve too short or a value outside
the data range gives an empty cell with the reason.

## 4. Data

**Per study** (`project.json`, schema 6, a new `results` block; older projects get the defaults):

```
results:
  parameters: [str]          # chosen history columns and derived names, in display order; empty = package defaults
  derived: [{name, formula, unit}]
  characteristics: [{name, formula, unit}]
  plots: [{x, y: [str], split: str | null}]   # own plots; split null = automatic
  packages: [str]            # enabled package ids, e.g. ["aero"]
  compare: [str]             # other study folders (absolute paths)
  filters: {Mach: [..], Beta: [..], Altitude: [..]}   # empty = all
  average_last: 100
  folded: [str]              # "plots" | "characteristics" | "results"
```

**Packages**: `{id, name, description, parameters, derived, characteristics, plots}`. The built-in **aero** package
ships in `resources/packages/aero.json`: CL, CD, CMy; L/D = CL / CD; CLα = slope(CL, Alpha, -2, 6),
α₀ = at(Alpha, CL, 0), CD₀ = at(CD, CL, 0), (L/D)max = max(L/D), α at (L/D)max = argmax(L/D, Alpha),
CMα = slope(CMy, Alpha, -2, 6); plots CL–α, CD–α, CMy–α, CL–CD. User packages live in
`~/.aerosuite/packages/<id>.json` (`AEROSUITE_HOME` as for profiles); a user package with a built-in id overrides it.
**Save as package…** stores the study's own derived values, characteristic values, plots and parameters.

Enabling a package adds its parameters, derived and characteristic values and shows its plots; disabling it removes
what it added unless the user also chose it. A package is available when the study's history has every history
column it names.

## 5. Engine behaviour

- `results.history_columns(folder)`: the union of history headers over the cases (iteration counters out).
- `results.group_of(column)` and the group order in §2.1.
- `summarize(runs_dir, columns, last_n, case_index, convergence_columns=…)`: as today, plus convergence judged on
  `convergence_columns` (the chosen history parameters that are not residuals, solver or convergence monitors). When
  none is chosen the status is **not judged** (shown "—", counted apart in the tiles), no longer "unconverged".
- `results.study_results(folder, settings)`: summary + derived values + characteristic values for one study, reading
  each case's history once; the overlays use the *current* study's definitions; a design missing a column shows empty
  cells and a note ("x07-wing-v2 has no CL(HT)").
- Everything is cached per (study, history file size and mtime), so changing a filter or a plot does not re-read files.
- `aerosuite summarize` uses the study's saved parameters and derived values (its `--columns` still overrides) and
  also writes `results/characteristics.csv` when there are characteristic values.

## 6. Web details

- The page reads results when opened and when a job finishes (the job watcher), not on a timer.
- The folded state, filters, chosen parameters, plots and overlays are saved in the study as they change.
- Monitor accepts `?case=<name>` so a clicked point opens that case.
- Charts: ECharts (as Monitor); a PNG button per chart (ECharts' save-as-image).
- Copy table puts tab-separated text on the clipboard (the browser's clipboard API over the tunnel's localhost page).

## 7. Tests to pin

1. The formula reader accepts the listed grammar and refuses everything else (attribute access, imports, lambdas,
   comprehensions, unknown names and functions) with a readable message; braces names; `^`; degrees in trig.
2. Derived values: L/D and Pt loss on known averages; division by zero → empty cell with a reason; constants from ISA
   in altitude mode; `q_inf` unavailable in manual mode.
3. Characteristic values on known curves: slope, α₀ by inverse interpolation, CD₀, (L/D)max and its α; too few points.
4. Grouping of real SU2 names (CL, CL(Wing), Avg_Massflow(outlet), rms[Rho], Cauchy[CD], LinSolRes, Inner_Iter).
5. Convergence judged on the chosen parameters: a duct with mass flow settled is converged; residuals only → not judged.
6. Schema 5 → 6: the `results` block defaults; a saved block round-trips.
7. Packages: the built-in aero package loads; a user package saves, loads, overrides; availability by columns;
   enabling and disabling adds and removes only what the package brought.
8. Overlays: a second study's rows use this study's formulas; missing columns give empty cells and a note.
9. Web: the picker's search filters; choosing and removing parameters updates the table; Add plot with several Y;
   the line rule (X = α → one line per Mach; X = Mach → one per α; X = CD → joined along α); folding is remembered;
   a clicked point opens Monitor on that case; Copy table and Export CSV contents.
10. CLI `summarize` with saved parameters and derived values; `characteristics.csv`.

# Import SU2 Runs: Design Spec

**Date:** 2026-09-30
**Status:** Agreed with the user (chat, 2026-09-29/30)
**Builds on:** `2026-09-29-results-design.md` (the Results page). Branch: `feat/web-ui-refresh`.

---

## 1. Why and scope

The user has SU2 runs made before AeroSuite (or by hand): **one folder per case, holding its `.cfg` and its
history file**. They want to read them with the Results page (parameters, derived and characteristic values, plots,
export) and compare them with new studies. **Reading only**: re-running imported cases is out of scope for now.

**Decided with the user:**
- A case's values come from its **`.cfg`** (what SU2 actually ran) and from its **folder name**; where both give a
  value, **the cfg wins** and the difference is shown as a warning.
- Folder names are read part by part (§3); parts that are not recognised form the **base name** (which
  configuration: `vt`, `ht`, `clean`…).
- Nothing is copied, moved or changed: the imported study records where each case folder is.

**Out of scope:** re-running imported cases; nested layouts (only the case folders directly inside the chosen folder
are scanned); user-defined name patterns; values that differ between cases other than those in §3 (e.g. the mesh).

## 2. User flow

1. **Projects page → Import SU2 runs** (a card beside *New project*): the runs folder (Browse), the parent folder and
   name of the new study, **Scan**.
2. **Scan preview** (nothing created yet): "N cases found" and a table of the first 10 (folder, Mach, α, β, altitude,
   temperature, Config) with "… and N more", then two folded amber rows (see the mockup
   `assets/2026-09-30-import/preview.png`): **warnings** where name and cfg disagree, **identical ones grouped**
   ("6 cases (M2p5_30km_a0_T200K, …): the cfg's FREESTREAM_TEMPERATURE is 216.65, the name says 200 — 216.65 used"),
   and **skipped folders** with the reason ("no history file", "no .cfg and no Mach in the name", …).
3. **Import** creates the study folder with only `project.json`, adds it to the recent projects and opens its
   Results page.
4. An imported study shows only **Results** and **Monitor** in the sidebar; its switcher line reads
   "imported · N cases". Results has a **Rescan** button: new case folders are added, gone ones dropped, changed
   values updated (the Results settings stay).
5. **Monitor** lists the imported cases and plots each one's history (as *Open file…* does).
6. **CLI:** `aerosuite import <runs-folder> <new-study-folder> [--name N]` prints the same preview and creates the
   study; `aerosuite show` lists the cases and their folders; `aerosuite summarize` works as for any study.

## 3. Reading a case folder

**Which files.** The `.cfg`: the one named like the folder, else the only one, else the one that sets
`MACH_NUMBER` (else: skipped, "several .cfg files, none named like the folder"). The history file: the cfg's
`CONV_FILENAME` (default `history`) with `.csv`, else `.dat`; else any `history*.csv` / `history*.dat` in the
folder. A folder with no history file is skipped.

**From the cfg** (when present and a number): Mach = `MACH_NUMBER`, α = `AOA`, β = `SIDESLIP_ANGLE`,
temperature = `FREESTREAM_TEMPERATURE`.

**From the folder name**, split at `_`, each part matched on its own, in any order (case-insensitive letters; `p` is
the decimal point, `n` a minus sign, as AeroSuite's own names):

| Part | Value | Examples |
|---|---|---|
| `M` + number | Mach | `M2p5` → 2.5, `M1p2` → 1.2, `M0p85` |
| number + `km`, number + `m` | altitude (km) | `30km`, `10p5km`, `11000m` → 11 |
| `a` + number | α (deg) | `a50`, `an4` → −4, `a2p5`; legacy `a5m` → −5 |
| `b` + number | β (deg) | `b6`, `bn2` |
| `T` + number + `K` | temperature (K) | `T200K`, `T216p65K` |
| anything else | part of the base name (joined with `_` in order) | `vt`, `flaps20` |

`sl` counts as altitude 0 (AeroSuite's default label). A part is used once: a second Mach part joins the base name.

**Combining.** Each value comes from the cfg when it has it, else from the name; β defaults to 0 when neither gives
it. Mach and α are required: a case without them is skipped with the reason. When both give a value and they differ
(beyond rounding: relative 1e-6), the cfg value is used and a warning says so ("M1p2_10km_vt_a0_b6: the cfg's
MACH_NUMBER is 1.25, the name says 1.2").

## 4. Data (schema 7)

`Project.imported: Optional[ImportedRuns] = None`:

```
imported:
  source: str                    # the runs folder (absolute)
  cases: [{name, folder, cfg: str | null, history: str, mach, alpha, beta, altitude_km: float | null,
           temperature_K: float | null, base: str}]   # folder/cfg/history absolute
  warnings: [str]                # from the last scan
```

The study's `cases` are the imported ones (so the case names and the switcher count work); its sweep is off and it
has no template or mesh. Older studies migrate unchanged (5 → 6 → 7 no-ops); an older AeroSuite refuses schema 7.

## 5. Engine

- `engine/imported.py`: `read_name(name) -> NameValues` (§3 table), `read_case(folder) -> ImportedCase | Skip`,
  `scan(source) -> Scan(cases, warnings, skipped)`, `create_imported_study(target, source, name)`,
  `rescan(project_dir, project) -> Scan` (updates `imported` and `cases`).
- **Where a case's history is**: `results.case_histories(project_dir, project) -> [(case, path)]`: an imported
  study's recorded files, else `runs/<case>/history.csv`. `history_columns`, `summarize` (a new `histories`
  argument instead of globbing `runs/`), `study_results` and its cache stamp use it.
- **Case values**: the case index of an imported study is built from `imported.cases` (Mach, Alpha, Beta, Altitude,
  Temperature, Config). `summarize` adds a **Temperature** column when any case has one and a **Config** column
  (the base name) when any case has one.
- **Temperature and Config on the Results page** (for every study): Temperature is a numeric variable like
  Altitude (a filter, a table column, an X axis, splits lines, a curve key); Config is a label (filter chips,
  a table column, splits lines, a curve key, never an X axis). Formulas can use `Temperature`.

## 6. Web

- Projects page: the *Import SU2 runs* card (§2), the scan preview in the card, **Import**.
- Sidebar and switcher for imported studies (§2.4); Setup, CFG/Aircraft, Sweep and Run are not offered.
- Results: **Rescan** (imported studies only) with a toast of what changed.
- Monitor: an imported study's case select lists its cases; the chart reads the case's history file (no jobs).
- A clicked point in Results opens that case in Monitor (as for any study).

## 7. Tests to pin

1. Name reading: the user's examples (`M2p5_30km_a50_T200K`, `M1p2_10km_vt_a0_b6`), AeroSuite names
   (`M0p8_sl_a2_b0`, `M0p8_an4_b0_x07`), metres, `p`/`n`, legacy `a5m`, a repeated part, unrecognised parts.
2. Case folders: cfg + csv history; `.dat` history; `CONV_FILENAME` custom; several cfgs; no cfg (name only);
   no history (skipped); no Mach anywhere (skipped); cfg wins over the name with a warning; β defaults to 0.
3. `create_imported_study`: `project.json` only, nothing in the source changed; schema 7; reopen round-trip.
4. Rescan: a new folder is added, a removed one dropped, a changed cfg updated; Results settings kept.
5. Results on an imported study: histories read from the case folders; Temperature and Config columns; Config
   splits lines and filters; derived values with `Temperature`.
6. Web: the import card's preview and Import; the imported study's sidebar; Monitor shows an imported case; Rescan.
7. CLI `import` and `summarize` on the imported study.

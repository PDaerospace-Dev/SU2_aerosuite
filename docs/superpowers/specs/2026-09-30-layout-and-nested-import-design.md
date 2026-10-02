# Results Layout, Projects Layout and Nested Import: Design Spec

**Date:** 2026-09-30
**Status:** Agreed with the user (chat, 2026-09-30)
**Builds on:** `2026-09-29-results-design.md`, `2026-09-30-import-runs-design.md`. Branch: `feat/web-ui-refresh`.

---

## 1. Why and scope

The user's comments after trying the Results page and Import on real data (`st_tail`, 93 cases in 9 group folders):

- Results: the controls (designs, filters, parameters, averaging) take too much height; the four count tiles take a
  whole row; lines of one study all have the same colour; the fixed conditions (Mach, altitude…) are not shown.
- Projects: three forms stacked on the right make the page long and busy.
- Import: runs are often grouped, `st_tail/M0p9_10km/M0p9_10km_a0_b2/…cfg`; only the folders directly inside the
  chosen one were read.

**Decided with the user:** Results layout "F" (mockup `assets/2026-09-30-layout/results-icon-strip.png`); Projects
layout "B" (`assets/2026-09-30-layout/projects-tabs.png`); no hover box on plot points (the default tooltip stays);
no per-case list in a side panel; nested import with the **group folder as Config** when case names clash.

**Out of scope:** new Results features; changing what a filter, parameter or package does.

## 2. Results page

1. **Conditions strip** under the breadcrumbs: one item per case variable (Mach, Altitude, Temperature, α, β,
   Config) over the shown cases: a single value ("0.9"), a short list ("2, 6, 10"), or a range with the count
   ("−10 … 45 · 5") when more than 4 values. Variables with no value are left out. At the right: pills
   "N cases", "C / N converged" (amber when not all converged, plain when none are judged, "not judged") and
   "N designs" (only when comparing). **The four tiles are removed.**
2. **Icon strip** at the left of the plots: Designs, Filters, Parameters, Average, Packages. A click opens that
   panel **over** the plots (one at a time; a second click or ✕ closes it). The panels hold what the Designs card,
   the Parameters card and the Plots head held before (same buttons and chips, same behaviour). The icon shows a
   small count where useful (designs, parameters, packages on).
3. **Plots** use the full width (two columns); *+ Add plot* stays in the Plots head. Characteristic values and the
   Results table stay below, as before. Notes from reading the designs (e.g. unreadable columns) show under the strip.
4. **Line colours:** with one study, **each line has its own colour** (the series colours in order) and a solid line;
   comparing studies, colour = study and line style = the splitting value (as before). The legend drops the study
   name when there is one study. Markers per Y parameter and hollow unconverged points stay.

## 3. Projects page

Two columns: **Recent projects** (wider, with a filter box on name and folder) and one card with three tabs —
**New**, **Open**, **Import SU2 runs** — holding the three forms as they are today. New is the first tab.

## 4. Nested import

1. The scan walks down from the chosen folder (hidden folders and AeroSuite study folders — ones with a
   `project.json` — left out), **at most 4 levels**. A folder that reads as a case (history + Mach and α) is a case
   and is not looked into; other folders are looked into.
2. A folder is listed as **skipped** only when it looks like a case (it holds a `.cfg` or a history file) and cannot
   be read. Empty folders and folders of other files are left out silently (so `results/` or an empty `M1p5_10km/`
   give no warning).
3. Each case records its **group**: the path of its parent folder under the chosen one ("" directly inside). The
   preview's first column shows `group / folder`.
4. **Clashing names** (two case folders with the same name in different groups, e.g. `M3_30km/…` and
   `M3_30km_new/…`): those cases are named `group/folder` and their **Config is the group** (e.g. `M3_30km_new`).
   Other cases keep their folder name and name-derived Config.
5. Rescan uses the same rules. No schema change (names and Config are strings).

## 5. Tests

- Engine: nested scan (depth, stop at a case, silent empty folders, skipped only when case-like, study folders left
  out), clashing names → group names and Config, group in the preview.
- Results view: the conditions text (single, list, range); converged pill text.
- Charts: one study → a colour per line, solid; two studies → colour per study, dashes per line; legend without the
  study name for one study.
- Web: the strip opens and closes panels; existing Results tests open the panel first; tiles gone, strip shown;
  Projects tabs and the filter box.

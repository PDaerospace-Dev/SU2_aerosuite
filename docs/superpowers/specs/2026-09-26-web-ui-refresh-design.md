# AeroSuite Web UI — Visual Refresh ("clean light dashboard") — Design Spec

**Date:** 2026-09-26
**Status:** Draft for review
**Builds on:** `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md`, `2026-09-23-web-config-modes-design.md`, `2026-09-25-web-run-monitor-design.md`. Branch `feat/web-ui-refresh`, stacked on `feat/web-run-monitor`.
**Mockups:** `docs/superpowers/specs/assets/2026-09-26-web-ui-refresh/` — `run.png`, `run-sidebar-collapsed.png`, `setup.png`, `sweep.png`, `monitor.png` (static mockups at 1280×800) and `topbar-reference.jpg` (the user's reference for the top bar).

---

## 1. Why and scope

The web UI works but looks unfinished: NiceGUI's default widgets are stacked in a column with no grouping, statuses are plain words, spacing is uneven and a long folder path sits in the header. The user paused behaviour work to give the **whole web UI** one consistent, modern look.

**Decided with the user:**
- Style **A, "clean light dashboard"** (chosen from options A–D; mockups in the assets folder): light grey page, white cards with thin borders, status pills, summary tiles, and a left sidebar of workflow steps with status dots.
- A **dark top bar** modelled on the user's reference (`topbar-reference.jpg`), adapted to AeroSuite (§2.2).
- The sidebar **collapses to an icon rail** for more working space.
- **Every page** is restyled: Projects, Setup, Config, Aircraft, Sweep, Run and Monitor.

**Out of scope:** any behaviour change (every page does exactly what it does today); dark mode (light only); a search box; the Results page; engine or CLI changes.

## 2. Look and shared building blocks

### 2.1 Tokens (one place: `aerosuite/web/theme.py`)

| Token | Value | Use |
|---|---|---|
| page background | `#f4f5f7` | behind all content |
| card | `#ffffff`, 1px border `#e3e5e8`, radius 10px, no shadow | every content group |
| text / muted | `#1f2328` / `#6a737d` | body / labels, hints, metadata |
| hairline | `#eef0f2` | table row dividers |
| accent | `#2f6fe4` (hover/selected tint `#eef2ff`, text `#2f3fbf`) | selection, links, current step |
| top bar | `#0f1b2d`, controls on `#16263d` with border `#2a3a52`, secondary text `#9fb0c8` | top bar only |
| primary button | `#1f2328` fill, white text | one per page |
| danger button | white fill, border `#ffd7d5`, text `#a40e26` | Cancel job and similar |
| status: Converged / Done | bg `#dafbe1`, text `#116329` | pill |
| status: Running | bg `#ddf4ff`, text `#0550ae` | pill; job indicator dot `#58a6ff` |
| status: Failed | bg `#ffebe9`, text `#a40e26` | pill; failure box bg `#fff5f5`, border `#ffd7d5` |
| status: Unconverged | bg `#fff8c5`, text `#7a5200` | pill |
| status: Pending / Not run | bg `#eef0f2`, text `#57606a` | pill |
| status: Cancelled | white, border `#d0d7de`, text `#57606a` | pill (outline) |
| step dot | done `#1a7f37`, attention `#bf8700`, plain `#8c959f`, later `#d0d7de` | sidebar |
| fonts | system stack (`"Segoe UI", system-ui, -apple-system, Ubuntu, sans-serif`); mono `Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace` | no web fonts (the workstation may be offline) |
| sizes | body 13px; labels/hints 12px; card titles 14px/600; tile numbers 22px/600 | |
| spacing | page padding 24–28px; gap between cards 14–16px; card padding 16px 18px; table cell 8–10px 14px | |

Icons are NiceGUI's bundled Material icons (served locally). `theme.py` sets Quasar's brand colours (`ui.colors`) and adds the component CSS with `ui.add_css`; the existing `apply_theme()` in `layout.py` is replaced by it.

### 2.2 Page frame (rebuilt `ProjectFrame` in `layout.py`)

- **Top bar** (dark, 52px, every project page):
  - left: logo mark + "AeroSuite", then the sidebar collapse toggle («/»);
  - right: the **job indicator** — only while a job of this project is active: a blue dot, "Running", "finished/total · current case" and a small progress bar; clicking it opens Run;
  - a help icon opening a menu with the AeroSuite version and "Web UI guide", which shows the README's web UI section (read from disk, rendered as markdown) in a dialog — works offline;
  - the **project switcher**: a badge with the project's initials, the project name, a second line ("sweep · N cases" or "single case"), and ▾ opening a menu: *All projects* (the Projects page) and the recent projects.
- **Sidebar** (white, 210px; collapsed 64px icon rail): the workflow steps shown today (`visible_steps`), each with an icon, a status dot from `step_badges` and the name; the current page highlighted (`#eef2ff`); steps that are "later" are faded and not links; collapsed, the name shows as a tooltip. The collapsed state is remembered per browser (browser local storage), not in the project.
- **Breadcrumb row** (replaces the big page title): "Projects › <project name> › <Page>" on the left (Projects and the project name are links); on the right an **actions slot** (`frame.actions`) where each page puts its buttons — at most one dark primary button, others outlined or danger.
- **Content**: a column of cards on the page background.
- The **Projects** start page uses the same top bar without the switcher and job indicator, and no sidebar.

### 2.3 Shared helpers (`aerosuite/web/ui_kit.py`, NiceGUI only)

`card(title=None, subtitle=None)` (context manager), `pill(status)`, `status_dot(state)`, `banner(kind, text)` (`info|warning|error|success`), `summary_tile(label, value, tone=None)`, `field` styling for inputs/selects/textareas (label above, rounded box, hint below; `mono=True` for paths), `path_field(...)` (field + Browse), `data_table` building blocks (header row, row, failure-box row), `primary_button`, `secondary_button`, `danger_button`. Pages use these instead of styling widgets themselves. Existing `aerosuite/web/fields.py` helpers keep their signatures and adopt the new styling.

### 2.4 Rules

- Every existing `.mark(...)` marker stays on an element with the same meaning; tests keep finding what they find today.
- Sentence case everywhere ("Submit 6 cases", "Generate configs"); no uppercase Quasar buttons (`no-caps`).
- Warnings/errors above the content they concern as banners; a clean state is one green dot line ("Checks passed · configs are up to date").
- Monospace for job ids, paths and cfg text only.

## 3. Pages (layout only; behaviour unchanged)

- **Projects** — top bar without switcher. Two columns: left card **Recent projects** (rows: name, folder in grey mono, sweep/single tag, latest run status pill; a row opens the project); right cards **Open a project** (folder path field + Browse + Open) and **New project** (name, folder + Browse, aircraft profile select, "Start from SU2's config_template.cfg", primary **Create project**).
- **Setup** (`setup.png`) — cards: **Project** (name; folder read-only mono); **Mesh** (path + Browse + Set; markers as small grey chips); **Study** (Sweep / Single case as two selectable tiles replacing the switch; aircraft profile select; "Apply profile defaults" and "Save as profile…" as secondary buttons). Dialogs use the card look.
- **Config** — two columns: **Template** card with the editor (70vh, mono, "Saved automatically · template.cfg" note) and the **SU2 reference** card (search + option list). Checks as banners above the editor or one green line.
- **Aircraft** (profile projects) — cards: **Numerics** (selects in a 2–3 column grid), **Markers** (checkbox grid), **Placeholders** (read-only list), **Extra SU2 options** (table option / value / delete; add row at the bottom).
- **Sweep** (`sweep.png`) — **Flight conditions** card (Mach, α, β side by side with hints; "Name cases with" checkboxes); **Cases** table card (restart select per row; `custom` path + Browse inline in the row); checks as a status line or banners; **Generate configs** as the primary action in the breadcrumb row.
- **Run** (`run.png`) — four summary tiles (Converged / Running / Needs attention = Failed + Unconverged + Cancelled / Pending = Pending + Not run); **Cases** card (filter chips All / Failed / Unconverged / Not run / None, Continue checkbox on the right, table with pills and the failure reason in a red box under a failed row); **Job history** card (rows with pills); **Cancel job** (danger, only while active) and **Submit N cases** (primary) in the breadcrumb row; preflight problems and plan warnings as banners.
- **Monitor** (`monitor.png`) — left controls card (Case, Open file…, source line with a status pill, Stop/Start, Normalize, column checkboxes with colour swatches matching the chart lines); right **Convergence** chart card filling the remaining width (70vh). Chart: white, thin grid, axis at the bottom, the same colours as the swatches.

## 4. Behaviour of the new frame pieces

- **Job indicator** reads `WATCHER.state(project_dir, project)` on the frame's timer: every 2 s while a job is active (the existing throttle applies), otherwise hidden and not polling job state beyond the existing outside-change check. Jobs started from the CLI or another tab appear too. Progress = finished cases / job cases; current case = the RUNNING case.
- **Project switcher** only navigates (no writes); recent projects come from the existing `recent.py`.
- **Collapse toggle** flips the sidebar between 210px and 64px immediately; the choice is read back on the next page load in that browser.
- A page's own timer and refresh rules (Run, Monitor) are unchanged.

## 5. Error handling

Unchanged: pages show user-facing messages and never crash. The frame's job indicator swallows `AeroSuiteError` (hides itself) so a broken job record never breaks navigation. Banners replace the plain red/amber labels with the same text.

## 6. Testing

- **Safety net:** the whole existing suite (518 tests at the start) must stay green with markers unchanged; a test may change only where it asserts layout itself (e.g. the old header path label) and the change must be named in the task report.
- **New tests** (simulated `user` fixture): top bar shows the switcher with the project name and the breadcrumb for each page; collapse toggle switches the sidebar mode; the job indicator appears while a fake-sweep job runs (with "finished/total" text) and disappears when it ends; `pill()` maps every status to its class/colour; `banner()` kinds; the Projects page shows recent projects as rows.
- **Visual check per page (controller):** headless Chrome screenshots at 1280×800 and 1920×1080 against a fake-sweep project, compared to the mockups; before/after images sent to the user as each page is done.
- No SU2, MPI or real browser in tests; everything passes on Windows and Linux.

## 7. Files

| File | Change |
|---|---|
| `aerosuite/web/theme.py` | new: tokens, Quasar colours, and the component CSS (card, pill, banner, table, sidebar, top bar) added with `ui.add_css` |
| `aerosuite/web/ui_kit.py` | new: shared helpers (§2.3) |
| `aerosuite/web/layout.py` | `ProjectFrame` rebuilt: top bar, collapsible sidebar, breadcrumbs, actions slot, job indicator |
| `aerosuite/web/fields.py` | new styling, same signatures |
| `aerosuite/web/pages/*.py` | each page restyled per §3 |
| `aerosuite/web/picker.py`, dialogs | card look |
| `tests/web/*` | new frame/kit tests; layout-only assertion updates |
| `README.md` | unchanged (its web UI section is what the help dialog shows) |

## 8. Order of work

1. Theme, UI kit and the new frame (top bar, sidebar, breadcrumbs, job indicator) — every page picks up the frame at once.
2. Run. 3. Monitor. 4. Sweep. 5. Setup. 6. Projects. 7. Config. 8. Aircraft.
9. Visual pass over all pages at both sizes; before/after set to the user.

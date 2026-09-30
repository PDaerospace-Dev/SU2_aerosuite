# Results Layout, Projects Layout and Nested Import: Implementation Plan

**Goal:** `docs/superpowers/specs/2026-09-30-layout-and-nested-import-design.md`.

**Constraints:** test first; one commit per task; the full suite stays green (baseline 920 passed, 1 skipped).

## Tasks

1. **Nested import** — `engine/imported.py`: walk (depth 4, stop at a case, skip study and hidden folders, skipped
   only when case-like), `FoundCase.group`, clashing names → `group/folder` and Config = group; preview column.
   Tests: `tests/engine/test_imported.py`, `tests/web/test_web_projects.py`.
2. **Line colours** — `web/results_charts.py`: colour per line with one study; legend without the study name.
   Tests: `tests/web/test_results_charts.py`.
3. **Conditions strip** — `web/results_view.py` (`conditions`, the converged text), `pages/results.py` (strip
   replaces the tiles). Tests: `test_results_view.py`, `test_web_results.py`.
4. **Icon strip and panels** — `pages/results.py`, `theme.py`: Designs, Filters, Parameters, Average, Packages as
   panels over full-width plots. Tests: `test_web_results.py`.
5. **Projects tabs** — `pages/projects.py`, `theme.py`: recent list with a filter box, tabbed New / Open / Import.
   Tests: `test_web_projects.py`. Then README / HANDOVER.

# Import SU2 Runs Implementation Plan

**Goal:** `docs/superpowers/specs/2026-09-30-import-runs-design.md`: read existing SU2 case folders (cfg + history)
into a read-only study that the Results page, Monitor and `summarize` use; Temperature and Config (the base name) as
case variables on the Results page for every study.

**Constraints:** test first; one commit per task; the full suite stays green (baseline 882 passed, 1 skipped). The
source folders are never written. Existing studies behave as before.

## Tasks

1. **Reading names and case folders** — `engine/imported.py`: `read_name`, `read_case` (cfg choice, history file,
   cfg wins with a warning, β default, required Mach/α), `scan` (direct subfolders; warnings grouped by
   (option, cfg value, name value)). Tests: `tests/engine/test_imported.py` (spec §7.1, §7.2).
2. **The imported study** — schema 7 (`ImportedRuns`, `ImportedCase`, `Project.imported`), `create_imported_study`
   (only `project.json`), `rescan`. Tests: same file (§7.3, §7.4).
3. **Histories wherever they are; Temperature and Config** — `results.case_histories`; `summarize(histories=…)`;
   `history_columns`, `study_results` (and its cache stamp) through them; the case index of an imported study
   (Mach, α, β, altitude, temperature, config); Temperature and Config columns in the summary. Tests:
   `test_history_parameters.py`, `test_study_results.py` (§7.5 engine).
4. **Results page with Temperature and Config** — a numeric variable (filter, column, X axis, splits lines, curve
   key, usable in formulas) and a label (filter chips, column, splits lines, curve key, never X); Rescan for imported
   studies. Tests: `test_results_view.py`, `test_results_charts.py`, `test_web_results.py`.
5. **Imported studies in the app** — sidebar (Results, Monitor), switcher line "imported · N cases", Monitor reads an
   imported case's history file. Tests: `test_status.py`, web Monitor test (§7.6).
6. **Import from the Projects page and the CLI** — the Import SU2 runs card (Scan, preview with grouped and folded
   warnings and skipped folders, Import), `aerosuite import`, `show` for imported studies; README and HANDOVER.
   Tests: web projects test, `tests/cli/test_cli_import.py` (§7.6, §7.7).

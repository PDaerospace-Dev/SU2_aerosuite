# Altitude Sweep Implementation Plan

**Goal:** altitude as a fourth sweep dimension in From-altitude mode (spec
`docs/superpowers/specs/2026-09-29-altitude-sweep-design.md`).

**Constraints:** projects in manual mode, and sweep-off projects, behave exactly as before. Test first; one commit
per task. Tests: `uv run pytest -q -p no:cacheprovider`; baseline 727 passed, 1 skipped (`5a1df30`).

## Tasks

1. **Model and migration.** `SweepSpec.altitudes_km`, `Case.altitude_km`, `SCHEMA_VERSION = 5`, `_v4_to_v5`.
   Tests: `tests/engine/test_project.py` (migration fills the list and the cases' altitudes; manual/no-altitude
   projects unchanged).
2. **Cases and configs.** `case_altitude`, `freestream_values(fs, altitude, mach)`, `freestream_for`,
   `freestream_setup_errors(project)`, `build_cases` (altitude outermost, per-case label, carry-over key),
   `render_case`, `case_freestream`, `cases.json`. Preflight uses the new setup errors.
   Tests: `test_freestream.py`, `test_cfg.py`, `test_preflight_freestream.py` (spec §6 items 2–4, 7).
3. **Editing.** `update_sweep(altitudes_km=)`, `set_freestream` rebuild rule, `set_altitudes`.
   Tests: `test_editing.py`.
4. **Results and profiles.** `summarize` Altitude column; `SWEEP_KEYS`, `save_profile`.
   Tests: `test_results.py`, `test_profiles.py`.
5. **CLI.** `set --altitude-km` list via `set_altitudes`; `show` lines. Tests: `tests/cli/test_cli_freestream.py`.
6. **Sweep page.** Altitudes field, Alt column, Set all → Previous per block. Tests: web sweep tests.
7. **Aircraft, Profiles pages and ISA calculator.** Read-only altitudes with link; summary range; profile field;
   ISA prefill and Apply. Tests: web aircraft/profiles tests, `tests/web/test_isa_rules.py`.
8. **Docs.** README (Sweep section), HANDOVER (round two confirmed; altitude sweep done, to check on the
   workstation).

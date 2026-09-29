# Calculators and Freestream from Altitude: Design Spec

**Date:** 2026-09-27
**Status:** Draft for review
**Builds on:** `2026-09-21-aerosuite-web-architecture-design.md` (it lists "Calculators: ISA and y+" for phase 4) and `2026-09-26-web-ui-refresh-design.md` (the look). Branch: stacked on `feat/web-ui-refresh`.
**Mockups:** `docs/superpowers/specs/assets/2026-09-27-calculators/`:
- `placement-page.png`
- `aircraft-manual.png`, `aircraft-altitude.png`
- `sweep-altitude.png`, `sweep-error.png`
- `isa.png`, `apply.png`, `yplus.png`

---

## 1. Why and scope

The old PyQt app had two calculators, **ISA atmosphere** and **y+ first cell height**. Their maths was ported to the engine in phase 0–1 (`aerosuite/engine/atmosphere/`), but the web UI has no page for them. The user wants both in the web UI now, and expects to add more calculators later.

The old app applied **one** Reynolds number, computed for one Mach, to every case. In a Mach sweep that value is only right for one Mach. The user chose to fix this: a project can take its freestream **from an altitude**, and then every case gets its own Reynolds number from its own Mach.

**Decided with the user:**
- **Placement.** The calculators get their own page, opened from a calculator icon in the top bar. It is reachable from every page, including Projects. *Apply to project* appears only when a project is open.
- **Freestream card.** The Aircraft page's Freestream card offers two modes: **Set by hand** (today's fields) and **From altitude**.
- **Altitude label.** In From-altitude mode, the case-name altitude label follows the altitude automatically.
- **General projects.** Apply writes into `template.cfg`, the file the user works in.

**Out of scope:**
- More calculators (the page is built so they are easy to add).
- Changes to the ISA or y+ maths, apart from the numeric validity ranges in §4.3.
- A y+ Apply: AeroSuite does not build meshes.
- Altitude sweeps (one altitude per project).

## 2. Freestream from altitude (engine)

### 2.1 Data

`Freestream` (in `engine/models.py`) gains two fields:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mode` | `"manual"` \| `"altitude"` | `"manual"` | which freestream values the configs get |
| `altitude_km` | float or None | None | ISA altitude for `"altitude"` mode |

- `temperature_K`, `reynolds` and `reynolds_length` stay as they are. `reynolds_length` is used in both modes. The two by-hand values are **kept** while altitude mode is on, so switching back restores them.
- `SCHEMA_VERSION` goes from 3 to 4 with a no-op migration. Existing projects open in manual mode, unchanged. An older AeroSuite refuses a schema-4 file ("saved by a newer AeroSuite") instead of silently dropping the mode.
- Profiles already copy the whole `freestream` group, so the mode and altitude travel with a profile.

### 2.2 Per-case values

New engine function: `freestream_for(settings, mach) -> dict[str, str] | None`.
- It returns `None` in manual mode.
- In altitude mode it returns:
  - `FREESTREAM_TEMPERATURE` = the ISA temperature at the altitude;
  - `REYNOLDS_NUMBER` = ρ·(M·a)·L/μ, from `ISACalculator.calculate(altitude_km, mach, reynolds_length)`;
  - `REYNOLDS_LENGTH` = L.

The number format is the one `cfg._number` already uses.

`case_parameters(project, case)` adds these values in altitude mode:
- With the sweep on, `mach` is the case's own Mach.
- With the sweep off (a single case), `mach` is the template's `MACH_NUMBER` (`template_case_values`), which is the Mach that runs.

Case parameters are the last layer (template → settings → overrides → case values), so in altitude mode the per-case values win over a manual value and over an override of the same key.

### 2.3 Altitude label

In altitude mode the sweep's case-name label is derived: `format_value(altitude_km) + "km"`, so 11 → `11km` and 10.5 → `10p5km`, the same style as Mach (`0p8`). The typed `sweep.altitude` stays stored and comes back in manual mode. It is also used while altitude mode has no altitude yet, so the case names don't change until an altitude is entered.
- `build_cases` uses the derived label in altitude mode.
- Changing the altitude or the mode rebuilds the cases, as a naming change does today.
- Restart choices are kept for cases whose name does not change (existing `build_cases` rule).

### 2.4 Checks (preflight, for generate and submit)

In altitude mode, these block Generate and Submit (errors):
- the altitude is missing or outside 0–100 km;
- the Reynolds length is missing or not greater than 0;
- a case's Mach is 0 or less. This includes a single-case template with no `MACH_NUMBER`. The message names the case and says a Reynolds number cannot be computed.

This is a warning, not an error:
- an override (the Placeholders table, or `--key`) sets `FREESTREAM_TEMPERATURE`, `REYNOLDS_NUMBER` or `REYNOLDS_LENGTH`: "ignored: freestream comes from the altitude".

The existing sidebar badges pick these up (the Sweep and Configs steps show attention).

### 2.5 CLI

`aerosuite set` gains:
- `--freestream manual|altitude`;
- `--altitude-km X`;
- `--reynolds-length L`.

With the project in altitude mode (already, or switched in the same command), `--altitude` (the typed label) is refused with "the altitude label follows --altitude-km in altitude mode". `aerosuite show` prints the mode, and in altitude mode it prints the altitude, the length and each case's Reynolds number.

## 3. Freestream from altitude (web pages)

### 3.1 Aircraft page, Freestream card

Mockups: `aircraft-manual.png`, `aircraft-altitude.png`.
- **Mode choice.** Two choice tiles at the top of the card: **Set by hand** ("One temperature and Reynolds number for every case") and **From altitude** ("Each case gets ISA temperature and its own Reynolds number"). Choosing one saves at once. It is the same radio-as-tiles control as Setup's study type.
- **Set by hand:** today's three fields, unchanged.
- **From altitude:**
  - Two fields, Altitude (km) with the hint "ISA, 0–100 km", and Reynolds length (m).
  - A grey summary strip: the temperature, and the Reynolds number range across the cases ("2.61e7 … 3.48e7, per case from each case's Mach (0.6 – 0.8) · see the Sweep page"). With the altitude invalid, the strip shows the error text instead.
  - A muted line naming the by-hand values being kept: "Kept for Set by hand: temperature 288.15 K, Reynolds number 1.2e7".

### 3.2 Sweep page

Mockups: `sweep-altitude.png`, `sweep-error.png`. These apply in altitude mode only.
- **Altitude label.** The field becomes read-only, shows the derived label, and has the hint "from the altitude on the Aircraft page".
- **Cases table.** It gains read-only **Temperature** and **Reynolds** columns between β and Restart. Each value comes from `freestream_for` (the same function the configs use). A case whose value cannot be computed shows "—".
- **Problems** from §2.4 appear as the usual banners above the page.

## 4. Calculators page

### 4.1 Page and registry

- **Top bar.** A calculator icon (`calculate`) sits left of Help in both top bars (project frame and Projects page). It opens `/calculators`, with `?project=<dir>` when a project is open and `&calc=<key>` naming the open calculator (default: the first one).
- **Layout** (`placement-page.png`, `isa.png`):
  - with a project, the project frame: breadcrumb "Projects › <project> › Calculators", sidebar with no step highlighted;
  - without a project, the Projects-style top bar;
  - on the left, a list of calculators (title and one-line description); on the right, the open calculator's card.
- **Registry.** `aerosuite/web/calculators/__init__.py` holds `CALCULATORS: list[Calculator]`, where `Calculator(key, title, description, build)`. `build(ctx)` draws the card, and `ctx` carries the optional project frame and the values handed over from another calculator. One module per calculator: `isa.py` and `yplus.py`. Adding a calculator means one module plus one registry line.

### 4.2 ISA calculator

Mockups: `isa.png`, `apply.png`.

**Inputs.** Altitude (km), Mach, Characteristic length (m). Results update as you type. Invalid input shows the engine's message under the field (e.g. "Altitude must be between 0 and 100 km") and the results show "—".

**Results** (tiles): temperature, pressure, density, speed of sound, true airspeed, dynamic pressure, dynamic viscosity, Reynolds number. The values Apply writes are highlighted: temperature and Reynolds number.

**Prefill in a project.** A note names where each value came from:
- altitude and length from the project, when it is in altitude mode;
- otherwise the length from `reynolds_length` when set;
- Mach: the sweep's highest Mach; with the sweep off, the template's `MACH_NUMBER`;
- anything else: defaults (0 km, Mach 0.8, 1 m).

**Apply to <project>…** Shown only when a project is open. It opens a confirm dialog listing every change as old → new. Nothing is written before **Apply** is pressed, and **Cancel** changes nothing.
- **Project with an aircraft profile.** Changes:
  - `freestream.mode` → altitude, `altitude_km` → the calculator's altitude, `reynolds_length` → its length;
  - the altitude label becomes the derived one (the dialog says how many cases get renamed).

  The save goes through `frame.save`, so an outside change on disk is refused as elsewhere.
- **General project, sweep off.** The `FREESTREAM_TEMPERATURE`, `REYNOLDS_NUMBER` and `REYNOLDS_LENGTH` lines of `template.cfg` are set (added if missing), using the existing `apply_parameters` and `set_template_text`.
  - The Reynolds number is computed at the **template's** `MACH_NUMBER`, the Mach that runs. When that differs from the calculator's Mach, the dialog says so: "computed for Mach 0.75 (the template's), not 0.8".
  - A template without `MACH_NUMBER` disables Apply with that reason.
- **General project, sweep on.** Apply is disabled, with the reason: "Per-case freestream is set on the Aircraft page, which needs an aircraft profile (Setup)".

**Send to y+ →** opens the y+ calculator with velocity (the true airspeed), density, dynamic viscosity and length handed over. A note there says "From ISA: 11 km, Mach 0.8".

### 4.3 y+ calculator

Mockup: `yplus.png`.

**Inputs.** External / Internal (segmented control), velocity (m/s), density (kg/m³), dynamic viscosity (Pa·s), characteristic length (m), target y+. Results update as you type, and bad input is shown as in ISA.

**Results.** First cell height (highlighted; µm or mm as fits), prism layers (to 0.3 δ), Reynolds number, skin friction Cf, wall shear τw, friction velocity uτ.

**Formula box.** It shows the regime, the formula name, the equation and the validity text, all from the engine's `FORMULAS`.

**Out-of-range note (new).** Each `FORMULAS` entry gains numeric `re_min` / `re_max` values matching its validity text:

| Formula | Range |
|---|---|
| laminar external | Re < 5×10⁵ |
| turbulent external | 5×10⁵ < Re < 10⁷ |
| laminar internal | Re < 2300 |
| turbulent internal | 3000 < Re < 5×10⁶ |

`calculate` returns `in_range: bool`. When it is false, the formula box shows an amber note: "Re = 3.48e7 is outside this formula's valid range; treat the height as an estimate". It is display only, and the results are still shown.

The y+ calculator has no Apply.

## 5. Error handling

- Calculator input errors appear next to the input and never break the page. Engine `ValueError` becomes a field message.
- A failed Apply (refused as stale, invalid on disk, a template write error) leaves the project unchanged and shows the reason as a toast, as other saves do.
- Opening `/calculators` with a project that cannot be opened shows the existing "cannot open" page. An unknown `calc` key falls back to the first calculator.

## 6. Testing

**Engine**
- `freestream_for`: manual gives None; altitude gives the ISA values for known inputs (11 km, 6 m: 216.65 K; Mach 0.6 gives 2.608e7, Mach 0.8 gives 3.477e7).
- Rendered configs: per case in a sweep; the template's Mach for a single case; it wins over an override.
- Preflight errors and the override warning.
- The derived label, and case renames.
- Schema 3→4 migration, and refusal of schema 5.
- The y+ `in_range` flag at both edges of each formula.
- CLI `set` and `show` for the new options.

**Web** (simulated `user` fixture)
- The Freestream mode switch saves, and the by-hand values survive a round trip.
- The Aircraft summary strip shows the range, or the error text.
- The Sweep columns and the read-only label appear only in altitude mode.
- The calculator icon is on both top bars.
- The registry drives the list, and `?calc=` selects a calculator.
- ISA results for known inputs; prefill rules; input errors.
- Apply in each of the three project kinds (aircraft, general single case, general sweep disabled), including the template-Mach note and Cancel.
- Send to y+ hands over the values.
- The out-of-range note.

All existing tests stay green. No SU2 or real browser in tests; everything runs on Windows and Linux.

## 7. Files

| File | Change |
|---|---|
| `aerosuite/engine/models.py` | `Freestream.mode`, `altitude_km`; `SCHEMA_VERSION` = 4 |
| `aerosuite/engine/project.py` | v3→v4 migration (no-op) |
| `aerosuite/engine/cfg.py` | `freestream_for`, per-case values in `case_parameters`, derived label in `build_cases` |
| `aerosuite/engine/preflight.py` | altitude-mode checks |
| `aerosuite/engine/atmosphere/yplus.py` | numeric ranges and `in_range` |
| `aerosuite/cli/project_cmds.py` | `--freestream`, `--altitude-km`, `--reynolds-length`; `show` output |
| `aerosuite/web/pages/aircraft.py` | Freestream mode card and summary strip |
| `aerosuite/web/pages/sweep.py` | read-only label and T/Re columns in altitude mode |
| `aerosuite/web/layout.py` | calculator icon in both top bars |
| `aerosuite/web/calculators/` (new) | registry, `isa.py`, `yplus.py` |
| `aerosuite/web/pages/calculators.py` (new) | the `/calculators` page |
| `aerosuite/web/app.py` | register the page |
| `README.md` | web UI section: the Calculators page and Freestream from altitude |
| `tests/engine/*`, `tests/cli/*`, `tests/web/*` | as in §6 |

## 8. Order of work

1. **Engine.** Model and schema, `freestream_for`, per-case values, derived label, preflight, y+ ranges.
2. **CLI** options and `show`.
3. **Aircraft** Freestream card, then the **Sweep** columns and label.
4. **Calculators page and registry**, then **ISA** with prefill and Apply, then **y+** with Send to y+ and the range note.
5. **README**, then a visual check of every changed page at 1280×800 and 1920×1080 against the mockups.

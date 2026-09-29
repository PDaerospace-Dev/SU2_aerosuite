# Altitude Sweep: Design Spec

**Date:** 2026-09-29
**Status:** Agreed with the user (chat, 2026-09-29)
**Builds on:** `2026-09-27-calculators-design.md` (freestream from altitude; it listed "Altitude sweeps" as out of
scope). Branch: `feat/web-ui-refresh`.

---

## 1. Why and scope

Freestream from altitude gives every case the ISA temperature and its own Reynolds number, but at **one**
altitude per project. The user wants altitude as a fourth sweep dimension, next to Mach, α and β, so one study
covers e.g. 0, 5 and 11 km.

**Decided with the user:**
- **Where.** The altitude list is edited on the **Sweep page**, next to Mach, α and β. The Aircraft page shows it
  read-only with a link to the Sweep page, the way it already shows the sweep's Mach numbers.
- **Only in From-altitude mode.** In Set-by-hand mode the temperature and Reynolds number are typed, so several
  altitudes would give identical configs; there the altitude stays a single typed name label, as today.
- **Case order: altitude outermost** (altitude → Mach → α → β). Each altitude is a complete block; `previous`
  means the case before in that order, as today. The first case of an altitude block restarts from the last case
  of the block before only if the user chose `previous` for it; **Set all → Previous** leaves the first case of
  every altitude block at `none` (as it leaves case 1 today). No special chaining rule.
- **Single case (sweep off)** keeps one altitude, set on the Aircraft page (as the single case's Mach comes from
  the template).

**Out of scope:** altitude sweeps in Set-by-hand mode; a Results page; altitude columns on the Run and Monitor
pages (case names carry the altitude label); parsing altitude from legacy case names without `cases.json`.

## 2. Data (schema 5)

| Where | Field | Meaning |
|---|---|---|
| `SweepSpec` | `altitudes_km: list[float] = []` | the swept altitudes; used when the sweep is on **and** the freestream is from altitude; kept (unused) otherwise |
| `Freestream` | `altitude_km` (unchanged) | the single case's altitude (sweep off) |
| `Case` | `altitude_km: Optional[float] = None` | the case's altitude; set by `build_cases` when the sweep is on and in altitude mode, else `None` |

The two altitude fields mirror Mach: the sweep list for a sweep, one value for a single case. Switching the sweep
on or off switches which one is used; neither is copied into the other.

**Migration 4 → 5:** when `freestream.altitude_km` is set, `sweep.altitudes_km = [altitude_km]`; in altitude
mode with the sweep on, every case gets `altitude_km` = that altitude (so restart choices stay attached). An
older AeroSuite refuses a schema-5 file (existing rule).

`case_altitude(project, case)` returns the altitude a case runs at: `case.altitude_km` with the sweep on, else
`freestream.altitude_km` (cf. `case_mach`).

## 3. Engine behaviour

- **`build_cases`**: loops `altitudes_km or [None]` (altitude mode, sweep on) outermost, else `[None]`. A case's
  name uses its own altitude label (`altitude_label`, e.g. `11km`, `10p5km`); a `None` altitude uses the typed
  label (today's fallback). Restart choices carry over by name, else by `(altitude, Mach, α, β)`, else — in a
  single-altitude sweep only, e.g. after changing that altitude — by `(Mach, α, β)` when one old case has them.
  A newly added altitude's cases start at `none`.
- **Per-case freestream**: `freestream_values(fs, altitude_km, mach)`; `render_case` and `case_freestream` use
  `case_altitude`. `CaseFreestream` gains `altitude_km`.
- **Setup errors** (`freestream_setup_errors(project)`), each reported once:
  - sweep on, altitude mode, empty list → "No altitudes in the sweep";
  - sweep off, no altitude → today's "needs an altitude" message;
  - each distinct altitude outside 0–100 km → today's range message;
  - Reynolds length missing or ≤ 0 → today's message.
- **Editing**:
  - `update_sweep(..., altitudes_km=[..])` stores the list (finite values only; the range is reported by the
    checks, like today) and rebuilds the cases. The typed label stays refused in altitude mode (message now
    points at the Sweep page's altitudes).
  - `set_freestream` rebuilds the cases whenever the rebuilt cases would differ (names or altitudes), e.g. a mode
    switch that changes the case count; an empty Mach sweep still gets no fake Mach-0 case.
  - New `set_altitudes(project, values)`: sweep on → `update_sweep(altitudes_km=values)`; sweep off → exactly one
    value, else "A single case has one altitude" → `set_freestream(altitude_km=value)`. Used by the CLI and the
    ISA calculator's Apply.
- **`cases.json`** adds `"altitude_km"` for cases that have one. **`summarize`** adds an `Altitude` column when any
  case has an altitude and then sorts by Altitude, Mach, Beta, Alpha; otherwise the table is as today.
- **Profiles**: `SWEEP_KEYS` gains `altitudes_km`; `save_profile` stores it.

## 4. Web

- **Sweep page**, Flight conditions card:
  - altitude mode → an **Altitudes (km)** list field (`sweep-altitudes`, same parsing as Mach: `0, 5, 11` or
    `0:12:3`) with the hint "each case is named with its altitude, e.g. 11km";
  - manual mode → the **Altitude label** text field as today (`sweep-altitude`).
- **Case table**, altitude mode: an **Alt (km)** column before Mach (`alt-<case>`); Temperature and Reynolds as
  today, now per altitude.
- **Set all → Previous**: the first case of each altitude block stays `none`.
- **Aircraft page**, From altitude: sweep on → "Altitudes (km)" read-only (`freestream-altitudes-sweep`) and a link
  "Set on the Sweep page"; sweep off → the editable Altitude (km) field as today. The summary strip shows a
  temperature range when the cases' temperatures differ and says "per case, from each case's altitude and Mach".
- **Profiles page**: an **Altitudes (km)** list field next to the Mach/α/β fields (`profile-altitudes_km`).
- **ISA calculator**: pre-fills the first swept altitude ("altitude from the Sweep page"); Apply uses
  `set_altitudes`, so with the sweep on it sets the list to that one altitude; the preview row reads
  "Altitudes  0, 5, 11 km → 11 km".

## 5. CLI

- `aerosuite set --altitude-km 0,5,11` takes a list (ranges too) and goes through `set_altitudes`.
- `aerosuite show` prints `Altitudes: 0, 5, 11 km` in altitude mode with the sweep on; the freestream line no
  longer repeats the altitude in that case.

## 6. Tests to pin

1. Migration: a schema-4 altitude-mode sweep project opens with `altitudes_km=[h]`, cases keep names and restarts.
2. Case order and names: altitudes `[0, 11]` × Mach `[0.6, 0.8]` → `M0p6_0km…, M0p8_0km…, M0p6_11km…, M0p8_11km…`.
3. Each case's config has the temperature of its own altitude and the Reynolds number of its altitude and Mach.
4. Naming without the altitude label and two altitudes → the duplicate-name error.
5. Set all → Previous leaves the first case of each altitude block at `none`.
6. Editing the altitudes on the Sweep page updates the Alt / Temperature / Reynolds columns at once.
7. Switching the sweep off uses `freestream.altitude_km`; `set_altitudes` with two values then refuses.
8. `summarize` with `cases.json` altitudes has an Altitude column; without, the table is unchanged.

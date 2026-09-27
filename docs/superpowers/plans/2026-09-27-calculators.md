# Calculators and Freestream from Altitude Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a project take its freestream from an ISA altitude, so each case gets its own temperature and Reynolds number from its own Mach, and add a Calculators page (ISA and y+) that can apply its results to the project.

**Architecture:** A new NiceGUI-free engine module, `engine/freestream.py`, computes per-case values from `ISACalculator`. `cfg.render_case` adds those values as the last layer, and `build_cases` names cases with the derived altitude label. `editing.set_freestream` is the one way the CLI and the web change the mode or altitude. Preflight and the pages read the same per-case rows (`cfg.case_freestream`). The Calculators page is a registry of self-contained calculator modules under `web/calculators/`. The rules for ISA prefill and Apply live in a NiceGUI-free module there, so they can be unit-tested.

**Tech Stack:** Python 3.12, pydantic 2, Typer, NiceGUI 3.17.1, pytest with the simulated `user` fixture, uv.

**Spec:** `docs/superpowers/specs/2026-09-27-calculators-design.md`. Mockups are in `docs/superpowers/specs/assets/2026-09-27-calculators/`.

## Global Constraints

- Existing behaviour is unchanged for projects in manual mode (the default). Existing projects open unchanged.
- `SCHEMA_VERSION` goes from 3 to 4 with a no-op migration. An older AeroSuite must refuse a schema-4 file.
- Per-case values are the last layer: template → settings → overrides → case values.
- Altitude range: 0–100 km, inclusive. The Reynolds length must be greater than 0. The Mach must be greater than 0.
- Config number format:
  - `FREESTREAM_TEMPERATURE` = `format_value(round(T, 3))`, e.g. `216.65`;
  - `REYNOLDS_NUMBER` = `format_value(round(Re))`, e.g. `34769586`;
  - `REYNOLDS_LENGTH` = `format_value(L)`.
- Derived altitude label: `format_value(altitude_km).replace(".", "p") + "km"`, e.g. `11km`, `10p5km`. The typed label is used while altitude mode has no altitude.
- UI copy is sentence case, built from ui_kit helpers only. Every existing marker stays on an element of the same meaning.
- Display format for large numbers: `sci()` gives three significant figures with a plain exponent, `3.48e7`.
- Tests: `uv run pytest -q -p no:cacheprovider`. Baseline **591 passed** (commit `135dbbc`). No SU2, MPI or real browser in tests. Everything passes on Windows and Linux.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Configs previewed while altitude mode is invalid** (no altitude yet, 120 km). The Config and Aircraft previews show an error banner; they don't crash the page. Pinned in Task 1 (`test_preview_shows_an_error_when_altitude_mode_is_invalid`).
2. **A profile saved from an altitude-mode project, applied to another project.** The mode and altitude carry over, and the case names are rebuilt with the derived label (today `apply_profile` never rebuilds cases). Pinned in Task 1 (`test_applying_a_profile_rebuilds_the_case_names`).
3. **Editing the sweep's Mach numbers in altitude mode.** The Sweep page's Temperature and Reynolds columns follow the new Machs immediately. Pinned in Task 6 (`test_reynolds_column_follows_a_mach_edit`).
4. **ISA at Mach 0, then "Send to y+".** y+ opens with velocity 0 and shows "Velocity must be greater than 0"; it doesn't crash. Pinned in Task 8 (`test_send_to_yplus_with_mach_zero_shows_the_yplus_error`).
5. **`aerosuite set --freestream altitude` with no altitude.** It saves, `show` says the altitude is not set, and generate refuses with the altitude message. Pinned in Task 4 (`test_altitude_mode_without_an_altitude`).

---

## File map

| File | Responsibility |
|---|---|
| `aerosuite/engine/freestream.py` (new) | `FreestreamValues`, `CaseFreestream`, `altitude_label`, `naming_altitude`, `freestream_setup_errors`, `freestream_values`, `freestream_for`, `FREESTREAM_KEYS` |
| `aerosuite/engine/models.py` | `Freestream.mode`, `Freestream.altitude_km`, `SCHEMA_VERSION = 4` |
| `aerosuite/engine/project.py` | `_v3_to_v4` migration |
| `aerosuite/engine/cfg.py` | `case_mach`, `case_freestream`; `render_case` adds per-case values; `build_cases` uses `naming_altitude` |
| `aerosuite/engine/editing.py` | `set_freestream`; `update_sweep` refuses a typed label in altitude mode |
| `aerosuite/engine/profiles.py` | `apply_profile` rebuilds the cases |
| `aerosuite/engine/preflight.py` | altitude-mode problems inside `sweep_problems` |
| `aerosuite/engine/atmosphere/yplus.py` | `re_min`/`re_max` per formula; `in_range` in results |
| `aerosuite/cli/project_cmds.py` | `--freestream`, `--altitude-km`, `--reynolds-length`; `describe()` freestream lines |
| `aerosuite/web/preview.py` | render errors become a banner |
| `aerosuite/web/ui_kit.py` | `sci`, `stat`, `result` |
| `aerosuite/web/theme.py` | CSS for strips, stats, the calculator list and result tiles |
| `aerosuite/web/pages/aircraft.py` | Freestream card with a mode choice and a summary strip |
| `aerosuite/web/pages/sweep.py` | read-only derived label; Temperature and Reynolds columns |
| `aerosuite/web/layout.py` | `calculators_url`, calculator icon in both top bars |
| `aerosuite/web/calculators/__init__.py` (new) | `Calculator`, `CalcContext`, `calculators()` |
| `aerosuite/web/calculators/yplus.py` (new) | y+ card |
| `aerosuite/web/calculators/isa_rules.py` (new, NiceGUI-free) | `isa_prefill`, `ApplyPlan`, `plan_isa_apply` |
| `aerosuite/web/calculators/isa.py` (new) | ISA card, Apply dialog, Send to y+ |
| `aerosuite/web/pages/calculators.py` (new) | `/calculators` page |
| `aerosuite/web/app.py` | register the page |
| `README.md` | web UI and CLI notes |

---

### Task 1: Engine, freestream from altitude

**Files:**
- Create: `aerosuite/engine/freestream.py`, `tests/engine/test_freestream.py`, `tests/web/test_web_freestream_preview.py`
- Modify: `aerosuite/engine/models.py`, `aerosuite/engine/project.py`, `aerosuite/engine/cfg.py`, `aerosuite/engine/editing.py`, `aerosuite/engine/profiles.py`, `aerosuite/web/preview.py`, `aerosuite/web/pages/aircraft.py` (`_rendered_keys` only), `tests/engine/test_project.py`, `tests/engine/test_single_case.py`

**Interfaces:**
- Produces:
  - `models.Freestream.mode: Literal["manual", "altitude"] = "manual"`, `models.Freestream.altitude_km: Optional[float] = None`
  - `freestream.FREESTREAM_KEYS = ("FREESTREAM_TEMPERATURE", "REYNOLDS_NUMBER", "REYNOLDS_LENGTH")`
  - `freestream.FreestreamValues(temperature_K: float, reynolds: float, reynolds_length: float)`
  - `freestream.CaseFreestream(name: str, mach: float, values: Optional[FreestreamValues], error: str)`
  - `freestream.altitude_label(altitude_km: float) -> str`
  - `freestream.naming_altitude(project: Project) -> str`
  - `freestream.freestream_setup_errors(fs: Freestream) -> list[str]`
  - `freestream.freestream_values(fs: Freestream, mach: float) -> FreestreamValues` (raises `ProjectError`)
  - `freestream.freestream_for(settings: Settings, mach: float) -> Optional[dict[str, str]]` (None in manual mode; raises `ProjectError` when invalid)
  - `cfg.case_mach(project: Project, case: Case, template: str) -> float`
  - `cfg.case_freestream(project: Project, template: str) -> list[CaseFreestream]`
  - `editing.set_freestream(project, *, mode=KEEP, altitude_km=KEEP, reynolds_length=KEEP) -> bool`, with `editing.KEEP` the "leave unchanged" sentinel; `None` clears a number

- [ ] **Step 1: Write the failing tests.** Create `tests/engine/test_freestream.py`:

```python
import json

import pytest

from aerosuite.engine.cfg import build_cases, case_freestream, render_case
from aerosuite.engine.editing import set_freestream, update_sweep
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.freestream import (altitude_label, freestream_for, freestream_setup_errors, naming_altitude)
from aerosuite.engine.models import Freestream, Project, Settings
from aerosuite.engine.profiles import apply_profile, load_profile, save_profile
from aerosuite.engine.project import PROJECT_FILE, create_project, open_project, save_project

TEMPLATE = "MACH_NUMBER= 0.3\nREYNOLDS_NUMBER= 1e6\nFREESTREAM_TEMPERATURE= 288.15\n"


def _altitude(altitude_km=11.0, length=6.0) -> Settings:
    return Settings(freestream=Freestream(mode="altitude", altitude_km=altitude_km, reynolds_length=length))


def _sweep_project(**freestream) -> Project:
    project = Project(name="p")
    project.sweep.mach = [0.6, 0.8]
    project.sweep.alpha = [0.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_base = False
    for key, value in freestream.items():
        setattr(project.settings.freestream, key, value)
    project.cases = build_cases(project)
    return project


def test_manual_mode_adds_nothing():
    assert freestream_for(Settings(), 0.8) is None


def test_values_for_known_inputs():
    assert freestream_for(_altitude(), 0.8) == {
        "FREESTREAM_TEMPERATURE": "216.65", "REYNOLDS_NUMBER": "34769586", "REYNOLDS_LENGTH": "6"}
    assert freestream_for(_altitude(), 0.6)["REYNOLDS_NUMBER"] == "26077190"


@pytest.mark.parametrize("altitude, length, mach, message", [
    (None, 6.0, 0.8, "needs an altitude"),
    (120.0, 6.0, 0.8, "outside the standard atmosphere"),
    (-1.0, 6.0, 0.8, "outside the standard atmosphere"),
    (11.0, None, 0.8, "Reynolds length greater than 0"),
    (11.0, 0.0, 0.8, "Reynolds length greater than 0"),
    (11.0, 6.0, 0.0, "must be greater than 0"),
])
def test_invalid_inputs_are_refused(altitude, length, mach, message):
    with pytest.raises(ProjectError, match=message):
        freestream_for(_altitude(altitude, length), mach)


def test_setup_errors_list_every_missing_value():
    errors = freestream_setup_errors(Freestream(mode="altitude"))
    assert len(errors) == 2 and "altitude" in errors[0] and "Reynolds length" in errors[1]


def test_altitude_labels():
    assert (altitude_label(11.0), altitude_label(10.5), altitude_label(0.0)) == ("11km", "10p5km", "0km")


def test_case_names_use_the_derived_label_only_with_an_altitude():
    assert [c.name for c in _sweep_project(mode="altitude").cases] == ["M0p6_sl_a0_b0", "M0p8_sl_a0_b0"]
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    assert naming_altitude(project) == "11km"
    assert [c.name for c in project.cases] == ["M0p6_11km_a0_b0", "M0p8_11km_a0_b0"]


def test_each_case_gets_its_own_reynolds_number_over_an_override():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.settings.overrides["REYNOLDS_NUMBER"] = "5"
    project.settings.freestream.reynolds = 1.2e7  # the kept by-hand value
    texts = [render_case(TEMPLATE, project, case) for case in project.cases]
    assert "REYNOLDS_NUMBER= 26077190" in texts[0] and "REYNOLDS_NUMBER= 34769586" in texts[1]
    assert "FREESTREAM_TEMPERATURE= 216.65" in texts[1] and "REYNOLDS_LENGTH= 6" in texts[1]


def test_a_single_case_uses_the_templates_mach():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.sweep.enabled = False
    project.cases = build_cases(project)
    assert "REYNOLDS_NUMBER= 13038595" in render_case(TEMPLATE, project, project.cases[0])


def test_manual_mode_renders_as_before():
    project = _sweep_project()
    project.settings.freestream.reynolds = 1.2e7
    assert "REYNOLDS_NUMBER= 12000000" in render_case(TEMPLATE, project, project.cases[0])


def test_case_freestream_rows_carry_values_or_the_error():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    rows = case_freestream(project, TEMPLATE)
    assert [(r.name, r.mach, round(r.values.reynolds)) for r in rows] == [
        ("M0p6_11km_a0_b0", 0.6, 26077190), ("M0p8_11km_a0_b0", 0.8, 34769586)]
    project.settings.freestream.altitude_km = 120.0
    assert all(r.values is None and "outside" in r.error for r in case_freestream(project, TEMPLATE))


def test_set_freestream_rebuilds_names_and_keeps_restarts():
    project = _sweep_project()
    assert set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    assert [c.name for c in project.cases] == ["M0p6_11km_a0_b0", "M0p8_11km_a0_b0"]
    project.cases[1].restart = "previous"
    set_freestream(project, reynolds_length=7.0)  # the label doesn't change: names and restarts stay
    assert project.cases[1].restart == "previous"
    set_freestream(project, altitude_km=None)  # cleared: back to the typed label
    assert project.cases[1].name == "M0p8_sl_a0_b0"
    assert not set_freestream(project, mode="altitude")  # no change


def test_set_freestream_refuses_bad_input():
    project = _sweep_project()
    with pytest.raises(ProjectError, match="manual' or 'altitude"):
        set_freestream(project, mode="sky")
    with pytest.raises(ProjectError, match="Altitude must be a number"):
        set_freestream(project, altitude_km=float("nan"))


def test_the_typed_label_is_refused_in_altitude_mode():
    project = _sweep_project(mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    with pytest.raises(ProjectError, match="follows the altitude"):
        update_sweep(project, altitude="cruise")


def test_schema_3_projects_open_in_manual_mode(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 3
    data["settings"]["freestream"] = {"temperature_K": 250.0}
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 4
    assert project.settings.freestream.mode == "manual" and project.settings.freestream.temperature_K == 250.0


def test_applying_a_profile_rebuilds_the_case_names(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))
    source = tmp_path / "source"
    project = create_project(source)
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    save_project(source, project)
    save_profile(source, project, "cruise", "Cruise")
    target = tmp_path / "target"
    other = create_project(target)
    other.sweep.mach, other.sweep.alpha, other.sweep.beta = [0.8], [0.0], [0.0]
    other.cases = build_cases(other)
    apply_profile(target, other, load_profile("cruise"), copy_template=False)
    assert other.settings.freestream.mode == "altitude"
    assert [c.name for c in other.cases] == [c.name for c in build_cases(other)]
    assert "_11km_" in other.cases[0].name
```

Create `tests/web/test_web_freestream_preview.py`:

```python
from nicegui.testing import User

from aerosuite.engine.editing import set_freestream
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


async def test_preview_shows_an_error_when_altitude_mode_is_invalid(user: User, ready_project):
    project_dir, _ = ready_project
    project = open_project(project_dir)
    set_freestream(project, mode="altitude")  # no altitude yet
    save_project(project_dir, project)
    await user.open(project_url("config", project_dir))
    with user:
        next(iter(user.find(marker="preview-toggle").elements)).set_value(True)
    await user.should_see(marker="preview-error")
    await user.should_see("needs an altitude")
```

Update the schema-pinning tests in `tests/engine/test_project.py`:
- `assert project.schema_version == 3` becomes `assert project.schema_version == models.SCHEMA_VERSION`.
- In `test_migrations_run_in_order`, `test_migrate_rejects_missing_migration` and `test_migration_error_propagates`, change the fake next schema from a hard-coded 4 to one past the real one:

```python
    current = models.SCHEMA_VERSION
    monkeypatch.setattr(models, "SCHEMA_VERSION", current + 1)
    ...
    monkeypatch.setattr(project_mod, "MIGRATIONS", {current: v3_to_v4})   # (or {} / {current: broken_migration})
    ...
    assert opened.schema_version == current + 1
```

(Read each test and swap only the numbers; the fake functions keep their bodies.) In `tests/engine/test_single_case.py`, `assert project.schema_version == 3` becomes `== 4`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/engine/test_freestream.py tests/web/test_web_freestream_preview.py tests/engine/test_project.py tests/engine/test_single_case.py -q -p no:cacheprovider`
Expected: collection error `No module named 'aerosuite.engine.freestream'`. The schema tests fail on `4 != 3` once collection passes.

- [ ] **Step 3: Model and migration.** In `aerosuite/engine/models.py` set `SCHEMA_VERSION = 4` and replace `Freestream` with:

```python
FreestreamMode = Literal["manual", "altitude"]


class Freestream(BaseModel):
    # "altitude": each case's temperature and Reynolds number come from the ISA at altitude_km and the
    # case's own Mach; temperature_K and reynolds are then kept (unused) for switching back.
    mode: FreestreamMode = "manual"
    altitude_km: Optional[float] = None
    temperature_K: Optional[float] = None
    reynolds: Optional[float] = None
    reynolds_length: Optional[float] = None
```

In `aerosuite/engine/project.py`, add after `_v2_to_v3`, and register it:

```python
def _v3_to_v4(data: dict, directory: Optional[Path]) -> dict:
    """Schema 4 adds freestream from altitude; older projects keep setting it by hand (the default)."""
    return data


MIGRATIONS: dict[int, Callable[[dict, Optional[Path]], dict]] = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4}
```

- [ ] **Step 4: Create `aerosuite/engine/freestream.py`**

```python
"""Freestream from an ISA altitude: each case's temperature and Reynolds number from its own Mach."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .atmosphere import ISACalculator
from .errors import ProjectError
from .models import Freestream, Project, Settings
from .naming import format_value

FREESTREAM_KEYS = ("FREESTREAM_TEMPERATURE", "REYNOLDS_NUMBER", "REYNOLDS_LENGTH")
ALTITUDE_MIN_KM, ALTITUDE_MAX_KM = 0.0, 100.0


@dataclass(frozen=True)
class FreestreamValues:
    temperature_K: float
    reynolds: float
    reynolds_length: float


@dataclass(frozen=True)
class CaseFreestream:
    name: str
    mach: float  # the Mach the case runs at
    values: Optional[FreestreamValues]  # None when they cannot be computed
    error: str  # why not; "" when values is set


def altitude_label(altitude_km: float) -> str:
    """The case-name label for an altitude, written like Mach: 11 -> '11km', 10.5 -> '10p5km'."""
    return format_value(altitude_km).replace(".", "p") + "km"


def naming_altitude(project: Project) -> str:
    """The altitude label case names use: derived in altitude mode once an altitude is set, else typed."""
    fs = project.settings.freestream
    if fs.mode == "altitude" and fs.altitude_km is not None:
        return altitude_label(fs.altitude_km)
    return project.sweep.altitude


def freestream_setup_errors(fs: Freestream) -> list[str]:
    """What stops altitude mode from computing anything (the same for every case)."""
    errors = []
    if fs.altitude_km is None:
        errors.append("Freestream from altitude needs an altitude (0–100 km)")
    elif not math.isfinite(fs.altitude_km) or not ALTITUDE_MIN_KM <= fs.altitude_km <= ALTITUDE_MAX_KM:
        errors.append(f"Altitude {format_value(fs.altitude_km)} km is outside the standard atmosphere (0–100 km)")
    if fs.reynolds_length is None or not fs.reynolds_length > 0:
        errors.append("Freestream from altitude needs a Reynolds length greater than 0")
    return errors


def freestream_values(fs: Freestream, mach: float) -> FreestreamValues:
    """ISA temperature and the Reynolds number at `mach`; ProjectError when they cannot be computed."""
    errors = freestream_setup_errors(fs)
    if errors:
        raise ProjectError(errors[0])
    if not mach > 0:
        raise ProjectError(f"Mach {format_value(mach)} gives no Reynolds number; the Mach must be greater than 0")
    isa = ISACalculator.calculate(fs.altitude_km, mach, fs.reynolds_length)
    return FreestreamValues(isa["temperature"], isa["reynolds_number"], fs.reynolds_length)


def freestream_for(settings: Settings, mach: float) -> Optional[dict[str, str]]:
    """The per-case config lines in altitude mode (None in manual mode)."""
    if settings.freestream.mode != "altitude":
        return None
    values = freestream_values(settings.freestream, mach)
    return {
        "FREESTREAM_TEMPERATURE": format_value(round(values.temperature_K, 3)),
        "REYNOLDS_NUMBER": format_value(round(values.reynolds)),
        "REYNOLDS_LENGTH": format_value(values.reynolds_length),
    }
```

- [ ] **Step 5: Wire it into `aerosuite/engine/cfg.py`.** Add the import `from .freestream import CaseFreestream, freestream_for, freestream_values, naming_altitude`. Replace `render_case` and add two functions after it:

```python
def case_mach(project: Project, case: Case, template: str) -> float:
    """The Mach a case runs at: its sweep Mach, or the template's MACH_NUMBER for a single case."""
    return case.mach if project.sweep.enabled else template_case_values(template)[0]


def render_case(template: str, project: Project, case: Case) -> str:
    """Template -> settings -> overrides -> case values; later layers win."""
    params = settings_parameters(project.settings)
    params.update(case_parameters(project, case))
    freestream = freestream_for(project.settings, case_mach(project, case, template))
    if freestream:
        params.update(freestream)  # per case, so it wins over a by-hand value and an override
    return apply_parameters(template, params)


def case_freestream(project: Project, template: str) -> list[CaseFreestream]:
    """Each case's altitude-mode values, or why they cannot be computed (for checks and the pages)."""
    rows = []
    for case in project.cases:
        mach = case_mach(project, case, template)
        try:
            rows.append(CaseFreestream(case.name, mach, freestream_values(project.settings.freestream, mach), ""))
        except ProjectError as exc:
            rows.append(CaseFreestream(case.name, mach, None, str(exc)))
    return rows
```

In `build_cases`, change `altitude=sweep.altitude,` to `altitude=naming_altitude(project),`.

- [ ] **Step 6: `set_freestream` and the label refusal** in `aerosuite/engine/editing.py`. Add `from typing import Any` to the imports and `from .freestream import naming_altitude`. Then add:

```python
KEEP: Any = object()  # set_freestream: leave this field as it is


def set_freestream(project: Project, *, mode: Any = KEEP, altitude_km: Any = KEEP,
                   reynolds_length: Any = KEEP) -> bool:
    """Change how configs get their freestream (None clears a number); rebuild the cases when the altitude
    label in their names changes. Returns whether anything changed."""
    fs = project.settings.freestream
    if mode is not KEEP and mode not in ("manual", "altitude"):
        raise ProjectError(f"Freestream mode must be 'manual' or 'altitude', not {mode!r}")
    for what, value in (("Altitude", altitude_km), ("Reynolds length", reynolds_length)):
        if value is not KEEP and value is not None and not math.isfinite(value):
            raise ProjectError(f"{what} must be a number")
    before = (fs.mode, fs.altitude_km, fs.reynolds_length)
    label = naming_altitude(project)
    if mode is not KEEP:
        fs.mode = mode
    if altitude_km is not KEEP:
        fs.altitude_km = altitude_km
    if reynolds_length is not KEEP:
        fs.reynolds_length = reynolds_length
    if naming_altitude(project) != label:
        project.cases = build_cases(project)
    return (fs.mode, fs.altitude_km, fs.reynolds_length) != before
```

In `update_sweep`, before `if altitude is not None:` add:

```python
    if altitude is not None and project.settings.freestream.mode == "altitude":
        raise ProjectError("The altitude label follows the altitude in altitude mode "
                           "(set the altitude on the Aircraft page, or with --altitude-km)")
```

(`editing.py` already imports `math`, `build_cases`, `ProjectError` and `Project`.)

- [ ] **Step 7: Rebuild cases when applying a profile.** In `aerosuite/engine/profiles.py`, add at the end of `apply_profile` (after `project.profile = profile.id`):

```python
    project.cases = build_cases(project)  # the profile's naming or altitude may change case names
```

Add `from .cfg import build_cases` to the imports. If that creates an import cycle (`cfg` must not import `profiles`), import it inside the function instead.

- [ ] **Step 8: Preview errors become a banner.** In `aerosuite/web/preview.py`, the `render()` body currently renders with `ui.code(render_case(template, project, case), ...)`. Render inside the same `try`:

```python
            try:
                template = read_template(frame.session.directory, project)
                case = next(case for case in project.cases if case.name == state["case"])
                text = render_case(template, project, case)
            except AeroSuiteError as exc:
                banner("error", f"Error: {exc}").mark("preview-error")
                return
            ui.code(text, language="ini").classes("w-full as-mono").mark("preview")
```

Also in `aerosuite/web/pages/aircraft.py`, `_rendered_keys` renders the first case for the reference panel's "In config" marks. Wrap its `render_case` call too, so an invalid altitude mode cannot break the Aircraft page:

```python
    if not project.cases:
        return keys_in(template)
    try:
        return keys_in(render_case(template, project, project.cases[0]))
    except AeroSuiteError:
        return keys_in(template)
```

- [ ] **Step 9: Run the tests, then the whole suite**

Run: `uv run pytest tests/engine/test_freestream.py tests/web/test_web_freestream_preview.py tests/engine/test_project.py tests/engine/test_single_case.py tests/engine/test_profiles.py -q -p no:cacheprovider` → PASS.
Run: `uv run pytest -q -p no:cacheprovider` → all pass. If a test fails because `apply_profile` now rebuilds cases (a case list compared before and after), check whether the old list was stale. Fix the test only if the new names are the correct ones, and name it in the report.

- [ ] **Step 10: Commit**

```bash
git add aerosuite/engine aerosuite/web/preview.py aerosuite/web/pages/aircraft.py tests/engine tests/web/test_web_freestream_preview.py
git commit -m "feat(engine): take the freestream from an ISA altitude, per case from each case's Mach

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Preflight checks for altitude mode

**Files:**
- Modify: `aerosuite/engine/preflight.py`
- Test: `tests/engine/test_preflight_freestream.py` (new)

**Interfaces:**
- Consumes: `cfg.case_freestream`, `freestream.freestream_setup_errors`, `freestream.FREESTREAM_KEYS`.
- Produces: `sweep_problems(project, project_dir=None)` also returns altitude-mode problems. The sidebar badges and `preflight` pick them up through it.

- [ ] **Step 1: Write the failing tests**

```python
from aerosuite.engine.cfg import build_cases
from aerosuite.engine.editing import set_freestream
from aerosuite.engine.preflight import preflight, sweep_problems
from aerosuite.engine.project import save_project


def _messages(problems, severity):
    return [p.message for p in problems if p.severity == severity]


def test_manual_mode_adds_no_problems(ready_project):
    project_dir, project = ready_project
    assert not [m for m in _messages(sweep_problems(project, project_dir), "error") if "altitude" in m.lower()]


def test_missing_altitude_and_length_are_both_errors(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude")
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("needs an altitude" in e for e in errors)
    assert any("Reynolds length greater than 0" in e for e in errors)


def test_out_of_range_altitude_is_an_error(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=120.0, reynolds_length=6.0)
    assert any("outside the standard atmosphere" in e for e in _messages(sweep_problems(project, project_dir), "error"))


def test_a_single_case_without_a_template_mach_is_an_error(ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").write_text("AOA= 0.0\n")
    project.sweep.enabled = False
    project.cases = build_cases(project)
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    errors = _messages(sweep_problems(project, project_dir), "error")
    assert any(e.startswith(f"{project.cases[0].name}: ") and "MACH_NUMBER" in e for e in errors)


def test_a_valid_altitude_project_has_no_freestream_problems(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    save_project(project_dir, project)
    assert not any("altitude" in p.message.lower() or "reynolds" in p.message.lower()
                   for p in sweep_problems(project, project_dir))


def test_overrides_of_freestream_keys_are_a_warning(ready_project):
    project_dir, project = ready_project
    set_freestream(project, mode="altitude", altitude_km=11.0, reynolds_length=6.0)
    project.settings.overrides["REYNOLDS_NUMBER"] = "5"
    warnings = _messages(sweep_problems(project, project_dir), "warning")
    assert "REYNOLDS_NUMBER ignored: freestream comes from the altitude" in warnings
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/engine/test_preflight_freestream.py -q -p no:cacheprovider`
Expected: the error and warning tests FAIL (no such problems yet). The manual-mode and valid tests pass.

- [ ] **Step 3: Implement** in `aerosuite/engine/preflight.py`. Add the imports `from .cfg import case_freestream` (extend the existing `from .cfg import ...` line) and `from .freestream import FREESTREAM_KEYS, freestream_setup_errors`. Add:

```python
def _template_text(project: Project, project_dir: Optional[Path]) -> str:
    """The template text for per-case checks; "" when there is no folder or it cannot be read."""
    if project_dir is None:
        return ""
    try:
        return (Path(project_dir) / project.template).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _freestream_problems(project: Project, project_dir: Optional[Path]) -> list[Problem]:
    fs = project.settings.freestream
    if fs.mode != "altitude":
        return []
    problems = [Problem("error", message) for message in freestream_setup_errors(fs)]
    if not problems:
        for row in case_freestream(project, _template_text(project, project_dir)):
            if row.values is None:
                reason = ("the template's MACH_NUMBER is missing or 0, so no Reynolds number can be computed"
                          if not project.sweep.enabled else row.error)
                problems.append(Problem("error", f"{row.name}: {reason}"))
    for key in FREESTREAM_KEYS:
        if key in project.settings.overrides:
            problems.append(Problem("warning", f"{key} ignored: freestream comes from the altitude"))
    return problems
```

In `sweep_problems`, before `problems += _restart_problems(project, project_dir)`, add `problems += _freestream_problems(project, project_dir)`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/engine/test_preflight_freestream.py tests/engine/test_preflight.py tests/engine/test_preflight_sweep.py tests/web/test_status.py -q -p no:cacheprovider` → PASS. Then `uv run pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/preflight.py tests/engine/test_preflight_freestream.py
git commit -m "feat(engine): check altitude-mode freestream before generating or running

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: y+ formula validity ranges

**Files:**
- Modify: `aerosuite/engine/atmosphere/yplus.py`
- Test: `tests/engine/test_atmosphere.py` (append)

**Interfaces:**
- Produces: each `FORMULAS` entry gains `re_min: Optional[float]` and `re_max: Optional[float]` (exclusive bounds). `calculate(...)` returns an extra key `in_range: bool`.

- [ ] **Step 1: Write the failing tests** (append to `tests/engine/test_atmosphere.py`). With density 1, viscosity 1 and length 1, Re equals the velocity:

```python
@pytest.mark.parametrize("domain, velocity, in_range", [
    ("External", 1e5, True),          # laminar, Re < 5e5
    ("External", 5e5, False),         # turbulent from 5e5; its range is 5e5 < Re (exclusive)
    ("External", 500_001, True),
    ("External", 9_999_999, True),
    ("External", 1e7, False),
    ("External", 3.4e7, False),
    ("Internal", 2299, True),         # laminar pipe, Re < 2300
    ("Internal", 2500, False),        # transitional: turbulent formula, valid from 3000
    ("Internal", 3001, True),
    ("Internal", 5e6, False),
])
def test_yplus_reports_whether_re_is_in_the_formulas_range(domain, velocity, in_range):
    r = yplus(velocity=velocity, density=1.0, viscosity=1.0, length=1.0, y_plus=1.0, domain_type=domain)
    assert r["Re"] == pytest.approx(velocity)
    assert r["in_range"] is in_range
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/engine/test_atmosphere.py -q -p no:cacheprovider`
Expected: FAIL with `KeyError: 'in_range'`.

- [ ] **Step 3: Implement.** In `FORMULAS` add to each entry:
  - `("Laminar", "External")`: `"re_min": None, "re_max": 5e5`
  - `("Turbulent", "External")`: `"re_min": 5e5, "re_max": 1e7`
  - `("Laminar", "Internal")`: `"re_min": None, "re_max": 2300.0`
  - `("Turbulent", "Internal")`: `"re_min": 3000.0, "re_max": 5e6`

In `calculate`, before `return`, add:

```python
    re_min, re_max = formula["re_min"], formula["re_max"]
    in_range = (re_min is None or Re > re_min) and (re_max is None or Re < re_max)
```

Add `"in_range": in_range,` to the returned dict, and `in_range` to the docstring's key list.

- [ ] **Step 4: Run** `uv run pytest tests/engine/test_atmosphere.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/atmosphere/yplus.py tests/engine/test_atmosphere.py
git commit -m "feat(engine): say when y+ uses a skin-friction formula outside its Reynolds range

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: CLI options and `show`

**Files:**
- Modify: `aerosuite/cli/project_cmds.py`
- Test: `tests/cli/test_cli_freestream.py` (new)

**Interfaces:**
- Consumes: `editing.set_freestream`, `editing.KEEP`, `cfg.case_freestream`, `cfg.read_template`, `freestream.naming_altitude`, `freestream.FREESTREAM_KEYS`.
- Produces: `aerosuite set --freestream manual|altitude --altitude-km X --reynolds-length L`. `describe()` gains a `Freestream:` line and, in altitude mode, `Re=` per case.

- [ ] **Step 1: Write the failing tests**

```python
from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.project import create_project, open_project

runner = CliRunner()


def _sweep(tmp_path):
    folder = tmp_path / "study"
    create_project(folder)
    (folder / "template.cfg").write_text("MACH_NUMBER= 0.3\n")
    result = runner.invoke(app, ["set", str(folder), "--mach", "0.6,0.8", "--alpha", "0", "--beta", "0"])
    assert result.exit_code == 0, result.output
    return folder


def test_set_altitude_mode_renames_cases_and_show_lists_reynolds(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude-km", "11",
                                 "--reynolds-length", "6"])
    assert result.exit_code == 0, result.output
    project = open_project(folder)
    assert project.settings.freestream.mode == "altitude"
    assert "_11km_" in project.cases[0].name
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Freestream: from altitude 11 km, Reynolds length 6 m" in shown
    assert "Re=26077190" in shown and "Re=34769586" in shown


def test_the_typed_label_is_refused_in_altitude_mode(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "altitude", "--altitude", "cruise"])
    assert result.exit_code != 0
    assert "follows the altitude" in result.output
    assert open_project(folder).settings.freestream.mode == "manual"  # nothing saved


def test_altitude_mode_without_an_altitude(tmp_path):
    folder = _sweep(tmp_path)
    assert runner.invoke(app, ["set", str(folder), "--freestream", "altitude"]).exit_code == 0
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Freestream: from altitude (altitude not set)" in shown
    generated = runner.invoke(app, ["generate", str(folder)])
    assert generated.exit_code != 0 and "needs an altitude" in generated.output


def test_a_bad_mode_is_refused(tmp_path):
    folder = _sweep(tmp_path)
    result = runner.invoke(app, ["set", str(folder), "--freestream", "sky"])
    assert result.exit_code != 0


def test_manual_mode_show_is_unchanged_apart_from_the_mode_line(tmp_path):
    folder = _sweep(tmp_path)
    shown = runner.invoke(app, ["show", str(folder)]).output
    assert "Freestream: set by hand" in shown and "Re=" not in shown
```

(Check how `generate` reports refusals in `tests/cli/` — a `GenerationError`/preflight message on the output with a non-zero exit. If `generate` has no project mesh here and fails for "No mesh selected" first, create a mesh file as `tests/cli/test_cli_set.py`-style tests do, or assert only on the `show` output and a direct `preflight` call. Name the choice in the report.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/cli/test_cli_freestream.py -q -p no:cacheprovider`
Expected: FAIL with "No such option: --freestream".

- [ ] **Step 3: Implement** in `aerosuite/cli/project_cmds.py`. Add the imports `from ..engine.editing import KEEP, set_freestream` (extend the existing editing import), `from ..engine.cfg import case_freestream, read_template` (extend), `from ..engine.freestream import naming_altitude`, and `from ..engine.errors import AeroSuiteError` if it is not already there. Add to the `set_` parameters:

```python
    freestream: Annotated[Optional[str], typer.Option(
        help="Freestream: 'manual' (set by hand) or 'altitude' (per case from --altitude-km)")] = None,
    altitude_km: Annotated[Optional[float], typer.Option(help="ISA altitude in km for altitude mode (0–100)")] = None,
    reynolds_length: Annotated[Optional[float], typer.Option(help="Reynolds length in m")] = None,
```

In the body, right after `changes: list[str] = []` (before the `--key` loop, so a refused label leaves nothing half-applied):

```python
    if set_freestream(
        project,
        mode=freestream if freestream is not None else KEEP,
        altitude_km=altitude_km if altitude_km is not None else KEEP,
        reynolds_length=reynolds_length if reynolds_length is not None else KEEP,
    ):
        changes.append("freestream")
```

`update_sweep` runs later with `altitude=`, and raises in altitude mode. `engine_errors` turns that into an exit code, and nothing is saved, because saving happens at the end.

In `describe()`:
- Replace the `Altitude:` line with `f"Altitude:  {naming_altitude(project)}"`.
- After the sweep lines, add:

```python
    fs = project.settings.freestream
    if fs.mode == "altitude":
        if fs.altitude_km is None:
            lines.append("Freestream: from altitude (altitude not set)")
        else:
            length = "not set" if fs.reynolds_length is None else f"{format_value(fs.reynolds_length)} m"
            lines.append(f"Freestream: from altitude {format_value(fs.altitude_km)} km, Reynolds length {length}")
    else:
        lines.append("Freestream: set by hand")
```

In the cases loop, add the Reynolds number per case in altitude mode:

```python
    reynolds: dict[str, str] = {}
    if fs.mode == "altitude":
        try:
            template = read_template(project_dir, project)
        except AeroSuiteError:
            template = ""
        reynolds = {row.name: f"  Re={round(row.values.reynolds)}" if row.values else "  Re=—"
                    for row in case_freestream(project, template)}
```

Append `reynolds.get(case.name, "")` to each case line (both branches). Import `format_value` from `..engine.naming` if not present.

- [ ] **Step 4: Run** `uv run pytest tests/cli -q -p no:cacheprovider` → PASS, then the whole suite.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/cli/project_cmds.py tests/cli/test_cli_freestream.py
git commit -m "feat(cli): set freestream from altitude and show each case's Reynolds number

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Aircraft page, Freestream card

**Files:**
- Modify: `aerosuite/web/pages/aircraft.py`, `aerosuite/web/ui_kit.py`, `aerosuite/web/theme.py`
- Test: `tests/web/test_web_aircraft.py` (append), `tests/web/test_ui_kit.py` (append)

**Interfaces:**
- Consumes: `editing.set_freestream`, `cfg.case_freestream`, `cfg.read_template`, `session.parse_optional_number`.
- Produces:
  - `ui_kit.sci(value: float) -> str` (`34769586 → "3.48e7"`, `0.00226 → "0.00226"`)
  - `ui_kit.stat(label: str, value: str) -> ui.label` (returns the value label)
  - CSS classes `as-strip`, `as-stat-label`, `as-stat-value`
  - Markers: `freestream-mode`, `freestream-altitude_km`, `freestream-summary`, `freestream-summary-error`, `freestream-kept`. The manual fields keep `freestream-temperature_K`, `freestream-reynolds` and `freestream-reynolds_length`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_ui_kit.py`:

```python
from aerosuite.web.ui_kit import sci


def test_sci_is_three_significant_figures_with_a_plain_exponent():
    assert (sci(34769586), sci(26077190), sci(0.00226), sci(5.134e-06), sci(216.65)) == (
        "3.48e7", "2.61e7", "0.00226", "5.13e-6", "217")
```

Append to `tests/web/test_web_aircraft.py` (it has `_element`, `_with_x07`, `_open`):

```python
from aerosuite.engine.freestream import naming_altitude
from aerosuite.engine.project import open_project as _open_project


def _shown(user, marker) -> bool:
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


async def test_freestream_switches_to_altitude_and_back_keeping_the_hand_values(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="freestream-temperature_K").clear().type("250").trigger("blur")
    _element(user, "freestream-mode").set_value("altitude")
    assert _open_project(project_dir).settings.freestream.mode == "altitude"
    await user.should_see(marker="freestream-altitude_km")
    assert not _shown(user, "freestream-temperature_K")
    user.find(marker="freestream-altitude_km").clear().type("11").trigger("blur")
    user.find(marker="freestream-reynolds_length").clear().type("6").trigger("blur")
    project = _open_project(project_dir)
    # (the ready project leaves the altitude out of case names, so check the label, not the names)
    assert project.settings.freestream.altitude_km == 11.0 and naming_altitude(project) == "11km"
    await user.should_see("216.65 K")
    await user.should_see(marker="freestream-kept")
    _element(user, "freestream-mode").set_value("manual")
    await user.should_see(marker="freestream-temperature_K")
    assert _element(user, "freestream-temperature_K").value == "250"


async def test_the_summary_shows_the_error_for_a_bad_altitude(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    _element(user, "freestream-mode").set_value("altitude")
    user.find(marker="freestream-altitude_km").clear().type("120").trigger("blur")
    await user.should_see(marker="freestream-summary-error")
    assert "outside the standard atmosphere" in _element(user, "freestream-summary-error").text
```

(The ready project sweeps Mach 0.8 only, so a single Reynolds number is shown, not a range. `_with_x07` may set a Reynolds length from the profile; the test types 6 anyway.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_ui_kit.py tests/web/test_web_aircraft.py -q -p no:cacheprovider`
Expected: FAIL (`cannot import name 'sci'`, then no `freestream-mode` marker).

- [ ] **Step 3: Kit and CSS.** Append to `aerosuite/web/ui_kit.py`:

```python
def sci(value: float) -> str:
    """Three significant figures with a plain exponent: 34769586 -> '3.48e7', 0.00226 -> '0.00226'."""
    text = f"{value:.3g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}e{int(exponent)}"
    return text


def stat(label: str, value: str) -> ui.label:
    """A small caption over a bold value, for summary strips; returns the value label."""
    with ui.column().classes("gap-0"):
        ui.label(label).classes("as-stat-label")
        return ui.label(value).classes("as-stat-value")
```

Add to `BASE_CSS` in `aerosuite/web/theme.py` (before the `.as-grid-2, ...` block):

```css
.as-strip { background: #f6f8fa; border-radius: 8px; padding: 10px 12px; gap: 28px; align-items: center;
  flex-wrap: wrap; width: 100%; }
.as-stat-label { font-size: 11px; color: var(--as-muted); }
.as-stat-value { font-weight: 600; }
```

- [ ] **Step 4: The Freestream card** in `aerosuite/web/pages/aircraft.py`. Remove the `"Freestream": [...]` entry from `NUMBER_FIELDS`. Add the imports: `from ...engine.cfg import case_freestream` (extend the existing cfg import); `from ...engine.editing import set_freestream` (extend); `from ...engine.errors import AeroSuiteError` (already imported); `from ..ui_kit import ..., hint, sci, stat` (extend). In `_build`, call `holders["freestream"] = _freestream(frame, hints, after)` before the `NUMBER_FIELDS` loop, inside the left column. Add:

```python
MODE_CHOICES = {
    "manual": "Set by hand · one temperature and Reynolds number for every case",
    "altitude": "From altitude · each case gets ISA temperature and its own Reynolds number",
}


def _freestream(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    with card("Freestream"):
        box = ui.column().classes("w-full gap-3")

    def both() -> None:
        render()
        after()

    def choose(mode: str) -> None:
        message = frame.save(lambda p: set_freestream(p, mode=mode), then=both)
        if message:
            ui.notify(message, type="negative")

    def number(label: str, name: str, value, placeholder: str) -> None:
        text_field(label, "" if value is None else format_value(value),
                   lambda text: frame.save(
                       lambda p: set_freestream(p, **{name: parse_optional_number(text, label)}), then=both),
                   mark=f"freestream-{name}", placeholder=placeholder)

    def render() -> None:
        # Plain synchronous rebuild: tests read these fields right after a change.
        box.clear()
        fs = frame.session.project.settings.freestream
        with box:
            ui.radio(MODE_CHOICES, value=fs.mode, on_change=lambda e: choose(e.value)).props("inline").classes(
                "as-choice").mark("freestream-mode")
            if fs.mode == "manual":
                with ui.element("div").classes("as-grid-3"):
                    for label, name in (("Temperature (K)", "temperature_K"), ("Reynolds number", "reynolds"),
                                        ("Reynolds length", "reynolds_length")):
                        with ui.column().classes("gap-1"):
                            _number_field(frame, hints, label, "freestream", name, "float", both)
                return
            with ui.element("div").classes("as-grid-2"):
                with ui.column().classes("gap-1"):
                    number("Altitude (km)", "altitude_km", fs.altitude_km, "ISA, 0–100 km")
                with ui.column().classes("gap-1"):
                    number("Reynolds length (m)", "reynolds_length", fs.reynolds_length,
                           "characteristic length for the Reynolds number")
            _summary(frame)
            kept = [f"temperature {format_value(fs.temperature_K)} K" if fs.temperature_K is not None else "",
                    f"Reynolds number {sci(fs.reynolds)}" if fs.reynolds is not None else ""]
            kept = [part for part in kept if part]
            if kept:
                hint("Kept for Set by hand: " + ", ".join(kept)).mark("freestream-kept")

    render()
    return render


def _summary(frame: ProjectFrame) -> None:
    """Temperature and the Reynolds range the cases get, or why they can't be computed."""
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        template = ""
    rows = case_freestream(project, template)
    with ui.row().classes("as-strip").mark("freestream-summary"):
        if not rows:
            ui.label("No cases yet").classes("as-muted")
            return
        failed = next((row for row in rows if row.values is None), None)
        if failed is not None:
            ui.label(failed.error).classes("as-error-text").mark("freestream-summary-error")
            return
        reynolds = sorted(row.values.reynolds for row in rows)
        machs = sorted(row.mach for row in rows)
        stat("Temperature", f"{format_value(round(rows[0].values.temperature_K, 2))} K")
        span = sci(reynolds[0]) if sci(reynolds[0]) == sci(reynolds[-1]) else f"{sci(reynolds[0])} … {sci(reynolds[-1])}"
        stat("Reynolds number", span)
        if project.sweep.enabled:
            where = (f"per case, from each case's Mach ({format_value(machs[0])} – {format_value(machs[-1])})"
                     if machs[0] != machs[-1] else f"at Mach {format_value(machs[0])}")
            ui.label(where + " · see the Sweep page").classes("as-muted")
        else:
            ui.label(f"at the template's Mach {format_value(machs[0])}").classes("as-muted")
```

(`read_template`, `format_value` and `parse_optional_number` are already imported by `aircraft.py`; add any that are missing. `_number_field`'s change function sets the field with `setattr`, which is right for the manual fields.)

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_aircraft.py tests/web/test_ui_kit.py -q -p no:cacheprovider` → PASS. Then `uv run pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 6: Controller visual check.** Start the demo server (scratchpad `visual/demo.py make` + `aerosuite serve`, as in the previous plan). In the Browser pane, open the aircraft demo project's Aircraft page at 1280×800. Switch to From altitude and enter 11 and 6. Compare with `docs/superpowers/specs/assets/2026-09-27-calculators/aircraft-altitude.png` and screenshot it for the user.

- [ ] **Step 7: Commit**

```bash
git add aerosuite/web/pages/aircraft.py aerosuite/web/ui_kit.py aerosuite/web/theme.py tests/web/test_web_aircraft.py tests/web/test_ui_kit.py
git commit -m "feat(web): choose freestream by hand or from altitude on the Aircraft page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sweep page, derived label and per-case columns

**Files:**
- Modify: `aerosuite/web/pages/sweep.py`
- Test: `tests/web/test_web_sweep.py` (append)

**Interfaces:**
- Consumes: `freestream.naming_altitude`, `cfg.case_freestream`, `cfg.read_template`, `ui_kit.sci`, `ui_kit.hint`.
- Produces: markers `sweep-altitude` (read-only in altitude mode), `sweep-altitude-note`, `temp-<case>`, `re-<case>`.

- [ ] **Step 1: Write the failing tests** (append to `tests/web/test_web_sweep.py`):

```python
from aerosuite.engine.editing import set_freestream


def _altitude_mode(project_dir, altitude_km=11.0):
    project = open_project(project_dir)
    set_freestream(project, mode="altitude", altitude_km=altitude_km, reynolds_length=6.0)
    save_project(project_dir, project)
    return project


async def test_altitude_mode_shows_the_derived_label_and_per_case_values(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir)
    await _open(user, project_dir)
    label = _element(user, "sweep-altitude")
    assert label.value == "11km" and "readonly" in label.props
    await user.should_see(marker="sweep-altitude-note")
    name = project.cases[0].name
    assert _element(user, f"temp-{name}").text == "216.65 K"
    assert _element(user, f"re-{name}").text == "3.48e7"


async def test_reynolds_column_follows_a_mach_edit(user: User, ready_project):
    project_dir, _ = ready_project
    _altitude_mode(project_dir)
    await _open(user, project_dir)
    user.find(marker="sweep-mach").clear().type("0.6").trigger("blur")
    name = open_project(project_dir).cases[0].name
    assert _element(user, f"re-{name}").text == "2.61e7"


async def test_an_invalid_altitude_shows_dashes(user: User, ready_project):
    project_dir, _ = ready_project
    project = _altitude_mode(project_dir, altitude_km=120.0)
    await _open(user, project_dir)
    assert _element(user, f"re-{project.cases[0].name}").text == "—"
    await user.should_see(marker="problem-error")


async def test_manual_mode_has_no_freestream_columns(user: User, ready_project):
    project_dir, project = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker=f"re-{project.cases[0].name}")
    assert "readonly" not in _element(user, "sweep-altitude").props
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_sweep.py -q -p no:cacheprovider`
Expected: the four new tests FAIL.

- [ ] **Step 3: Implement** in `aerosuite/web/pages/sweep.py`. Add the imports: `from ...engine.cfg import build_cases, case_freestream, read_template` (extend), `from ...engine.errors import AeroSuiteError, ProjectError` (extend), `from ...engine.freestream import naming_altitude`, and `hint, sci` to the ui_kit import.

In `_sweep_fields`, replace the "Altitude label" `text_field(...)` column with:

```python
            with ui.column().classes("gap-1"):
                if frame.session.project.settings.freestream.mode == "altitude":
                    field(ui.input("Altitude label", value=naming_altitude(frame.session.project))).props(
                        "readonly").classes("w-full").mark("sweep-altitude")
                    hint("from the altitude on the Aircraft page").mark("sweep-altitude-note")
                else:
                    text_field("Altitude label", sweep.altitude,
                               lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=after),
                               mark="sweep-altitude")
```

In `_case_table`, after `duplicates = ...`, compute the columns:

```python
    altitude_mode = project.settings.freestream.mode == "altitude"
    freestream = {}
    if altitude_mode:
        try:
            template = read_template(frame.session.directory, project)
        except AeroSuiteError:
            template = ""
        freestream = {row.name: row for row in case_freestream(project, template)}
    columns = "minmax(10rem, 1.2fr) repeat(3, minmax(3.5rem, .4fr))"
    headings = ["Case", "Mach", "α", "β"]
    if altitude_mode:
        columns += " minmax(6rem, .6fr) minmax(6rem, .6fr)"
        headings += ["Temperature", "Reynolds"]
    columns += " 11rem minmax(18rem, 2fr)"
    headings += ["Restart", "Restart from"]
```

Use `table(columns)` and `for heading in headings: th(heading)`. After the β cell of each case, add:

```python
            if altitude_mode:
                row = freestream.get(case.name)
                values = row.values if row is not None else None
                td(f"{format_value(round(values.temperature_K, 2))} K" if values else "—").mark(f"temp-{case.name}")
                td(sci(values.reynolds) if values else "—").mark(f"re-{case.name}")
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_sweep.py -q -p no:cacheprovider` → PASS. Then `uv run pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 5: Controller visual check** against `sweep-altitude.png` and `sweep-error.png`, with a screenshot to the user.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/pages/sweep.py tests/web/test_web_sweep.py
git commit -m "feat(web): show each case's temperature and Reynolds number on the Sweep page in altitude mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Calculators page, registry, top-bar icon and the y+ calculator

**Files:**
- Create: `aerosuite/web/calculators/__init__.py`, `aerosuite/web/calculators/yplus.py`, `aerosuite/web/pages/calculators.py`, `tests/web/test_web_calculators.py`
- Modify: `aerosuite/web/layout.py`, `aerosuite/web/app.py`, `aerosuite/web/ui_kit.py`, `aerosuite/web/theme.py`

**Interfaces:**
- Consumes: `ProjectFrame`, `open_session`, `header`, ui_kit helpers, `engine.atmosphere.yplus`, `engine.atmosphere.FORMULAS`.
- Produces:
  - `layout.calculators_url(directory=None, calc: Optional[str] = None) -> str`; marker `calculators` on the icon in both top bars
  - `calculators.CalcContext(frame: Optional[ProjectFrame], handoff: dict, open: Callable[[str, dict], None])`
  - `calculators.Calculator(key: str, title: str, description: str, build: Callable[[CalcContext], None])`
  - `calculators.calculators() -> list[Calculator]` (Task 7: `[yplus.CALCULATOR]`; Task 8 puts ISA first)
  - `yplus.first_cell_text(y1_m: float) -> str`; `yplus.CALCULATOR`
  - `ui_kit.result(label: str, highlight: bool = False) -> ui.label` (the value label)
  - Markers: `calc-item-<key>`, `yplus-velocity`, `yplus-density`, `yplus-viscosity`, `yplus-length`, `yplus-y_plus`, `yplus-domain`, `yplus-error`, `yplus-first-cell`, `yplus-layers`, `yplus-re`, `yplus-cf`, `yplus-tau`, `yplus-utau`, `yplus-formula`, `yplus-range-note`, `yplus-from`

- [ ] **Step 1: Write the failing tests** — `tests/web/test_web_calculators.py`:

```python
from nicegui.testing import User

from aerosuite.engine.atmosphere import yplus as engine_yplus
from aerosuite.web.calculators.yplus import first_cell_text
from aerosuite.web.layout import calculators_url, project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _shown(user, marker) -> bool:
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


def test_calculators_url():
    assert calculators_url() == "/calculators"
    assert calculators_url(calc="yplus") == "/calculators?calc=yplus"
    assert calculators_url("C:/p").startswith("/calculators?project=C%3A%2Fp")


def test_first_cell_text_picks_a_unit():
    assert first_cell_text(5.134e-06) == "5.13 µm"
    assert first_cell_text(2.5e-3) == "2.5 mm"


async def test_the_icon_is_on_both_top_bars(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open("/")
    await user.should_see(marker="calculators")
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="calculators")


async def test_without_a_project_there_is_no_project_frame(user: User):
    await user.open("/calculators?calc=yplus")
    await user.should_see(marker="calc-item-yplus")
    await user.should_not_see(marker="project-switcher")


async def test_inside_a_project_the_breadcrumb_says_calculators(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(calculators_url(project_dir, "yplus"))
    assert _element(user, "crumb-page").text == "Calculators"


async def test_an_unknown_calculator_falls_back_to_the_first(user: User):
    await user.open("/calculators?calc=nope")
    await user.should_see(marker="yplus-velocity")


async def test_yplus_results_for_the_defaults(user: User):
    await user.open("/calculators?calc=yplus")
    expected = engine_yplus(50.0, 1.225, 1.789e-5, 1.0, 1.0, "External")
    assert _element(user, "yplus-first-cell").text == first_cell_text(expected["y1"])
    assert _element(user, "yplus-layers").text == str(expected["n_layers"])
    assert not _shown(user, "yplus-range-note")  # Re = 3.4e6 is inside the turbulent range


async def test_out_of_range_note_and_input_errors(user: User):
    await user.open("/calculators?calc=yplus")
    user.find(marker="yplus-velocity").clear().type("300")
    await user.should_see(marker="yplus-range-note")
    user.find(marker="yplus-velocity").clear().type("abc")
    assert _element(user, "yplus-error").text == "Velocity (m/s): 'abc' is not a number"
    user.find(marker="yplus-velocity").clear().type("0")
    assert _element(user, "yplus-error").text == "Velocity (m/s) must be greater than 0"
    assert _element(user, "yplus-first-cell").text == "—"


async def test_internal_flow_uses_the_pipe_formula(user: User):
    await user.open("/calculators?calc=yplus")
    _element(user, "yplus-domain").set_value("Internal")
    assert "Pipe" in _element(user, "yplus-formula").text
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_calculators.py -q -p no:cacheprovider`
Expected: collection error (`No module named 'aerosuite.web.calculators'`).

- [ ] **Step 3: Kit, CSS, URL and icon.** Append to `aerosuite/web/ui_kit.py`:

```python
def result(label: str, highlight: bool = False) -> ui.label:
    """A calculator result tile; returns its value label."""
    with ui.column().classes("as-result" + (" as-result-hi" if highlight else "")):
        ui.label(label).classes("as-stat-label")
        return ui.label("—").classes("as-result-value")
```

Add to `BASE_CSS` in `theme.py`, and add `.as-grid-4` to the shared `display: grid` selector list next to `.as-grid-3`:

```css
.as-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.as-calc { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; align-items: start; width: 100%; }
.as-calc-item { padding: 10px 12px; border-radius: 8px; border: 1px solid transparent; cursor: pointer; gap: 2px; }
.as-calc-item:hover { background: #fff; }
.as-calc-item-on { background: #fff; border-color: var(--as-border); box-shadow: inset 3px 0 0 var(--as-accent); }
.as-result { background: #f6f8fa; border-radius: 8px; padding: 8px 12px; gap: 0; }
.as-result-hi { background: var(--as-accent-tint); }
.as-result-hi .as-result-value { color: var(--as-accent-text); }
.as-result-value { font-size: 16px; font-weight: 600; }
.as-formula { background: #f6f8fa; border-radius: 8px; padding: 10px 12px; gap: 3px; }
```

Also add `.as-grid-4` to the `@media (max-width: 900px)` single-column rule.

In `aerosuite/web/layout.py`, add after `project_url`:

```python
def calculators_url(directory=None, calc: Optional[str] = None) -> str:
    query = []
    if directory is not None:
        query.append(f"project={quote(str(directory), safe='')}")
    if calc:
        query.append(f"calc={quote(calc, safe='')}")
    return "/calculators" + ("?" + "&".join(query) if query else "")


def _calculators_button(directory=None) -> None:
    ui.button(icon="calculate", color=None, on_click=lambda: ui.navigate.to(calculators_url(directory))).props(
        "flat dense").classes("as-topbar-icon").mark("calculators")
```

Call `_calculators_button()` in `header()` right before `_help_button()`. Call `_calculators_button(self.session.directory)` in `ProjectFrame._top_bar` right before `_help_button()`.

- [ ] **Step 4: Registry** — `aerosuite/web/calculators/__init__.py`:

```python
"""The Calculators page's calculators. Each is a module with CALCULATOR = Calculator(...); to add one,
write the module and list it in calculators()."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ..layout import ProjectFrame


@dataclass
class CalcContext:
    frame: Optional["ProjectFrame"]  # the open project's frame; None outside a project
    handoff: dict  # values handed over from another calculator (ISA -> y+); may be empty
    open: Callable[[str, dict], None]  # show another calculator with a handoff


@dataclass(frozen=True)
class Calculator:
    key: str
    title: str
    description: str
    build: Callable[[CalcContext], None]  # draws the calculator's card


def calculators() -> list[Calculator]:
    from . import yplus  # here, not at the top: the calculator modules import this one

    return [yplus.CALCULATOR]
```

- [ ] **Step 5: y+ calculator** — `aerosuite/web/calculators/yplus.py`:

```python
"""y+ first cell height: a flat-plate estimate of the wall spacing for a target y+ (engine: atmosphere.yplus)."""
from __future__ import annotations

import math

from nicegui import ui

from ...engine.atmosphere import yplus as calculate
from ...engine.naming import format_value
from ..ui_kit import card, field, hint, result, sci
from . import CalcContext, Calculator

INPUTS = [  # (key, label, default)
    ("velocity", "Velocity (m/s)", 50.0),
    ("density", "Density (kg/m³)", 1.225),
    ("viscosity", "Dynamic viscosity (Pa·s)", 1.789e-5),
    ("length", "Characteristic length (m)", 1.0),
    ("y_plus", "Target y+", 1.0),
]


def first_cell_text(y1_m: float) -> str:
    return f"{y1_m * 1e6:.3g} µm" if y1_m < 1e-3 else f"{y1_m * 1e3:.3g} mm"


def _read(boxes: dict, label: dict) -> dict:
    """The inputs as positive numbers; ValueError with the message to show."""
    values = {}
    for key, box in boxes.items():
        text = (box.value or "").strip()
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{label[key]}: {text!r} is not a number") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label[key]} must be greater than 0")
        values[key] = value
    return values


def build(ctx: CalcContext) -> None:
    label = {key: text for key, text, _ in INPUTS}
    start = {key: ctx.handoff.get(key, default) for key, _, default in INPUTS}
    with card("y+ first cell height", "flat-plate estimate of the wall spacing for a target y+"):
        if ctx.handoff.get("source"):
            ui.label(ctx.handoff["source"]).classes("as-strip as-muted").mark("yplus-from")
        with ui.row().classes("items-center gap-3"):
            domain = ui.toggle(["External", "Internal"], value="External",
                               on_change=lambda _: recompute()).props("no-caps unelevated").mark("yplus-domain")
            hint("external: flow over a body · internal: duct or pipe")
        boxes = {}
        with ui.element("div").classes("as-grid-3"):
            for key, text, _ in INPUTS:
                boxes[key] = field(ui.input(text, value=f"{start[key]:.6g}", on_change=lambda _: recompute())).mark(
                    f"yplus-{key}")
        error = ui.label("").classes("as-error-text").mark("yplus-error")
        with ui.element("div").classes("as-grid-3"):
            out = {
                "first": result("First cell height", highlight=True).mark("yplus-first-cell"),
                "layers": result("Prism layers (to 0.3 δ)").mark("yplus-layers"),
                "re": result("Reynolds number").mark("yplus-re"),
                "cf": result("Skin friction Cf").mark("yplus-cf"),
                "tau": result("Wall shear τw (Pa)").mark("yplus-tau"),
                "utau": result("Friction velocity uτ (m/s)").mark("yplus-utau"),
            }
        with ui.column().classes("as-formula w-full"):
            formula = ui.label("").classes("as-strong").mark("yplus-formula")
            equation = ui.label("").classes("as-mono")
            detail = hint("")
            note = hint("").classes("as-hint-warning").mark("yplus-range-note")

    def recompute() -> None:
        try:
            v = _read(boxes, label)
            r = calculate(v["velocity"], v["density"], v["viscosity"], v["length"], v["y_plus"], domain.value)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            error.text = str(exc)
            for tile in out.values():
                tile.text = "—"
            note.set_visibility(False)
            return
        error.text = ""
        out["first"].text = first_cell_text(r["y1"])
        out["layers"].text = str(r["n_layers"])
        out["re"].text = sci(r["Re"])
        out["cf"].text = sci(r["Cf"])
        out["tau"].text = format_value(round(r["tau_w"], 3))
        out["utau"].text = format_value(round(r["u_tau"], 3))
        formula.text = f"{r['flow_type']} · {r['formula']['name']}"
        equation.text = r["formula"]["latex"]
        detail.text = r["formula"]["detail"]
        note.text = f"Re = {sci(r['Re'])} is outside this formula's valid range; treat the height as an estimate"
        note.set_visibility(not r["in_range"])

    recompute()


CALCULATOR = Calculator("yplus", "y+ first cell height", "wall spacing for a target y+", build)
```

- [ ] **Step 6: The page** — `aerosuite/web/pages/calculators.py`:

```python
"""Calculators: a list of calculators on the left, the open one on the right; Apply appears inside a project."""
from typing import Optional

from nicegui import ui

from ..calculators import CalcContext, calculators
from ..layout import ProjectFrame, header, open_session


def register() -> None:
    @ui.page("/calculators")
    def calculators_page(project: str = "", calc: str = "") -> None:
        views: list = []
        frame: Optional[ProjectFrame] = None
        if project:
            session = open_session(project)
            if session is None:
                return
            frame = ProjectFrame(session, "calculators",
                                 on_reload=lambda: views[0].show(views[0].key, {}) if views else None)
            holder = frame.content
        else:
            header()
            holder = ui.column().classes("as-page w-full")
            with holder:
                with ui.row().classes("as-crumbs w-full"):
                    ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                    ui.label("›").classes("as-crumb-sep")
                    ui.label("Calculators").classes("as-crumb-current").mark("crumb-page")
        with holder:
            views.append(CalculatorsView(frame, calc))


class CalculatorsView:
    def __init__(self, frame: Optional[ProjectFrame], key: str) -> None:
        self.frame = frame
        keys = [c.key for c in calculators()]
        self.key = key if key in keys else keys[0]
        with ui.element("div").classes("as-calc"):
            self.list = ui.column().classes("gap-1")
            self.card = ui.column().classes("w-full")
        self.show(self.key, {})

    def show(self, key: str, handoff: dict) -> None:
        self.key = key
        items = calculators()
        self.list.clear()
        with self.list:
            for calc in items:
                item = ui.column().classes("as-calc-item" + (" as-calc-item-on" if calc.key == key else "")).mark(
                    f"calc-item-{calc.key}")
                item.on("click", lambda _, k=calc.key: self.show(k, {}))
                with item:
                    ui.label(calc.title).classes("as-strong")
                    ui.label(calc.description).classes("as-muted")
        self.card.clear()
        with self.card:
            next(c for c in items if c.key == key).build(CalcContext(self.frame, handoff, self.show))
```

In `aerosuite/web/app.py`, import `calculators` in the pages import line (`from .pages import aircraft, calculators, monitor, projects, run, setup, sweep`) and call `calculators.register()` after `monitor.register()`.

- [ ] **Step 7: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_calculators.py tests/web/test_web_topbar.py -q -p no:cacheprovider` → PASS. Then `uv run pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 8: Controller visual check** against `yplus.png`, with a screenshot to the user.

- [ ] **Step 9: Commit**

```bash
git add aerosuite/web/calculators aerosuite/web/pages/calculators.py aerosuite/web/app.py aerosuite/web/layout.py aerosuite/web/ui_kit.py aerosuite/web/theme.py tests/web/test_web_calculators.py
git commit -m "feat(web): add the Calculators page with the y+ first-cell-height calculator

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: ISA calculator, prefill, Apply and Send to y+

**Files:**
- Create: `aerosuite/web/calculators/isa_rules.py`, `aerosuite/web/calculators/isa.py`, `tests/web/test_isa_rules.py`
- Modify: `aerosuite/web/calculators/__init__.py`, `tests/web/test_web_calculators.py` (append)

**Interfaces:**
- Consumes:
  - `editing.set_freestream`, `freestream.freestream_for`, `freestream.naming_altitude`, `cfg.template_case_values`, `cfg.apply_parameters`, `cfg.read_template`;
  - `project.set_template_text`, `project.TEMPLATE_FILE`, `models.Freestream`, `models.Settings`;
  - `CalcContext.open` (Task 7), `yplus` handoff keys `velocity`, `density`, `viscosity`, `length`, `source`.
- Produces:
  - `isa_rules.Prefill(altitude_km: float, mach: float, length_m: float, note: str)`, `isa_rules.isa_prefill(project: Optional[Project], template: str) -> Prefill`
  - `isa_rules.ApplyPlan(kind: Literal["aircraft", "template", "blocked"], changes: list[tuple[str, str, str]], note: str = "", reason: str = "", template_params: dict[str, str])`
  - `isa_rules.plan_isa_apply(project, template: Optional[str], altitude_km, mach, length_m) -> ApplyPlan`, with the constant `isa_rules.SWEEP_REASON`
  - Markers: `isa-altitude`, `isa-mach`, `isa-length`, `isa-error`, `isa-from`, `isa-temperature`, `isa-pressure`, `isa-density`, `isa-sound`, `isa-tas`, `isa-q`, `isa-mu`, `isa-re`, `isa-send-yplus`, `isa-apply`, `isa-apply-reason`, `apply-change-<n>`, `apply-note`, `apply-cancel`, `apply-confirm`

- [ ] **Step 1: Write the failing tests.** `tests/web/test_isa_rules.py`:

```python
from aerosuite.engine.cfg import build_cases
from aerosuite.engine.models import Project
from aerosuite.web.calculators.isa_rules import SWEEP_REASON, isa_prefill, plan_isa_apply

TEMPLATE = "MACH_NUMBER= 0.3\nREYNOLDS_NUMBER= 1e6\n"


def _sweep(profile=None) -> Project:
    project = Project(name="p", profile=profile)
    project.sweep.mach, project.sweep.alpha, project.sweep.beta = [0.6, 0.8], [0.0], [0.0]
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    return project


def test_prefill_outside_a_project():
    assert isa_prefill(None, "") == (0.0, 0.8, 1.0, "")


def test_prefill_from_a_sweep_project():
    project = _sweep()
    project.settings.freestream.mode, project.settings.freestream.altitude_km = "altitude", 11.0
    project.settings.freestream.reynolds_length = 6.0
    prefill = isa_prefill(project, TEMPLATE)
    assert (prefill.altitude_km, prefill.mach, prefill.length_m) == (11.0, 0.8, 6.0)
    assert "Mach 0.8 (the sweep's highest)" in prefill.note


def test_prefill_single_case_uses_the_template_mach():
    project = _sweep()
    project.sweep.enabled = False
    assert isa_prefill(project, TEMPLATE).mach == 0.3


def test_plan_for_an_aircraft_project_lists_changes_and_renames():
    plan = plan_isa_apply(_sweep(profile="x07"), TEMPLATE, 11.0, 0.8, 6.0)
    assert plan.kind == "aircraft"
    assert plan.changes[:3] == [("Freestream", "Set by hand", "From altitude"), ("Altitude", "—", "11 km"),
                                ("Reynolds length", "—", "6 m")]
    assert plan.changes[3] == ("Altitude label (case names)", "sl", "11km")
    assert plan.note == "Renames 2 cases"


def test_plan_for_a_general_single_case_writes_template_lines_at_the_templates_mach():
    project = _sweep()
    project.sweep.enabled = False
    plan = plan_isa_apply(project, TEMPLATE, 11.0, 0.8, 6.0)
    assert plan.kind == "template"
    assert plan.template_params == {"FREESTREAM_TEMPERATURE": "216.65", "REYNOLDS_NUMBER": "13038595",
                                    "REYNOLDS_LENGTH": "6"}
    assert ("REYNOLDS_NUMBER", "1e6", "13038595") in plan.changes
    assert ("FREESTREAM_TEMPERATURE", "—", "216.65") in plan.changes
    assert plan.note == "The Reynolds number is computed for Mach 0.3 (the template's), not 0.8"


def test_plan_is_blocked_for_a_general_sweep_and_a_template_without_mach():
    assert plan_isa_apply(_sweep(), TEMPLATE, 11.0, 0.8, 6.0).reason == SWEEP_REASON
    project = _sweep()
    project.sweep.enabled = False
    blocked = plan_isa_apply(project, "AOA= 0\n", 11.0, 0.8, 6.0)
    assert blocked.kind == "blocked" and "MACH_NUMBER" in blocked.reason
    assert plan_isa_apply(project, None, 11.0, 0.8, 6.0).kind == "blocked"
```

Append to `tests/web/test_web_calculators.py`:

```python
from aerosuite.engine.freestream import naming_altitude
from aerosuite.engine.profiles import apply_profile, load_profile
from aerosuite.engine.project import open_project, save_project


def _x07(project_dir):
    project = open_project(project_dir)
    apply_profile(project_dir, project, load_profile("x07"), copy_template=False)
    save_project(project_dir, project)


def _isa_inputs(user, altitude="11", mach="0.8", length="6"):
    for marker, text in (("isa-altitude", altitude), ("isa-mach", mach), ("isa-length", length)):
        user.find(marker=marker).clear().type(text)


async def test_isa_results_for_known_inputs(user: User):
    await user.open("/calculators")
    _isa_inputs(user)
    assert _element(user, "isa-temperature").text == "216.65 K"
    assert _element(user, "isa-re").text == "3.48e7"
    assert not _shown(user, "isa-apply")  # no project


async def test_isa_input_error(user: User):
    await user.open("/calculators")
    _isa_inputs(user, altitude="120")
    assert "between 0 and 100" in _element(user, "isa-error").text
    assert _element(user, "isa-re").text == "—"


async def test_apply_to_an_aircraft_project(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    _x07(project_dir)
    await user.open(calculators_url(project_dir))
    _isa_inputs(user)
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-confirm")
    user.find(marker="apply-confirm").click()
    await eventually(lambda: open_project(project_dir).settings.freestream.mode == "altitude")
    project = open_project(project_dir)
    assert project.settings.freestream.altitude_km == 11.0 and naming_altitude(project) == "11km"


async def test_cancel_changes_nothing(user: User, ready_project):
    project_dir, _ = ready_project
    _x07(project_dir)
    before = (project_dir / "project.json").read_text()
    await user.open(calculators_url(project_dir))
    _isa_inputs(user)
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-cancel")
    user.find(marker="apply-cancel").click()
    await user.should_not_see(marker="apply-cancel")
    assert (project_dir / "project.json").read_text() == before


async def test_apply_to_a_general_single_case_writes_the_template(user: User, ready_project, eventually):
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)
    await user.open(calculators_url(project_dir))
    _isa_inputs(user, mach="0.3")
    user.find(marker="isa-apply").click()
    await user.should_see(marker="apply-confirm")
    user.find(marker="apply-confirm").click()
    await eventually(lambda: "REYNOLDS_NUMBER= 13038595" in (project_dir / "template.cfg").read_text())


async def test_apply_is_disabled_for_a_general_sweep(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(calculators_url(project_dir))
    assert not _element(user, "isa-apply").enabled
    await user.should_see(marker="isa-apply-reason")


async def test_send_to_yplus_hands_over_the_flow(user: User):
    await user.open("/calculators")
    _isa_inputs(user)
    user.find(marker="isa-send-yplus").click()
    await user.should_see(marker="yplus-from")
    assert _element(user, "yplus-velocity").value == "236.06"
    assert _element(user, "yplus-length").value == "6"


async def test_send_to_yplus_with_mach_zero_shows_the_yplus_error(user: User):
    await user.open("/calculators")
    _isa_inputs(user, mach="0")
    user.find(marker="isa-send-yplus").click()
    await user.should_see(marker="yplus-from")
    assert _element(user, "yplus-error").text == "Velocity (m/s) must be greater than 0"
```

Add `from aerosuite.engine.cfg import build_cases` to that file's imports. Because ISA is now first in the registry, change `test_an_unknown_calculator_falls_back_to_the_first` to expect `isa-altitude` instead of `yplus-velocity`. That's a layout-order update; name it in the report.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_isa_rules.py tests/web/test_web_calculators.py -q -p no:cacheprovider`
Expected: collection error for `isa_rules`; the web ISA tests fail (no `isa-*` markers).

- [ ] **Step 3: Rules** — `aerosuite/web/calculators/isa_rules.py`:

```python
"""ISA calculator rules without NiceGUI: what it pre-fills from a project, and what Apply would change."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, NamedTuple, Optional

from ...engine.cfg import template_case_values
from ...engine.editing import set_freestream
from ...engine.errors import ProjectError
from ...engine.freestream import freestream_for, naming_altitude
from ...engine.models import Freestream, Project, Settings
from ...engine.naming import format_value

SWEEP_REASON = "Per-case freestream is set on the Aircraft page, which needs an aircraft profile (Setup)"
NO_MACH_REASON = "The template has no MACH_NUMBER; the Reynolds number needs the Mach that runs"
MODE_TEXT = {"manual": "Set by hand", "altitude": "From altitude"}


class Prefill(NamedTuple):
    altitude_km: float
    mach: float
    length_m: float
    note: str


@dataclass(frozen=True)
class ApplyPlan:
    kind: Literal["aircraft", "template", "blocked"]
    changes: list[tuple[str, str, str]] = field(default_factory=list)  # (what, old, new)
    note: str = ""
    reason: str = ""  # why Apply is not possible (kind "blocked")
    template_params: dict[str, str] = field(default_factory=dict)


def _num(value: Optional[float], unit: str) -> str:
    return "—" if value is None else f"{format_value(value)} {unit}"


def isa_prefill(project: Optional[Project], template: str) -> Prefill:
    if project is None:
        return Prefill(0.0, 0.8, 1.0, "")
    fs, notes = project.settings.freestream, []
    altitude, length, mach = 0.0, 1.0, 0.8
    if fs.mode == "altitude" and fs.altitude_km is not None:
        altitude = fs.altitude_km
        notes.append("altitude from the Aircraft page")
    if fs.reynolds_length:
        length = fs.reynolds_length
        notes.append("length from the project's Reynolds length")
    if project.sweep.enabled and project.sweep.mach:
        mach = max(project.sweep.mach)
        notes.append(f"Mach {format_value(mach)} (the sweep's highest)")
    elif template_case_values(template)[0] > 0:
        mach = template_case_values(template)[0]
        notes.append(f"Mach {format_value(mach)} (the template's)")
    note = f"Filled from {project.name}: " + ", ".join(notes) if notes else ""
    return Prefill(altitude, mach, length, note)


def _template_value(template: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.*?)\s*$", template, re.MULTILINE)
    return match.group(1) if match else "—"


def plan_isa_apply(project: Project, template: Optional[str], altitude_km: float, mach: float,
                   length_m: float) -> ApplyPlan:
    if project.profile:
        fs = project.settings.freestream
        new = project.model_copy(deep=True)
        try:
            set_freestream(new, mode="altitude", altitude_km=altitude_km, reynolds_length=length_m)
        except ProjectError as exc:
            return ApplyPlan("blocked", reason=str(exc))
        changes = [("Freestream", MODE_TEXT[fs.mode], "From altitude"),
                   ("Altitude", _num(fs.altitude_km, "km"), _num(altitude_km, "km")),
                   ("Reynolds length", _num(fs.reynolds_length, "m"), _num(length_m, "m"))]
        renamed = sum(1 for old, now in zip(project.cases, new.cases) if old.name != now.name)
        old_label, new_label = naming_altitude(project), naming_altitude(new)
        if old_label != new_label and project.sweep.enabled and project.sweep.naming.include_altitude:
            changes.append(("Altitude label (case names)", old_label, new_label))
        note = f"Renames {renamed} case{'' if renamed == 1 else 's'}" if renamed else ""
        return ApplyPlan("aircraft", changes, note)
    if project.sweep.enabled:
        return ApplyPlan("blocked", reason=SWEEP_REASON)
    if template is None:
        return ApplyPlan("blocked", reason="The template cannot be read")
    run_mach = template_case_values(template)[0]
    if run_mach <= 0:
        return ApplyPlan("blocked", reason=NO_MACH_REASON)
    settings = Settings(freestream=Freestream(mode="altitude", altitude_km=altitude_km, reynolds_length=length_m))
    try:
        params = freestream_for(settings, run_mach)
    except ProjectError as exc:
        return ApplyPlan("blocked", reason=str(exc))
    changes = [(key, _template_value(template, key), value) for key, value in params.items()]
    note = ("" if run_mach == mach else
            f"The Reynolds number is computed for Mach {format_value(run_mach)} (the template's), "
            f"not {format_value(mach)}")
    return ApplyPlan("template", changes, note, template_params=params)
```

- [ ] **Step 4: The ISA card** — `aerosuite/web/calculators/isa.py`:

```python
"""ISA atmosphere: properties at an altitude, Apply to the project, and Send to y+."""
from __future__ import annotations

from typing import Optional

from nicegui import ui

from ...engine.atmosphere import ISACalculator
from ...engine.cfg import apply_parameters, read_template
from ...engine.editing import set_freestream
from ...engine.errors import AeroSuiteError
from ...engine.naming import format_value
from ...engine.project import TEMPLATE_FILE, set_template_text
from ..ui_kit import card, field, primary_button, result, sci, secondary_button, table, td, th
from . import CalcContext, Calculator
from .isa_rules import ApplyPlan, isa_prefill, plan_isa_apply

INPUTS = [("altitude", "Altitude (km)"), ("mach", "Mach"), ("length", "Characteristic length (m)")]
RESULTS = [  # (marker, label, engine key, format, highlight)
    ("isa-temperature", "Temperature", "temperature", lambda v: f"{format_value(round(v, 2))} K", True),
    ("isa-pressure", "Pressure", "pressure", lambda v: f"{format_value(round(v))} Pa", False),
    ("isa-density", "Density", "density", lambda v: f"{v:.4g} kg/m³", False),
    ("isa-sound", "Speed of sound", "speed_of_sound", lambda v: f"{format_value(round(v, 2))} m/s", False),
    ("isa-tas", "True airspeed", "true_airspeed", lambda v: f"{format_value(round(v, 2))} m/s", False),
    ("isa-q", "Dynamic pressure", "dynamic_pressure", lambda v: f"{format_value(round(v))} Pa", False),
    ("isa-mu", "Dynamic viscosity", "dynamic_viscosity", lambda v: f"{sci(v)} Pa·s", False),
    ("isa-re", "Reynolds number", "reynolds_number", sci, True),
]


def _template(ctx: CalcContext) -> Optional[str]:
    if ctx.frame is None:
        return None
    try:
        return read_template(ctx.frame.session.directory, ctx.frame.session.project)
    except AeroSuiteError:
        return None


def build(ctx: CalcContext) -> None:
    project = ctx.frame.session.project if ctx.frame else None
    prefill = isa_prefill(project, _template(ctx) or "")
    start = {"altitude": prefill.altitude_km, "mach": prefill.mach, "length": prefill.length_m}
    state: dict = {"isa": None, "inputs": None}
    with card("ISA atmosphere", "International Standard Atmosphere, 0–100 km"):
        if prefill.note:
            ui.label(prefill.note).classes("as-strip as-muted").mark("isa-from")
        boxes = {}
        with ui.element("div").classes("as-grid-3"):
            for key, text in INPUTS:
                boxes[key] = field(ui.input(text, value=format_value(start[key]),
                                            on_change=lambda _: recompute())).mark(f"isa-{key}")
        error = ui.label("").classes("as-error-text").mark("isa-error")
        with ui.element("div").classes("as-grid-4"):
            tiles = {marker: result(text, highlight).mark(marker) for marker, text, _, _, highlight in RESULTS}
        with ui.row().classes("w-full justify-end items-center gap-2"):
            reason = ui.label("").classes("as-hint").mark("isa-apply-reason")
            secondary_button("Send to y+ →", on_click=lambda: send()).mark("isa-send-yplus")
            apply_button = None
            if ctx.frame is not None:
                apply_button = primary_button(f"Apply to {project.name}…", on_click=lambda: confirm()).mark("isa-apply")

    def read() -> tuple[float, float, float]:
        values = []
        for key, text in INPUTS:
            raw = (boxes[key].value or "").strip()
            try:
                values.append(float(raw))
            except ValueError:
                raise ValueError(f"{text}: {raw!r} is not a number") from None
        return values[0], values[1], values[2]

    def plan() -> Optional[ApplyPlan]:
        if ctx.frame is None or state["inputs"] is None:
            return None
        return plan_isa_apply(ctx.frame.session.project, _template(ctx), *state["inputs"])

    def recompute() -> None:
        try:
            altitude, mach, length = read()
            state["isa"] = ISACalculator.calculate(altitude, mach, length)
            state["inputs"] = (altitude, mach, length)
            error.text = ""
        except ValueError as exc:
            state["isa"], state["inputs"] = None, None
            error.text = str(exc)
        for marker, _, key, fmt, _ in RESULTS:
            tiles[marker].text = fmt(state["isa"][key]) if state["isa"] else "—"
        current = plan()
        blocked = current is None or current.kind == "blocked"
        if apply_button is not None:
            apply_button.set_enabled(not blocked)
        reason.text = current.reason if current is not None and current.kind == "blocked" else ""
        reason.set_visibility(bool(reason.text))

    def send() -> None:
        isa, inputs = state["isa"], state["inputs"]
        handoff = {} if isa is None else {
            "velocity": isa["true_airspeed"], "density": isa["density"], "viscosity": isa["dynamic_viscosity"],
            "length": inputs[2],
            "source": f"From ISA: {format_value(inputs[0])} km, Mach {format_value(inputs[1])}",
        }
        ctx.open("yplus", handoff)

    async def confirm() -> None:
        current = plan()
        if current is None or current.kind == "blocked":
            return
        with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
            ui.label(f"Apply ISA to {ctx.frame.session.project.name}?").classes("as-dialog-title")
            with table("minmax(10rem, 1.2fr) minmax(6rem, 1fr) minmax(6rem, 1fr)"):
                for heading in ("", "Now", "After"):
                    th(heading)
                for index, (what, old, new) in enumerate(current.changes):
                    td(what).mark(f"apply-change-{index}")
                    td(old).classes("as-muted")
                    td(new)
            if current.note:
                ui.label(current.note).classes("as-hint").mark("apply-note")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(False)).mark("apply-cancel")
                primary_button("Apply", on_click=lambda: dialog.submit(True)).mark("apply-confirm")
        confirmed = await dialog
        dialog.delete()
        if confirmed:
            _apply(ctx, current, state["inputs"])
            recompute()

    recompute()


def _apply(ctx: CalcContext, plan: ApplyPlan, inputs: tuple[float, float, float]) -> None:
    frame = ctx.frame
    altitude, _, length = inputs
    if plan.kind == "aircraft":
        message = frame.save(lambda p: set_freestream(p, mode="altitude", altitude_km=altitude,
                                                      reynolds_length=length))
    else:
        # Like the Config page: template.cfg is written directly, not through project.json.
        try:
            text = read_template(frame.session.directory, frame.session.project)
            set_template_text(frame.session.directory, frame.session.project,
                              apply_parameters(text, plan.template_params))
            message = None
            if frame.session.project.template != TEMPLATE_FILE:
                message = frame.save(lambda p: setattr(p, "template", TEMPLATE_FILE))
            else:
                frame.refresh()
        except AeroSuiteError as exc:
            message = str(exc)
    if message:
        ui.notify(message, type="negative")
    else:
        ui.notify(f"Applied ISA to {frame.session.project.name}", type="positive")


CALCULATOR = Calculator("isa", "ISA atmosphere", "T, p, ρ, μ, Re from altitude and Mach", build)
```

In `aerosuite/web/calculators/__init__.py`, change `calculators()` to:

```python
def calculators() -> list[Calculator]:
    from . import isa, yplus  # here, not at the top: the calculator modules import this one

    return [isa.CALCULATOR, yplus.CALCULATOR]
```

`ISACalculator.calculate` raises `ValueError` for an altitude outside 0–100 km with the message "Altitude must be between 0 and 100 km"; `recompute` shows it.

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_isa_rules.py tests/web/test_web_calculators.py -q -p no:cacheprovider` → PASS. Then `uv run pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 6: Controller visual check** against `isa.png` and `apply.png`, with screenshots to the user.

- [ ] **Step 7: Commit**

```bash
git add aerosuite/web/calculators tests/web/test_isa_rules.py tests/web/test_web_calculators.py
git commit -m "feat(web): add the ISA calculator with Apply to project and Send to y+

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: README and final visual pass

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README.** Make these changes:
  - In "## Web UI", "Pages:": add a **Calculators** bullet. The calculator icon in the top bar opens ISA atmosphere and y+ first cell height. ISA's *Apply to project* sets an aircraft project to Freestream *From altitude*, or writes the freestream lines of a general single-case template. *Send to y+* copies the flow into the y+ calculator.
  - In the **Aircraft** bullet: Freestream is *Set by hand* or *From altitude*. From altitude, each case gets the ISA temperature and its own Reynolds number from its Mach; the Sweep page shows them, and the case names' altitude label follows the altitude.
  - In "## Command line": `aerosuite set <dir> --freestream altitude --altitude-km 11 --reynolds-length 6`.

- [ ] **Step 2: Full suite.** Run `uv run pytest -q -p no:cacheprovider` → all pass; record the count.

- [ ] **Step 3: Visual pass (controller).** With the demo server:
  - screenshot the Aircraft (altitude mode), Sweep (altitude mode), Calculators ISA, Apply dialog and y+ pages at 1280×800 and 1920×1080;
  - compare them with the spec mockups;
  - send the set to the user.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: describe the Calculators page and freestream from altitude

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

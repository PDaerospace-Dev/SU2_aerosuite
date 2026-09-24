# AeroSuite Engine (Phases 0–1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, UI-free `aerosuite.engine` package (project model, case naming, config rendering, results, job runner) and fix the legacy PyQt5 app's silent-wrong-answer bugs by routing it through that engine.

**Architecture:** A new `aerosuite/engine/` package holds all logic with no UI imports. Projects are folders with a `project.json` (pydantic). A `LocalRunner` launches the existing `aoa_sweep_v8.py` detached and derives all job state from disk and the OS. The legacy PyQt5 app keeps working; its generator, results and run pages delegate the buggy parts to the engine.

**Tech Stack:** Python 3.12 (via `uv`), pydantic v2, pandas, psutil, pytest. Legacy app: PyQt5, matplotlib, qtawesome.

**Spec:** `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md` (sections 3–6, 9–11 apply to this plan).

## Global Constraints

- AeroSuite runs on Python ≥ 3.10; the environment is Python 3.12 created with `uv`. The workstation's system Python 3.7.6 is not modified.
- `aerosuite/resources/aoa_sweep_v8.py` must stay compatible with Python 3.7 (it runs under the system Python that imports SU2).
- `aerosuite/engine/` must never import PyQt5, matplotlib or anything from `aerosuite/ui`.
- Engine functions raise `AeroSuiteError` subclasses with user-facing messages; no `print`-and-continue in the engine.
- Case names: whole-number values produce the same names as AeroSuite v7 (`M0p8`, `M1p0`, `a5`, `an5`, `b0`); non-whole values keep every significant digit (`M0p85`, `a2p5`, `an0p5`).
- Values written into `.cfg` files use the same exact formatting as names (`0.85`, not `0.8`).
- `MARKER_*` settings: value `None` removes the line; a key that is absent keeps the template's value.
- Process liveness and killing use `psutil` on every platform. Never call `os.kill(pid, 0)` (it terminates the process on Windows).
- Tests must pass on Windows and Linux and must not need SU2, MPI or a display.
- Every command in this plan is run from the repository root.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | Environment and packaging (Task 1) |
| `aerosuite/engine/__init__.py` | Package marker, no imports |
| `aerosuite/engine/errors.py` | `AeroSuiteError` hierarchy |
| `aerosuite/engine/naming.py` | Value formatting, case names ⇄ Mach/α/β, collisions |
| `aerosuite/engine/models.py` | pydantic `Project` and sub-models |
| `aerosuite/engine/cfg.py` | Marker extraction, parameter substitution, `render_case`, `build_cases`, `generate_configs` |
| `aerosuite/engine/project.py` | Create/open/save project folders, schema migration, template and mesh selection |
| `aerosuite/engine/atmosphere/` | `isa.py`, `yplus.py` moved from `core/` |
| `aerosuite/engine/results.py` | History reading (incremental), convergence check, summary |
| `aerosuite/engine/jobs/runner.py` | `JobRecord`, states, `Runner` protocol, sweep-script path |
| `aerosuite/engine/jobs/store.py` | Job JSON persistence, project lock, process liveness and tree kill |
| `aerosuite/engine/jobs/local.py` | `LocalRunner` |
| `aerosuite/engine/preflight.py` | Pre-generate / pre-run checks returning `Problem`s |
| `aerosuite/core/*.py` | Become thin delegations to the engine (Tasks 6, 11, 12) |
| `aerosuite/ui/sweep_setup_tab.py`, `aerosuite/ui/sweep_tab.py` | Small legacy fixes (Tasks 11, 12) |
| `tests/…` | pytest suite; `tests/fixtures/fake_sweep.py` stands in for SU2 |

---

### Task 1: Python 3.12 environment, housekeeping, test scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version` (generated), `uv.lock` (generated), `tests/conftest.py`, `tests/test_smoke.py`
- Delete: `test_imports.py`, all tracked `__pycache__/` files
- Add to git: `aerosuite/resources/aoa_sweep_v8.py` (currently untracked)
- Modify: `README.md` (Installation and Running sections), `aerosuite/requirements.txt` (delete; replaced by `pyproject.toml`)

**Interfaces:**
- Produces: a `uv` environment where `uv run pytest` works and `aerosuite` is importable; a `tests/conftest.py` that forces matplotlib's `Agg` backend.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "aerosuite"
version = "8.0.0.dev0"
description = "Prepare, run and post-process SU2 CFD sweeps"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.1",
    "pydantic>=2.6",
    "psutil>=5.9",
    # Legacy PyQt5 app — removed in Phase 5
    "PyQt5>=5.15.10",
    "matplotlib>=3.8",
    "qtawesome>=1.3",
]

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["aerosuite*"]

[tool.setuptools.package-data]
aerosuite = ["resources/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
*.egg-info/
build/
dist/
```

- [ ] **Step 3: Pin Python, create the environment, delete the old requirements file**

```bash
uv python pin 3.12
uv sync
git rm -q aerosuite/requirements.txt
```

Expected: `.python-version` contains `3.12`, `.venv/` and `uv.lock` exist, `uv sync` ends with `Installed N packages`.

- [ ] **Step 4: Remove tracked `__pycache__` files and the obsolete import script**

```bash
git rm -r -q --cached $(git ls-files | grep __pycache__)
git rm -q test_imports.py
```

Expected: `git ls-files | grep -c __pycache__` prints `0`.

- [ ] **Step 5: Write `tests/conftest.py`**

```python
"""Shared pytest configuration."""
import matplotlib

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")
```

- [ ] **Step 6: Write the smoke tests `tests/test_smoke.py`**

```python
"""Import-level checks for the legacy app and the bundled sweep script."""
import ast
import importlib
from pathlib import Path

import pytest

SWEEP_SCRIPT = Path(__file__).resolve().parents[1] / "aerosuite" / "resources" / "aoa_sweep_v8.py"


def test_core_and_utils_import():
    importlib.import_module("aerosuite.core")
    importlib.import_module("aerosuite.utils")


def test_legacy_ui_imports_headless(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt5.QtWidgets")
    importlib.import_module("aerosuite.ui")
    importlib.import_module("aerosuite.main")


def test_sweep_script_stays_python37_compatible():
    source = SWEEP_SCRIPT.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 7))
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest -v`
Expected: 3 passed.

- [ ] **Step 8: Update `README.md` Installation and Running sections**

Replace everything from the line `## Installation` up to (not including) the line `## Typical Workflow` with:

````markdown
## Installation
AeroSuite runs on **Python 3.12** in its own environment, managed by [uv](https://docs.astral.sh/uv/).
The system Python (3.7.6 on the workstation) is not touched; the sweep script keeps running under it,
because that is the Python that can import SU2.

One-time setup (no admin rights needed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /path/to/SU2_aerosuite
uv sync
```

### Running
```bash
uv run python run_aerosuite.py
```

On the workstation, point the `su2aero2` alias at the new environment:
```bash
alias su2aero2='uv run --project /path/to/SU2_aerosuite python /path/to/SU2_aerosuite/run_aerosuite.py'
```

### Tests
```bash
uv run pytest
```

````

- [ ] **Step 9: Launch the legacy app once to confirm it still starts under Python 3.12**

Run: `uv run python run_aerosuite.py`
Expected: the main window opens; close it. (Manual check — on a headless machine skip this; the smoke test covers imports.)

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore tests/ README.md aerosuite/resources/aoa_sweep_v8.py
git commit -m "chore: move to uv-managed Python 3.12, add pytest scaffold, drop committed pycache"
```

---

### Task 2: Engine errors and case naming

**Files:**
- Create: `aerosuite/engine/__init__.py`, `aerosuite/engine/errors.py`, `aerosuite/engine/naming.py`
- Test: `tests/engine/test_naming.py`

**Interfaces:**
- Produces:
  - `errors.AeroSuiteError(Exception)`, subclasses `ProjectError`, `TemplateError`, `GenerationError`, `JobError`
  - `naming.format_value(value: float) -> str`
  - `naming.mach_token(mach: float) -> str` (e.g. `"M0p85"`)
  - `naming.angle_token(angle: float) -> str` (no prefix; e.g. `"n2p5"`)
  - `naming.case_name(mach, alpha, beta, *, altitude="", base_name="", include_mach=True, include_alpha=True, include_beta=True, include_altitude=True, include_base=True) -> str` (no `.cfg`)
  - `naming.ParsedName(NamedTuple)` with `mach`, `alpha`, `beta: float | None`
  - `naming.parse_case_name(name: str) -> ParsedName`
  - `naming.find_collisions(names: Iterable[str]) -> list[str]`

- [ ] **Step 1: Write the failing tests `tests/engine/test_naming.py`**

```python
import pytest

from aerosuite.engine.errors import GenerationError
from aerosuite.engine.naming import (
    angle_token,
    case_name,
    find_collisions,
    format_value,
    mach_token,
    parse_case_name,
)


@pytest.mark.parametrize(
    "value, text",
    [(0.85, "0.85"), (0.8, "0.8"), (5.0, "5"), (-0.5, "-0.5"), (0.0, "0"), (-0.0, "0"),
     (2.25, "2.25"), (6.5e6, "6500000"), (1e-5, "0.00001")],
)
def test_format_value_is_exact(value, text):
    assert format_value(value) == text


@pytest.mark.parametrize(
    "mach, token",
    [(0.8, "M0p8"), (0.85, "M0p85"), (0.78, "M0p78"), (1.5, "M1p5"), (1.0, "M1p0"), (2, "M2p0")],
)
def test_mach_token(mach, token):
    assert mach_token(mach) == token


@pytest.mark.parametrize(
    "angle, token",
    [(5, "5"), (-5, "n5"), (0, "0"), (2.5, "2p5"), (-0.5, "n0p5"), (1.5, "1p5")],
)
def test_angle_token(angle, token):
    assert angle_token(angle) == token


def test_case_name_default_order_matches_v7():
    assert case_name(0.8, 5, 0, altitude="SL", base_name="X07") == "M0p8_sl_a5_b0_x07"


def test_case_name_respects_include_flags():
    name = case_name(0.85, -2.5, 1, include_altitude=False, include_base=False)
    assert name == "M0p85_an2p5_b1"


def test_case_name_requires_a_component():
    with pytest.raises(GenerationError):
        case_name(0.8, 0, 0, include_mach=False, include_alpha=False, include_beta=False,
                  include_altitude=False, include_base=False)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("M0p85_a2p5_bn1", (0.85, 2.5, -1.0)),
        ("M0p8_sl_an5_b0_x07", (0.8, -5.0, 0.0)),
        ("M0p8_sl_an5_b0_x07.cfg", (0.8, -5.0, 0.0)),
        ("ht_M0p3_A5_B0_sl", (0.3, 5.0, 0.0)),      # v7 legacy: Mach not first, upper case
        ("M0p6_A10m", (0.6, -10.0, None)),           # legacy m/p suffix
        ("M0p6_A10p", (0.6, 10.0, None)),
        ("M0p6_A-3", (0.6, -3.0, None)),
        ("sl_a5", (None, 5.0, None)),
        ("wing_baseline", (None, None, None)),
    ],
)
def test_parse_case_name(name, expected):
    assert tuple(parse_case_name(name)) == expected


@pytest.mark.parametrize("mach", [0.3, 0.8, 0.85, 1.25])
@pytest.mark.parametrize("alpha", [-4, -0.5, 0, 2.5, 12])
@pytest.mark.parametrize("beta", [-2, 0, 1.5])
def test_names_round_trip(mach, alpha, beta):
    parsed = parse_case_name(case_name(mach, alpha, beta, altitude="10km", base_name="x07"))
    assert parsed == (mach, alpha, beta)


def test_find_collisions():
    assert find_collisions(["a", "b", "a", "c", "b"]) == ["a", "b"]
    assert find_collisions(["a", "b"]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_naming.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'aerosuite.engine'`.

- [ ] **Step 3: Create `aerosuite/engine/__init__.py`**

```python
"""AeroSuite engine: all project, config, results and job logic. No UI imports."""
```

- [ ] **Step 4: Create `aerosuite/engine/errors.py`**

```python
"""Engine error types. Messages are written for the end user and shown as-is."""


class AeroSuiteError(Exception):
    """Base class for every error the engine raises on purpose."""


class ProjectError(AeroSuiteError):
    """A project folder, project.json or mesh could not be used."""


class TemplateError(AeroSuiteError):
    """The master .cfg template is missing or unreadable."""


class GenerationError(AeroSuiteError):
    """Case names or config files cannot be generated."""


class JobError(AeroSuiteError):
    """A job could not be started, refreshed or cancelled."""
```

- [ ] **Step 5: Create `aerosuite/engine/naming.py`**

```python
"""Case naming: sweep values <-> case names, in one place.

Names are tokens joined by "_":
    Mach   M<int>p<frac>        0.85 -> M0p85, 1.0 -> M1p0
    alpha  a[n]<int>[p<frac>]   5 -> a5, -5 -> an5, 2.5 -> a2p5
    beta   b[n]<int>[p<frac>]   same rules as alpha
Whole numbers give the same names as AeroSuite v7, so old run folders still parse.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, NamedTuple, Optional

from .errors import GenerationError


def format_value(value: float) -> str:
    """Shortest exact decimal text: 0.85 -> '0.85', 5.0 -> '5', -0.5 -> '-0.5'."""
    value = float(value)
    if value == 0:
        return "0"
    text = repr(value)
    if "e" in text:
        text = format(value, ".15f").rstrip("0").rstrip(".")
    if text.endswith(".0"):
        text = text[:-2]
    return text


def mach_token(mach: float) -> str:
    text = format_value(mach)
    if "." not in text:
        text += ".0"
    return "M" + text.replace(".", "p")


def angle_token(angle: float) -> str:
    """Angle token without its a/b prefix: 5 -> '5', -5 -> 'n5', 2.5 -> '2p5'."""
    text = format_value(abs(float(angle))).replace(".", "p")
    return "n" + text if float(angle) < 0 else text


def case_name(
    mach: float,
    alpha: float,
    beta: float,
    *,
    altitude: str = "",
    base_name: str = "",
    include_mach: bool = True,
    include_alpha: bool = True,
    include_beta: bool = True,
    include_altitude: bool = True,
    include_base: bool = True,
) -> str:
    parts = []
    if include_mach:
        parts.append(mach_token(mach))
    if include_altitude and altitude:
        parts.append(altitude.lower())
    if include_alpha:
        parts.append("a" + angle_token(alpha))
    if include_beta:
        parts.append("b" + angle_token(beta))
    if include_base and base_name:
        parts.append(base_name.lower())
    if not parts:
        raise GenerationError("At least one naming component must be included in case names")
    return "_".join(parts)


class ParsedName(NamedTuple):
    mach: Optional[float]
    alpha: Optional[float]
    beta: Optional[float]


_MACH_RE = re.compile(r"^m(\d+)(?:[p.](\d+))?$", re.IGNORECASE)
# Accepts a2p5 / an5 / a-5 (current) and legacy a5m / a5p sign suffixes.
_ANGLE_RE = re.compile(
    r"^(?P<neg>n|-)?(?P<int>\d+)(?:[p.](?P<frac>\d+))?(?P<sfx>[mp])?$", re.IGNORECASE
)


def _parse_angle(body: str) -> Optional[float]:
    match = _ANGLE_RE.match(body)
    if not match:
        return None
    value = float(match["int"] + ("." + match["frac"] if match["frac"] else ""))
    negative = bool(match["neg"]) or (match["sfx"] or "").lower() == "m"
    return -value if negative else value


def parse_case_name(name: str) -> ParsedName:
    """Recover Mach/alpha/beta from a case name; missing parts are None."""
    if name.lower().endswith(".cfg"):
        name = name[:-4]
    mach = alpha = beta = None
    for token in name.split("_"):
        if mach is None and (match := _MACH_RE.match(token)):
            mach = float(match[1] + ("." + match[2] if match[2] else ""))
            continue
        head, body = token[:1].lower(), token[1:]
        if alpha is None and head == "a":
            alpha = _parse_angle(body)
        elif beta is None and head == "b":
            beta = _parse_angle(body)
    return ParsedName(mach, alpha, beta)


def find_collisions(names: Iterable[str]) -> list[str]:
    """Names that occur more than once, sorted."""
    counts = Counter(names)
    return sorted(name for name, count in counts.items() if count > 1)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_naming.py -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add aerosuite/engine tests/engine/test_naming.py
git commit -m "feat(engine): add error types and exact, collision-aware case naming"
```

---

### Task 3: Project model

**Files:**
- Create: `aerosuite/engine/models.py`
- Test: `tests/engine/test_models.py`

**Interfaces:**
- Produces (all pydantic `BaseModel`, mutable):
  - `SCHEMA_VERSION: int = 1`
  - `Mesh(path: str = "", markers: list[str] = [])`
  - `Freestream(temperature_K, reynolds, reynolds_length: float | None = None)`
  - `Reference(origin_x, origin_y, origin_z, ref_length, ref_area: float | None = None)`
  - `Numerics(turb_model: str | None, cfl: float | None, iter: int | None, conv_method: str | None, muscl: str | None)` all default `None`
  - `Settings(freestream, reference, numerics, markers: dict[str, str | None] = {}, overrides: dict[str, str] = {})`
  - `Naming(include_mach=True, include_alpha=True, include_beta=True, include_altitude=True, include_base=True, base_name="")`
  - `SweepSpec(mach: list[float] = [], alpha: list[float] = [], beta: list[float] = [], altitude: str = "sl", naming: Naming)`
  - `RestartOption = Literal["none", "previous", "initial", "custom", "from_case"]`
  - `Case(name: str, mach: float, alpha: float, beta: float, restart: RestartOption = "none", restart_ref: str | None = None)`
  - `RunSettings(partitions: int >= 1 = 1, sweep_script: str = "", sweep_python: str = "python3", initial_restart: str | None = None)`
  - `Project(schema_version, name, created, modified, mesh, template: str = "template.cfg", preset: str | None, settings, sweep, cases: list[Case], run)`

- [ ] **Step 1: Write the failing tests `tests/engine/test_models.py`**

```python
import pytest
from pydantic import ValidationError

from aerosuite.engine.models import SCHEMA_VERSION, Case, Project, RunSettings


def test_new_project_defaults():
    project = Project(name="demo")
    assert project.schema_version == SCHEMA_VERSION
    assert project.template == "template.cfg"
    assert project.cases == []
    assert project.run.partitions == 1
    assert project.run.sweep_python == "python3"
    assert project.sweep.altitude == "sl"
    assert project.sweep.naming.include_mach is True


def test_json_round_trip_keeps_marker_removal_and_cases():
    project = Project(name="demo")
    project.settings.markers = {"MARKER_FAR": "( farfield )", "MARKER_PLOTTING": None}
    project.settings.freestream.reynolds = 6.5e6
    project.cases = [Case(name="M0p8_a0_b0", mach=0.8, alpha=0.0, beta=0.0, restart="previous")]
    restored = Project.model_validate_json(project.model_dump_json())
    assert restored == project
    assert restored.settings.markers["MARKER_PLOTTING"] is None


def test_partitions_must_be_positive():
    with pytest.raises(ValidationError):
        RunSettings(partitions=0)


def test_unknown_restart_option_rejected():
    with pytest.raises(ValidationError):
        Case(name="x", mach=0.8, alpha=0, beta=0, restart="sometimes")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.models'`.

- [ ] **Step 3: Create `aerosuite/engine/models.py`**

```python
"""Project model: every setting of a study, saved as project.json."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Mesh(BaseModel):
    path: str = ""
    markers: list[str] = Field(default_factory=list)


class Freestream(BaseModel):
    temperature_K: Optional[float] = None
    reynolds: Optional[float] = None
    reynolds_length: Optional[float] = None


class Reference(BaseModel):
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    origin_z: Optional[float] = None
    ref_length: Optional[float] = None
    ref_area: Optional[float] = None


class Numerics(BaseModel):
    turb_model: Optional[str] = None
    cfl: Optional[float] = None
    iter: Optional[int] = None
    conv_method: Optional[str] = None
    muscl: Optional[str] = None


class Settings(BaseModel):
    """Project-wide SU2 settings. A field left as None keeps the template's value."""

    freestream: Freestream = Field(default_factory=Freestream)
    reference: Reference = Field(default_factory=Reference)
    numerics: Numerics = Field(default_factory=Numerics)
    # None removes the MARKER_ line; an absent key keeps the template's line.
    markers: dict[str, Optional[str]] = Field(default_factory=dict)
    overrides: dict[str, str] = Field(default_factory=dict)


class Naming(BaseModel):
    include_mach: bool = True
    include_alpha: bool = True
    include_beta: bool = True
    include_altitude: bool = True
    include_base: bool = True
    base_name: str = ""


class SweepSpec(BaseModel):
    mach: list[float] = Field(default_factory=list)
    alpha: list[float] = Field(default_factory=list)
    beta: list[float] = Field(default_factory=list)
    altitude: str = "sl"
    naming: Naming = Field(default_factory=Naming)


RestartOption = Literal["none", "previous", "initial", "custom", "from_case"]


class Case(BaseModel):
    name: str
    mach: float
    alpha: float
    beta: float
    restart: RestartOption = "none"
    # custom: restart file path; from_case: name of an earlier case
    restart_ref: Optional[str] = None


class RunSettings(BaseModel):
    partitions: int = Field(default=1, ge=1)
    sweep_script: str = ""  # empty = bundled resources/aoa_sweep_v8.py
    sweep_python: str = "python3"  # must be able to import SU2
    initial_restart: Optional[str] = None  # passed as -r for cases with restart = "initial"


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = Field(default_factory=datetime.now)
    mesh: Mesh = Field(default_factory=Mesh)
    template: str = "template.cfg"
    preset: Optional[str] = None
    settings: Settings = Field(default_factory=Settings)
    sweep: SweepSpec = Field(default_factory=SweepSpec)
    cases: list[Case] = Field(default_factory=list)
    run: RunSettings = Field(default_factory=RunSettings)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/models.py tests/engine/test_models.py
git commit -m "feat(engine): add pydantic project model"
```

---

### Task 4: Config rendering and generation

**Files:**
- Create: `aerosuite/engine/cfg.py`
- Test: `tests/engine/test_cfg.py`

**Interfaces:**
- Consumes: `naming.case_name`, `naming.find_collisions`, `naming.format_value`; `models.Case`, `models.Project`, `models.Settings`; `errors.GenerationError`, `errors.ProjectError`, `errors.TemplateError`
- Produces:
  - constants `CONFIGS_DIR = "configs"`, `RUN_CONTROL_FILE = "run_control.txt"`, `CASE_INDEX_FILE = "cases.json"`
  - `extract_markers(mesh_path: Path) -> list[str]` (raises `ProjectError`)
  - `apply_parameters(content: str, parameters: Mapping[str, str | None]) -> str`
  - `settings_parameters(settings: Settings) -> dict[str, str | None]`
  - `case_parameters(project: Project, case: Case) -> dict[str, str]`
  - `read_template(project_dir: Path, project: Project) -> str` (raises `TemplateError`)
  - `render_case(template: str, project: Project, case: Case) -> str`
  - `build_cases(project: Project) -> list[Case]`
  - `run_control_text(cases: Sequence[Case]) -> str`
  - `generate_configs(project_dir: Path, project: Project) -> list[Path]` (raises `GenerationError`, `TemplateError`)

- [ ] **Step 1: Write the failing tests `tests/engine/test_cfg.py`**

```python
import json

import pytest

from aerosuite.engine.cfg import (
    CASE_INDEX_FILE,
    CONFIGS_DIR,
    RUN_CONTROL_FILE,
    apply_parameters,
    build_cases,
    extract_markers,
    generate_configs,
    render_case,
    run_control_text,
    settings_parameters,
)
from aerosuite.engine.errors import GenerationError, ProjectError, TemplateError
from aerosuite.engine.models import Case, Project

TEMPLATE = """\
% test template
MACH_NUMBER= 0.3
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_TEMPERATURE= 288.15
MARKER_FAR= ( farfield )
MARKER_HEATFLUX= ( wall, 0.0 )
MARKER_PLOTTING= ( wall )
MESH_FILENAME= mesh.su2
"""


def _project(**sweep):
    project = Project(name="t")
    project.sweep.mach = sweep.get("mach", [0.8])
    project.sweep.alpha = sweep.get("alpha", [0.0, 2.5])
    project.sweep.beta = sweep.get("beta", [0.0])
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    return project


def test_extract_markers(tmp_path):
    mesh = tmp_path / "m.su2"
    mesh.write_text("NDIME= 3\nNMARK= 2\nMARKER_TAG= farfield\nMARKER_ELEMS= 1\nMARKER_TAG = wall\n")
    assert extract_markers(mesh) == ["farfield", "wall"]


def test_extract_markers_missing_file(tmp_path):
    with pytest.raises(ProjectError):
        extract_markers(tmp_path / "nope.su2")


def test_apply_parameters_replaces_removes_and_appends():
    out = apply_parameters(TEMPLATE, {"AOA": "2.5", "MARKER_PLOTTING": None, "CFL_NUMBER": "5"})
    assert "AOA= 2.5\n" in out
    assert "MARKER_PLOTTING" not in out
    assert out.endswith("\n\nCFL_NUMBER= 5\n")


def test_apply_parameters_keeps_backslashes_literal():
    out = apply_parameters(TEMPLATE, {"MESH_FILENAME": r"C:\meshes\wing.su2"})
    assert r"MESH_FILENAME= C:\meshes\wing.su2" in out


def test_apply_parameters_does_not_touch_longer_keys():
    out = apply_parameters("MARKER_FARFIELD= x\nMARKER_FAR= y\n", {"MARKER_FAR": "z"})
    assert out == "MARKER_FARFIELD= x\nMARKER_FAR= z\n"


def test_settings_parameters_skip_unset_and_format_numbers():
    project = Project(name="t")
    project.settings.freestream.reynolds = 6.5e6
    project.settings.numerics.iter = 2000
    project.settings.markers = {"MARKER_PLOTTING": None}
    params = settings_parameters(project.settings)
    assert params == {"REYNOLDS_NUMBER": "6500000", "ITER": "2000", "MARKER_PLOTTING": None}


def test_render_case_layers_case_values_last(tmp_path):
    project = _project()
    project.mesh.path = str(tmp_path / "wing.su2")
    project.settings.overrides = {"AOA": "99", "CONV_FIELD": "LIFT"}
    project.settings.markers = {"MARKER_PLOTTING": None}
    case = project.cases[1]  # alpha 2.5
    out = render_case(TEMPLATE, project, case)
    assert "AOA= 2.5\n" in out
    assert "MACH_NUMBER= 0.8\n" in out
    assert "CONV_FIELD= LIFT" in out
    assert "MARKER_PLOTTING" not in out
    assert f"MESH_FILENAME= {(tmp_path / 'wing.su2').resolve()}" in out
    assert f"BREAKDOWN_FILENAME= {case.name}_FB.dat" in out


def test_build_cases_names_values_and_keeps_restart_choices():
    project = _project(mach=[0.8, 0.85], alpha=[0.0, 2.5], beta=[0.0])
    assert [c.name for c in project.cases] == [
        "M0p8_a0_b0", "M0p8_a2p5_b0", "M0p85_a0_b0", "M0p85_a2p5_b0",
    ]
    project.cases[1].restart = "previous"
    project.sweep.beta = [0.0, 1.0]
    rebuilt = build_cases(project)
    assert len(rebuilt) == 8
    assert next(c for c in rebuilt if c.name == "M0p8_a2p5_b0").restart == "previous"
    assert next(c for c in rebuilt if c.name == "M0p8_a2p5_b1").restart == "none"


def test_build_cases_empty_lists_default_to_zero():
    project = _project(mach=[0.5], alpha=[], beta=[])
    assert [(c.alpha, c.beta) for c in project.cases] == [(0.0, 0.0)]


def test_run_control_text():
    cases = [
        Case(name="c1", mach=0.8, alpha=0, beta=0),
        Case(name="c2", mach=0.8, alpha=2, beta=0, restart="previous"),
        Case(name="c3", mach=0.8, alpha=4, beta=0, restart="custom", restart_ref="/r/restart.dat"),
        Case(name="c4", mach=0.8, alpha=6, beta=0, restart="from_case", restart_ref="c1"),
        Case(name="c5", mach=0.8, alpha=8, beta=0, restart="initial"),
    ]
    assert run_control_text(cases) == (
        "c1.cfg, none\n"
        "c2.cfg, previous\n"
        "c3.cfg, custom, /r/restart.dat\n"
        "c4.cfg, from_case, c1.cfg\n"
        "c5.cfg, initial\n"
    )


def test_generate_configs_writes_cfgs_control_and_index(tmp_path):
    (tmp_path / "template.cfg").write_text(TEMPLATE)
    configs = tmp_path / CONFIGS_DIR
    configs.mkdir()
    (configs / "stale_old_case.cfg").write_text("old")
    project = _project()
    written = generate_configs(tmp_path, project)
    assert sorted(p.name for p in written) == ["M0p8_a0_b0.cfg", "M0p8_a2p5_b0.cfg"]
    assert not (configs / "stale_old_case.cfg").exists()
    assert "AOA= 2.5\n" in (configs / "M0p8_a2p5_b0.cfg").read_text()
    assert (configs / RUN_CONTROL_FILE).read_text() == "M0p8_a0_b0.cfg, none\nM0p8_a2p5_b0.cfg, none\n"
    index = json.loads((configs / CASE_INDEX_FILE).read_text())
    assert index["M0p8_a2p5_b0"] == {"mach": 0.8, "alpha": 2.5, "beta": 0.0}


def test_generate_configs_refuses_duplicate_names(tmp_path):
    (tmp_path / "template.cfg").write_text(TEMPLATE)
    project = _project(alpha=[2.0, 2.0])
    with pytest.raises(GenerationError, match="M0p8_a2_b0"):
        generate_configs(tmp_path, project)


def test_generate_configs_missing_template(tmp_path):
    with pytest.raises(TemplateError):
        generate_configs(tmp_path, _project())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_cfg.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.cfg'`.

- [ ] **Step 3: Create `aerosuite/engine/cfg.py`**

```python
"""SU2 config rendering: template + project settings + case values -> .cfg text."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .errors import GenerationError, ProjectError, TemplateError
from .models import Case, Project, Settings
from .naming import case_name, find_collisions, format_value

CONFIGS_DIR = "configs"
RUN_CONTROL_FILE = "run_control.txt"
CASE_INDEX_FILE = "cases.json"

_MARKER_TAG_RE = re.compile(r"^\s*MARKER_TAG\s*=\s*(\S+)")


def extract_markers(mesh_path: Path) -> list[str]:
    """Boundary marker names from the MARKER_TAG= lines of an .su2 mesh."""
    try:
        with open(mesh_path, "r", encoding="utf-8", errors="replace") as fh:
            return [m.group(1) for line in fh if (m := _MARKER_TAG_RE.match(line))]
    except OSError as exc:
        raise ProjectError(f"Cannot read mesh file {mesh_path}: {exc}") from exc


def apply_parameters(content: str, parameters: Mapping[str, Optional[str]]) -> str:
    """Set KEY= value lines in cfg text.

    Existing key -> line replaced; missing key -> appended at the end;
    value None -> line removed.
    """
    appended = []
    for key, value in parameters.items():
        line_re = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if value is None:
            content = re.sub(rf"^{re.escape(key)}\s*=.*(?:\n)?", "", content, flags=re.MULTILINE)
            continue
        line = f"{key}= {value}"
        if line_re.search(content):
            content = line_re.sub(lambda _match: line, content)
        else:
            appended.append(line)
    if appended:
        content = content.rstrip("\n") + "\n\n" + "\n".join(appended) + "\n"
    return content


def _number(value) -> Optional[str]:
    return None if value is None else format_value(value)


def settings_parameters(settings: Settings) -> dict[str, Optional[str]]:
    """Project-wide parameters; unset fields are omitted so the template value stands."""
    fs, ref, num = settings.freestream, settings.reference, settings.numerics
    candidates = {
        "FREESTREAM_TEMPERATURE": _number(fs.temperature_K),
        "REYNOLDS_NUMBER": _number(fs.reynolds),
        "REYNOLDS_LENGTH": _number(fs.reynolds_length),
        "REF_ORIGIN_MOMENT_X": _number(ref.origin_x),
        "REF_ORIGIN_MOMENT_Y": _number(ref.origin_y),
        "REF_ORIGIN_MOMENT_Z": _number(ref.origin_z),
        "REF_LENGTH": _number(ref.ref_length),
        "REF_AREA": _number(ref.ref_area),
        "KIND_TURB_MODEL": num.turb_model,
        "CFL_NUMBER": _number(num.cfl),
        "ITER": None if num.iter is None else str(num.iter),
        "CONV_NUM_METHOD_FLOW": num.conv_method,
        "MUSCL_FLOW": num.muscl,
    }
    params: dict[str, Optional[str]] = {k: v for k, v in candidates.items() if v is not None}
    params.update(settings.markers)
    params.update(settings.overrides)
    return params


def case_parameters(project: Project, case: Case) -> dict[str, str]:
    params = {
        "MACH_NUMBER": format_value(case.mach),
        "AOA": format_value(case.alpha),
        "SIDESLIP_ANGLE": format_value(case.beta),
        "BREAKDOWN_FILENAME": f"{case.name}_FB.dat",
    }
    if project.mesh.path:
        # Absolute, because the sweep runs from runs/ rather than from the cfg folder.
        params["MESH_FILENAME"] = str(Path(project.mesh.path).resolve())
    return params


def read_template(project_dir: Path, project: Project) -> str:
    path = Path(project_dir) / project.template
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Cannot read template {path}: {exc}") from exc


def render_case(template: str, project: Project, case: Case) -> str:
    """Template -> settings -> overrides -> case values; later layers win."""
    params = settings_parameters(project.settings)
    params.update(case_parameters(project, case))
    return apply_parameters(template, params)


def build_cases(project: Project) -> list[Case]:
    """Expand the sweep into cases, keeping restart choices of cases that still exist."""
    sweep, naming = project.sweep, project.sweep.naming
    previous = {case.name: case for case in project.cases}
    cases = []
    for mach in sweep.mach or [0.0]:
        for alpha in sweep.alpha or [0.0]:
            for beta in sweep.beta or [0.0]:
                name = case_name(
                    mach, alpha, beta,
                    altitude=sweep.altitude,
                    base_name=naming.base_name,
                    include_mach=naming.include_mach,
                    include_alpha=naming.include_alpha,
                    include_beta=naming.include_beta,
                    include_altitude=naming.include_altitude,
                    include_base=naming.include_base,
                )
                old = previous.get(name)
                cases.append(Case(
                    name=name, mach=mach, alpha=alpha, beta=beta,
                    restart=old.restart if old else "none",
                    restart_ref=old.restart_ref if old else None,
                ))
    return cases


def run_control_text(cases: Sequence[Case]) -> str:
    """run_control.txt in the format aoa_sweep_v8.py reads."""
    lines = []
    for case in cases:
        fields = [f"{case.name}.cfg", case.restart]
        if case.restart == "custom":
            fields.append(case.restart_ref or "")
        elif case.restart == "from_case":
            fields.append(f"{case.restart_ref}.cfg")
        lines.append(", ".join(fields))
    return "\n".join(lines) + "\n"


def generate_configs(project_dir: Path, project: Project) -> list[Path]:
    """Write configs/<case>.cfg for every case, plus run_control.txt and cases.json."""
    if not project.cases:
        raise GenerationError("The sweep has no cases; build the cases first")
    duplicates = find_collisions(case.name for case in project.cases)
    if duplicates:
        raise GenerationError(
            "These case names occur more than once and would overwrite each other: "
            + ", ".join(duplicates)
        )
    template = read_template(project_dir, project)
    out_dir = Path(project_dir) / CONFIGS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.cfg"):
        stale.unlink()
    written = []
    for case in project.cases:
        path = out_dir / f"{case.name}.cfg"
        path.write_text(render_case(template, project, case), encoding="utf-8", newline="\n")
        written.append(path)
    (out_dir / RUN_CONTROL_FILE).write_text(
        run_control_text(project.cases), encoding="utf-8", newline="\n"
    )
    index = {c.name: {"mach": c.mach, "alpha": c.alpha, "beta": c.beta} for c in project.cases}
    (out_dir / CASE_INDEX_FILE).write_text(json.dumps(index, indent=2), encoding="utf-8")
    return written
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_cfg.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/cfg.py tests/engine/test_cfg.py
git commit -m "feat(engine): add layered cfg rendering, case expansion and config generation"
```

---

### Task 5: Project folders

**Files:**
- Create: `aerosuite/engine/project.py`
- Test: `tests/engine/test_project.py`

**Interfaces:**
- Consumes: `models` (module, for `SCHEMA_VERSION`), `models.Project`, `models.Mesh`; `cfg.extract_markers`; `errors.ProjectError`, `errors.TemplateError`
- Produces:
  - constants `PROJECT_FILE = "project.json"`, `TEMPLATE_FILE = "template.cfg"`
  - `MIGRATIONS: dict[int, Callable[[dict], dict]]` (key = version migrated *from*)
  - `create_project(directory: Path, name: str | None = None) -> Project`
  - `open_project(directory: Path) -> Project`
  - `save_project(directory: Path, project: Project) -> None`
  - `migrate(data: dict) -> dict`
  - `set_template(directory: Path, project: Project, source: Path) -> None`
  - `set_mesh(project: Project, mesh_path: Path) -> None`

- [ ] **Step 1: Write the failing tests `tests/engine/test_project.py`**

```python
import json

import pytest

from aerosuite.engine import models, project as project_mod
from aerosuite.engine.errors import ProjectError, TemplateError
from aerosuite.engine.project import (
    PROJECT_FILE,
    TEMPLATE_FILE,
    create_project,
    open_project,
    save_project,
    set_mesh,
    set_template,
)


def test_create_then_open(tmp_path):
    folder = tmp_path / "study"
    created = create_project(folder)
    assert created.name == "study"
    assert (folder / PROJECT_FILE).is_file()
    opened = open_project(folder)
    assert opened.name == "study"


def test_create_refuses_existing_project(tmp_path):
    create_project(tmp_path)
    with pytest.raises(ProjectError):
        create_project(tmp_path)


def test_open_missing_or_invalid(tmp_path):
    with pytest.raises(ProjectError, match="No project"):
        open_project(tmp_path)
    (tmp_path / PROJECT_FILE).write_text("{not json")
    with pytest.raises(ProjectError):
        open_project(tmp_path)


def test_save_updates_modified_and_persists(tmp_path):
    project = create_project(tmp_path)
    before = project.modified
    project.sweep.mach = [0.85]
    save_project(tmp_path, project)
    assert project.modified >= before
    assert open_project(tmp_path).sweep.mach == [0.85]
    assert not list(tmp_path.glob("*.tmp"))


def test_newer_schema_is_refused(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = models.SCHEMA_VERSION + 1
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    with pytest.raises(ProjectError, match="newer"):
        open_project(tmp_path)


def test_migrations_run_in_order(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 2)

    def v1_to_v2(data):
        data["name"] = data["name"] + "-migrated"
        return data

    monkeypatch.setattr(project_mod, "MIGRATIONS", {1: v1_to_v2})
    opened = open_project(tmp_path)
    assert opened.name.endswith("-migrated")
    assert opened.schema_version == 2


def test_set_template_copies_into_project(tmp_path):
    project = create_project(tmp_path / "p")
    source = tmp_path / "master.cfg"
    source.write_text("AOA= 0\n")
    set_template(tmp_path / "p", project, source)
    assert (tmp_path / "p" / TEMPLATE_FILE).read_text() == "AOA= 0\n"
    assert project.template == TEMPLATE_FILE
    with pytest.raises(TemplateError):
        set_template(tmp_path / "p", project, tmp_path / "missing.cfg")


def test_set_mesh_reads_markers(tmp_path):
    project = create_project(tmp_path / "p")
    mesh = tmp_path / "wing.su2"
    mesh.write_text("MARKER_TAG= farfield\nMARKER_TAG= wall\n")
    set_mesh(project, mesh)
    assert project.mesh.path == str(mesh.resolve())
    assert project.mesh.markers == ["farfield", "wall"]
    with pytest.raises(ProjectError):
        set_mesh(project, tmp_path / "missing.su2")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_project.py -v`
Expected: `ImportError` for `aerosuite.engine.project`.

- [ ] **Step 3: Create `aerosuite/engine/project.py`**

```python
"""Project folders: create, open, save, schema migration, template and mesh selection."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from . import models
from .cfg import extract_markers
from .errors import ProjectError, TemplateError
from .models import Mesh, Project

PROJECT_FILE = "project.json"
TEMPLATE_FILE = "template.cfg"

# {from_version: function(data) -> data at from_version + 1}
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def create_project(directory: Path, name: Optional[str] = None) -> Project:
    directory = Path(directory)
    if (directory / PROJECT_FILE).exists():
        raise ProjectError(f"{directory} already contains a project")
    directory.mkdir(parents=True, exist_ok=True)
    project = Project(name=name or directory.resolve().name)
    save_project(directory, project)
    return project


def migrate(data: dict) -> dict:
    version = int(data.get("schema_version", 1))
    if version > models.SCHEMA_VERSION:
        raise ProjectError(
            f"This project was saved by a newer AeroSuite (schema {version}); please upgrade AeroSuite"
        )
    while version < models.SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


def open_project(directory: Path) -> Project:
    path = Path(directory) / PROJECT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError(f"No project found in {directory}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"Cannot read {path}: {exc}") from exc
    try:
        return Project.model_validate(migrate(data))
    except ValidationError as exc:
        raise ProjectError(f"{path} is not a valid project:\n{exc}") from exc


def save_project(directory: Path, project: Project) -> None:
    """Write project.json atomically (temp file + rename)."""
    project.modified = datetime.now()
    path = Path(directory) / PROJECT_FILE
    tmp = path.with_name(PROJECT_FILE + ".tmp")
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def set_template(directory: Path, project: Project, source: Path) -> None:
    """Copy a master template into the project so later edits to the original don't leak in."""
    source = Path(source)
    if not source.is_file():
        raise TemplateError(f"Template not found: {source}")
    shutil.copyfile(source, Path(directory) / TEMPLATE_FILE)
    project.template = TEMPLATE_FILE


def set_mesh(project: Project, mesh_path: Path) -> None:
    mesh_path = Path(mesh_path).resolve()
    if not mesh_path.is_file():
        raise ProjectError(f"Mesh not found: {mesh_path}")
    markers = extract_markers(mesh_path) if mesh_path.suffix.lower() == ".su2" else []
    project.mesh = Mesh(path=str(mesh_path), markers=markers)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_project.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/project.py tests/engine/test_project.py
git commit -m "feat(engine): add project folder create/open/save with schema migration"
```

---

### Task 6: Move atmosphere calculators into the engine

**Files:**
- Move: `aerosuite/core/isa_calculator.py` → `aerosuite/engine/atmosphere/isa.py`; `aerosuite/core/yplus_calculator.py` → `aerosuite/engine/atmosphere/yplus.py`
- Create: `aerosuite/engine/atmosphere/__init__.py`; new shim files at the old `core/` paths
- Test: `tests/engine/test_atmosphere.py`

**Interfaces:**
- Produces: `aerosuite.engine.atmosphere.ISACalculator` (unchanged class), `aerosuite.engine.atmosphere.yplus` (function, the old `calculate`), `FORMULAS`, `detect_flow_regime`, `compute_layers`. Old imports `aerosuite.core.isa_calculator.ISACalculator` and `aerosuite.core.yplus_calculator.calculate` keep working.

- [ ] **Step 1: Write the failing tests `tests/engine/test_atmosphere.py`**

```python
import pytest

from aerosuite.core.isa_calculator import ISACalculator as LegacyISA
from aerosuite.core.yplus_calculator import calculate as legacy_yplus
from aerosuite.engine.atmosphere import ISACalculator, yplus


def test_isa_sea_level():
    r = ISACalculator.calculate(0.0, 0.0, 1.0)
    assert r["temperature"] == pytest.approx(288.15)
    assert r["pressure"] == pytest.approx(101325.0)
    assert r["density"] == pytest.approx(1.2250, abs=1e-3)


def test_isa_tropopause():
    r = ISACalculator.calculate(11.0, 0.8, 1.0)
    assert r["temperature"] == pytest.approx(216.65)
    assert r["pressure"] == pytest.approx(22632, rel=1e-3)


def test_isa_rejects_out_of_range():
    with pytest.raises(ValueError):
        ISACalculator.calculate(101.0, 0.5, 1.0)


def test_yplus_turbulent_external():
    r = yplus(velocity=50.0, density=1.225, viscosity=1.789e-5, length=1.0,
              y_plus=1.0, domain_type="External")
    assert r["flow_type"] == "Turbulent"
    assert r["y1"] > 0
    assert r["y1_mm"] == pytest.approx(r["y1"] * 1000)


def test_legacy_imports_still_work():
    assert LegacyISA is ISACalculator
    assert legacy_yplus is yplus
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_atmosphere.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.atmosphere'`.

- [ ] **Step 3: Move the modules with history**

```bash
mkdir -p aerosuite/engine/atmosphere
git mv aerosuite/core/isa_calculator.py aerosuite/engine/atmosphere/isa.py
git mv aerosuite/core/yplus_calculator.py aerosuite/engine/atmosphere/yplus.py
```

- [ ] **Step 4: Create `aerosuite/engine/atmosphere/__init__.py`**

```python
"""Standard atmosphere and y+ first-cell-height calculators."""
from .isa import ISACalculator
from .yplus import FORMULAS, compute_layers, detect_flow_regime
from .yplus import calculate as yplus

__all__ = ["ISACalculator", "FORMULAS", "compute_layers", "detect_flow_regime", "yplus"]
```

- [ ] **Step 5: Create shim `aerosuite/core/isa_calculator.py`**

```python
"""Compatibility shim: moved to aerosuite.engine.atmosphere.isa (removed in Phase 5)."""
from aerosuite.engine.atmosphere.isa import ISACalculator  # noqa: F401
```

- [ ] **Step 6: Create shim `aerosuite/core/yplus_calculator.py`**

```python
"""Compatibility shim: moved to aerosuite.engine.atmosphere.yplus (removed in Phase 5)."""
from aerosuite.engine.atmosphere.yplus import (  # noqa: F401
    FORMULAS,
    calculate,
    compute_layers,
    detect_flow_regime,
)
```

- [ ] **Step 7: Run the atmosphere and smoke tests**

Run: `uv run pytest tests/engine/test_atmosphere.py tests/test_smoke.py -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/engine/atmosphere aerosuite/core/isa_calculator.py aerosuite/core/yplus_calculator.py tests/engine/test_atmosphere.py
git commit -m "refactor(engine): move ISA and y+ calculators into engine.atmosphere with core shims"
```

---

### Task 7: Results — history reading, convergence, summary

**Files:**
- Create: `aerosuite/engine/results.py`
- Modify: `tests/conftest.py` (add `history_writer` fixture)
- Test: `tests/engine/test_results.py`

**Interfaces:**
- Consumes: `naming.parse_case_name`; `cfg.CASE_INDEX_FILE`
- Produces:
  - constants `HISTORY_FILE = "history.csv"`, `DEFAULT_CONVERGENCE_COLUMNS = ("CL", "CD", "CMy")`, `MIN_CONVERGENCE_ITERATIONS = 10`, `CONVERGENCE_THRESHOLD = 1e-3`
  - `class HistoryReader(path)` with `.columns: list[str]` and `.read_new() -> pd.DataFrame`
  - `read_history(path: Path) -> pd.DataFrame`
  - `check_convergence(df: pd.DataFrame, columns: Sequence[str] = DEFAULT_CONVERGENCE_COLUMNS) -> tuple[bool, str]`
  - `load_case_index(configs_dir: Path) -> dict[str, dict[str, float]]`
  - `summarize(runs_dir: Path, columns: Sequence[str], last_n: int = 100, case_index: Mapping | None = None, skip: Iterable[str] = ()) -> tuple[pd.DataFrame, list[str]]` — columns `Case, Mach, Alpha, Beta, Converged, *columns`, sorted by Mach, Beta, Alpha
  - test fixture `history_writer` → `write(folder: Path, cl: list[float]) -> Path`

- [ ] **Step 1: Replace `tests/conftest.py` with this version (adds the `history_writer` fixture)**

```python
"""Shared pytest configuration and fixtures."""
from pathlib import Path

import matplotlib
import pytest

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

HISTORY_HEADER = '"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"'


@pytest.fixture
def history_writer():
    """Write an SU2-style history.csv whose CL column follows `cl`."""

    def write(folder: Path, cl: list[float]) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [HISTORY_HEADER]
        for i, value in enumerate(cl):
            lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {value:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
        path = folder / "history.csv"
        path.write_text("\n".join(lines) + "\n")
        return path

    return write
```

- [ ] **Step 2: Write the failing tests `tests/engine/test_results.py`**

```python
import json
import math

import pytest

from aerosuite.engine.results import (
    HistoryReader,
    check_convergence,
    load_case_index,
    read_history,
    summarize,
)

STEADY = [0.5] * 50
WOBBLY = [0.5 + 0.2 * math.sin(i) for i in range(50)]


def test_read_history_parses_su2_csv(tmp_path, history_writer):
    path = history_writer(tmp_path / "c", STEADY)
    df = read_history(path)
    assert list(df.columns) == ["Inner_Iter", "rms[Rho]", "CL", "CD", "CMy"]
    assert len(df) == 50
    assert df["CL"].iloc[-1] == pytest.approx(0.5)


def test_history_reader_returns_only_new_complete_rows(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text('"Inner_Iter", "CL"\n0, 0.1\n1, 0.2\n')
    reader = HistoryReader(path)
    assert len(reader.read_new()) == 2
    with open(path, "a") as fh:
        fh.write("2, 0.3\n3, 0.")  # last row incomplete
    new = reader.read_new()
    assert new["CL"].tolist() == [0.3]
    with open(path, "a") as fh:
        fh.write("4\n")
    assert reader.read_new()["CL"].tolist() == [0.4]


def test_history_reader_restarts_when_file_is_rewritten(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text('"Inner_Iter", "CL"\n0, 0.1\n1, 0.2\n2, 0.3\n')
    reader = HistoryReader(path)
    reader.read_new()
    path.write_text('"Inner_Iter", "CL"\n0, 0.9\n')
    assert reader.read_new()["CL"].tolist() == [0.9]


def test_read_history_legacy_tecplot_format(tmp_path):
    path = tmp_path / "history.dat"
    path.write_text('TITLE = "SU2"\nVARIABLES = "Iteration","CL"\nZONE T= "x"\n0, 0.1\n1, 0.2\n')
    df = read_history(path)
    assert list(df.columns) == ["Iteration", "CL"]
    assert len(df) == 2


def test_read_history_missing_file_is_empty(tmp_path):
    assert read_history(tmp_path / "none.csv").empty


def test_check_convergence(tmp_path, history_writer):
    steady = read_history(history_writer(tmp_path / "a", STEADY))
    wobbly = read_history(history_writer(tmp_path / "b", WOBBLY))
    short = read_history(history_writer(tmp_path / "c", STEADY[:5]))
    assert check_convergence(steady) == (True, "Converged")
    ok, message = check_convergence(wobbly)
    assert not ok and message.startswith("CL not converged")
    ok, message = check_convergence(short)
    assert not ok and "Insufficient iterations" in message


def test_load_case_index(tmp_path):
    assert load_case_index(tmp_path) == {}
    (tmp_path / "cases.json").write_text(json.dumps({"x": {"mach": 0.8, "alpha": 1.0, "beta": 0.0}}))
    assert load_case_index(tmp_path)["x"]["alpha"] == 1.0


def test_summarize_uses_index_then_names_and_sorts(tmp_path, history_writer):
    runs = tmp_path / "runs"
    history_writer(runs / "M0p8_a2p5_b1", STEADY)
    history_writer(runs / "M0p8_a0_b0", STEADY)
    history_writer(runs / "M0p8_a5_b0", WOBBLY)
    history_writer(runs / "custom_name", STEADY)
    history_writer(runs / "no_angles_here", STEADY)
    index = {"custom_name": {"mach": 0.6, "alpha": 1.0, "beta": 0.0}}
    df, warnings = summarize(runs, ["CL", "CD", "Missing"], last_n=10, case_index=index)
    assert df["Case"].tolist() == ["custom_name", "M0p8_a0_b0", "M0p8_a5_b0", "M0p8_a2p5_b1"]
    assert df.loc[df["Case"] == "M0p8_a2p5_b1", "Beta"].item() == 1.0
    assert not df.loc[df["Case"] == "M0p8_a5_b0", "Converged"].item()
    assert df["CL"].iloc[0] == pytest.approx(0.5)
    assert df["Missing"].isna().all()
    assert any("no_angles_here" in w for w in warnings)
    assert any("M0p8_a5_b0" in w for w in warnings)


def test_summarize_skip_and_empty(tmp_path, history_writer):
    runs = tmp_path / "runs"
    history_writer(runs / "M0p8_a0_b0", STEADY)
    df, _ = summarize(runs, ["CL"], skip=["M0p8_a0_b0"])
    assert df.empty
    assert list(df.columns) == ["Case", "Mach", "Alpha", "Beta", "Converged", "CL"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_results.py -v`
Expected: `ImportError` for `aerosuite.engine.results`.

- [ ] **Step 4: Create `aerosuite/engine/results.py`**

```python
"""SU2 results: history files, convergence and batch summaries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import pandas as pd

from .cfg import CASE_INDEX_FILE
from .naming import parse_case_name

HISTORY_FILE = "history.csv"
DEFAULT_CONVERGENCE_COLUMNS = ("CL", "CD", "CMy")
MIN_CONVERGENCE_ITERATIONS = 10
CONVERGENCE_THRESHOLD = 1e-3
SUMMARY_KEY_COLUMNS = ["Case", "Mach", "Alpha", "Beta", "Converged"]


def _fields(line: str) -> list[str]:
    return [field.strip().strip('"').replace(" ", "") for field in line.split(",")]


class HistoryReader:
    """Reads an SU2 history file incrementally.

    Each read_new() returns only the complete rows appended since the previous call,
    so live monitoring never re-reads the whole file. If the file shrinks (the case
    was re-run), reading starts over.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.columns: list[str] = []
        self._offset = 0

    def read_new(self) -> pd.DataFrame:
        try:
            if self.path.stat().st_size < self._offset:
                self._offset, self.columns = 0, []
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read()
        except FileNotFoundError:
            return pd.DataFrame(columns=self.columns)
        end = chunk.rfind(b"\n")
        if end < 0:
            return pd.DataFrame(columns=self.columns)
        complete = chunk[: end + 1]
        self._offset += len(complete)
        rows = []
        for raw in complete.decode("utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("TITLE", "ZONE", "#")):
                continue
            if not self.columns:
                if line.startswith("VARIABLES"):
                    line = line.split("=", 1)[1]
                self.columns = _fields(line)
                continue
            try:
                values = [float(field) for field in _fields(line)]
            except ValueError:
                continue
            if len(values) == len(self.columns):
                rows.append(values)
        return pd.DataFrame(rows, columns=self.columns)


def read_history(path: Path) -> pd.DataFrame:
    return HistoryReader(path).read_new()


def check_convergence(
    df: pd.DataFrame, columns: Sequence[str] = DEFAULT_CONVERGENCE_COLUMNS
) -> tuple[bool, str]:
    """Converged when std/mean over the last 10% (at least 10 rows) is below the threshold."""
    if len(df) < MIN_CONVERGENCE_ITERATIONS:
        return False, f"Insufficient iterations ({len(df)} < {MIN_CONVERGENCE_ITERATIONS})"
    check = [col for col in columns if col in df.columns]
    if not check:
        return True, "No convergence columns found, assuming converged"
    tail = df.tail(max(10, int(len(df) * 0.1)))
    for col in check:
        std = tail[col].std()
        mean = abs(tail[col].mean())
        if mean > 0 and std / mean > CONVERGENCE_THRESHOLD:
            return False, f"{col} not converged (std/mean = {std / mean:.2e})"
    return True, "Converged"


def load_case_index(configs_dir: Path) -> dict[str, dict[str, float]]:
    """cases.json written by generate_configs, or {} for legacy runs."""
    path = Path(configs_dir) / CASE_INDEX_FILE
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(
    runs_dir: Path,
    columns: Sequence[str],
    last_n: int = 100,
    case_index: Optional[Mapping[str, Mapping[str, float]]] = None,
    skip: Iterable[str] = (),
) -> tuple[pd.DataFrame, list[str]]:
    """Average the last `last_n` rows of every case's history into one table."""
    case_index = case_index or {}
    skip = set(skip)
    rows, warnings = [], []
    for history in sorted(Path(runs_dir).rglob(HISTORY_FILE)):
        name = history.parent.name
        if name in skip:
            continue
        if name in case_index:
            values = case_index[name]
            mach, alpha, beta = values.get("mach"), values.get("alpha"), values.get("beta")
        else:
            mach, alpha, beta = parse_case_name(name)
        if alpha is None:
            warnings.append(f"{name}: cannot determine alpha from the case name, skipped")
            continue
        df = read_history(history)
        if df.empty:
            warnings.append(f"{name}: history file is empty, skipped")
            continue
        converged, message = check_convergence(df)
        if not converged:
            warnings.append(f"{name}: {message}")
        averages = df.tail(max(1, min(last_n, len(df)))).mean(numeric_only=True)
        row = {"Case": name, "Mach": mach, "Alpha": alpha, "Beta": beta, "Converged": converged}
        for col in columns:
            row[col] = averages.get(col, float("nan"))
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=SUMMARY_KEY_COLUMNS + list(columns)), warnings
    summary = pd.DataFrame(rows)
    summary = summary.sort_values(["Mach", "Beta", "Alpha"], na_position="last").reset_index(drop=True)
    return summary, warnings
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_results.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/engine/results.py tests/engine/test_results.py tests/conftest.py
git commit -m "feat(engine): add incremental history reader, convergence check and summary"
```

---

### Task 8: Job records, job store, project lock, process helpers

**Files:**
- Create: `aerosuite/engine/jobs/__init__.py`, `aerosuite/engine/jobs/runner.py`, `aerosuite/engine/jobs/store.py`
- Test: `tests/engine/test_jobs_store.py`

**Interfaces:**
- Consumes: `models.Project`, `models.RunSettings`; `errors.JobError`
- Produces:
  - `runner.JobState(str, Enum)`: `QUEUED, RUNNING, DONE, FAILED, CANCELLED`
  - `runner.CaseState(str, Enum)`: `PENDING, RUNNING, CONVERGED, UNCONVERGED, FAILED, CANCELLED`
  - `runner.JobRecord` (pydantic): `id, backend, backend_ref: dict, cases: list[str], log_path: str (relative to project dir), created, finished: datetime | None, state: JobState, case_status: dict[str, CaseState], failure_tail: dict[str, str]`; property `is_active: bool`
  - `runner.Runner(Protocol)`: `submit(project_dir, project) -> JobRecord`, `refresh(project_dir, job) -> JobRecord`, `cancel(project_dir, job) -> JobRecord`
  - `runner.BUNDLED_SWEEP_SCRIPT: Path`, `runner.new_job_id() -> str`, `runner.sweep_script_path(run: RunSettings) -> Path`
  - `store.JOBS_DIR = "jobs"`, `store.LOCK_FILE = ".lock"`
  - `store.save_job(project_dir, job) -> None`, `store.load_job(project_dir, job_id) -> JobRecord`, `store.list_jobs(project_dir) -> list[JobRecord]` (newest first)
  - `store.process_alive(pid: int, create_time: float) -> bool`
  - `store.kill_tree(pid: int, timeout: float = 5.0) -> None`
  - `store.write_lock(project_dir, job_id: str, pid: int, create_time: float) -> None` (raises `JobError` if a lock exists)
  - `store.read_lock(project_dir) -> dict | None`, `store.clear_lock(project_dir, job_id: str | None = None) -> None`, `store.active_lock(project_dir) -> dict | None`

- [ ] **Step 1: Write the failing tests `tests/engine/test_jobs_store.py`**

```python
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import psutil
import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.runner import (
    BUNDLED_SWEEP_SCRIPT,
    CaseState,
    JobRecord,
    JobState,
    new_job_id,
    sweep_script_path,
)
from aerosuite.engine.jobs.store import (
    active_lock,
    clear_lock,
    kill_tree,
    list_jobs,
    load_job,
    process_alive,
    read_lock,
    save_job,
    write_lock,
)
from aerosuite.engine.models import RunSettings


def _job(job_id="j1", created=None):
    return JobRecord(
        id=job_id, backend="local", cases=["a"], log_path=f"jobs/{job_id}.log",
        created=created or datetime.now(), case_status={"a": CaseState.PENDING},
    )


def test_job_round_trip_and_listing(tmp_path):
    old = _job("old", datetime.now() - timedelta(hours=1))
    new = _job("new")
    new.state = JobState.RUNNING
    save_job(tmp_path, old)
    save_job(tmp_path, new)
    assert load_job(tmp_path, "new") == new
    assert [j.id for j in list_jobs(tmp_path)] == ["new", "old"]
    assert new.is_active and not _job().model_copy(update={"state": JobState.DONE}).is_active


def test_load_missing_job(tmp_path):
    with pytest.raises(JobError):
        load_job(tmp_path, "nope")


def test_ids_and_script_path():
    assert new_job_id() != new_job_id()
    assert sweep_script_path(RunSettings()) == BUNDLED_SWEEP_SCRIPT
    assert BUNDLED_SWEEP_SCRIPT.is_file()
    assert str(sweep_script_path(RunSettings(sweep_script="/x/s.py"))).endswith("s.py")


def test_process_alive():
    me = psutil.Process()
    assert process_alive(os.getpid(), me.create_time())
    assert not process_alive(os.getpid(), me.create_time() - 1000)  # pid reused by another process
    assert not process_alive(2**22 + 12345, 0.0)


def test_lock_lifecycle(tmp_path):
    me = psutil.Process()
    write_lock(tmp_path, "j1", os.getpid(), me.create_time())
    with pytest.raises(JobError):
        write_lock(tmp_path, "j2", os.getpid(), me.create_time())
    assert active_lock(tmp_path)["job_id"] == "j1"
    clear_lock(tmp_path, "other-job")
    assert read_lock(tmp_path) is not None
    clear_lock(tmp_path, "j1")
    assert read_lock(tmp_path) is None


def test_stale_lock_is_removed(tmp_path):
    write_lock(tmp_path, "j1", os.getpid(), 0.0)  # start time does not match: stale
    assert active_lock(tmp_path) is None
    assert read_lock(tmp_path) is None


def test_kill_tree_kills_children(tmp_path):
    code = (
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    parent = psutil.Process(proc.pid)
    deadline = time.monotonic() + 10
    while not parent.children() and time.monotonic() < deadline:
        time.sleep(0.05)
    children = parent.children(recursive=True)
    assert children
    tracked = [(p.pid, p.create_time()) for p in [parent, *children]]
    kill_tree(proc.pid)
    proc.wait(timeout=10)
    assert not any(process_alive(pid, ct) for pid, ct in tracked)


def test_kill_tree_on_dead_pid_is_harmless():
    kill_tree(2**22 + 12345)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_jobs_store.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.jobs'`.

- [ ] **Step 3: Create `aerosuite/engine/jobs/__init__.py`**

```python
"""Job execution: records, persistence and runners."""
```

- [ ] **Step 4: Create `aerosuite/engine/jobs/runner.py`**

```python
"""Job records and the Runner interface every backend (local, later Slurm) implements."""
from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from ..models import Project, RunSettings

BUNDLED_SWEEP_SCRIPT = Path(__file__).resolve().parents[2] / "resources" / "aoa_sweep_v8.py"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CaseState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CONVERGED = "CONVERGED"
    UNCONVERGED = "UNCONVERGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_JOB_STATES = {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
FINAL_CASE_STATES = {CaseState.CONVERGED, CaseState.UNCONVERGED, CaseState.FAILED, CaseState.CANCELLED}


class JobRecord(BaseModel):
    id: str
    backend: str
    backend_ref: dict[str, Any] = Field(default_factory=dict)  # local: {"pid", "create_time"}
    cases: list[str]
    log_path: str  # relative to the project directory
    created: datetime = Field(default_factory=datetime.now)
    finished: Optional[datetime] = None
    state: JobState = JobState.QUEUED
    case_status: dict[str, CaseState] = Field(default_factory=dict)
    failure_tail: dict[str, str] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state not in TERMINAL_JOB_STATES


class Runner(Protocol):
    def submit(self, project_dir: Path, project: Project) -> JobRecord: ...

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord: ...

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord: ...


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def sweep_script_path(run: RunSettings) -> Path:
    return Path(run.sweep_script) if run.sweep_script else BUNDLED_SWEEP_SCRIPT
```

- [ ] **Step 5: Create `aerosuite/engine/jobs/store.py`**

```python
"""Job persistence, the per-project lock, and process helpers (psutil, all platforms)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import psutil
from pydantic import ValidationError

from ..errors import JobError
from .runner import JobRecord

JOBS_DIR = "jobs"
LOCK_FILE = ".lock"


def _job_file(project_dir: Path, job_id: str) -> Path:
    return Path(project_dir) / JOBS_DIR / f"{job_id}.json"


def save_job(project_dir: Path, job: JobRecord) -> None:
    path = _job_file(project_dir, job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_job(project_dir: Path, job_id: str) -> JobRecord:
    path = _job_file(project_dir, job_id)
    try:
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise JobError(f"No job {job_id} in {project_dir}") from None
    except (OSError, ValidationError) as exc:
        raise JobError(f"Cannot read job record {path}: {exc}") from exc


def list_jobs(project_dir: Path) -> list[JobRecord]:
    """All jobs of a project, newest first."""
    jobs_dir = Path(project_dir) / JOBS_DIR
    jobs = [load_job(project_dir, p.stem) for p in jobs_dir.glob("*.json")] if jobs_dir.is_dir() else []
    return sorted(jobs, key=lambda job: job.created, reverse=True)


def process_alive(pid: int, create_time: float) -> bool:
    """True if `pid` is running and is the same process (start time matches). Zombies count as dead."""
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - create_time) > 1.0:
            return False
        return proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _running(proc: psutil.Process) -> bool:
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_gone(procs: list[psutil.Process], timeout: float) -> list[psutil.Process]:
    deadline = time.monotonic() + timeout
    alive = list(procs)
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _running(p)]
        if alive:
            time.sleep(0.05)
    return alive


def kill_tree(pid: int, timeout: float = 5.0) -> None:
    """Terminate a process and all its descendants (mpirun, SU2 ranks); kill survivors."""
    try:
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for proc in procs:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    for proc in _wait_gone(procs, timeout):
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    _wait_gone(procs, timeout)


def write_lock(project_dir: Path, job_id: str, pid: int, create_time: float) -> None:
    path = Path(project_dir) / LOCK_FILE
    try:
        with open(path, "x", encoding="utf-8") as fh:
            json.dump({"job_id": job_id, "pid": pid, "create_time": create_time}, fh)
    except FileExistsError:
        raise JobError("A job is already running for this project") from None


def read_lock(project_dir: Path) -> Optional[dict]:
    path = Path(project_dir) / LOCK_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return {"job_id": "?", "pid": -1, "create_time": 0.0}  # unreadable: treated as stale


def clear_lock(project_dir: Path, job_id: Optional[str] = None) -> None:
    """Remove the lock; with job_id, only if the lock belongs to that job."""
    lock = read_lock(project_dir)
    if lock is None or (job_id is not None and lock.get("job_id") != job_id):
        return
    try:
        (Path(project_dir) / LOCK_FILE).unlink()
    except FileNotFoundError:
        pass


def active_lock(project_dir: Path) -> Optional[dict]:
    """The lock if its process is still alive; a stale lock is removed and None returned."""
    lock = read_lock(project_dir)
    if lock is None:
        return None
    if process_alive(int(lock.get("pid", -1)), float(lock.get("create_time", 0.0))):
        return lock
    clear_lock(project_dir)
    return None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_jobs_store.py -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add aerosuite/engine/jobs tests/engine/test_jobs_store.py
git commit -m "feat(engine): add job records, job store, project lock and psutil process helpers"
```

---

### Task 9: LocalRunner with a fake sweep script

**Files:**
- Create: `aerosuite/engine/jobs/local.py`, `tests/fixtures/fake_sweep.py`
- Modify: `tests/conftest.py` (add `FAKE_SWEEP`, `TEMPLATE`, `ready_project` fixture)
- Test: `tests/engine/test_local_runner.py`

**Interfaces:**
- Consumes: `cfg.CONFIGS_DIR`, `cfg.RUN_CONTROL_FILE`, `cfg.build_cases`, `cfg.generate_configs`; `project.set_mesh`, `project.save_project`; `results.HISTORY_FILE`, `results.check_convergence`, `results.read_history`; everything from Task 8
- Produces:
  - `local.RUNS_DIR = "runs"`
  - `local.LocalRunner` with `backend = "local"`, `submit(project_dir, project) -> JobRecord`, `refresh(project_dir, job) -> JobRecord`, `cancel(project_dir, job) -> JobRecord`
  - test fixture `ready_project` → `(project_dir: Path, project: Project)`: template, `.su2` mesh with markers `farfield`, `wall`; sweep Mach `[0.8]`, α `[0, 2, 4]`, β `[0]`; cases `M0p8_a0_b0`, `M0p8_a2_b0`, `M0p8_a4_b0`; `run.sweep_python = sys.executable`, `run.sweep_script = FAKE_SWEEP`; configs **not** generated; project saved.

- [ ] **Step 1: Create the fake sweep script `tests/fixtures/fake_sweep.py`**

```python
"""Test stand-in for aoa_sweep_v8.py: same CLI, banners and output layout, no SU2.

Per-case behaviour comes from <cfg_dir>/fake_plan.json:
    {"delay": 0.05, "cases": {"<case name>": "converge" | "diverge" | "fail" | "hang"}}
Cases not listed converge.
"""
import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path


def write_history(folder: Path, diverge: bool) -> None:
    lines = ['"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"']
    for i in range(50):
        cl = 0.5 + (0.2 * math.sin(i) if diverge else 0.0)
        lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {cl:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
    (folder / "history.csv").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", dest="cfg_dir", required=True)
    parser.add_argument("-c", dest="control_file", required=True)
    parser.add_argument("-n", dest="partitions", default="1")
    parser.add_argument("-r", dest="initial_restart", default=None)
    args = parser.parse_args()

    plan_path = Path(args.cfg_dir) / "fake_plan.json"
    plan = json.loads(plan_path.read_text()) if plan_path.is_file() else {}
    delay = float(plan.get("delay", 0.05))
    behaviour = plan.get("cases", {})
    cfgs = [
        line.split(",")[0].strip()
        for line in Path(args.control_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

    if input("Proceed with this execution plan? (yes/no): ").strip().lower() not in ("yes", "y"):
        print("Execution cancelled by user.")
        return 0

    for i, cfg in enumerate(cfgs, 1):
        print(f"=== Running Case {i}/{len(cfgs)}: {cfg} ===", flush=True)
        name = cfg[:-4]
        folder = Path(name)
        if folder.is_dir():
            shutil.rmtree(folder)
        folder.mkdir()
        mode = behaviour.get(name, "converge")
        if mode == "hang":
            while True:
                time.sleep(0.1)
        time.sleep(delay)
        if mode == "fail":
            (folder / "error.log").write_text(f"Failed to run {cfg}:\nboom\n")
            print(f"ERROR: Simulation for {cfg} failed: boom", flush=True)
            continue
        write_history(folder, diverge=(mode == "diverge"))
        print("--> Iterations completed: 50", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Replace `tests/conftest.py` with this final version (adds `ready_project`)**

```python
"""Shared pytest configuration and fixtures."""
import sys
from pathlib import Path

import matplotlib
import pytest

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

from aerosuite.engine.cfg import build_cases  # noqa: E402
from aerosuite.engine.models import Project  # noqa: E402
from aerosuite.engine.project import save_project, set_mesh  # noqa: E402

HISTORY_HEADER = '"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"'


@pytest.fixture
def history_writer():
    """Write an SU2-style history.csv whose CL column follows `cl`."""

    def write(folder: Path, cl: list[float]) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [HISTORY_HEADER]
        for i, value in enumerate(cl):
            lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {value:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
        path = folder / "history.csv"
        path.write_text("\n".join(lines) + "\n")
        return path

    return write


FAKE_SWEEP = Path(__file__).resolve().parent / "fixtures" / "fake_sweep.py"

TEMPLATE = """\
MACH_NUMBER= 0.3
AOA= 0.0
SIDESLIP_ANGLE= 0.0
MARKER_FAR= ( farfield )
MARKER_HEATFLUX= ( wall, 0.0 )
MESH_FILENAME= mesh.su2
"""


@pytest.fixture
def ready_project(tmp_path):
    """A saved project with template, mesh, three cases and the fake sweep script."""
    project_dir = tmp_path / "study"
    project_dir.mkdir()
    (project_dir / "template.cfg").write_text(TEMPLATE)
    mesh = tmp_path / "wing.su2"
    mesh.write_text("NMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    project = Project(name="study")
    set_mesh(project, mesh)
    project.sweep.mach = [0.8]
    project.sweep.alpha = [0.0, 2.0, 4.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    project.run.sweep_python = sys.executable
    project.run.sweep_script = str(FAKE_SWEEP)
    save_project(project_dir, project)
    return project_dir, project
```

- [ ] **Step 3: Write the failing tests `tests/engine/test_local_runner.py`**

```python
import json
import os
import time

import pytest

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import load_job, process_alive, read_lock, write_lock

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _prepare(project_dir, project, cases=None, delay=0.05):
    generate_configs(project_dir, project)
    plan = {"delay": delay, "cases": cases or {}}
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps(plan))


def _wait(runner, project_dir, job, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.refresh(project_dir, job)
        if until(job):
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out: state={job.state} cases={job.case_status}")


def _finished(job):
    return not job.is_active


def test_all_cases_converge(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    assert job.state is JobState.RUNNING
    assert read_lock(project_dir)["job_id"] == job.id
    job = _wait(runner, project_dir, job, _finished)
    assert job.state is JobState.DONE
    assert set(job.case_status.values()) == {CaseState.CONVERGED}
    assert (project_dir / RUNS_DIR / A4 / "history.csv").is_file()
    assert read_lock(project_dir) is None
    assert load_job(project_dir, job.id).state is JobState.DONE


def test_failed_and_unconverged_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "fail", A4: "diverge"})
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.FAILED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.FAILED, A4: CaseState.UNCONVERGED,
    }
    assert "boom" in job.failure_tail[A2]


def test_cancel_stops_process_and_marks_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "hang"})
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    job = _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    pid, create_time = job.backend_ref["pid"], job.backend_ref["create_time"]
    job = runner.cancel(project_dir, job)
    assert job.state is JobState.CANCELLED
    assert job.case_status == {
        A0: CaseState.CONVERGED, A2: CaseState.CANCELLED, A4: CaseState.CANCELLED,
    }
    assert not process_alive(pid, create_time)
    assert read_lock(project_dir) is None


def test_second_submit_refused_while_running(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    try:
        with pytest.raises(JobError, match="already running"):
            runner.submit(project_dir, project)
    finally:
        runner.cancel(project_dir, job)


def test_state_survives_a_new_runner_instance(ready_project):
    """Simulates restarting the server: a fresh runner rebuilds state from disk and the OS."""
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A0: "hang"})
    first = LocalRunner()
    job = first.submit(project_dir, project)
    _wait(first, project_dir, job, lambda j: j.case_status[A0] is CaseState.RUNNING)

    second = LocalRunner()
    reloaded = second.refresh(project_dir, load_job(project_dir, job.id))
    assert reloaded.state is JobState.RUNNING
    assert reloaded.case_status[A0] is CaseState.RUNNING
    cancelled = second.cancel(project_dir, reloaded)
    assert cancelled.state is JobState.CANCELLED
    assert not process_alive(job.backend_ref["pid"], job.backend_ref["create_time"])


def test_stale_lock_does_not_block_submit(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    write_lock(project_dir, "ghost", os.getpid(), 0.0)
    runner = LocalRunner()
    job = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert job.state is JobState.DONE


def test_submit_without_configs(ready_project):
    project_dir, project = ready_project
    with pytest.raises(JobError, match="generate configs"):
        LocalRunner().submit(project_dir, project)


def test_submit_with_missing_python(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    project.run.sweep_python = str(project_dir / "no-such-python")
    with pytest.raises(JobError, match="Cannot start"):
        LocalRunner().submit(project_dir, project)
    assert read_lock(project_dir) is None
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_local_runner.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.jobs.local'`.

- [ ] **Step 5: Create `aerosuite/engine/jobs/local.py`**

```python
"""LocalRunner: runs the sweep script on this machine as a detached process.

All state is derived from disk and the OS (process liveness, the job log's
"Running Case i/n: <cfg>" banners, runs/<case>/error.log and history.csv), so a
fresh LocalRunner — e.g. after a server restart — reports the same state.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psutil

from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE
from ..errors import JobError
from ..models import Project
from ..results import HISTORY_FILE, check_convergence, read_history
from .runner import FINAL_CASE_STATES, CaseState, JobRecord, JobState, new_job_id, sweep_script_path
from .store import JOBS_DIR, active_lock, clear_lock, kill_tree, process_alive, save_job, write_lock

RUNS_DIR = "runs"
BANNER_RE = re.compile(r"Running Case\s+\d+/\d+:\s+(\S+?)\.cfg")
TAIL_LINES = 50


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _case_log_segment(log_text: str, name: str) -> str:
    """The part of the job log between this case's banner and the next one."""
    start = re.search(rf"Running Case\s+\d+/\d+:\s+{re.escape(name)}\.cfg", log_text)
    if not start:
        return ""
    rest = log_text[start.start():]
    following = BANNER_RE.search(rest, 1)
    return rest[: following.start()] if following else rest


class LocalRunner:
    backend = "local"

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        # job id -> (bytes of the log already scanned, case names whose banner was seen)
        self._scan: dict[str, tuple[int, list[str]]] = {}

    # -- Runner interface ---------------------------------------------------

    def submit(self, project_dir: Path, project: Project) -> JobRecord:
        project_dir = Path(project_dir).resolve()
        configs = project_dir / CONFIGS_DIR
        control = configs / RUN_CONTROL_FILE
        if not control.is_file():
            raise JobError(f"{control} not found; generate configs first")
        if active_lock(project_dir):
            raise JobError("A job is already running for this project")

        job_id = new_job_id()
        job = JobRecord(
            id=job_id,
            backend=self.backend,
            cases=[case.name for case in project.cases],
            log_path=f"{JOBS_DIR}/{job_id}.log",
            case_status={case.name: CaseState.PENDING for case in project.cases},
        )
        (project_dir / JOBS_DIR).mkdir(exist_ok=True)
        runs = project_dir / RUNS_DIR
        runs.mkdir(exist_ok=True)

        cmd = [
            project.run.sweep_python, str(sweep_script_path(project.run)),
            "-d", str(configs), "-c", str(control), "-n", str(project.run.partitions),
        ]
        if project.run.initial_restart:
            cmd += ["-r", project.run.initial_restart]
        if sys.platform == "win32":
            detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            detach = {"start_new_session": True}  # closing AeroSuite must not kill SU2
        try:
            with open(project_dir / job.log_path, "wb") as log:
                proc = subprocess.Popen(
                    cmd, cwd=runs, stdin=subprocess.PIPE, stdout=log,
                    stderr=subprocess.STDOUT, **detach,
                )
        except OSError as exc:
            raise JobError(f"Cannot start the sweep script ({' '.join(cmd)}): {exc}") from exc

        try:  # the script asks "Proceed with this execution plan? (yes/no)"
            proc.stdin.write(b"yes\n")
            proc.stdin.close()
        except OSError:
            pass
        try:
            create_time = psutil.Process(proc.pid).create_time()
        except psutil.NoSuchProcess:
            create_time = 0.0

        job.backend_ref = {"pid": proc.pid, "create_time": create_time}
        job.state = JobState.RUNNING
        try:
            write_lock(project_dir, job.id, proc.pid, create_time)
        except JobError:
            kill_tree(proc.pid)
            proc.wait()
            raise
        self._procs[job.id] = proc
        save_job(project_dir, job)
        return job

    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        alive = self._alive(job)
        self._update_cases(project_dir, job, alive)
        if not alive:
            self._finish(project_dir, job)
        save_job(project_dir, job)
        return job

    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord:
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        alive = self._alive(job)
        self._update_cases(project_dir, job, alive)  # mark the case that is running now
        if alive:
            kill_tree(job.backend_ref["pid"])
        proc = self._procs.pop(job.id, None)
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for name, state in job.case_status.items():
            if state in (CaseState.PENDING, CaseState.RUNNING):
                job.case_status[name] = CaseState.CANCELLED
        job.state = JobState.CANCELLED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(job.id, None)
        save_job(project_dir, job)
        return job

    # -- internals ------------------------------------------------------------

    def _alive(self, job: JobRecord) -> bool:
        proc = self._procs.get(job.id)
        if proc is not None:  # we started it: poll() also reaps it
            if proc.poll() is None:
                return True
            self._procs.pop(job.id, None)
            return False
        ref = job.backend_ref
        return process_alive(int(ref.get("pid", -1)), float(ref.get("create_time", 0.0)))

    def _started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        """Case names whose banner is in the log, reading only bytes not scanned yet."""
        offset, started = self._scan.get(job.id, (0, []))
        try:
            with open(project_dir / job.log_path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except FileNotFoundError:
            return started
        end = chunk.rfind(b"\n")
        if end >= 0:
            text = chunk[: end + 1].decode("utf-8", errors="replace")
            started = started + BANNER_RE.findall(text)
            offset += end + 1
        self._scan[job.id] = (offset, started)
        return started

    def _update_cases(self, project_dir: Path, job: JobRecord, alive: bool) -> None:
        started = self._started_cases(project_dir, job)
        current = started[-1] if (alive and started) else None
        runs = project_dir / RUNS_DIR
        for name in job.cases:
            if job.case_status.get(name) in FINAL_CASE_STATES:
                continue
            if name not in started:
                job.case_status[name] = CaseState.PENDING
            elif name == current:
                job.case_status[name] = CaseState.RUNNING
            else:
                self._evaluate_finished_case(project_dir, job, runs / name, name)

    def _evaluate_finished_case(self, project_dir: Path, job: JobRecord, folder: Path, name: str) -> None:
        error_log = folder / "error.log"
        if error_log.is_file():
            segment = _case_log_segment(_read_text(project_dir / job.log_path), name)
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = _tail(_read_text(error_log) + "\n" + segment)
            return
        history = folder / HISTORY_FILE
        df = read_history(history) if history.is_file() else None
        if df is None or df.empty:
            segment = _case_log_segment(_read_text(project_dir / job.log_path), name)
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = "No history.csv was written.\n" + _tail(segment)
            return
        converged, _message = check_convergence(df)
        job.case_status[name] = CaseState.CONVERGED if converged else CaseState.UNCONVERGED

    def _finish(self, project_dir: Path, job: JobRecord) -> None:
        log_tail = _tail(_read_text(project_dir / job.log_path))
        for name, state in job.case_status.items():
            if state is CaseState.PENDING:
                job.case_status[name] = CaseState.FAILED
                job.failure_tail[name] = "The sweep process exited before this case started.\n" + log_tail
        ok = {CaseState.CONVERGED, CaseState.UNCONVERGED}
        job.state = JobState.DONE if all(s in ok for s in job.case_status.values()) else JobState.FAILED
        job.finished = datetime.now()
        clear_lock(project_dir, job.id)
        self._scan.pop(job.id, None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_local_runner.py -v`
Expected: 8 passed (each runs a real subprocess; total well under a minute).

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/engine/jobs/local.py tests/fixtures/fake_sweep.py tests/conftest.py tests/engine/test_local_runner.py
git commit -m "feat(engine): add LocalRunner with disk-derived job state, tested against a fake sweep"
```

---

### Task 10: Preflight checks

**Files:**
- Create: `aerosuite/engine/preflight.py`
- Test: `tests/engine/test_preflight.py`

**Interfaces:**
- Consumes: `cfg.CONFIGS_DIR`, `cfg.RUN_CONTROL_FILE`, `cfg.generate_configs`; `naming.find_collisions`; `jobs.runner.sweep_script_path`; `jobs.store.active_lock`, `jobs.store.write_lock`; `ready_project` fixture
- Produces:
  - `Problem` (frozen dataclass): `severity: Literal["error", "warning"]`, `message: str`
  - `preflight(project_dir: Path, project: Project, action: Literal["generate", "run"]) -> list[Problem]`
  - `has_errors(problems: Iterable[Problem]) -> bool`

- [ ] **Step 1: Write the failing tests `tests/engine/test_preflight.py`**

```python
import os

import psutil

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.store import write_lock
from aerosuite.engine.models import Case
from aerosuite.engine.preflight import Problem, has_errors, preflight


def _messages(problems, severity):
    return [p.message for p in problems if p.severity == severity]


def test_valid_project_has_no_generate_problems(ready_project):
    project_dir, project = ready_project
    assert preflight(project_dir, project, "generate") == []


def test_missing_template_and_mesh(ready_project):
    project_dir, project = ready_project
    (project_dir / "template.cfg").unlink()
    project.mesh.path = str(project_dir / "gone.su2")
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("Template not found" in m for m in errors)
    assert any("Mesh not found" in m for m in errors)


def test_no_mesh_and_no_cases(ready_project):
    project_dir, project = ready_project
    project.mesh.path = ""
    project.cases = []
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert "No mesh selected" in errors
    assert "The sweep has no cases" in errors


def test_duplicate_case_names(ready_project):
    project_dir, project = ready_project
    project.cases.append(project.cases[0].model_copy())
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert any("M0p8_a0_b0" in m and "Duplicate" in m for m in errors)


def test_unknown_marker_is_a_warning(ready_project):
    project_dir, project = ready_project
    project.settings.markers = {"MARKER_HEATFLUX": "( wall, fuselage, 0.0 )", "MARKER_PLOTTING": None}
    problems = preflight(project_dir, project, "generate")
    assert not has_errors(problems)
    assert _messages(problems, "warning") == [
        "MARKER_HEATFLUX refers to 'fuselage', which is not a marker in the mesh"
    ]


def test_restart_problems(ready_project, tmp_path):
    project_dir, project = ready_project
    a0, a2, a4 = project.cases
    a0.restart = "previous"
    a2.restart, a2.restart_ref = "from_case", "M0p8_a4_b0"  # later case: invalid
    a4.restart, a4.restart_ref = "custom", str(tmp_path / "missing.dat")
    project.cases.append(Case(name="extra", mach=0.8, alpha=6, beta=0, restart="initial"))
    problems = preflight(project_dir, project, "generate")
    assert any("first case" in m for m in _messages(problems, "warning"))
    errors = _messages(problems, "error")
    assert any("M0p8_a2_b0" in m and "earlier case" in m for m in errors)
    assert any("M0p8_a4_b0" in m and "restart file not found" in m for m in errors)
    assert any("extra" in m and "initial_restart" in m for m in errors)


def test_run_checks(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.delenv("SU2_RUN", raising=False)
    project.run.sweep_script = str(project_dir / "missing_script.py")
    project.run.sweep_python = "definitely-not-a-python-xyz"
    errors = _messages(preflight(project_dir, project, "run"), "error")
    assert any("have not been generated" in m for m in errors)
    assert any("SU2_RUN" in m for m in errors)
    assert any("Sweep script not found" in m for m in errors)
    assert any("Python for the sweep script not found" in m for m in errors)


def test_run_ready_and_locked(ready_project, monkeypatch):
    project_dir, project = ready_project
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    generate_configs(project_dir, project)
    assert preflight(project_dir, project, "run") == []
    write_lock(project_dir, "j1", os.getpid(), psutil.Process().create_time())
    errors = _messages(preflight(project_dir, project, "run"), "error")
    assert errors == ["Job j1 is still running for this project"]


def test_has_errors():
    assert has_errors([Problem("warning", "w"), Problem("error", "e")])
    assert not has_errors([Problem("warning", "w")])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_preflight.py -v`
Expected: `ModuleNotFoundError: No module named 'aerosuite.engine.preflight'`.

- [ ] **Step 3: Create `aerosuite/engine/preflight.py`**

```python
"""Checks run before generating configs or starting a job. Returns every problem at once."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .cfg import CONFIGS_DIR, RUN_CONTROL_FILE
from .jobs.runner import sweep_script_path
from .jobs.store import active_lock
from .models import Project
from .naming import find_collisions


@dataclass(frozen=True)
class Problem:
    severity: Literal["error", "warning"]
    message: str


def has_errors(problems: Iterable[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _marker_problems(project: Project) -> list[Problem]:
    known = set(project.mesh.markers)
    if not known:
        return []
    problems = []
    for key, value in project.settings.markers.items():
        if not value:
            continue
        names = [part.strip() for part in value.strip().strip("()").split(",") if part.strip()]
        for name in names:
            if not _is_number(name) and name not in known:
                problems.append(Problem(
                    "warning", f"{key} refers to '{name}', which is not a marker in the mesh"
                ))
    return problems


def _restart_problems(project: Project) -> list[Problem]:
    problems = []
    earlier: set[str] = set()
    for index, case in enumerate(project.cases):
        if case.restart == "previous" and index == 0:
            problems.append(Problem(
                "warning", f"{case.name}: 'previous' restart on the first case will start from scratch"
            ))
        elif case.restart == "custom":
            if not case.restart_ref:
                problems.append(Problem("error", f"{case.name}: 'custom' restart needs a restart file"))
            elif not Path(case.restart_ref).is_file():
                problems.append(Problem("error", f"{case.name}: restart file not found: {case.restart_ref}"))
        elif case.restart == "from_case" and case.restart_ref not in earlier:
            problems.append(Problem(
                "error",
                f"{case.name}: 'from_case' must reference an earlier case (got {case.restart_ref!r})",
            ))
        elif case.restart == "initial":
            initial = project.run.initial_restart
            if not initial:
                problems.append(Problem(
                    "error", f"{case.name}: 'initial' restart needs run.initial_restart to be set"
                ))
            elif not Path(initial).is_file():
                problems.append(Problem("error", f"{case.name}: initial restart file not found: {initial}"))
        earlier.add(case.name)
    return problems


def _run_problems(project_dir: Path, project: Project) -> list[Problem]:
    problems = []
    if not (project_dir / CONFIGS_DIR / RUN_CONTROL_FILE).is_file():
        problems.append(Problem("error", "Configs have not been generated (configs/run_control.txt is missing)"))
    if not os.environ.get("SU2_RUN"):
        problems.append(Problem("error", "SU2_RUN is not set; the sweep script needs it to import SU2"))
    script = sweep_script_path(project.run)
    if not script.is_file():
        problems.append(Problem("error", f"Sweep script not found: {script}"))
    python = project.run.sweep_python
    if shutil.which(python) is None and not Path(python).is_file():
        problems.append(Problem("error", f"Python for the sweep script not found: {python}"))
    lock = active_lock(project_dir)
    if lock:
        problems.append(Problem("error", f"Job {lock['job_id']} is still running for this project"))
    return problems


def preflight(project_dir: Path, project: Project, action: Literal["generate", "run"]) -> list[Problem]:
    project_dir = Path(project_dir)
    problems: list[Problem] = []
    template = project_dir / project.template
    if not template.is_file():
        problems.append(Problem("error", f"Template not found: {template}"))
    if not project.mesh.path:
        problems.append(Problem("error", "No mesh selected"))
    elif not Path(project.mesh.path).is_file():
        problems.append(Problem("error", f"Mesh not found: {project.mesh.path}"))
    if not project.cases:
        problems.append(Problem("error", "The sweep has no cases"))
    duplicates = find_collisions(case.name for case in project.cases)
    if duplicates:
        problems.append(Problem(
            "error", "Duplicate case names (files would overwrite each other): " + ", ".join(duplicates)
        ))
    problems += _marker_problems(project)
    problems += _restart_problems(project)
    if action == "run":
        problems += _run_problems(project_dir, project)
    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_preflight.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/preflight.py tests/engine/test_preflight.py
git commit -m "feat(engine): add preflight checks for generate and run"
```

---

### Task 11: Legacy generator and Sweep page use exact values and names

**Files:**
- Modify: `aerosuite/core/su2_generator.py` (whole file replaced below)
- Modify: `aerosuite/ui/sweep_setup_tab.py:21` (import) and `:222-224` (value formatting)
- Test: `tests/legacy/test_legacy_generator.py`

**Interfaces:**
- Consumes: `naming.angle_token`, `naming.case_name`, `naming.find_collisions`, `naming.mach_token`; `cfg.apply_parameters`, `cfg.extract_markers`; `errors.ProjectError`
- Produces: unchanged public API of `SU2Generator` and `GenerationConfig` (`format_mach`, `format_angle`, `generate_filename`, `generate_all_filenames`, `validate_config`, `REMOVE_LINE`, `update_template_content`, `extract_mesh_markers`, `create_batch_file`), now correct.

- [ ] **Step 1: Write the failing tests `tests/legacy/test_legacy_generator.py`**

```python
from pathlib import Path

from aerosuite.core.su2_generator import GenerationConfig, SU2Generator


def _config(tmp_path, **overrides):
    template = tmp_path / "base.cfg"
    template.write_text("AOA= 0\n")
    values = dict(
        mach_values=[0.8], alpha_values=[0.0], beta_values=[0.0],
        include_mach=True, include_alpha=True, include_beta=True,
        include_altitude=True, include_base=True, altitude="sl", base_name="x07",
        output_dir=tmp_path / "out", template_path=template,
    )
    values.update(overrides)
    return GenerationConfig(**values)


def test_format_mach_keeps_all_digits_and_v7_whole_numbers():
    assert SU2Generator.format_mach(0.85) == "M0p85"
    assert SU2Generator.format_mach(0.78) == "M0p78"
    assert SU2Generator.format_mach(0.8) == "M0p8"
    assert SU2Generator.format_mach(1.0) == "M1p0"


def test_format_angle():
    assert SU2Generator.format_angle(-5) == "n5"
    assert SU2Generator.format_angle(2.5) == "2p5"
    assert SU2Generator.format_angle(1.5) == "1p5"


def test_filenames_no_longer_collide(tmp_path):
    config = _config(tmp_path, mach_values=[0.78, 0.8, 0.82, 0.85], alpha_values=[1.5, 2.5])
    names = SU2Generator.generate_all_filenames(config)
    assert len(set(names)) == 8
    assert "M0p85_sl_a2p5_b0_x07.cfg" in names


def test_validate_config_rejects_duplicate_names(tmp_path):
    ok, message = SU2Generator.validate_config(_config(tmp_path, alpha_values=[2.0, 2.0]))
    assert not ok
    assert "M0p8_sl_a2_b0_x07.cfg" in message


def test_validate_config_accepts_distinct_values(tmp_path):
    assert SU2Generator.validate_config(_config(tmp_path, alpha_values=[1.5, 2.5])) == (True, "")


def test_update_template_content_remove_and_backslash():
    content = "MARKER_PLOTTING= ( wall )\nMESH_FILENAME= a.su2\n"
    out = SU2Generator.update_template_content(content, {
        "MARKER_PLOTTING": SU2Generator.REMOVE_LINE,
        "MESH_FILENAME": r"C:\m\wing.su2",
    })
    assert out == "MESH_FILENAME= C:\\m\\wing.su2\n"


def test_extract_mesh_markers_missing_file_returns_empty(tmp_path):
    assert SU2Generator.extract_mesh_markers(Path(tmp_path / "none.su2")) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/legacy/test_legacy_generator.py -v`
Expected: FAIL — e.g. `assert 'M0p8' == 'M0p85'` and the duplicate-name test passing validation.

- [ ] **Step 3: Replace `aerosuite/core/su2_generator.py` with**

```python
"""
SU2 Configuration File Generator (legacy API).

Naming and template substitution now delegate to aerosuite.engine so the
legacy pages and the new engine can never disagree.
"""

from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass

from aerosuite.engine.cfg import apply_parameters, extract_markers
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.naming import angle_token, case_name, find_collisions, mach_token


@dataclass
class GenerationConfig:
    """Configuration for batch file generation."""
    mach_values: List[float]
    alpha_values: List[float]
    beta_values: List[float]
    include_mach: bool
    include_alpha: bool
    include_beta: bool
    include_altitude: bool
    include_base: bool
    altitude: str
    base_name: str
    output_dir: Path
    template_path: Path

    def get_total_cases(self) -> int:
        """Calculate total number of cases to generate."""
        return len(self.mach_values) * len(self.alpha_values) * len(self.beta_values)


class SU2Generator:
    """Generator for SU2 configuration files."""

    @staticmethod
    def format_mach(mach: float) -> str:
        """Mach token for filenames, e.g. 'M0p85' for 0.85, 'M1p0' for 1.0."""
        return mach_token(mach)

    @staticmethod
    def format_angle(angle: float) -> str:
        """Angle token for filenames, e.g. 'n5' for -5, '2p5' for 2.5."""
        return angle_token(angle)

    @staticmethod
    def generate_filename(
        mach: float,
        alpha: float,
        beta: float,
        altitude: str,
        base_name: str,
        include_mach: bool,
        include_alpha: bool,
        include_beta: bool,
        include_altitude: bool,
        include_base: bool
    ) -> str:
        """Filename (with .cfg) for one case."""
        return case_name(
            mach, alpha, beta,
            altitude=altitude, base_name=base_name,
            include_mach=include_mach, include_alpha=include_alpha,
            include_beta=include_beta, include_altitude=include_altitude,
            include_base=include_base,
        ) + ".cfg"

    @staticmethod
    def generate_all_filenames(config: GenerationConfig) -> List[str]:
        """Filenames for every Mach x alpha x beta combination, in generation order."""
        return [
            SU2Generator.generate_filename(
                m, a, b, config.altitude, config.base_name,
                config.include_mach, config.include_alpha, config.include_beta,
                config.include_altitude, config.include_base,
            )
            for m in config.mach_values
            for a in config.alpha_values
            for b in config.beta_values
        ]

    @staticmethod
    def validate_config(config: GenerationConfig) -> Tuple[bool, str]:
        """Return (is_valid, error_message)."""
        if not config.template_path.exists():
            return False, "Template file does not exist"

        conflicts = []
        if len(config.mach_values) > 1 and not config.include_mach:
            conflicts.append("Mach Numbers")
        if len(config.alpha_values) > 1 and not config.include_alpha:
            conflicts.append("Alpha Values")
        if len(config.beta_values) > 1 and not config.include_beta:
            conflicts.append("Beta Values")

        if conflicts:
            msg = (
                f"You have multiple values for {', '.join(conflicts)} "
                "but haven't checked 'Inc. in Name'. Files will overwrite.\n\n"
                "Please check the naming boxes."
            )
            return False, msg

        if not any([
            config.include_base, config.include_mach,
            config.include_altitude, config.include_alpha,
            config.include_beta
        ]):
            return False, "At least one naming component must be checked"

        duplicates = find_collisions(SU2Generator.generate_all_filenames(config))
        if duplicates:
            return False, (
                "These files would be generated more than once and overwrite each other "
                "(check for repeated values):\n  " + "\n  ".join(duplicates)
            )

        return True, ""

    # Sentinel value: pass this as a parameter value to remove the line entirely
    REMOVE_LINE = "__REMOVE_LINE__"

    @staticmethod
    def update_template_content(content: str, parameters: Dict[str, str]) -> str:
        """Replace existing KEY= lines, append missing keys, delete REMOVE_LINE keys."""
        return apply_parameters(content, {
            key: (None if value == SU2Generator.REMOVE_LINE else value)
            for key, value in parameters.items()
        })

    @staticmethod
    def extract_mesh_markers(mesh_path: Path) -> List[str]:
        """Boundary marker tags of an .su2 mesh; [] if the file cannot be read."""
        try:
            return extract_markers(mesh_path)
        except ProjectError as e:
            print(f"Error reading mesh file: {e}")
            return []

    @staticmethod
    def create_batch_file(
        output_dir: Path,
        files: List[str],
        restart_option: str,
        custom_path: Path = None
    ) -> bool:
        """
        Create batch control file for sequential runs.

        Args:
            output_dir: Output directory
            files: List of configuration filenames
            restart_option: Restart option ('none', 'previous', 'custom')
            custom_path: Custom restart path (for 'custom' option)

        Returns:
            True if successful, False otherwise
        """
        batch_path = output_dir / "run_control.txt"

        try:
            with open(batch_path, 'w', encoding='utf-8') as f:
                for i, cfg in enumerate(files):
                    if restart_option == 'none':
                        f.write(f"{cfg}, none\n")
                    elif restart_option == 'previous':
                        if i == 0:
                            f.write(f"{cfg}, none\n")
                        else:
                            f.write(f"{cfg}, previous\n")
                    elif restart_option == 'custom' and custom_path:
                        cfg_stem = Path(cfg).stem
                        restart_path = custom_path / cfg_stem / "restart_flow.dat"
                        f.write(f"{cfg}, custom, {restart_path}\n")
            return True
        except IOError as e:
            print(f"Error creating batch file: {e}")
            return False
```

- [ ] **Step 4: Fix the value formatting on the legacy Sweep page**

In `aerosuite/ui/sweep_setup_tab.py`, after the line `from ..core.su2_generator import SU2Generator, GenerationConfig` add:

```python
from ..engine.naming import format_value
```

and replace

```python
                    "MACH_NUMBER":            f"{m:.1f}",
                    "AOA":                    f"{a:.1f}",
                    "SIDESLIP_ANGLE":         f"{b:.1f}",
```

with

```python
                    "MACH_NUMBER":            format_value(m),
                    "AOA":                    format_value(a),
                    "SIDESLIP_ANGLE":         format_value(b),
```

- [ ] **Step 5: Run the legacy and smoke tests**

Run: `uv run pytest tests/legacy/test_legacy_generator.py tests/test_smoke.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/core/su2_generator.py aerosuite/ui/sweep_setup_tab.py tests/legacy/test_legacy_generator.py
git commit -m "fix: sweep writes exact Mach/AoA/beta and refuses colliding case names"
```

---

### Task 12: Legacy results read beta; runs report convergence; Stop kills the tree

**Files:**
- Modify: `aerosuite/core/aerosummary.py` (imports; `check_convergence`, `extract_mach_from_case_name`, `extract_alpha_from_case_name`, `is_valid_case_name`; new `extract_beta_from_case_name`; Beta column + sort in `consolidate_results`; `generate_plots`)
- Modify: `aerosuite/core/sweep_runner.py` (imports, `stop`, `_build_results`, new `_convergence_status`)
- Modify: `aerosuite/ui/sweep_tab.py` (`_STATUS_DISPLAY`, `_on_finished`)
- Test: `tests/legacy/test_legacy_results.py`

**Interfaces:**
- Consumes: `naming.parse_case_name`; `results.check_convergence`, `results.read_history`, `results.HISTORY_FILE`; `jobs.store.kill_tree`; `history_writer` fixture
- Produces: `AeroSummary.extract_beta_from_case_name(name) -> float` (0.0 when absent); summary DataFrame gains a `Beta` column, sorted Mach → Beta → Alpha; `SweepRunner._build_results` statuses `CONVERGED | UNCONVERGED | FAILED | STOPPED | NOT RUN`

- [ ] **Step 1: Write the failing tests `tests/legacy/test_legacy_results.py`**

```python
import math
from pathlib import Path

from aerosuite.core.aerosummary import AeroSummary
from aerosuite.core.sweep_runner import SweepRunner

STEADY = [0.5] * 50
WOBBLY = [0.5 + 0.2 * math.sin(i) for i in range(50)]


def test_name_extraction_uses_engine_parser():
    assert AeroSummary.extract_mach_from_case_name("M0p85_a2p5_bn1") == 0.85
    assert AeroSummary.extract_alpha_from_case_name("M0p85_a2p5_bn1") == 2.5
    assert AeroSummary.extract_beta_from_case_name("M0p85_a2p5_bn1") == -1.0
    assert AeroSummary.extract_alpha_from_case_name("ht_M0p3_A5_B0_sl") == 5.0
    assert AeroSummary.extract_beta_from_case_name("M0p6_A10m") == 0.0
    assert AeroSummary.extract_mach_from_case_name("sl_a5") == 999.0
    assert AeroSummary.is_valid_case_name("sl_a5")
    assert not AeroSummary.is_valid_case_name("wing_baseline")


def test_consolidate_adds_beta_and_sorts(tmp_path, history_writer):
    for name in ["M0p8_a2_b1", "M0p8_a0_b1", "M0p8_a2_b0", "M0p8_a0_b0"]:
        history_writer(tmp_path / name, STEADY)
    df, _ = AeroSummary.consolidate_results(str(tmp_path), ["CL"], 10, log_callback=lambda m: None)
    assert df[["Beta", "Alpha"]].values.tolist() == [[0, 0], [0, 2], [1, 0], [1, 2]]


def test_plots_split_by_beta_only_when_several(tmp_path, history_writer):
    for name in ["M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a0_b1", "M0p8_a2_b1"]:
        history_writer(tmp_path / "runs" / name, STEADY)
    df, _ = AeroSummary.consolidate_results(str(tmp_path / "runs"), ["CL"], 10, log_callback=lambda m: None)
    files = AeroSummary.generate_plots(df, ["CL"], str(tmp_path / "plots"))
    assert sorted(Path(p).name for p in files) == [
        "M0p8_B0p0_CL_vs_Alpha.png", "M0p8_B1p0_CL_vs_Alpha.png",
    ]

    single = df[df["Beta"] == 0]
    files = AeroSummary.generate_plots(single, ["CL"], str(tmp_path / "plots2"))
    assert [Path(p).name for p in files] == ["M0p8_CL_vs_Alpha.png"]


def test_build_results_reports_convergence(tmp_path, history_writer):
    history_writer(tmp_path / "good", STEADY)
    history_writer(tmp_path / "wobbly", WOBBLY)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "error.log").write_text("boom")
    (tmp_path / "empty").mkdir()
    runner = SweepRunner(script_path="unused.py", cfg_dir=str(tmp_path), control_file="unused.txt")
    run_list = [
        {"cfg_file": f"{name}.cfg", "restart_option": "none", "restart_path": None}
        for name in ["good", "wobbly", "broken", "empty", "never"]
    ]
    statuses = {r["cfg_file"]: r["status"] for r in runner._build_results(run_list, {})}
    assert statuses == {
        "good.cfg": "CONVERGED",
        "wobbly.cfg": "UNCONVERGED",
        "broken.cfg": "FAILED",
        "empty.cfg": "FAILED",
        "never.cfg": "NOT RUN",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/legacy/test_legacy_results.py -v`
Expected: FAIL — `AttributeError: ... extract_beta_from_case_name`, `KeyError: 'Beta'`, and `SUCCESS` instead of `CONVERGED`.

- [ ] **Step 3: Update imports and constants at the top of `aerosuite/core/aerosummary.py`**

Replace

```python
import pandas as pd
import matplotlib.pyplot as plt


# Constants
MIN_CONVERGENCE_ITERATIONS = 10
CONVERGENCE_THRESHOLD = 1e-3
```

with

```python
import pandas as pd
import matplotlib.pyplot as plt

from aerosuite.engine import results as engine_results
from aerosuite.engine.naming import parse_case_name
```

- [ ] **Step 4: Replace the four name/convergence methods in `AeroSummary`**

Replace the whole bodies of `check_convergence`, `extract_mach_from_case_name`, `extract_alpha_from_case_name` and `is_valid_case_name` (everything from `    @staticmethod\n    def check_convergence(` down to, not including, `    @staticmethod\n    def consolidate_results(`) with:

```python
    @staticmethod
    def check_convergence(df: pd.DataFrame, columns: List[str]) -> Tuple[bool, str]:
        """Convergence of whichever of CD/CL/CMy the user selected (engine rule)."""
        return engine_results.check_convergence(df, [c for c in ('CD', 'CL', 'CMy') if c in columns])

    @staticmethod
    def extract_mach_from_case_name(case_name: str) -> float:
        """Mach from a case directory name; 999.0 when absent."""
        mach = parse_case_name(case_name).mach
        return 999.0 if mach is None else mach

    @staticmethod
    def extract_alpha_from_case_name(case_name: str) -> float:
        """Angle of attack from a case directory name; 999.0 when absent."""
        alpha = parse_case_name(case_name).alpha
        return 999.0 if alpha is None else alpha

    @staticmethod
    def extract_beta_from_case_name(case_name: str) -> float:
        """Sideslip from a case directory name; 0.0 when the name has no beta token."""
        beta = parse_case_name(case_name).beta
        return 0.0 if beta is None else beta

    @staticmethod
    def is_valid_case_name(case_name: str) -> bool:
        """A case is usable when its name carries an angle of attack."""
        return parse_case_name(case_name).alpha is not None

```

- [ ] **Step 5: In `consolidate_results`, read histories with the engine and add Beta + the new sort**

Replace the two lines

```python
                df = pd.read_csv(history_path, sep=r'\s*,\s*|\s+', engine='python')
                df.columns = df.columns.str.strip().str.replace('"', '')
```

with

```python
                df = engine_results.read_history(history_path)
```

Replace the single line

```python
        summary_df = summary_df.sort_values(by=['Mach', 'Alpha']).reset_index(drop=True)
```

with

```python
        summary_df['Beta'] = summary_df['Case'].apply(
            AeroSummary.extract_beta_from_case_name
        )
        summary_df = summary_df.sort_values(by=['Mach', 'Beta', 'Alpha']).reset_index(drop=True)
```

and change the comment line directly above it from `# Sort by Mach then Alpha` to `# Sort by Mach, then Beta, then Alpha`.

- [ ] **Step 6: Replace `generate_plots` in `AeroSummary`**

Replace the whole `generate_plots` method (from `    @staticmethod\n    def generate_plots(` down to, not including, `    @staticmethod\n    def get_available_columns(`) with:

```python
    @staticmethod
    def generate_plots(
        summary_df: pd.DataFrame,
        columns_to_plot: List[str],
        plot_directory: str,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> List[str]:
        """
        Plot each column vs Alpha, one figure per Mach (and per Beta when the
        summary holds more than one Beta).

        Returns:
            List of generated plot file paths
        """
        os.makedirs(plot_directory, exist_ok=True)
        generated_files = []
        split_beta = 'Beta' in summary_df.columns and summary_df['Beta'].nunique() > 1
        group_keys = ['Mach', 'Beta'] if split_beta else ['Mach']
        groups = list(summary_df.groupby(group_keys))

        total_plots = max(1, len(groups) * len(columns_to_plot))
        current_plot = 0

        for key, group in groups:
            key = key if isinstance(key, tuple) else (key,)
            mach = key[0]
            beta = key[1] if split_beta else None
            data = group.sort_values(by='Alpha')

            for col in columns_to_plot:
                if col not in data.columns or data[col].dtype == object:
                    continue

                plt.figure(figsize=(10, 6))
                plt.plot(data['Alpha'], data[col], 'o-', linewidth=2, markersize=8)
                title = f'{col} vs. Alpha (Mach {mach}'
                title += f', Beta {beta})' if split_beta else ')'
                plt.title(title, fontweight='bold', fontsize=14)
                plt.xlabel('Angle of Attack (deg)', fontsize=12)
                plt.ylabel(col, fontsize=12)
                plt.grid(True, linestyle='--', alpha=0.7)
                plt.minorticks_on()
                plt.grid(which='minor', linestyle=':', alpha=0.4)

                name = f"M{str(mach).replace('.', 'p')}"
                if split_beta:
                    name += f"_B{str(float(beta)).replace('-', 'n').replace('.', 'p')}"
                filepath = os.path.join(plot_directory, f"{name}_{col}_vs_Alpha.png")
                plt.savefig(filepath, bbox_inches='tight', dpi=150)
                plt.close()

                generated_files.append(filepath)

                current_plot += 1
                if progress_callback:
                    progress_callback(50 + int((current_plot / total_plots) * 50))

        return generated_files

```

- [ ] **Step 7: Update `aerosuite/core/sweep_runner.py`**

Replace

```python
import os
import re
import signal
import subprocess
```

with

```python
import os
import re
import subprocess
```

After the line `from typing import Callable, Dict, List, Optional, Tuple` add:

```python

from aerosuite.engine.jobs.store import kill_tree
from aerosuite.engine.results import HISTORY_FILE, check_convergence, read_history


def _convergence_status(folder: str) -> Tuple[str, Optional[str]]:
    """CONVERGED / UNCONVERGED from the case's history, or FAILED if there is none."""
    history = os.path.join(folder, HISTORY_FILE)
    if not os.path.isfile(history):
        return "FAILED", "No history.csv was written"
    df = read_history(history)
    if df.empty:
        return "FAILED", "history.csv is empty"
    converged, message = check_convergence(df)
    return ("CONVERGED", None) if converged else ("UNCONVERGED", message)
```

Replace the body of `stop`:

```python
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                else:
                    self._proc.kill()
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
```

with

```python
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            kill_tree(self._proc.pid)  # script + mpirun + SU2 ranks, on every platform
```

In `_build_results` replace

```python
            elif os.path.isdir(folder):
                status = "SUCCESS"
                error  = None
```

with

```python
            elif os.path.isdir(folder):
                status, error = _convergence_status(folder)
```

- [ ] **Step 8: Show the new statuses on the legacy Run page**

In `aerosuite/ui/sweep_tab.py`, replace

```python
    "SUCCESS":  ("✓   SUCCESS",    QColor("#e8f5e9"),  QColor("#2e7d32")),
```

with

```python
    "SUCCESS":  ("✓   SUCCESS",    QColor("#e8f5e9"),  QColor("#2e7d32")),
    "CONVERGED":   ("✓   Converged",   QColor("#e8f5e9"), QColor("#2e7d32")),
    "UNCONVERGED": ("⚠   Unconverged", QColor("#fffde7"), QColor("#f57f17")),
```

Replace the whole `_on_finished` method with:

```python
    def _on_finished(self, results: List[Dict]):
        self._unlock_ui()
        log_path = getattr(self._worker.runner, "log_path", None)
        self._populate_final_status(results, log_path)
        n_ok     = sum(1 for r in results if r["status"] in ("CONVERGED", "SUCCESS"))
        n_unconv = sum(1 for r in results if r["status"] == "UNCONVERGED")
        n_fail   = sum(1 for r in results if r["status"] == "FAILED")
        n_stop   = sum(1 for r in results if r["status"] == "STOPPED")
        summary = f"{n_ok} converged, {n_unconv} unconverged, {n_fail} failed"
        if n_stop:
            self.status_message.emit(f"Sweep stopped — {summary}, {n_stop} not run")
        else:
            self.status_message.emit(f"Sweep finished — {summary}")
        log_note = f"\n\nLog: {log_path}" if log_path else ""
        if n_fail or n_unconv:
            QMessageBox.warning(
                self, "Sweep Finished",
                f"{summary}.\n"
                "Failed cases have an error.log in their folder; unconverged cases "
                f"should be checked on the Monitor page.{log_note}"
            )
        elif n_stop:
            QMessageBox.information(
                self, "Sweep Stopped",
                f"Stopped by user. {n_ok} case(s) converged before stop.{log_note}"
            )
        else:
            QMessageBox.information(
                self, "Sweep Finished",
                f"All {n_ok} case(s) converged.{log_note}"
            )
```

- [ ] **Step 9: Run the legacy tests and the full suite**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 10: Commit**

```bash
git add aerosuite/core/aerosummary.py aerosuite/core/sweep_runner.py aerosuite/ui/sweep_tab.py tests/legacy/test_legacy_results.py
git commit -m "fix: results read beta, runs report convergence, Stop kills the whole process tree"
```

---

### Task 13: Documentation and final verification

**Files:**
- Modify: `README.md` (Project Structure section)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Update the Project Structure block in `README.md`**

Replace the fenced block under `## Project Structure` with:

````markdown
```
run_aerosuite.py             Entry point (legacy PyQt5 app)
diagnose.py                  Startup diagnostics
pyproject.toml, uv.lock      Environment (Python 3.12 via uv)
aerosuite/
├── main.py                  Legacy main window
├── engine/                  All logic, no UI imports — the future of AeroSuite
│   ├── models.py            Project model (project.json)
│   ├── project.py           Create / open / save project folders
│   ├── naming.py            Case names <-> Mach/alpha/beta
│   ├── cfg.py               Template rendering, config generation
│   ├── results.py           History reading, convergence, summaries
│   ├── preflight.py         Checks before generate / run
│   ├── atmosphere/          ISA and y+ calculators
│   └── jobs/                Job records, LocalRunner, lock
├── core/                    Legacy API, now delegating to engine/
├── ui/                      Legacy PyQt5 pages (retired in Phase 5)
├── utils/                   Legacy file / validation helpers
└── resources/
    ├── config_template.cfg  Bundled default reference config
    └── aoa_sweep_v8.py      Sweep script (runs under the system Python that imports SU2)
tests/                       pytest suite; tests/fixtures/fake_sweep.py stands in for SU2
docs/superpowers/            Design spec and implementation plans
```
````

- [ ] **Step 2: Run the full suite one last time**

Run: `uv run pytest -v`
Expected: all passed, no warnings about missing modules.

- [ ] **Step 3: Confirm the engine has no UI imports**

Run: `git grep -nE "PyQt5|matplotlib|aerosuite\.ui|from \.\.ui" -- aerosuite/engine`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: describe the engine package and new project layout"
```

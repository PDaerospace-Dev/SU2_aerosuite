# Web Config Modes, Reference Panel and Aircraft Profiles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the desktop app's two ways of working in the web UI:
- General: one config edited as text, with SU2's reference beside it.
- Aircraft: a profile-driven Aircraft Aero form and a sweep.

Both are built as layers on one project type, with a two-card start screen for new projects.

**Architecture:**
- **Engine:** projects gain `profile` and `sweep.enabled` (schema 2). A sweep-off project is one case whose config is written as the template says. New engine modules:
  - `reference.py` parses SU2's `config_template.cfg`.
  - `profiles.py` loads, applies and saves aircraft profiles.
  - `study.py` creates a study from the start screen's choices.
- **Web:**
  - New `config` and `aircraft` pages. The Aircraft page replaces the 3a Settings page.
  - A shared reference panel, preview box and checks panel.
  - Setup gains profile and sweep controls. Projects gains the new-study form.

**Tech Stack:** Python 3.12 (uv), pydantic v2, NiceGUI 3.17, pytest + pytest-asyncio + NiceGUI `user_plugin`.

**Spec:** `docs/superpowers/specs/2026-09-23-web-config-modes-design.md`. It builds on `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md`, whose §3, §6 and §7.1 still apply.

## Global Constraints

- AeroSuite runs on Python ≥ 3.10 in the uv Python 3.12 environment.
- **Import boundaries:**
  - `aerosuite/engine/` never imports NiceGUI, Typer, starlette, PyQt5, matplotlib, or anything from `aerosuite/web`, `aerosuite/cli` or `aerosuite/ui`.
  - `aerosuite/web/` imports only the engine, NiceGUI, pydantic, starlette and the standard library.
- **Writes and file access in `web/`:**
  - Web pages never write project files directly. Every change goes through `ProjectFrame.save` (`ProjectSession.apply`) or an engine function.
  - Direct filesystem use in `web/` is limited to existence checks for display and the picker's listings.
- **Autosave:**
  - Text fields and the config editor commit on blur, or on Enter for single-line fields. Unchanged text is not re-saved.
  - Selects, checkboxes and switches commit on change.
  - An invalid value shows the engine's message and saves nothing.
- **NiceGUI 3.17 refresh timing:** `refreshable.refresh()` is fire-and-forget. Parts that tests read synchronously right after a change must rebuild synchronously: clear a container, then build again. The page body stays `@ui.refreshable` and is refreshed only on reload. `pages/settings.py` and `pages/sweep.py` already follow this pattern.
- **Schema:** `schema_version` becomes 2. Migration 1→2 adds `profile = None` and `sweep.enabled = True`.
- **Sweep-off projects:**
  - They have exactly one case, named from the project name (`single_case_name`).
  - Rendering does not inject `MACH_NUMBER`, `AOA`, `SIDESLIP_ANGLE` or `BREAKDOWN_FILENAME`. It still applies settings, markers, overrides and the absolute `MESH_FILENAME`.
  - `cases.json` takes Mach/α/β from the template's lines, with 0.0 when a line is missing or not a number.
- **Profiles:**
  - Bundled profiles live in `aerosuite/resources/profiles/<id>/`, user profiles in `$AEROSUITE_HOME/profiles/<id>/` (default `~/.aerosuite/profiles/`). A user profile replaces a bundled one with the same id.
  - Each is a `profile.json`, plus an optional `template.cfg`.
  - Profile ids match `^[A-Za-z0-9_-]+$`.
  - "Save as profile" never copies the mesh path, sweep values, cases or restarts.
- **Bundled X07 profile:**
  - It has no template.
  - Settings: `reference.ref_length` 6, `ref_area` 16.213, `origin_x` 5.16, `origin_y` 0, `origin_z` 0; `freestream.reynolds_length` 1; `numerics.conv_method` "ROE", `muscl` "YES", `turb_model` "SST", `cfl` 1.0, `iter` 1500.
  - Hints: `MARKER_HEATFLUX`, `MARKER_PLOTTING` and `MARKER_MONITORING` → "( Fuselage, Wing, VT, HT )"; `MARKER_FAR` → "( FarField )".
- **Sidebar order:** `Setup · Config · [Aircraft] · [Sweep] · Configs · Run · Monitor · Results`. Aircraft is shown only when `profile` is set, and Sweep only when `sweep.enabled`. Run, Monitor and Results stay greyed.
- **Aircraft dropdowns:**
  - Fixed lists: Convective ROE/JST/AUSM, MUSCL YES/NO, Turbulence SST/SA.
  - An empty choice means "template value".
  - A current value not in the list is shown as an extra option.
- **Code style:** no `from __future__ import annotations` in `aerosuite/web/pages/*`, `layout.py`, `fields.py`, `picker.py`, `checks.py`, `preview.py`, `reference_panel.py` or `aerosuite/cli/*`.
- **Tests:**
  - They pass on Windows and Linux and need no SU2, MPI, display or real browser.
  - Page tests use NiceGUI's simulated `user` fixture and find elements by `.mark(...)` markers.
  - Run every command from the repository root.

---

## File map

| File | Responsibility |
|---|---|
| `aerosuite/engine/models.py` | `SCHEMA_VERSION = 2`, `Project.profile`, `SweepSpec.enabled` |
| `aerosuite/engine/project.py` | migration 1→2, `template_warnings`, `read_template_text`, `set_template_text` |
| `aerosuite/engine/cfg.py` | `single_case_name`, `template_case_values`; sweep-off `build_cases` / `case_parameters` / `generate_configs` |
| `aerosuite/engine/preflight.py` | "No Mach numbers" only when the sweep is on |
| `aerosuite/engine/reference.py` | parse / load / search SU2 reference, `keys_in`, `find_lines` |
| `aerosuite/engine/profiles.py` | list / load / apply / save profiles |
| `aerosuite/engine/study.py` | `create_study` for the start screen |
| `aerosuite/resources/profiles/x07/profile.json` | bundled X07 profile (no template) |
| `aerosuite/web/status.py`, `layout.py` | new steps, visible-steps sidebar, page background |
| `aerosuite/web/checks.py` | checks + Generate (moved out of `pages/sweep.py`) |
| `aerosuite/web/preview.py` | Preview switch + rendered config of a chosen case |
| `aerosuite/web/reference_panel.py` | search / Insert / Find / Load another reference |
| `aerosuite/web/pages/config.py` | Config page |
| `aerosuite/web/pages/aircraft.py` | Aircraft page (replaces `pages/settings.py`) |
| `aerosuite/web/pages/setup.py`, `projects.py`, `sweep.py` | study controls, new-study form, sweep-off notice |
| `tests/…` | engine and page tests; `tests/web/main_app.py` gains `/_test/reference` |

---

### Task 1: Schema 2 and sweep-off (single-case) projects in the engine

**Files:**
- Modify: `aerosuite/engine/models.py`, `aerosuite/engine/project.py`, `aerosuite/engine/cfg.py`, `aerosuite/engine/preflight.py`
- Modify: `tests/engine/test_project.py` (three existing migration tests assume schema 1 is current)
- Test: `tests/engine/test_single_case.py`, `tests/engine/test_template_text.py`

**Interfaces:**
- Produces:
  - `models.SCHEMA_VERSION = 2`, `Project.profile: Optional[str] = None`, `SweepSpec.enabled: bool = True`
  - `project.MIGRATIONS = {1: _v1_to_v2}`
  - `project.template_warnings(text: str) -> list[str]`
  - `project.read_template_text(project_dir: Path, project: Project) -> str` (raises `TemplateError`)
  - `project.set_template_text(project_dir: Path, project: Project, text: str) -> list[str]` (writes `template.cfg` atomically, sets `project.template = "template.cfg"`, returns warnings; `OSError` → `TemplateError`)
  - `cfg.single_case_name(project: Project) -> str`
  - `cfg.template_case_values(template: str) -> tuple[float, float, float]`

- [ ] **Step 1: Write the failing tests `tests/engine/test_single_case.py`**

```python
import json
import time

from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import JobState
from aerosuite.engine.results import load_case_index, summarize
from aerosuite.engine.cfg import (
    CASE_INDEX_FILE,
    CONFIGS_DIR,
    build_cases,
    generate_configs,
    read_template,
    render_case,
    single_case_name,
    template_case_values,
)
from aerosuite.engine.models import Project
from aerosuite.engine.preflight import preflight, sweep_problems
from aerosuite.engine.project import create_project, open_project, save_project, PROJECT_FILE


def _single(ready_project):
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)
    return project_dir, project


def test_single_case_name_is_a_safe_stem():
    assert single_case_name(Project(name="nozzle_study")) == "nozzle_study"
    assert single_case_name(Project(name="My wing: v2")) == "My_wing_v2"
    assert single_case_name(Project(name="...")) == "case"


def test_template_case_values():
    assert template_case_values("MACH_NUMBER= 0.3\nAOA= 2.5 % deg\nSIDESLIP_ANGLE= -1\n") == (0.3, 2.5, -1.0)
    assert template_case_values("AOA= abc\n") == (0.0, 0.0, 0.0)


def test_sweep_off_builds_one_case_and_keeps_its_restart(ready_project):
    project_dir, project = _single(ready_project)
    assert [c.name for c in project.cases] == ["study"]
    project.cases[0].restart = "previous"
    assert build_cases(project)[0].restart == "previous"


def test_sweep_off_renders_the_template_as_written(ready_project):
    project_dir, project = _single(ready_project)
    project.settings.overrides = {"CFL_NUMBER": "5"}
    text = render_case(read_template(project_dir, project), project, project.cases[0])
    assert "MACH_NUMBER= 0.3" in text and "AOA= 0.0" in text
    assert "BREAKDOWN_FILENAME" not in text
    assert "CFL_NUMBER= 5" in text
    assert "MESH_FILENAME=" in text and "wing.su2" in text


def test_sweep_off_generate_indexes_values_from_the_template(ready_project):
    project_dir, project = _single(ready_project)
    written = generate_configs(project_dir, project)
    assert [p.name for p in written] == ["study.cfg"]
    index = json.loads((project_dir / CONFIGS_DIR / CASE_INDEX_FILE).read_text())
    assert index == {"study": {"mach": 0.3, "alpha": 0.0, "beta": 0.0}}


def test_single_case_runs_and_summarizes(ready_project):
    project_dir, project = _single(ready_project)
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": {}}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    deadline = time.monotonic() + 20
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.1)
        job = runner.refresh(project_dir, job)
    assert job.state is JobState.DONE
    assert set(job.case_status) == {"study"}
    table, _ = summarize(project_dir / RUNS_DIR, ["CL"],
                         case_index=load_case_index(project_dir / CONFIGS_DIR))
    assert table["Case"].tolist() == ["study"]
    assert table["Mach"].tolist() == [0.3]


def test_no_mach_check_only_applies_to_sweeps(ready_project):
    project_dir, project = _single(ready_project)
    project.sweep.mach = []
    assert not any("No Mach" in p.message for p in sweep_problems(project))
    assert not any(p.severity == "error" for p in preflight(project_dir, project, "generate"))


def test_schema_1_projects_upgrade_to_sweep_on_without_profile(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 1
    del data["profile"]
    del data["sweep"]["enabled"]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 2
    assert project.profile is None and project.sweep.enabled is True
```

- [ ] **Step 2: Write the failing tests `tests/engine/test_template_text.py`**

```python
import pytest

from aerosuite.engine.errors import TemplateError
from aerosuite.engine.project import (
    TEMPLATE_FILE,
    create_project,
    read_template_text,
    set_template_text,
    template_warnings,
)


def test_template_warnings():
    text = "% comment\n\nSOLVER= RANS\nnot an option\nAOA= 1\nAOA= 2\n"
    assert template_warnings(text) == [
        'Line 4 is not an option or a comment: "not an option"',
        "AOA is set on lines 5 and 6; both will be changed together",
    ]
    assert template_warnings("A= 1\nA= 2\nA= 3\n") == [
        "A is set on lines 1, 2 and 3; all will be changed together"
    ]
    assert template_warnings("SOLVER= EULER\n") == []


def test_set_and_read_template_text(tmp_path):
    project = create_project(tmp_path)
    warnings = set_template_text(tmp_path, project, "SOLVER= RANS\nbroken\n")
    assert (tmp_path / TEMPLATE_FILE).read_text() == "SOLVER= RANS\nbroken\n"
    assert project.template == TEMPLATE_FILE
    assert warnings == ['Line 2 is not an option or a comment: "broken"']
    assert read_template_text(tmp_path, project) == "SOLVER= RANS\nbroken\n"


def test_read_missing_template(tmp_path):
    project = create_project(tmp_path)
    with pytest.raises(TemplateError):
        read_template_text(tmp_path, project)


def test_preflight_lists_template_warnings(ready_project):
    from aerosuite.engine.preflight import has_errors, preflight

    project_dir, project = ready_project
    (project_dir / TEMPLATE_FILE).write_text("MACH_NUMBER= 0.3\nAOA= 1\nAOA= 2\n")
    found = preflight(project_dir, project, "generate")
    assert any(p.severity == "warning" and "AOA is set on lines 2 and 3" in p.message for p in found)
    assert not has_errors(found)


def test_set_template_text_reports_os_errors(tmp_path):
    project = create_project(tmp_path / "p")
    (tmp_path / "p" / TEMPLATE_FILE).mkdir()  # a folder where the file should go
    with pytest.raises(TemplateError, match="Cannot write"):
        set_template_text(tmp_path / "p", project, "A= 1\n")
```

- [ ] **Step 3: Update the three migration tests in `tests/engine/test_project.py` for schema 2**

In `test_migrations_run_in_order`:
- replace `monkeypatch.setattr(models, "SCHEMA_VERSION", 2)` with `monkeypatch.setattr(models, "SCHEMA_VERSION", 3)`;
- replace `monkeypatch.setattr(project_mod, "MIGRATIONS", {1: v1_to_v2})` with `monkeypatch.setattr(project_mod, "MIGRATIONS", {2: v1_to_v2})`;
- replace `assert opened.schema_version == 2` with `assert opened.schema_version == 3`.

In `test_migrate_rejects_missing_migration`, replace `monkeypatch.setattr(models, "SCHEMA_VERSION", 2)` with `monkeypatch.setattr(models, "SCHEMA_VERSION", 3)`.

In `test_migration_error_propagates`:
- replace `monkeypatch.setattr(models, "SCHEMA_VERSION", 2)` with `monkeypatch.setattr(models, "SCHEMA_VERSION", 3)`;
- replace `{1: broken_migration}` with `{2: broken_migration}`.

(New projects are now saved at schema 2, so these tests migrate 2→3.)

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_single_case.py tests/engine/test_template_text.py -v`
Expected: `ImportError` for `single_case_name`, `template_warnings` and the other new names.

- [ ] **Step 5: Update `aerosuite/engine/models.py`**

- Change `SCHEMA_VERSION = 1` to `SCHEMA_VERSION = 2`.
- In `SweepSpec`, add a first field: `enabled: bool = True  # False: the project is a single case`.
- In `Project`, after `preset: Optional[str] = None`, add: `profile: Optional[str] = None  # aircraft profile id; None = general project`.

- [ ] **Step 6: Update `aerosuite/engine/project.py`**

Add `import re` to the imports. Replace `from .cfg import extract_markers` with `from .cfg import extract_markers, read_template`.

Replace `MIGRATIONS: dict[int, Callable[[dict], dict]] = {}` with:

```python
def _v1_to_v2(data: dict) -> dict:
    """Schema 2 adds aircraft profiles and a sweep on/off switch; old projects keep their sweep."""
    data.setdefault("profile", None)
    sweep = data.setdefault("sweep", {})
    if isinstance(sweep, dict):
        sweep.setdefault("enabled", True)
    return data


# {from_version: function(data) -> data at from_version + 1}
MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: _v1_to_v2}
```

Add at the end of the file:

```python
_OPTION_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=")


def template_warnings(text: str) -> list[str]:
    """Lines that are not options or comments, and options set more than once."""
    warnings: list[str] = []
    seen: dict[str, list[int]] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        match = _OPTION_LINE_RE.match(line)
        if match is None:
            shown = line if len(line) <= 60 else line[:57] + "..."
            warnings.append(f'Line {number} is not an option or a comment: "{shown}"')
            continue
        seen.setdefault(match.group(1), []).append(number)
    for key, lines in seen.items():
        if len(lines) > 1:
            where = ", ".join(str(n) for n in lines[:-1]) + f" and {lines[-1]}"
            together = "both" if len(lines) == 2 else "all"
            warnings.append(f"{key} is set on lines {where}; {together} will be changed together")
    return warnings


def read_template_text(project_dir: Path, project: Project) -> str:
    return read_template(project_dir, project)


def set_template_text(project_dir: Path, project: Project, text: str) -> list[str]:
    """Save edited template text as the project's template.cfg; returns warnings (never blocks)."""
    path = Path(project_dir) / TEMPLATE_FILE
    tmp = path.with_name(TEMPLATE_FILE + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise TemplateError(f"Cannot write {path}: {exc}") from exc
    project.template = TEMPLATE_FILE
    return template_warnings(text)
```

- [ ] **Step 7: Update `aerosuite/engine/cfg.py`**

Add these two functions after `_number`:

```python
def single_case_name(project: Project) -> str:
    """The one case of a sweep-off project: the project name as a safe file stem."""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", project.name).strip("._")
    return stem or "case"


def template_case_values(template: str) -> tuple[float, float, float]:
    """MACH_NUMBER, AOA and SIDESLIP_ANGLE as written in a template (0.0 if missing or not a number)."""
    values = []
    for key in ("MACH_NUMBER", "AOA", "SIDESLIP_ANGLE"):
        match = re.search(rf"^{key}\s*=\s*([^\s%]+)", template, re.MULTILINE)
        try:
            values.append(float(match.group(1)) if match else 0.0)
        except ValueError:
            values.append(0.0)
    return values[0], values[1], values[2]
```

Replace the body of `case_parameters` with:

```python
    params: dict[str, str] = {}
    if project.sweep.enabled:
        params.update({
            "MACH_NUMBER": format_value(case.mach),
            "AOA": format_value(case.alpha),
            "SIDESLIP_ANGLE": format_value(case.beta),
            "BREAKDOWN_FILENAME": f"{case.name}_FB.dat",
        })
    if project.mesh.path:
        # Absolute, because the sweep runs from runs/ rather than from the cfg folder.
        params["MESH_FILENAME"] = str(Path(project.mesh.path).resolve())
    return params
```

In `build_cases`, right after the line `previous = {case.name: case for case in project.cases}`, insert:

```python
    if not sweep.enabled:
        name = single_case_name(project)
        old = previous.get(name)
        return [Case(
            name=name, mach=0.0, alpha=0.0, beta=0.0,
            restart=old.restart if old else "none",
            restart_ref=old.restart_ref if old else None,
        )]
```

In `generate_configs`, replace the line that builds `index` with:

```python
    if project.sweep.enabled:
        index = {c.name: {"mach": c.mach, "alpha": c.alpha, "beta": c.beta} for c in project.cases}
    else:
        mach, alpha, beta = template_case_values(template)
        index = {c.name: {"mach": mach, "alpha": alpha, "beta": beta} for c in project.cases}
```

- [ ] **Step 8: Update `aerosuite/engine/preflight.py`**

In `sweep_problems`, replace `if not project.sweep.mach:` with `if project.sweep.enabled and not project.sweep.mach:`.

Template warnings become preflight warnings: they never block, but they appear in the checks.
- Add `from .project import template_warnings` to the imports. `project.py` does not import `preflight`, so this creates no cycle.
- In `preflight`, replace

```python
    if not template.is_file():
        problems.append(Problem("error", f"Template not found: {template}"))
```

with

```python
    if not template.is_file():
        problems.append(Problem("error", f"Template not found: {template}"))
    else:
        try:
            text = template.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(Problem("error", f"Cannot read template {template}: {exc}"))
        else:
            problems += [Problem("warning", warning) for warning in template_warnings(text)]
```

If an existing test now fails, check whether its template really has a duplicate option or a stray line. If it does, update the test's expected problems and record that. Do not weaken the warning.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/engine -v`
Expected: all passed.

- [ ] **Step 10: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/engine/models.py aerosuite/engine/project.py aerosuite/engine/cfg.py aerosuite/engine/preflight.py tests/engine/test_single_case.py tests/engine/test_template_text.py tests/engine/test_project.py
git commit -m "feat(engine): add schema 2 with profiles, sweep switch and single-case projects"
```

---

### Task 2: SU2 reference parser

**Files:**
- Create: `aerosuite/engine/reference.py`
- Test: `tests/engine/test_reference.py`

**Interfaces:**
- Produces:
  - `reference.BUNDLED_REFERENCE: Path`
  - `reference.RefOption` (frozen dataclass): `key`, `line`, `description`, `section`, `line_no`, plus the property `default_value -> str`
  - `reference.parse_reference(text: str) -> list[RefOption]`
  - `reference.read_reference_text(path: Path | None = None) -> str`, which raises `ProjectError`
  - `reference.load_reference(path: Path | None = None) -> list[RefOption]`, which raises `ProjectError` when the file is unreadable or has no options
  - `reference.search(options, query: str, limit: int = 50) -> list[RefOption]`
  - `reference.keys_in(text: str) -> set[str]`
  - `reference.find_lines(text: str, query: str) -> list[int]` (1-based line numbers, case-insensitive)

- [ ] **Step 1: Write the failing tests `tests/engine/test_reference.py`**

```python
import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.reference import (
    find_lines,
    keys_in,
    load_reference,
    parse_reference,
    read_reference_text,
    search,
)

SMALL = """\
%%%%%%%%%%%%%%%%%%%%%%%%
% SU2 configuration file   %
%%%%%%%%%%%%%%%%%%%%%%%%

% ------------- SOLVER SETUP ------------%
%
% Solver type (EULER, NAVIER_STOKES,
%              RANS)
SOLVER= EULER
%
% Specify turbulence model (NONE, SA, SST)
KIND_TURB_MODEL= NONE

% ------------- BOUNDARIES ------------%
%
% Euler wall boundary marker(s)
MARKER_EULER= ( airfoil )
%
% Temperature of the wall
FREESTREAM_TEMPERATURE= 288.15
"""


def test_parse_small_file():
    options = parse_reference(SMALL)
    assert [o.key for o in options] == ["SOLVER", "KIND_TURB_MODEL", "MARKER_EULER", "FREESTREAM_TEMPERATURE"]
    solver = options[0]
    assert solver.description == "Solver type (EULER, NAVIER_STOKES, RANS)"
    assert solver.section == "SOLVER SETUP"
    assert solver.line == "SOLVER= EULER"
    assert solver.line_no == 9
    assert options[2].default_value == "( airfoil )"
    assert options[2].section == "BOUNDARIES"


def test_bundled_reference():
    options = load_reference()
    euler = [o for o in options if o.key == "MARKER_EULER"]
    assert euler and "Euler wall boundary marker" in euler[0].description
    assert euler[0].section == "BOUNDARY CONDITION DEFINITION"
    temps = [o for o in options if o.key == "FREESTREAM_TEMPERATURE"]
    assert len(temps) >= 2 and len({o.section for o in temps}) >= 2


def test_search_orders_key_matches_first():
    options = parse_reference(SMALL)
    assert [o.key for o in search(options, "euler")] == ["MARKER_EULER", "SOLVER"]
    assert [o.key for o in search(options, "TEMPERATURE")] == ["FREESTREAM_TEMPERATURE"]
    assert search(options, "  ") == []
    assert len(search(load_reference(), "marker", limit=5)) == 5


def test_keys_in_and_find_lines():
    text = "SOLVER= RANS\n% CFL_NUMBER= 5\n  AOA = 2\nnot an option\n"
    assert keys_in(text) == {"SOLVER", "AOA"}
    assert find_lines(SMALL, "euler") == [7, 16, 17]
    assert find_lines(SMALL, "") == []


def test_load_errors(tmp_path):
    with pytest.raises(ProjectError, match="Cannot read"):
        read_reference_text(tmp_path / "missing.cfg")
    empty = tmp_path / "empty.cfg"
    empty.write_text("% only comments\n")
    with pytest.raises(ProjectError, match="no SU2 options"):
        load_reference(empty)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_reference.py -v`
Expected: `No module named 'aerosuite.engine.reference'`.

- [ ] **Step 3: Create `aerosuite/engine/reference.py`**

```python
"""SU2's reference config (config_template.cfg): options with their descriptions, for lookup."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .errors import ProjectError

BUNDLED_REFERENCE = Path(__file__).resolve().parents[1] / "resources" / "config_template.cfg"

_BANNER_RE = re.compile(r"^%\s*-{3,}\s*(.*?)\s*-{3,}\s*%?\s*$")
_OPTION_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=")
_KEYS_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


@dataclass(frozen=True)
class RefOption:
    key: str
    line: str
    description: str
    section: str
    line_no: int

    @property
    def default_value(self) -> str:
        return self.line.split("=", 1)[1].strip()


def parse_reference(text: str) -> list[RefOption]:
    """Options in file order; each gets the comment block above it and the latest section banner."""
    options: list[RefOption] = []
    section = ""
    block: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            block = []
            continue
        banner = _BANNER_RE.match(stripped)
        if banner:
            section = banner.group(1).strip()
            block = []
            continue
        if stripped.startswith("%"):
            comment = stripped.strip("%").strip()
            if comment:
                block.append(comment)
            else:
                block = []
            continue
        match = _OPTION_RE.match(stripped)
        if match:
            options.append(RefOption(match.group(1), stripped, " ".join(block), section, number))
        block = []
    return options


def read_reference_text(path: Optional[Path] = None) -> str:
    path = Path(path) if path is not None else BUNDLED_REFERENCE
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ProjectError(f"Cannot read reference {path}: {exc}") from exc


def load_reference(path: Optional[Path] = None) -> list[RefOption]:
    options = parse_reference(read_reference_text(path))
    if not options:
        raise ProjectError(f"{path or BUNDLED_REFERENCE} contains no SU2 options")
    return options


def search(options: Sequence[RefOption], query: str, limit: int = 50) -> list[RefOption]:
    """Options whose key contains the query first, then those whose description does."""
    q = query.strip().lower()
    if not q:
        return []
    by_key = [o for o in options if q in o.key.lower()]
    by_description = [o for o in options if q not in o.key.lower() and q in o.description.lower()]
    return (by_key + by_description)[:limit]


def keys_in(text: str) -> set[str]:
    """Option keys set (not commented out) in a config text."""
    return set(_KEYS_RE.findall(text))


def find_lines(text: str, query: str) -> list[int]:
    """1-based numbers of the lines containing `query`, ignoring case."""
    q = query.strip().lower()
    if not q:
        return []
    return [number for number, line in enumerate(text.splitlines(), 1) if q in line.lower()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_reference.py -v`
Expected: 5 passed. If `test_bundled_reference` fails because the bundled file's banner text differs, print `[o.section for o in load_reference() if o.key == "MARKER_EULER"]` and record the actual value. Change the test's expected section only if the file really uses different text, and record that as a deviation.

- [ ] **Step 5: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/engine/reference.py tests/engine/test_reference.py
git commit -m "feat(engine): parse and search SU2's reference config"
```

---

### Task 3: Aircraft profiles and study creation

**Files:**
- Create: `aerosuite/engine/profiles.py`, `aerosuite/engine/study.py`, `aerosuite/resources/profiles/x07/profile.json`
- Modify: `pyproject.toml` (package data)
- Test: `tests/engine/test_profiles.py`, `tests/engine/test_study.py`

**Interfaces:**
- Consumes:
  - `models.Settings`, `Naming`, `Project`
  - `project.create_project`, `set_template`, `set_mesh`, `save_project`, `TEMPLATE_FILE`
  - `cfg.build_cases`
  - `reference.BUNDLED_REFERENCE`
- Produces:
  - `profiles.BUNDLED_PROFILES: Path`, `profiles.PROFILE_FILE = "profile.json"`
  - `profiles.ProfileData`, a pydantic model with `id`, `name`, `description`, `settings: dict`, `hints: dict[str, str]` and `naming: dict`
  - `profiles.Profile`, a frozen dataclass with `data`, `folder` and `bundled`, plus these properties:
    - `id`, `name`, `description` and `hints`
    - `template -> Path | None`
    - `setting_hints -> dict[str, str]`: keys look like `"reference.ref_area"`, and values are the profile's settings formatted as text
  - `profiles.user_profiles_dir() -> Path`
  - `profiles.list_profiles() -> tuple[list[Profile], list[str]]`, returning the profiles sorted by name plus problem messages
  - `profiles.load_profile(profile_id: str) -> Profile`
  - `profiles.apply_profile(project_dir: Path, project: Project, profile: Profile) -> None`
  - `profiles.save_profile(project_dir: Path, project: Project, profile_id: str, name: str, description: str = "", overwrite: bool = False) -> Profile`
  - `study.create_study(directory: Path, *, profile_id: str | None = None, sweep: bool | None = None, template: Path | None = None, use_reference_template: bool = False, mesh: Path | None = None) -> Project`

- [ ] **Step 1: Create the bundled X07 profile `aerosuite/resources/profiles/x07/profile.json`**

```json
{
  "id": "x07",
  "name": "X07",
  "description": "X07 aircraft: the desktop app's Aircraft Aero defaults. No master template yet; add it with Save as profile.",
  "settings": {
    "freestream": {"reynolds_length": 1},
    "reference": {"ref_length": 6, "ref_area": 16.213, "origin_x": 5.16, "origin_y": 0, "origin_z": 0},
    "numerics": {"conv_method": "ROE", "muscl": "YES", "turb_model": "SST", "cfl": 1.0, "iter": 1500}
  },
  "hints": {
    "MARKER_HEATFLUX": "( Fuselage, Wing, VT, HT )",
    "MARKER_FAR": "( FarField )",
    "MARKER_PLOTTING": "( Fuselage, Wing, VT, HT )",
    "MARKER_MONITORING": "( Fuselage, Wing, VT, HT )"
  },
  "naming": {}
}
```

In `pyproject.toml`, replace `aerosuite = ["resources/*"]` with `aerosuite = ["resources/*", "resources/profiles/*/*"]`.

- [ ] **Step 2: Write the failing tests `tests/engine/test_profiles.py`**

```python
import json

import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.profiles import (
    PROFILE_FILE,
    apply_profile,
    list_profiles,
    load_profile,
    save_profile,
    user_profiles_dir,
)
from aerosuite.engine.project import TEMPLATE_FILE


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


def test_bundled_x07():
    x07 = load_profile("x07")
    assert x07.bundled and x07.name == "X07" and x07.template is None
    assert x07.data.settings["reference"]["ref_area"] == 16.213
    assert x07.hints["MARKER_FAR"] == "( FarField )"
    assert x07.setting_hints["reference.ref_area"] == "16.213"
    assert x07.setting_hints["numerics.conv_method"] == "ROE"
    profiles, problems = list_profiles()
    assert "x07" in [p.id for p in profiles] and problems == []


def test_apply_profile(ready_project):
    project_dir, project = ready_project
    project.settings.numerics.cfl = 9.0
    project.settings.overrides = {"CONV_FIELD": "LIFT"}
    apply_profile(project_dir, project, load_profile("x07"))
    assert project.profile == "x07"
    assert project.settings.reference.ref_area == 16.213
    assert project.settings.numerics.cfl == 1.0          # the profile defines it
    assert project.settings.numerics.turb_model == "SST"
    assert project.settings.overrides == {"CONV_FIELD": "LIFT"}  # untouched
    assert (project_dir / TEMPLATE_FILE).read_text().startswith("MACH_NUMBER= 0.3")  # no profile template


def _write_user_profile(profile_id, body):
    folder = user_profiles_dir() / profile_id
    folder.mkdir(parents=True)
    (folder / PROFILE_FILE).write_text(json.dumps(body))
    return folder


def test_user_profile_overrides_bundled_and_broken_ones_are_reported():
    _write_user_profile("x07", {"id": "x07", "name": "My X07"})
    _write_user_profile("broken", {"id": "other", "name": "Broken"})
    _write_user_profile("typo", {"id": "typo", "name": "Typo", "settings": {"reference": {"ref_areaa": 1}}})
    profiles, problems = list_profiles()
    assert {p.id: p.name for p in profiles}["x07"] == "My X07"
    assert "broken" not in [p.id for p in profiles] and "typo" not in [p.id for p in profiles]
    assert any("broken" in m for m in problems) and any("ref_areaa" in m for m in problems)
    with pytest.raises(ProjectError, match="Unknown profile"):
        load_profile("nope")


def test_save_profile(ready_project):
    project_dir, project = ready_project
    project.settings.reference.ref_area = 20.0
    project.settings.markers = {"MARKER_FAR": "( far )", "MARKER_PLOTTING": None}
    project.settings.overrides = {"CONV_FIELD": "LIFT"}
    project.sweep.naming.base_name = "jet"
    saved = save_profile(project_dir, project, "my_jet", "My jet", "test")
    assert not saved.bundled and saved.template is not None
    data = json.loads((user_profiles_dir() / "my_jet" / PROFILE_FILE).read_text())
    assert data["settings"]["reference"] == {"ref_area": 20.0}
    assert data["settings"]["markers"] == {"MARKER_FAR": "( far )", "MARKER_PLOTTING": None}
    assert data["settings"]["overrides"] == {"CONV_FIELD": "LIFT"}
    assert data["naming"]["base_name"] == "jet"
    assert set(data) == {"id", "name", "description", "settings", "hints", "naming"}
    text = json.dumps(data)
    assert "wing.su2" not in text and "M0p8" not in text  # no mesh, no cases
    with pytest.raises(ProjectError, match="already exists"):
        save_profile(project_dir, project, "my_jet", "Again")
    assert save_profile(project_dir, project, "my_jet", "Again", overwrite=True).name == "Again"
    with pytest.raises(ProjectError, match="letters, digits"):
        save_profile(project_dir, project, "bad id", "x")
    with pytest.raises(ProjectError, match="name"):
        save_profile(project_dir, project, "ok_id", "  ")
```

- [ ] **Step 3: Write the failing tests `tests/engine/test_study.py`**

```python
import pytest

from aerosuite.engine.errors import ProjectError, TemplateError
from aerosuite.engine.project import TEMPLATE_FILE, open_project
from aerosuite.engine.reference import BUNDLED_REFERENCE
from aerosuite.engine.study import create_study


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


@pytest.fixture
def inputs(tmp_path):
    template = tmp_path / "x07.cfg"
    template.write_text("MACH_NUMBER= 0.7\nAOA= 1\n")
    mesh = tmp_path / "x07.su2"
    mesh.write_text("MARKER_TAG= Wing\n")
    return template, mesh


def test_general_case_from_the_reference(tmp_path):
    project = create_study(tmp_path / "nozzle", use_reference_template=True)
    assert project.profile is None and project.sweep.enabled is False
    assert [c.name for c in project.cases] == ["nozzle"]
    assert (tmp_path / "nozzle" / TEMPLATE_FILE).read_text(encoding="utf-8") == \
        BUNDLED_REFERENCE.read_text(encoding="utf-8")
    assert open_project(tmp_path / "nozzle").sweep.enabled is False


def test_aircraft_study(tmp_path, inputs):
    template, mesh = inputs
    project = create_study(tmp_path / "x07_a", profile_id="x07", template=template, mesh=mesh)
    assert project.profile == "x07" and project.sweep.enabled is True
    assert project.settings.reference.ref_area == 16.213
    assert project.mesh.markers == ["Wing"]
    assert (tmp_path / "x07_a" / TEMPLATE_FILE).read_text() == "MACH_NUMBER= 0.7\nAOA= 1\n"


def test_aircraft_without_any_template_is_refused_before_creating(tmp_path):
    with pytest.raises(TemplateError, match="X07 has none"):
        create_study(tmp_path / "x07_b", profile_id="x07")
    assert not (tmp_path / "x07_b").exists()


def test_bad_inputs_create_nothing(tmp_path, inputs):
    template, _ = inputs
    with pytest.raises(ProjectError, match="Mesh not found"):
        create_study(tmp_path / "c", template=template, mesh=tmp_path / "gone.su2")
    with pytest.raises(TemplateError, match="Template not found"):
        create_study(tmp_path / "d", template=tmp_path / "gone.cfg")
    with pytest.raises(ProjectError, match="Unknown profile"):
        create_study(tmp_path / "e", profile_id="nope", template=template)
    assert not any((tmp_path / name).exists() for name in "cde")


def test_sweep_can_be_chosen_explicitly(tmp_path, inputs):
    template, _ = inputs
    assert create_study(tmp_path / "f", template=template, sweep=True).sweep.enabled is True
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_profiles.py tests/engine/test_study.py -v`
Expected: `No module named 'aerosuite.engine.profiles'` (and `study`).

- [ ] **Step 5: Create `aerosuite/engine/profiles.py`**

```python
"""Aircraft profiles: reusable default settings (and optionally a master template) for studies."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from .errors import ProjectError
from .models import Naming, Project, Settings
from .naming import format_value
from .project import TEMPLATE_FILE, set_template

BUNDLED_PROFILES = Path(__file__).resolve().parents[1] / "resources" / "profiles"
PROFILE_FILE = "profile.json"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_GROUPS = ("freestream", "reference", "numerics")


class ProfileData(BaseModel):
    id: str
    name: str
    description: str = ""
    settings: dict = Field(default_factory=dict)
    hints: dict[str, str] = Field(default_factory=dict)
    naming: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    data: ProfileData
    folder: Path
    bundled: bool

    @property
    def id(self) -> str:
        return self.data.id

    @property
    def name(self) -> str:
        return self.data.name

    @property
    def description(self) -> str:
        return self.data.description

    @property
    def hints(self) -> dict[str, str]:
        return self.data.hints

    @property
    def template(self) -> Optional[Path]:
        path = self.folder / TEMPLATE_FILE
        return path if path.is_file() else None

    @property
    def setting_hints(self) -> dict[str, str]:
        """The profile's own settings as grey hint text, keyed "group.field"."""
        hints: dict[str, str] = {}
        for group in _GROUPS:
            for name, value in self.data.settings.get(group, {}).items():
                hints[f"{group}.{name}"] = format_value(value) if isinstance(value, (int, float)) else str(value)
        return hints


def user_profiles_dir() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return (Path(home) if home else Path.home() / ".aerosuite") / "profiles"


def _merged_settings(current: Settings, partial: dict) -> Settings:
    data = current.model_dump()
    for group, values in partial.items():
        if group not in data or not isinstance(values, dict):
            raise ProjectError(f"Unknown settings group {group!r} in profile")
        if group in _GROUPS:
            unknown = set(values) - set(data[group])
            if unknown:
                raise ProjectError(f"Unknown setting {group}.{sorted(unknown)[0]} in profile")
        data[group] = {**data[group], **values}
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(f"Invalid profile settings: {exc}") from exc


def _merged_naming(current: Naming, partial: dict) -> Naming:
    data = current.model_dump()
    unknown = set(partial) - set(data)
    if unknown:
        raise ProjectError(f"Unknown naming option {sorted(unknown)[0]} in profile")
    data.update(partial)
    try:
        return Naming.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(f"Invalid profile naming: {exc}") from exc


def _read(folder: Path, bundled: bool) -> Profile:
    path = folder / PROFILE_FILE
    try:
        data = ProfileData.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ProjectError(f"Invalid profile {folder.name}: {exc}") from exc
    if data.id != folder.name:
        raise ProjectError(f"Invalid profile {folder.name}: its id {data.id!r} does not match its folder")
    try:
        _merged_settings(Settings(), data.settings)
        _merged_naming(Naming(), data.naming)
    except ProjectError as exc:
        raise ProjectError(f"Invalid profile {folder.name}: {exc}") from exc
    return Profile(data, folder, bundled)


def list_profiles() -> tuple[list[Profile], list[str]]:
    """Bundled and user profiles (a user profile replaces a bundled one with the same id)."""
    found: dict[str, Profile] = {}
    problems: list[str] = []
    for base, bundled in ((BUNDLED_PROFILES, True), (user_profiles_dir(), False)):
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            try:
                found[folder.name] = _read(folder, bundled)
            except ProjectError as exc:
                problems.append(str(exc))
    return sorted(found.values(), key=lambda p: p.name.lower()), problems


def load_profile(profile_id: str) -> Profile:
    for base, bundled in ((user_profiles_dir(), False), (BUNDLED_PROFILES, True)):
        folder = base / profile_id
        if (folder / PROFILE_FILE).is_file():
            return _read(folder, bundled)
    raise ProjectError(f"Unknown profile {profile_id!r}")


def apply_profile(project_dir: Path, project: Project, profile: Profile) -> None:
    """Use `profile` for this project: its settings, naming and template overwrite what it defines."""
    project.settings = _merged_settings(project.settings, profile.data.settings)
    project.sweep.naming = _merged_naming(project.sweep.naming, profile.data.naming)
    if profile.template is not None:
        set_template(project_dir, project, profile.template)
    project.profile = profile.id


def save_profile(project_dir: Path, project: Project, profile_id: str, name: str,
                 description: str = "", overwrite: bool = False) -> Profile:
    """Save this project's template, settings and naming as a user profile (never mesh or sweep)."""
    if not _ID_RE.match(profile_id or ""):
        raise ProjectError("Profile ids use letters, digits, '-' and '_' only")
    if not name.strip():
        raise ProjectError("Give the profile a name")
    folder = user_profiles_dir() / profile_id
    if folder.exists() and not overwrite:
        raise ProjectError(f"Profile {profile_id} already exists")
    settings = project.settings
    saved_settings: dict = {
        group: {k: v for k, v in getattr(settings, group).model_dump().items() if v is not None}
        for group in _GROUPS
    }
    saved_settings["markers"] = dict(settings.markers)
    saved_settings["overrides"] = dict(settings.overrides)
    hints: dict[str, str] = {}
    if project.profile:
        try:
            hints = dict(load_profile(project.profile).hints)
        except ProjectError:
            hints = {}
    data = ProfileData(
        id=profile_id, name=name.strip(), description=description.strip(),
        settings=saved_settings, hints=hints, naming=project.sweep.naming.model_dump(),
    )
    template = Path(project_dir) / project.template
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PROFILE_FILE).write_text(data.model_dump_json(indent=2), encoding="utf-8")
        if template.is_file():
            shutil.copyfile(template, folder / TEMPLATE_FILE)
    except OSError as exc:
        raise ProjectError(f"Cannot save profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)
```

- [ ] **Step 6: Create `aerosuite/engine/study.py`**

```python
"""Create a study the way the web start screen describes it: a general case or an aircraft study."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .cfg import build_cases
from .errors import ProjectError, TemplateError
from .models import Project
from .profiles import apply_profile, load_profile
from .project import create_project, save_project, set_mesh, set_template
from .reference import BUNDLED_REFERENCE


def create_study(
    directory: Path,
    *,
    profile_id: Optional[str] = None,
    sweep: Optional[bool] = None,
    template: Optional[Path] = None,
    use_reference_template: bool = False,
    mesh: Optional[Path] = None,
) -> Project:
    """New project folder. With a profile: aircraft study (sweep on by default); without: general case.

    Every input is checked before anything is created, so a failure leaves no half-made project.
    The template is, in order: `template`, SU2's reference (`use_reference_template`), the profile's.
    """
    profile = load_profile(profile_id) if profile_id else None
    if template is not None and not Path(template).is_file():
        raise TemplateError(f"Template not found: {template}")
    if mesh is not None and not Path(mesh).is_file():
        raise ProjectError(f"Mesh not found: {mesh}")
    source = template or (BUNDLED_REFERENCE if use_reference_template else None) or (
        profile.template if profile else None)
    if source is None:
        suffix = f" (profile {profile.name} has none)" if profile else ""
        raise TemplateError(f"Choose a template{suffix}")
    project = create_project(directory)
    if profile is not None:
        apply_profile(directory, project, profile)
    set_template(directory, project, source)
    if mesh is not None:
        set_mesh(project, mesh)
    project.sweep.enabled = (profile is not None) if sweep is None else sweep
    project.cases = build_cases(project)
    save_project(directory, project)
    return project
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_profiles.py tests/engine/test_study.py -v`
Expected: all passed.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/engine/profiles.py aerosuite/engine/study.py aerosuite/resources/profiles/x07/profile.json pyproject.toml tests/engine/test_profiles.py tests/engine/test_study.py
git commit -m "feat(engine): add aircraft profiles (bundled X07) and study creation"
```

---

### Task 4: Sidebar for the new steps, shared checks panel, page background

**Files:**
- Modify: `aerosuite/web/status.py`, `aerosuite/web/layout.py`, `aerosuite/web/pages/sweep.py`
- Create: `aerosuite/web/checks.py`
- Modify tests: `tests/web/test_status.py`
- Test: `tests/web/test_web_frame_steps.py`

**Interfaces:**
- Consumes: `project.template_warnings` and `cfg.read_template` (Task 1).
- Produces:
  - `status.STEPS`, which lists setup, config, aircraft, sweep, configs, run, monitor and results.
  - `status.visible_steps(project) -> list[tuple[str, str]]`.
  - `status.step_badges(...)`, whose keys are now `setup, config, aircraft, sweep, configs, run, monitor, results`. The `settings` key is removed.
  - `layout.PAGE_CSS: str` and `layout.apply_theme() -> None`.
  - `checks.render_checks(frame: ProjectFrame, refresh: Callable[[], None]) -> None`. It keeps the old markers: `problems-none`, `problem-error`, `problem-warning` and `generate`.
  - Sweep page marker `sweep-off`.

- [ ] **Step 1: Replace `tests/web/test_status.py`**

```python
from aerosuite.engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, build_cases, generate_configs
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.project import TEMPLATE_FILE, create_project
from aerosuite.web.status import STEPS, step_badges, visible_steps


def test_steps_order():
    assert [key for key, _ in STEPS] == [
        "setup", "config", "aircraft", "sweep", "configs", "run", "monitor", "results"]


def test_ready_project(ready_project):
    project_dir, project = ready_project
    assert step_badges(project_dir, project) == {
        "setup": "done", "config": "done", "aircraft": "done", "sweep": "done", "configs": "todo",
        "run": "later", "monitor": "later", "results": "later",
    }


def test_visible_steps(ready_project):
    _, project = ready_project
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "config", "sweep", "configs", "run", "monitor", "results"]
    project.profile = "x07"
    project.sweep.enabled = False
    assert [k for k, _ in visible_steps(project)] == [
        "setup", "config", "aircraft", "configs", "run", "monitor", "results"]


def test_new_project(tmp_path):
    project = create_project(tmp_path / "p")
    badges = step_badges(tmp_path / "p", project)
    assert (badges["setup"], badges["config"], badges["sweep"], badges["configs"]) == ("todo", "todo", "todo", "todo")


def test_config_badge_flags_template_warnings(ready_project):
    project_dir, project = ready_project
    (project_dir / TEMPLATE_FILE).write_text("AOA= 1\nAOA= 2\n")
    assert step_badges(project_dir, project)["config"] == "attention"


def test_broken_setup_and_duplicate_cases(ready_project, tmp_path):
    project_dir, project = ready_project
    project.mesh.path = str(tmp_path / "gone.su2")
    project.cases.append(project.cases[0].model_copy())
    badges = step_badges(project_dir, project)
    assert badges["setup"] == "attention"
    assert badges["sweep"] == "attention"


def test_configs_badge_follows_the_sweep(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    assert step_badges(project_dir, project)["configs"] == "done"
    update_sweep(project, alpha=[0.0, 2.0])
    assert step_badges(project_dir, project)["configs"] == "attention"
    (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).write_text("{broken")
    assert step_badges(project_dir, project)["configs"] == "attention"
```

- [ ] **Step 2: Write the failing page tests `tests/web/test_web_frame_steps.py`**

```python
from nicegui.testing import User

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _switch(project_dir, *, profile=None, sweep=True):
    project = open_project(project_dir)
    project.profile = profile
    project.sweep.enabled = sweep
    project.cases = build_cases(project)
    save_project(project_dir, project)


async def test_sidebar_shows_config_and_hides_aircraft_without_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="badge-config-done")
    await user.should_see(marker="badge-sweep-done")
    await user.should_not_see(marker="badge-aircraft-done")


async def test_sidebar_with_a_profile_and_the_sweep_off(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, profile="x07", sweep=False)
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="badge-aircraft-done")
    await user.should_not_see(marker="badge-sweep-done")
    await user.should_not_see(marker="badge-sweep-todo")


async def test_sweep_page_when_the_sweep_is_off(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, sweep=False)
    await user.open(project_url("sweep", project_dir))
    await user.should_see(marker="sweep-off")
    await user.should_not_see(marker="generate")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_status.py tests/web/test_web_frame_steps.py -v`
Expected: FAIL (`cannot import name 'visible_steps'`, the markers are not found).

- [ ] **Step 4: Replace `aerosuite/web/status.py`**

```python
"""Sidebar badges: which workflow steps look done, need attention, are not started, or come later."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..engine.cfg import CASE_INDEX_FILE, CONFIGS_DIR, read_template
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.models import Project
from ..engine.preflight import sweep_problems
from ..engine.project import template_warnings
from ..engine.results import load_case_index

Badge = Literal["done", "attention", "todo", "later"]

STEPS: list[tuple[str, str]] = [
    ("setup", "Setup"),
    ("config", "Config"),
    ("aircraft", "Aircraft"),
    ("sweep", "Sweep"),
    ("configs", "Configs"),
    ("run", "Run"),
    ("monitor", "Monitor"),
    ("results", "Results"),
]


def visible_steps(project: Project) -> list[tuple[str, str]]:
    """Aircraft only with a profile; Sweep only when the sweep is on."""
    return [
        (key, label) for key, label in STEPS
        if not (key == "aircraft" and not project.profile)
        and not (key == "sweep" and not project.sweep.enabled)
    ]


def _configs_badge(project_dir: Path, project: Project) -> Badge:
    if not (project_dir / CONFIGS_DIR / CASE_INDEX_FILE).is_file():
        return "todo"
    try:
        generated = set(load_case_index(project_dir / CONFIGS_DIR))
    except ProjectError:
        return "attention"
    return "done" if generated and generated == {case.name for case in project.cases} else "attention"


def _config_badge(project_dir: Path, project: Project, template_ok: bool) -> Badge:
    if not template_ok:
        return "todo"
    try:
        warnings = template_warnings(read_template(project_dir, project))
    except AeroSuiteError:
        return "attention"
    return "attention" if warnings else "done"


def step_badges(project_dir: Path, project: Project) -> dict[str, Badge]:
    project_dir = Path(project_dir)
    template_ok = (project_dir / project.template).is_file()
    mesh_ok = bool(project.mesh.path) and Path(project.mesh.path).is_file()
    if template_ok and mesh_ok:
        setup: Badge = "done"
    elif not template_ok and not project.mesh.path:
        setup = "todo"
    else:
        setup = "attention"
    if not project.sweep.mach and not project.cases:
        sweep: Badge = "todo"
    elif any(problem.severity == "error" for problem in sweep_problems(project)):
        sweep = "attention"
    else:
        sweep = "done"
    return {
        "setup": setup,
        "config": _config_badge(project_dir, project, template_ok),
        "aircraft": "done" if template_ok else "todo",
        "sweep": sweep,
        "configs": _configs_badge(project_dir, project),
        "run": "later",
        "monitor": "later",
        "results": "later",
    }
```

- [ ] **Step 5: Update `aerosuite/web/layout.py`**

- Replace `from .status import STEPS, step_badges` with `from .status import step_badges, visible_steps`.
- Replace the `PAGE_OF_STEP = {...}` line with:

```python
PAGE_OF_STEP = {"setup": "setup", "config": "config", "aircraft": "aircraft", "sweep": "sweep"}
PAGE_CSS = "body { background-color: #f7f7f7; color: #1f1f1f; }"


def apply_theme() -> None:
    """Paint our own background so text stays readable in browsers that use a dark canvas."""
    ui.add_css(PAGE_CSS)
```

- In `header()`, add `apply_theme()` as its first line.
- In `ProjectFrame.__init__`, add `apply_theme()` as the first line after `self._on_reload = on_reload`.
- In `ProjectFrame.refresh`:
  - replace `for key, label in STEPS:` with `for key, label in visible_steps(self.session.project):`;
  - replace `page = PAGE_OF_STEP.get(key)` with:

```python
                    page = PAGE_OF_STEP.get(key)
                    if key == "configs":
                        page = "sweep" if self.session.project.sweep.enabled else "config"
```

- [ ] **Step 6: Create `aerosuite/web/checks.py` by moving `_problems` out of the Sweep page**

```python
"""Checks and the Generate button: shared by the Config page (sweep off) and the Sweep page."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import generate_configs
from ..engine.errors import AeroSuiteError
from ..engine.preflight import has_errors, preflight
from .layout import ProjectFrame


def render_checks(frame: ProjectFrame, refresh: Callable[[], None]) -> None:
    found = preflight(frame.session.directory, frame.session.project, "generate")
    if not found:
        ui.label("No problems found.").classes("text-positive").mark("problems-none")
    for problem in found:
        style = "text-negative" if problem.severity == "error" else "text-warning"
        prefix = "Error" if problem.severity == "error" else "Warning"
        ui.label(f"{prefix}: {problem.message}").classes(style).mark(f"problem-{problem.severity}")

    def generate() -> None:
        stale = frame.ensure_current(notify=False)  # one toast, worded for Generate, not two
        if stale is not None:
            if frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; generate again", type="warning")
            return
        # Check again: files may have gone (e.g. the mesh deleted) since these checks were drawn.
        errors = [p for p in preflight(frame.session.directory, frame.session.project, "generate")
                  if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            refresh()
            return
        try:
            written = generate_configs(frame.session.directory, frame.session.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        plural = "" if len(written) == 1 else "s"
        ui.notify(f"Wrote {len(written)} config{plural}", type="positive")
        frame.refresh()
        refresh()

    button = ui.button("Generate configs", on_click=generate).mark("generate")
    button.set_enabled(not has_errors(found))
```

In `aerosuite/web/pages/sweep.py`:
- delete the whole `_problems` function;
- remove the now-unused imports `generate_configs`, `AeroSuiteError`, `has_errors` and `preflight`, keeping any that are still used;
- add `from ..checks import render_checks`;
- in `render_problems`, replace `_problems(frame, render_problems)` with `render_checks(frame, render_problems)`.

In `sweep_page`'s `body()`, insert these lines at the top of the function, before `_sweep_fields(frame, after)`. The check sits inside `body()` so that an outside change which switches the sweep on or off is picked up by the reload (`on_reload` calls `body.refresh()`):

```python
            if not frame.session.project.sweep.enabled:
                holders.clear()  # render_cases / render_problems then do nothing
                ui.label("The sweep is off for this project: it is a single case. "
                         "Switch the sweep on in Setup to run Mach/alpha/beta cases.").mark("sweep-off")
                return
```

- [ ] **Step 7: Run the web tests**

Run: `uv run pytest tests/web -v`
Expected: all passed. `tests/web/test_web_settings.py` still passes, because the Settings page is not removed until Task 7. The sidebar no longer links to it.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/web/status.py aerosuite/web/layout.py aerosuite/web/checks.py aerosuite/web/pages/sweep.py tests/web/test_status.py tests/web/test_web_frame_steps.py
git commit -m "feat(web): show Config/Aircraft/Sweep steps per project, share checks, paint page background"
```

---

### Task 5: Reference panel component

**Files:**
- Create: `aerosuite/web/reference_panel.py`
- Modify: `tests/web/main_app.py` (add the test-only page `/_test/reference`)
- Test: `tests/web/test_web_reference.py`

**Interfaces:**
- Consumes: `reference.load_reference`, `read_reference_text`, `search`, `find_lines` and `RefOption` (Task 2); `picker.pick_path`.
- Deliberate simplification of spec §5: there is no "Show full file" toggle. The Find box is always shown under the results. The file is only ever shown as a window of lines around the current match, so a toggle would have nothing to hide.
- Produces:
  - `reference_panel.reference_panel(on_insert: Callable[[RefOption], str | None], in_config: Callable[[], set[str]]) -> Callable[[], None]`. It builds the panel and returns a function that redraws the results.
  - `on_insert` returns the note to show. On `None` the panel shows "Inserted KEY".
  - Markers:
    - `ref-source`, `ref-error`, `ref-search`, `ref-no-results`
    - `ref-result-<KEY>`, `ref-insert-<KEY>`, `ref-in-config-<KEY>`, `ref-insert-note`
    - `ref-find`, `ref-find-next`, `ref-find-status`, `ref-window`, `ref-load`

- [ ] **Step 1: Add the test page to `tests/web/main_app.py`**

Insert before the final `ui.run(...)` line:

```python
from aerosuite.web.reference_panel import reference_panel  # noqa: E402


@ui.page("/_test/reference")
def _test_reference_page() -> None:
    """Test-only page: a reference panel wired to an in-memory config text."""
    state = {"text": "SOLVER= EULER\n", "inserted": []}
    shown = ui.label("").mark("t-inserted")

    def on_insert(option):
        state["inserted"].append(option.key)
        state["text"] += option.line + "\n"
        shown.text = ",".join(state["inserted"])
        return None

    reference_panel(on_insert=on_insert, in_config=lambda: {
        line.split("=")[0].strip() for line in state["text"].splitlines() if "=" in line})
```

- [ ] **Step 2: Write the failing tests `tests/web/test_web_reference.py`**

```python
from nicegui.testing import User


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_search_and_insert(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("marker_euler")
    await user.should_see(marker="ref-result-MARKER_EULER")
    user.find(marker="ref-insert-MARKER_EULER").click()
    assert _element(user, "t-inserted").text == "MARKER_EULER"
    await user.should_see("Inserted MARKER_EULER")
    await user.should_see(marker="ref-in-config-MARKER_EULER")


async def test_options_already_in_the_config_are_marked(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("solver")
    await user.should_see(marker="ref-in-config-SOLVER")
    await user.should_not_see(marker="ref-insert-SOLVER")


async def test_no_results(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("zzzzqqq")
    await user.should_see(marker="ref-no-results")


async def test_find_in_the_full_file(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-find").type("MARKER_EULER")
    user.find(marker="ref-find-next").click()
    status = _element(user, "ref-find-status").text
    assert status.startswith("Match 1 of ")
    assert "MARKER_EULER" in _element(user, "ref-window").content
    user.find(marker="ref-find-next").click()
    assert _element(user, "ref-find-status").text.startswith("Match 2 of ")
    user.find(marker="ref-find").clear().type("zzzzqqq")
    user.find(marker="ref-find-next").click()
    assert _element(user, "ref-find-status").text == "No match"


async def test_load_another_reference(user: User, tmp_path, eventually):
    (tmp_path / "old_su2.cfg").write_text("% Old option\nOLD_THING= 1\n")
    (tmp_path / "empty.cfg").write_text("% nothing\n")
    await user.open("/_test/reference")
    user.find(marker="ref-load").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-old_su2.cfg").click()
    await eventually(lambda: _element(user, "ref-source").text == "old_su2.cfg")
    user.find(marker="ref-search").type("old")
    await user.should_see(marker="ref-result-OLD_THING")

    user.find(marker="ref-load").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-empty.cfg").click()
    await eventually(lambda: "no SU2 options" in _element(user, "ref-error").text)
    assert _element(user, "ref-source").text == "old_su2.cfg"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_web_reference.py -v`
Expected: collection error `No module named 'aerosuite.web.reference_panel'`.

- [ ] **Step 4: Create `aerosuite/web/reference_panel.py`**

```python
"""SU2 reference beside your config: search options, Insert them, Find in the full file."""
import html
from typing import Callable, Optional

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.reference import RefOption, find_lines, load_reference, read_reference_text, search
from .picker import pick_path

WINDOW = 8  # lines shown on each side of a Find match


def _window_html(text: str, line_no: int) -> str:
    lines = text.splitlines()
    start = max(1, line_no - WINDOW)
    end = min(len(lines), line_no + WINDOW)
    rows = []
    for number in range(start, end + 1):
        content = html.escape(lines[number - 1])
        if number == line_no:
            content = f"<mark>{content}</mark>"
        rows.append(f"{number:>5}  {content}")
    return '<pre style="font-size:12px;margin:0;white-space:pre-wrap">' + "\n".join(rows) + "</pre>"


def reference_panel(
    on_insert: Callable[[RefOption], Optional[str]],
    in_config: Callable[[], set[str]],
) -> Callable[[], None]:
    """Build the panel; returns a function that redraws the search results."""
    state = {"options": load_reference(), "text": read_reference_text(),
             "query": "", "find": "", "matches": [], "index": -1}

    ui.label("Reference").classes("text-lg")
    source = ui.label("config_template.cfg").classes("text-xs text-grey-8").mark("ref-source")
    error = ui.label("").classes("text-negative text-xs").mark("ref-error")
    ui.input("Search options", on_change=lambda e: on_search(e.value)).classes("w-full").mark("ref-search")
    note = ui.label("").classes("text-xs text-grey-8").mark("ref-insert-note")
    results = ui.column().classes("w-full gap-1")

    def render_results() -> None:
        results.clear()
        found = search(state["options"], state["query"])
        present = in_config()
        with results:
            if state["query"].strip() and not found:
                ui.label("No options match").classes("text-grey-7").mark("ref-no-results")
            for option in found:
                with ui.row().classes("w-full items-start no-wrap gap-2"):
                    with ui.column().classes("grow gap-0"):
                        ui.label(option.line).classes("font-mono text-xs").mark(f"ref-result-{option.key}")
                        ui.label(option.description or "(no description)").classes("text-xs text-grey-8")
                    if option.key in present:
                        ui.label("In config").classes("text-positive text-xs").mark(f"ref-in-config-{option.key}")
                    else:
                        ui.button("Insert", icon="add", on_click=lambda o=option: insert(o)).props(
                            "flat dense").mark(f"ref-insert-{option.key}")

    def on_search(value: Optional[str]) -> None:
        state["query"] = value or ""
        note.text = ""
        render_results()

    def insert(option: RefOption) -> None:
        message = on_insert(option)
        render_results()
        note.text = message or f"Inserted {option.key}"

    ui.label("Find in the full file").classes("text-sm")
    with ui.row().classes("w-full items-center no-wrap"):
        find_box = ui.input("Find").classes("grow").mark("ref-find")
        ui.button("Find next", on_click=lambda: find_next()).props("flat").mark("ref-find-next")
    status = ui.label("").classes("text-xs").mark("ref-find-status")
    window = ui.html("", sanitize=False).classes("w-full").mark("ref-window")

    def find_next() -> None:
        query = (find_box.value or "").strip()
        if query != state["find"]:
            state["find"] = query
            state["matches"] = find_lines(state["text"], query)
            state["index"] = -1
        if not state["matches"]:
            status.text = "No match"
            window.content = ""
            return
        state["index"] = (state["index"] + 1) % len(state["matches"])
        line_no = state["matches"][state["index"]]
        status.text = f"Match {state['index'] + 1} of {len(state['matches'])} — line {line_no}"
        window.content = _window_html(state["text"], line_no)

    async def load_other() -> None:
        path = await pick_path("Choose a reference config", mode="file", suffixes=(".cfg",))
        if path is None:
            return
        try:
            options = load_reference(path)
            text = read_reference_text(path)
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        state.update(options=options, text=text, find="", matches=[], index=-1)
        source.text = path.name
        error.text = ""
        status.text = ""
        window.content = ""
        render_results()

    ui.button("Load another reference…", on_click=load_other).props("flat").mark("ref-load")
    render_results()
    return render_results
```

`sanitize=False` is safe here because `_window_html` escapes every line with `html.escape` before adding its own `<mark>`/`<pre>`. NiceGUI 3.17's `ui.html` accepts the argument.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_reference.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/web/reference_panel.py tests/web/main_app.py tests/web/test_web_reference.py
git commit -m "feat(web): add the SU2 reference panel (search, insert, find, load another)"
```

---

### Task 6: Config page and shared preview

**Files:**
- Create: `aerosuite/web/preview.py`, `aerosuite/web/pages/config.py`
- Modify: `aerosuite/web/app.py` (register `config`)
- Test: `tests/web/test_web_config.py`

**Interfaces:**
- Consumes: `project.read_template_text`, `set_template_text` and `template_warnings` (Task 1); `reference.keys_in` and `RefOption` (Task 2); `reference_panel` (Task 5); `checks.render_checks` (Task 4); `cfg.read_template` and `render_case`.
- Produces:
  - `preview.preview_section(frame: ProjectFrame) -> Callable[[], None]`, which returns a redraw function. Its markers are `preview-toggle`, `preview-case`, `preview`, `preview-empty` and `preview-error`.
  - The page `/config`. Its markers are `config-text`, `config-text-error`, `config-warning`, `config-checks`, plus the reference panel's and preview's markers.
  - `pages.config.ADDED_HEADING = "% --- added from reference ---"`

- [ ] **Step 1: Write the failing tests `tests/web/test_web_config.py`**

```python
import json

from nicegui.testing import User

from aerosuite.engine.cfg import build_cases
from aerosuite.engine.project import TEMPLATE_FILE, open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _single(project_dir):
    project = open_project(project_dir)
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)


async def _open(user, project_dir):
    await user.open(project_url("config", project_dir))


async def test_editor_shows_and_saves_the_template(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    editor = _element(user, "config-text")
    assert editor.value.startswith("MACH_NUMBER= 0.3")
    user.find(marker="config-text").type("CFL_NUMBER= 5\n").trigger("blur")
    assert (project_dir / TEMPLATE_FILE).read_text().endswith("CFL_NUMBER= 5\n")


async def test_warnings_are_shown_but_do_not_block(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="config-text").type("oops\nAOA= 5\n").trigger("blur")
    await user.should_see("is not an option or a comment")
    await user.should_see("AOA is set on lines")
    assert "oops" in (project_dir / TEMPLATE_FILE).read_text()


async def test_insert_from_the_reference(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="ref-search").type("marker_euler")
    user.find(marker="ref-insert-MARKER_EULER").click()
    text = (project_dir / TEMPLATE_FILE).read_text()
    assert text.endswith("% --- added from reference ---\nMARKER_EULER= ( airfoil )\n")
    await user.should_see(marker="ref-in-config-MARKER_EULER")
    user.find(marker="ref-search").clear().type("marker_sym")
    user.find(marker="ref-insert-MARKER_SYM").click()
    text = (project_dir / TEMPLATE_FILE).read_text()
    assert text.count("% --- added from reference ---") == 1
    assert text.endswith("MARKER_EULER= ( airfoil )\nMARKER_SYM= ( NONE )\n")


async def test_insert_of_an_option_already_typed(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="ref-search").type("marker_euler")
    user.find(marker="config-text").type("MARKER_EULER= ( wing )\n")  # typed, not yet saved
    user.find(marker="ref-insert-MARKER_EULER").click()
    await user.should_see("MARKER_EULER is already set on line")


async def test_preview_of_a_sweep_case(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="preview")
    toggle = _element(user, "preview-toggle")
    with user:
        toggle.set_value(True)
    assert "MACH_NUMBER= 0.8" in _element(user, "preview").content
    await user.should_not_see(marker="config-checks")  # sweep on: Generate lives on the Sweep page


async def test_single_case_preview_checks_and_generate(user: User, ready_project):
    project_dir, _ = ready_project
    _single(project_dir)
    await _open(user, project_dir)
    toggle = _element(user, "preview-toggle")
    with user:
        toggle.set_value(True)
    content = _element(user, "preview").content
    assert "MACH_NUMBER= 0.3" in content and "BREAKDOWN_FILENAME" not in content
    await user.should_see(marker="config-checks")
    user.find(marker="generate").click()
    await user.should_see("Wrote 1 config")
    index = json.loads((project_dir / "configs" / "cases.json").read_text())
    assert index == {"study": {"mach": 0.3, "alpha": 0.0, "beta": 0.0}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_web_config.py -v`
Expected: FAIL (`/config` returns 404).

- [ ] **Step 3: Create `aerosuite/web/preview.py`**

```python
"""A 'Preview' switch and the rendered config of a chosen case (Config and Aircraft pages)."""
from typing import Callable

from nicegui import ui

from ..engine.cfg import read_template, render_case
from ..engine.errors import AeroSuiteError
from .layout import ProjectFrame


def preview_section(frame: ProjectFrame) -> Callable[[], None]:
    """Build the switch and box; returns a function that redraws the preview (synchronously)."""
    state = {"on": False, "case": None}

    def toggle(value: bool) -> None:
        state["on"] = value
        render()

    ui.switch("Preview", value=False, on_change=lambda e: toggle(e.value)).mark("preview-toggle")
    box = ui.column().classes("w-full gap-2")

    def choose(name: str) -> None:
        state["case"] = name
        render()

    def render() -> None:
        box.clear()
        if not state["on"]:
            return
        project = frame.session.project
        with box:
            if not project.cases:
                ui.label("No case to preview yet.").mark("preview-empty")
                return
            names = [case.name for case in project.cases]
            if state["case"] not in names:
                state["case"] = names[0]
            if len(names) > 1:
                ui.select(names, value=state["case"], label="Case",
                          on_change=lambda e: choose(e.value)).mark("preview-case")
            try:
                template = read_template(frame.session.directory, project)
            except AeroSuiteError as exc:
                ui.label(f"Error: {exc}").classes("text-negative").mark("preview-error")
                return
            case = next(case for case in project.cases if case.name == state["case"])
            ui.code(render_case(template, project, case), language="ini").classes("w-full").mark("preview")

    render()
    return render
```

- [ ] **Step 4: Create `aerosuite/web/pages/config.py`**

```python
"""Config: the project's template as text, with a live preview and SU2's reference beside it."""
import re
from typing import Optional

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.project import read_template_text, set_template_text, template_warnings
from ...engine.reference import RefOption, keys_in
from ..checks import render_checks
from ..layout import ProjectFrame, open_session
from ..preview import preview_section
from ..reference_panel import reference_panel

ADDED_HEADING = "% --- added from reference ---"


def register() -> None:
    @ui.page("/config")
    def config_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "config", on_reload=lambda: body.refresh())

        @ui.refreshable
        def body() -> None:
            _build(frame)

        with frame.content:
            ui.label("Config").classes("text-2xl")
            body()


def _initial_text(frame: ProjectFrame) -> str:
    try:
        return read_template_text(frame.session.directory, frame.session.project)
    except AeroSuiteError:
        return ""


def _build(frame: ProjectFrame) -> None:
    initial = _initial_text(frame)
    last = {"text": initial}
    holders: dict = {}

    def show_warnings(warnings: list[str]) -> None:
        box = holders["warnings"]
        box.clear()
        with box:
            for warning in warnings:
                ui.label(warning).classes("text-warning text-xs").mark("config-warning")

    def render_checks_box() -> None:
        box = holders.get("checks")
        if box is None:
            return
        box.clear()
        with box:
            render_checks(frame, render_checks_box)

    def after_save() -> None:
        holders["preview"]()
        render_checks_box()
        holders["reference"]()

    def save_text(text: str) -> Optional[str]:
        found: list[str] = []

        def change(p) -> None:
            found.extend(set_template_text(frame.session.directory, p, text))

        message = frame.save(change, then=after_save)
        if message is None:
            last["text"] = text
            show_warnings(found)
        return message

    def commit() -> None:
        text = holders["editor"].value or ""
        if text == last["text"] and not holders["error"].text:
            return
        holders["error"].text = save_text(text) or ""

    def insert(option: RefOption) -> Optional[str]:
        text = holders["editor"].value or ""
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(rf"^\s*{re.escape(option.key)}\s*=", line):
                return f"{option.key} is already set on line {number}"
        addition = "" if (not text or text.endswith("\n")) else "\n"
        if ADDED_HEADING not in text:
            addition += ADDED_HEADING + "\n"
        new_text = text + addition + option.line + "\n"
        holders["editor"].value = new_text
        message = save_text(new_text)
        holders["error"].text = message or ""
        return message

    with ui.row().classes("w-full no-wrap items-start gap-6"):
        with ui.column().classes("w-1/2 gap-2"):
            editor = ui.textarea("Template (template.cfg)", value=initial).props(
                "outlined autogrow input-class=font-mono").classes("w-full").mark("config-text")
            holders["editor"] = editor
            holders["error"] = ui.label("").classes("text-negative text-xs").mark("config-text-error")
            holders["warnings"] = ui.column().classes("gap-0")
            editor.on("blur", commit)
            holders["preview"] = preview_section(frame)
            if not frame.session.project.sweep.enabled:
                ui.label("Checks").classes("text-lg")
                holders["checks"] = ui.column().classes("w-full gap-2").mark("config-checks")
        with ui.column().classes("w-1/2 gap-2"):
            holders["reference"] = reference_panel(
                on_insert=insert, in_config=lambda: keys_in(holders["editor"].value or ""))
    show_warnings(template_warnings(initial))
    render_checks_box()
```

- [ ] **Step 5: Register the page in `aerosuite/web/app.py`**

Replace

```python
    from .pages import projects, settings, setup, sweep

    projects.register()
    setup.register()
    settings.register()
    sweep.register()
```

with

```python
    from .pages import config, projects, settings, setup, sweep

    projects.register()
    setup.register()
    config.register()
    settings.register()
    sweep.register()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_config.py -v`
Expected: 6 passed. The bundled reference has `MARKER_EULER= ( airfoil )` (line 1083) and `MARKER_SYM= ( NONE )` (line 1112), and each appears only once.

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/web/preview.py aerosuite/web/pages/config.py aerosuite/web/app.py tests/web/test_web_config.py
git commit -m "feat(web): add the Config page (template editor, preview, reference, single-case generate)"
```

---

### Task 7: Aircraft page (replaces Settings)

**Files:**
- Move: `aerosuite/web/pages/settings.py` → `aerosuite/web/pages/aircraft.py` (`git mv`, then rewrite)
- Delete: `tests/web/test_web_settings.py` (its coverage moves to the new test file)
- Modify: `aerosuite/web/app.py`
- Test: `tests/web/test_web_aircraft.py`

**Interfaces:**
- Consumes:
  - `profiles.load_profile` and `Profile.hints` / `setting_hints` (Task 3)
  - `reference_panel` (Task 5) and `preview_section` (Task 6)
  - `editing.set_parameter`, `unset_parameter`, `MARKER_PREFIX`
  - `cfg.read_template` and `render_case`; `reference.keys_in`
- Produces the page `/aircraft`, with these markers:
  - `aircraft-none`
  - form fields: `<group>-<field>` for number fields (for example `reference-ref_area`, `freestream-temperature_K`, `numerics-cfl`, `numerics-iter`)
  - dropdowns: `numerics-conv_method`, `numerics-muscl`, `numerics-turb_model`
  - markers: `marker-<KEY>-include` and `marker-<KEY>-value`
  - Placeholders: `override-<KEY>-value`, `override-<KEY>-delete`, `override-new-key`, `override-new-value`, `override-add`, `override-add-error`

- [ ] **Step 1: Write the failing tests `tests/web/test_web_aircraft.py`**

```python
from nicegui.testing import User

from aerosuite.engine.profiles import apply_profile, load_profile
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _with_x07(project_dir, **numerics):
    project = open_project(project_dir)
    apply_profile(project_dir, project, load_profile("x07"))
    for name, value in numerics.items():
        setattr(project.settings.numerics, name, value)
    save_project(project_dir, project)


async def _open(user, project_dir):
    await user.open(project_url("aircraft", project_dir))


def _preview(user):
    with user:
        _element(user, "preview-toggle").set_value(True)
    return _element(user, "preview").content


async def test_without_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_see(marker="aircraft-none")


async def test_profile_values_and_number_fields(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "reference-ref_area").value == "16.213"
    user.find(marker="freestream-temperature_K").type("250").trigger("blur")
    assert open_project(project_dir).settings.freestream.temperature_K == 250.0
    user.find(marker="numerics-cfl").clear().type("abc").trigger("blur")
    await user.should_see("CFL number: 'abc' is not a number")
    assert open_project(project_dir).settings.numerics.cfl == 1.0


async def test_dropdowns(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir, turb_model="SA_NEG")
    await _open(user, project_dir)
    conv = _element(user, "numerics-conv_method")
    assert conv.value == "ROE"
    with user:
        conv.set_value("JST")
    assert open_project(project_dir).settings.numerics.conv_method == "JST"
    with user:
        _element(user, "numerics-conv_method").set_value("")
    assert open_project(project_dir).settings.numerics.conv_method is None
    turb = _element(user, "numerics-turb_model")
    assert turb.value == "SA_NEG" and "SA_NEG" in turb.options


async def test_markers_include_and_value(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    assert _element(user, "marker-MARKER_HEATFLUX-value").props["placeholder"] == "( Fuselage, Wing, VT, HT )"
    with user:
        _element(user, "marker-MARKER_FAR-include").set_value(False)
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": None}
    assert "MARKER_FAR=" not in _preview(user)
    with user:
        _element(user, "marker-MARKER_FAR-include").set_value(True)
    assert open_project(project_dir).settings.markers == {}
    user.find(marker="marker-MARKER_FAR-value").type("( far2 )").trigger("blur")
    assert open_project(project_dir).settings.markers == {"MARKER_FAR": "( far2 )"}
    user.find(marker="marker-MARKER_FAR-value").clear().trigger("blur")
    assert open_project(project_dir).settings.markers == {}


async def test_placeholders(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="override-new-key").type("conv_field")
    user.find(marker="override-new-value").type("LIFT")
    user.find(marker="override-add").click()
    assert open_project(project_dir).settings.overrides == {"CONV_FIELD": "LIFT"}
    user.find(marker="override-CONV_FIELD-value").clear().type("DRAG").trigger("blur")
    assert open_project(project_dir).settings.overrides == {"CONV_FIELD": "DRAG"}
    user.find(marker="override-new-key").type("AOA")
    user.find(marker="override-new-value").type("3")
    user.find(marker="override-add").click()
    await user.should_see("set per case")
    user.find(marker="override-CONV_FIELD-delete").click()
    assert open_project(project_dir).settings.overrides == {}


async def test_insert_from_the_reference(user: User, ready_project):
    project_dir, _ = ready_project
    _with_x07(project_dir)
    await _open(user, project_dir)
    user.find(marker="ref-search").type("conv_cauchy_eps")
    user.find(marker="ref-insert-CONV_CAUCHY_EPS").click()
    overrides = open_project(project_dir).settings.overrides
    assert list(overrides) == ["CONV_CAUCHY_EPS"] and overrides["CONV_CAUCHY_EPS"]
    await user.should_see(marker="override-CONV_CAUCHY_EPS-value")
    user.find(marker="ref-search").clear().type("marker_euler")
    user.find(marker="ref-insert-MARKER_EULER").click()
    assert open_project(project_dir).settings.markers["MARKER_EULER"] == "( airfoil )"
    await user.should_see(marker="marker-MARKER_EULER-value")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_web_aircraft.py -v`
Expected: FAIL (`/aircraft` returns 404).

- [ ] **Step 3: Move the Settings page and rewrite it as the Aircraft page**

```bash
git mv aerosuite/web/pages/settings.py aerosuite/web/pages/aircraft.py
git rm -q tests/web/test_web_settings.py
```

Replace the whole content of `aerosuite/web/pages/aircraft.py` with:

```python
"""Aircraft: the Aircraft Aero form (profile defaults as hints), placeholders and the reference."""
from typing import Callable, Optional

from nicegui import ui

from ...engine.cfg import read_template, render_case
from ...engine.editing import MARKER_PREFIX, set_parameter, unset_parameter
from ...engine.errors import AeroSuiteError, ProjectError
from ...engine.models import Project
from ...engine.naming import format_value
from ...engine.profiles import load_profile
from ...engine.reference import RefOption, keys_in
from ..fields import text_field
from ..layout import ProjectFrame, open_session
from ..preview import preview_section
from ..reference_panel import reference_panel
from ..session import parse_optional_int, parse_optional_number

# (label, settings group, field, kind) — kind: "float" | "int"
NUMBER_FIELDS = {
    "Freestream": [
        ("Temperature (K)", "freestream", "temperature_K", "float"),
        ("Reynolds number", "freestream", "reynolds", "float"),
        ("Reynolds length", "freestream", "reynolds_length", "float"),
    ],
    "Physical and reference": [
        ("Reference length", "reference", "ref_length", "float"),
        ("Reference area", "reference", "ref_area", "float"),
        ("Moment origin x", "reference", "origin_x", "float"),
        ("Moment origin y", "reference", "origin_y", "float"),
        ("Moment origin z", "reference", "origin_z", "float"),
    ],
}
NUMERIC_TEXT = [("CFL number", "cfl", "float"), ("Iterations", "iter", "int")]
DROPDOWNS = [
    ("Convective", "conv_method", ["ROE", "JST", "AUSM"]),
    ("MUSCL", "muscl", ["YES", "NO"]),
    ("Turbulence", "turb_model", ["SST", "SA"]),
]
MARKER_ROWS = ["MARKER_HEATFLUX", "MARKER_FAR", "MARKER_PLOTTING", "MARKER_MONITORING"]


def register() -> None:
    @ui.page("/aircraft")
    def aircraft_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "aircraft", on_reload=lambda: body.refresh())

        @ui.refreshable
        def body() -> None:
            if not frame.session.project.profile:
                ui.label("This project has no aircraft profile. Choose one in Setup "
                         "to use the Aircraft Aero form.").mark("aircraft-none")
                return
            _build(frame)

        with frame.content:
            ui.label("Aircraft").classes("text-2xl")
            body()


def _hints(project: Project) -> dict[str, str]:
    try:
        profile = load_profile(project.profile)
    except ProjectError:
        return {}
    return {**profile.setting_hints, **profile.hints}


def _rendered_keys(frame: ProjectFrame) -> set[str]:
    project = frame.session.project
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError:
        return set()
    if not project.cases:
        return keys_in(template)
    return keys_in(render_case(template, project, project.cases[0]))


def _build(frame: ProjectFrame) -> None:
    hints = _hints(frame.session.project)
    holders: dict = {}

    def after() -> None:
        holders["preview"]()
        holders["reference"]()

    with ui.row().classes("w-full no-wrap items-start gap-6"):
        with ui.column().classes("w-1/2 gap-2"):
            for title, rows in NUMBER_FIELDS.items():
                ui.label(title).classes("text-lg")
                for label, group, name, kind in rows:
                    _number_field(frame, hints, label, group, name, kind, after)
            ui.label("Numerics").classes("text-lg")
            for label, name, options in DROPDOWNS:
                _dropdown(frame, label, name, options, after)
            for label, name, kind in NUMERIC_TEXT:
                _number_field(frame, hints, label, "numerics", name, kind, after)
            holders["markers"] = _markers(frame, hints, after)
            holders["overrides"] = _placeholders(frame, after)
            holders["preview"] = preview_section(frame)
        with ui.column().classes("w-1/2 gap-2"):
            holders["reference"] = reference_panel(
                on_insert=lambda option: _insert(frame, option, holders, after),
                in_config=lambda: _rendered_keys(frame))


def _number_field(frame, hints, label, group, name, kind, after) -> None:
    current = getattr(getattr(frame.session.project.settings, group), name)
    shown = "" if current is None else (format_value(current) if kind == "float" else str(current))
    parse = parse_optional_number if kind == "float" else parse_optional_int

    def change(p: Project, text: str) -> None:
        setattr(getattr(p.settings, group), name, parse(text, label))

    text_field(label, shown, lambda text: frame.save(lambda p: change(p, text), then=after),
               mark=f"{group}-{name}", placeholder=hints.get(f"{group}.{name}", "template value"))


def _dropdown(frame, label, name, choices, after) -> None:
    current = getattr(frame.session.project.settings.numerics, name)
    options = {"": "(template value)", **{c: c for c in choices}}
    if current and current not in options:
        options[current] = current  # keep a template value that is not in the fixed list

    def change(value) -> None:
        message = frame.save(lambda p: setattr(p.settings.numerics, name, value or None), then=after)
        if message:
            ui.notify(message, type="negative")

    ui.select(options, value=current or "", label=label,
              on_change=lambda e: change(e.value)).classes("w-full").mark(f"numerics-{name}")


def _markers(frame: ProjectFrame, hints: dict[str, str], after: Callable[[], None]) -> Callable[[], None]:
    ui.label("Markers").classes("text-lg")
    mesh = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    ui.label(f"Mesh markers: {mesh}").classes("text-xs text-grey-8")
    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        # Plain synchronous rebuild: tests read these rows right after a change.
        box.clear()
        markers = frame.session.project.settings.markers
        keys = MARKER_ROWS + sorted(k for k in markers if k not in MARKER_ROWS)
        with box:
            for key in keys:
                value = markers.get(key, "")
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.checkbox(key, value=value is not None,
                                on_change=lambda e, k=key: include(k, e.value)).classes("w-56").mark(
                        f"marker-{key}-include")
                    text_field("Value", value or "", lambda text, k=key: set_value(k, text),
                               mark=f"marker-{key}-value", placeholder=hints.get(key, "template value"))

    def both() -> None:
        render()
        after()

    def include(key: str, on: bool) -> None:
        def change(p: Project) -> None:
            if not on:
                p.settings.markers[key] = None  # the line is removed from every config
            elif key in p.settings.markers and p.settings.markers[key] is None:
                del p.settings.markers[key]  # back to the template's line

        message = frame.save(change, then=both)
        if message:
            ui.notify(message, type="negative")

    def set_value(key: str, text: str) -> Optional[str]:
        if text.strip():
            return frame.save(lambda p: set_parameter(p.settings, key, text), then=both)
        if frame.session.project.settings.markers.get(key) is not None:
            return frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        return None

    render()
    return render


def _placeholders(frame: ProjectFrame, after: Callable[[], None]) -> Callable[[], None]:
    ui.label("Placeholders").classes("text-lg")
    ui.label("Any other SU2 option, written into every config.").classes("text-xs text-grey-8")
    box = ui.column().classes("w-full gap-2")

    def render() -> None:
        box.clear()
        with box:
            for key, value in sorted(frame.session.project.settings.overrides.items()):
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label(key).classes("w-48")
                    text_field("Value", value,
                               lambda text, k=key: frame.save(
                                   lambda p: set_parameter(p.settings, k, text), then=after),
                               mark=f"override-{key}-value")
                    ui.button(icon="delete", on_click=lambda k=key: forget(k)).props("flat").mark(
                        f"override-{key}-delete")

    def both() -> None:
        render()
        after()

    def forget(key: str) -> None:
        message = frame.save(lambda p: unset_parameter(p.settings, key), then=both)
        if message:
            ui.notify(message, type="negative")

    with ui.row().classes("w-full items-center no-wrap"):
        key_box = ui.input("Option").classes("w-48").mark("override-new-key")
        value_box = ui.input("Value").classes("grow").mark("override-new-value")
        ui.button("Add", on_click=lambda: add()).mark("override-add")
    error = ui.label("").classes("text-negative text-xs").mark("override-add-error")

    def add() -> None:
        name = (key_box.value or "").strip().upper()

        def change(p: Project) -> None:
            if name.startswith(MARKER_PREFIX):
                raise ProjectError("Use the Markers section for MARKER_ options")
            set_parameter(p.settings, name, value_box.value or "")

        message = frame.save(change, then=both)
        error.text = message or ""
        if message is None:
            key_box.value = ""
            value_box.value = ""

    render()
    return render


def _insert(frame: ProjectFrame, option: RefOption, holders: dict, after: Callable[[], None]) -> Optional[str]:
    settings = frame.session.project.settings
    if option.key.startswith(MARKER_PREFIX):
        if settings.markers.get(option.key):
            return f"{option.key} is already in Markers"
        target, place = holders["markers"], "Markers"
    else:
        if option.key in settings.overrides:
            return f"{option.key} is already in Placeholders"
        target, place = holders["overrides"], "Placeholders"

    def both() -> None:
        target()
        after()

    message = frame.save(lambda p: set_parameter(p.settings, option.key, option.default_value), then=both)
    return message or f"Added {option.key} to {place}"
```

- [ ] **Step 4: Update `aerosuite/web/app.py`**

Replace

```python
    from .pages import config, projects, settings, setup, sweep

    projects.register()
    setup.register()
    config.register()
    settings.register()
    sweep.register()
```

with

```python
    from .pages import aircraft, config, projects, setup, sweep

    projects.register()
    setup.register()
    config.register()
    aircraft.register()
    sweep.register()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_aircraft.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed. `test_web_settings.py` has been removed.

```bash
git add aerosuite/web/pages/aircraft.py aerosuite/web/app.py tests/web/test_web_aircraft.py
git commit -m "feat(web): replace the Settings page with the profile-driven Aircraft page"
```

---

### Task 8: Setup: profile, "Apply defaults", "Save as profile", sweep switch

**Files:**
- Modify: `aerosuite/web/pages/setup.py`
- Test: `tests/web/test_web_setup_study.py`

**Interfaces:**
- Consumes:
  - `profiles.list_profiles`, `load_profile`, `apply_profile`, `save_profile` and `user_profiles_dir` (Task 3)
  - `cfg.build_cases`
- Produces these Setup markers:
  - `setup-profile` and `setup-profile-problem`
  - `setup-apply-profile`, `confirm-apply` and `confirm-cancel`
  - `setup-save-profile`, `profile-id`, `profile-name`, `profile-description`, `profile-save`, `profile-replace`, `profile-cancel` and `profile-error`
  - `setup-sweep`

- [ ] **Step 1: Write the failing tests `tests/web/test_web_setup_study.py`**

```python
from nicegui.testing import User

from aerosuite.engine.profiles import PROFILE_FILE, user_profiles_dir
from aerosuite.engine.project import open_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def _open(user, project_dir):
    await user.open(project_url("setup", project_dir))


async def test_choose_a_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-profile").set_value("x07")
    assert open_project(project_dir).profile == "x07"
    await user.should_see(marker="badge-aircraft-done")
    with user:
        _element(user, "setup-profile").set_value("")
    assert open_project(project_dir).profile is None


async def test_apply_profile_defaults_asks_first(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-profile").set_value("x07")
    user.find(marker="setup-apply-profile").click()
    await user.should_see(marker="confirm-apply")
    user.find(marker="confirm-cancel").click()
    await user.should_not_see(marker="confirm-apply")
    assert open_project(project_dir).settings.reference.ref_area is None
    user.find(marker="setup-apply-profile").click()
    await user.should_see(marker="confirm-apply")
    user.find(marker="confirm-apply").click()
    await user.should_see("Applied X07 defaults")
    assert open_project(project_dir).settings.reference.ref_area == 16.213


async def test_save_as_profile(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="setup-save-profile").click()
    user.find(marker="profile-id").type("my_jet")
    user.find(marker="profile-name").type("My jet")
    user.find(marker="profile-save").click()
    await user.should_see("Saved profile My jet")
    assert (user_profiles_dir() / "my_jet" / PROFILE_FILE).is_file()
    assert open_project(project_dir).profile == "my_jet"

    user.find(marker="setup-save-profile").click()
    user.find(marker="profile-id").type("my_jet")
    user.find(marker="profile-name").type("Renamed")
    user.find(marker="profile-save").click()
    await user.should_see("already exists")
    user.find(marker="profile-replace").click()
    await user.should_see("Saved profile Renamed")


async def test_sweep_switch(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    with user:
        _element(user, "setup-sweep").set_value(False)
    project = open_project(project_dir)
    assert project.sweep.enabled is False and [c.name for c in project.cases] == ["study"]
    await user.should_not_see(marker="badge-sweep-done")
    with user:
        _element(user, "setup-sweep").set_value(True)
    assert len(open_project(project_dir).cases) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_web_setup_study.py -v`
Expected: FAIL (markers not found).

- [ ] **Step 3: Add the study section to `aerosuite/web/pages/setup.py`**

Add these imports:

```python
from ...engine.cfg import build_cases
from ...engine.errors import ProjectError
from ...engine.profiles import apply_profile, list_profiles, load_profile, save_profile
```

In `setup_page`'s `body()`, add `_study_section(frame)` as the first call, before `_mesh_section(frame)`.

Add this function before `_path_setter`:

```python
def _study_section(frame: ProjectFrame) -> None:
    project = frame.session.project
    profiles, problems = list_profiles()
    ui.label("Study").classes("text-lg")
    for problem in problems:
        ui.label(f"Profile skipped: {problem}").classes("text-warning text-xs").mark("setup-profile-problem")
    options = {"": "None (general case)", **{p.id: p.name for p in profiles}}
    if project.profile and project.profile not in options:
        options[project.profile] = f"{project.profile} (not found)"

    def choose(value) -> None:
        message = frame.save(lambda p: setattr(p, "profile", value or None))
        if message:
            ui.notify(message, type="negative")

    with ui.row().classes("w-full items-center no-wrap gap-4"):
        select = ui.select(options, value=project.profile or "", label="Aircraft profile",
                           on_change=lambda e: choose(e.value)).classes("w-64").mark("setup-profile")
        ui.button("Apply profile defaults", on_click=lambda: apply_defaults()).props("flat").mark(
            "setup-apply-profile")
        ui.button("Save as profile…", on_click=lambda: save_as()).props("flat").mark("setup-save-profile")

    def sweep(on: bool) -> None:
        def change(p) -> None:
            p.sweep.enabled = on
            p.cases = build_cases(p)

        message = frame.save(change)
        if message:
            ui.notify(message, type="negative")

    ui.switch("Sweep (Mach / alpha / beta cases)", value=project.sweep.enabled,
              on_change=lambda e: sweep(e.value)).mark("setup-sweep")

    async def apply_defaults() -> None:
        profile_id = frame.session.project.profile
        if not profile_id:
            ui.notify("Choose a profile first", type="warning")
            return
        try:
            profile = load_profile(profile_id)
        except ProjectError as exc:
            ui.notify(str(exc), type="negative")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Overwrite the settings {profile.name} defines with its defaults?")
            with ui.row():
                ui.button("Apply", on_click=lambda: dialog.submit(True)).mark("confirm-apply")
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat").mark("confirm-cancel")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        message = frame.save(lambda p: apply_profile(frame.session.directory, p, profile))
        ui.notify(message or f"Applied {profile.name} defaults", type="negative" if message else "positive")

    async def save_as() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Save this project's template and settings as a profile").classes("text-lg")
            id_box = ui.input("Profile id (letters, digits, - and _)").classes("w-full").mark("profile-id")
            name_box = ui.input("Name").classes("w-full").mark("profile-name")
            description_box = ui.input("Description").classes("w-full").mark("profile-description")
            error = ui.label("").classes("text-negative text-xs").mark("profile-error")
            with ui.row():
                ui.button("Save", on_click=lambda: attempt(False)).mark("profile-save")
                replace = ui.button("Replace existing", on_click=lambda: attempt(True)).mark("profile-replace")
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat").mark("profile-cancel")
            replace.set_visibility(False)

        def attempt(overwrite: bool) -> None:
            try:
                saved = save_profile(frame.session.directory, frame.session.project,
                                     (id_box.value or "").strip(), name_box.value or "",
                                     description_box.value or "", overwrite=overwrite)
            except ProjectError as exc:
                error.text = str(exc)
                replace.set_visibility("already exists" in str(exc))
                return
            dialog.submit(saved)

        saved = await dialog
        dialog.delete()
        if saved is None:
            return
        # Show the new profile in the dropdown and select it; choose() saves project.profile.
        select.set_options({**select.options, saved.id: saved.name}, value=saved.id)
        if frame.session.project.profile != saved.id:
            choose(saved.id)
        ui.notify(f"Saved profile {saved.name}", type="positive")
```

The "Save as profile" dialog writes only the user's profile folder, through the engine's `save_profile`. The project's own files change only through `frame.save`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_setup_study.py tests/web/test_web_setup.py -v`
Expected: all passed.

- [ ] **Step 5: Run the full suite and commit**

Run: `uv run pytest`
Expected: all passed.

```bash
git add aerosuite/web/pages/setup.py tests/web/test_web_setup_study.py
git commit -m "feat(web): choose, apply and save aircraft profiles and switch the sweep in Setup"
```

---

### Task 9: New-study start screen, README, final checks

**Files:**
- Modify: `aerosuite/web/pages/projects.py` (the new-project form), `tests/web/test_web_projects.py` (two existing tests), `README.md`
- Test: `tests/web/test_web_new_study.py`

**Interfaces:**
- Consumes: `study.create_study` and `profiles.list_profiles` (Task 3).
- Produces these Projects markers:
  - `new-kind-general` and `new-kind-aircraft` (cards), `new-profile`
  - `new-parent`, `new-browse`, `new-name`
  - `new-template`, `new-template-browse`, `new-use-reference`
  - `new-mesh`, `new-mesh-browse`
  - `new-create`, `new-error`, `profile-problem`

- [ ] **Step 1: Write the failing tests `tests/web/test_web_new_study.py`**

```python
from nicegui.testing import User

from aerosuite.engine.project import TEMPLATE_FILE, open_project


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_general_case_from_the_reference(user: User, tmp_path):
    await user.open("/")
    assert not _element(user, "new-profile").visible
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("nozzle")
    with user:
        _element(user, "new-use-reference").set_value(True)
    user.find(marker="new-create").click()
    await user.should_see(marker="project-name")
    project = open_project(tmp_path / "nozzle")
    assert project.sweep.enabled is False and project.profile is None
    assert "SOLVER=" in (tmp_path / "nozzle" / TEMPLATE_FILE).read_text(encoding="utf-8")


async def test_aircraft_study_needs_a_template_when_the_profile_has_none(user: User, tmp_path):
    await user.open("/")
    user.find(marker="new-kind-aircraft").click()
    assert _element(user, "new-profile").visible
    with user:
        _element(user, "new-profile").set_value("x07")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("x07_a")
    user.find(marker="new-create").click()
    await user.should_see("X07 has none")
    assert not (tmp_path / "x07_a").exists()


async def test_aircraft_study(user: User, tmp_path):
    template = tmp_path / "x07.cfg"
    template.write_text("MACH_NUMBER= 0.7\n")
    mesh = tmp_path / "x07.su2"
    mesh.write_text("MARKER_TAG= Wing\n")
    await user.open("/")
    user.find(marker="new-kind-aircraft").click()
    with user:
        _element(user, "new-profile").set_value("x07")
    user.find(marker="new-parent").type(str(tmp_path))
    user.find(marker="new-name").type("x07_b")
    user.find(marker="new-template").type(str(template))
    user.find(marker="new-mesh").type(str(mesh))
    user.find(marker="new-create").click()
    await user.should_see(marker="badge-aircraft-done")
    project = open_project(tmp_path / "x07_b")
    assert project.profile == "x07" and project.sweep.enabled is True
    assert project.settings.reference.ref_area == 16.213
    assert project.mesh.markers == ["Wing"]
```

- [ ] **Step 2: Update the two existing new-project tests in `tests/web/test_web_projects.py`**

In `test_create_a_new_project`, insert these lines before `user.find(marker="new-create").click()`. A general case now needs a template:

```python
    with user:
        next(iter(user.find(marker="new-use-reference").elements)).set_value(True)
```

In `test_new_project_checks_its_inputs`, leave everything as it is. Its name and parent checks run before the template check.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_web_new_study.py tests/web/test_web_projects.py -v`
Expected: FAIL (new markers not found).

- [ ] **Step 4: Replace `_new_form` in `aerosuite/web/pages/projects.py`**

Add these imports:

```python
from ...engine.profiles import list_profiles
from ...engine.study import create_study
```

Replace the whole `_new_form` function with:

```python
def _kind_card(title: str, text: str, mark: str, on_choose) -> ui.card:
    card = ui.card().classes("w-72 cursor-pointer").mark(mark)
    card.on("click", lambda _: on_choose())
    with card:
        ui.label(title).classes("text-base font-medium")
        ui.label(text).classes("text-xs text-grey-8")
    return card


def _path_row(label: str, mark: str, title: str, mode: str, suffixes=()) -> ui.input:
    with ui.row().classes("w-full items-center no-wrap"):
        box = ui.input(label).classes("grow").mark(mark)

        async def browse() -> None:
            chosen = await pick_path(title, mode=mode, suffixes=suffixes)
            if chosen is not None:
                box.value = str(chosen)

        ui.button("Browse", on_click=browse).props("flat").mark(
            "new-browse" if mark == "new-parent" else f"{mark}-browse")
    return box


def _new_form() -> None:
    ui.label("New project").classes("text-lg")
    profiles, problems = list_profiles()
    for problem in problems:
        ui.label(f"Profile skipped: {problem}").classes("text-warning text-xs").mark("profile-problem")
    state = {"kind": "general"}

    def choose(kind: str) -> None:
        state["kind"] = kind
        general.classes(add="border-2 border-primary" if kind == "general" else "",
                        remove="border-2 border-primary" if kind != "general" else "")
        aircraft.classes(add="border-2 border-primary" if kind == "aircraft" else "",
                         remove="border-2 border-primary" if kind != "aircraft" else "")
        profile.set_visibility(kind == "aircraft")
        use_reference.set_visibility(kind == "general")

    with ui.row().classes("gap-4"):
        general = _kind_card("General case", "One config from a template, edited as text with SU2's "
                             "reference beside it. One case.", "new-kind-general", lambda: choose("general"))
        aircraft = _kind_card("Aircraft study", "Aircraft Aero form with profile defaults, "
                              "placeholders and a Mach/alpha/beta sweep.", "new-kind-aircraft",
                              lambda: choose("aircraft"))
    profile = ui.select({p.id: p.name for p in profiles}, label="Aircraft profile",
                        value=profiles[0].id if profiles else None).classes("w-64").mark("new-profile")
    parent = _path_row("Parent folder", "new-parent", "Choose the parent folder", "folder")
    name = ui.input("Project name").classes("w-full").mark("new-name")
    template = _path_row("Template (.cfg)", "new-template", "Choose the template", "file", (".cfg",))
    use_reference = ui.checkbox("Start from SU2's config_template.cfg").mark("new-use-reference")
    mesh = _path_row("Mesh (.su2, optional)", "new-mesh", "Choose the mesh", "file", (".su2", ".cgns"))
    ui.button("Create", on_click=lambda: create()).mark("new-create")
    error = ui.label("").classes("text-negative text-sm").mark("new-error")
    choose("general")

    def create() -> None:
        parent_text = (parent.value or "").strip()
        name_text = (name.value or "").strip()
        if not parent_text or not name_text:
            error.text = "Choose a parent folder and a name"
            return
        if not _is_plain_name(name_text):
            error.text = "Choose a plain folder name (no '.', '..', drive or separators)"
            return
        if not Path(parent_text).is_dir():
            error.text = f"Parent folder not found: {parent_text}"
            return
        aircraft_study = state["kind"] == "aircraft"
        if aircraft_study and not profile.value:
            error.text = "Choose an aircraft profile"
            return
        template_text = (template.value or "").strip()
        mesh_text = (mesh.value or "").strip()
        target = Path(parent_text) / name_text
        try:
            create_study(
                target,
                profile_id=profile.value if aircraft_study else None,
                template=Path(template_text) if template_text else None,
                use_reference_template=bool(use_reference.value) and not aircraft_study,
                mesh=Path(mesh_text) if mesh_text else None,
            )
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        _go_to(target)
```

If clicking a `ui.card` does not dispatch its `click` handler under NiceGUI's simulated user, put a "Choose" button (`.mark(mark)`) inside each card, wired to the same handler, and record the deviation. The tests address the marker either way.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_new_study.py tests/web/test_web_projects.py -v`
Expected: all passed.

- [ ] **Step 6: Update the README "Web UI" section**

In `README.md`, replace the paragraph that starts `Pages so far:` with:

```markdown
Pages:
- **Projects**: recent, open, and **new project**. First choose a *General case* (one config, no sweep) or an *Aircraft study* (pick a profile such as X07; sweep on).
- **Setup**: mesh, template, run settings. The **aircraft profile** is chosen here, with *Apply profile defaults* and *Save as profile…* (this saves your template and settings for the next study of that aircraft). The **sweep on/off** switch is here too.
- **Config**: your config as text, with a live preview. **SU2's reference** is beside it: search any option, then click *Insert*, or use *Find* in the full file. With the sweep off, *Generate config* is here.
- **Aircraft** (with a profile): the Aircraft Aero form (dropdowns for scheme, MUSCL and turbulence; the four marker lines; placeholders), with the same reference panel.
- **Sweep** (sweep on): Mach/α/β ranges, naming, restarts, checks, Generate.

Every field saves as soon as you leave it; invalid values are shown in red and not saved. Run, Monitor and Results arrive in phase 3b; until then use `aerosuite run / status / summarize`.

The bundled X07 profile has the desktop app's form defaults but no template. On the workstation, create an X07 study with your template, then use *Save as profile…* with the id `x07` to keep it.
```

- [ ] **Step 7: Run the full suite and the boundary checks**

Run: `uv run pytest -q`
Expected: all passed.

Run: `git grep -nE "nicegui|starlette|aerosuite\.web|from \.\.web|typer|aerosuite\.cli" -- aerosuite/engine ; echo "exit=$?"`
Expected: no matches, `exit=1`.

Run: `git grep -nE "aerosuite\.(cli|core|ui)|from \.\.\.?(cli|core|ui)|PyQt5|matplotlib|typer" -- aerosuite/web ; echo "exit=$?"`
Expected: no matches, `exit=1`.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/web/pages/projects.py tests/web/test_web_new_study.py tests/web/test_web_projects.py README.md
git commit -m "feat(web): add the new-study start screen and document config modes"
```

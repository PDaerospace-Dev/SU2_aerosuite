# Run and Monitor (Phase 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the web UI's Run and Monitor pages — submit all or selected cases (optionally continuing from their own last solution), cancel, see per-case status and job history, and watch one case's residuals, coefficients and solver log live — and reduce the per-case restart options to `none`, `previous` and `custom`.

**Architecture:** The engine gains a restart-file lookup (`engine/restarts.py`), a job-input builder that writes each job's own configs and `run_control.txt` (`engine/jobs/plan.py`), subset submits in `LocalRunner`, and a per-case overview across jobs (`engine/jobs/overview.py`). The web layer gets one server-wide `JobWatcher` (`web/jobs.py`, no NiceGUI) that owns the single `LocalRunner`, throttles refreshes to one per 2 s per project and keeps incremental history buffers; the Run and Monitor pages poll it on 2 s timers.

**Tech Stack:** Python 3.12, pydantic v2, pandas, psutil (engine); NiceGUI 3.17 with `ui.echart` (web); pytest + NiceGUI's simulated `user` fixture; `tests/fixtures/fake_sweep.py` stands in for SU2.

**Spec:** `docs/superpowers/specs/2026-09-25-web-run-monitor-design.md` (binding). Base specs: `docs/superpowers/specs/2026-09-21-aerosuite-web-architecture-design.md`, `docs/superpowers/specs/2026-09-23-web-config-modes-design.md`.

## Global Constraints

- AeroSuite runs on Python ≥ 3.10 in the uv Python 3.12 environment. Run every command from the repository root with `uv run ...`.
- **Import boundaries:** `aerosuite/engine/` never imports NiceGUI, Typer, starlette, PyQt5, matplotlib, or anything from `aerosuite/web`, `aerosuite/cli` or `aerosuite/ui`. `aerosuite/web/` imports only the engine, NiceGUI, pydantic, starlette and the standard library — **not pandas** (history frames come from engine objects; web code only calls their methods).
- **Writes in `web/`:** pages never write project files directly; every change goes through `ProjectFrame.save` / `ProjectSession.apply` or an engine function.
- **NiceGUI 3.17 refresh timing:** `refreshable.refresh()` is fire-and-forget. Parts that tests read synchronously right after a change are rebuilt synchronously: clear a container, then build again (see `aerosuite/web/pages/sweep.py`).
- **Code style:** no `from __future__ import annotations` in `aerosuite/web/pages/*`, `layout.py`, `fields.py`, `picker.py`, `checks.py`, `preview.py`, `reference_panel.py` or `aerosuite/cli/*`.
- **Restart options:** exactly `none`, `previous`, `custom`. `custom`'s `restart_ref` is an absolute path to a restart file or a case folder. `schema_version` is 3.
- **Sweep script:** `aerosuite/resources/aoa_sweep_v8.py` is not modified (it must stay Python 3.7 compatible). AeroSuite writes only `none`, `previous`, `from_case` (only for a case running earlier in the same job) and `custom` control lines, and never passes `-r`.
- **Job inputs:** every submit runs from `jobs/<id>/configs/` (the selected cases' `.cfg` files + `run_control.txt`). `RESTART_SOL= YES` is written only into the job's copy of a continued case. `template.cfg` and `configs/` are never modified by a submit.
- **Polling:** the Run and Monitor pages refresh every 2 s while something is running and do not poll otherwise; `JobWatcher` refreshes an active job at most once per 2 s per project.
- **Monitor:** one case at a time; no overlay. Residuals are SU2's `rms[...]` columns, which are already log10 values, so they are drawn on a linear axis named "log10 residual".
- **Results** stays greyed in the sidebar. **No startup token** in 3b.
- **Tests:** pass on Windows and Linux; no SU2, MPI, display or real browser. Page tests use the simulated `user` fixture and find elements by `.mark(...)` markers.

## Review Focus

- A `custom` restart path containing a comma (run_control.txt separates fields with commas) → preflight error naming the case, not a silently truncated path. Test: Task 1.
- The project's cases change on disk (another tab or the CLI rebuilds the sweep) while the Run page is open → the table follows the new cases after the reload and ticks for vanished cases are dropped. Test: Task 7.
- A long history (tens of thousands of iterations) → each chart series is thinned to ≤ 2000 points and still ends at the last iteration. Test: Task 8.
- A history column holding NaN (SU2 writes `nan` when a run blows up) → that point is a gap (`None`), the page still renders. Test: Task 8.
- A job log of many megabytes → the log tail reads only the last 64 KB and still returns the last 40 lines. Test: Task 6.

---

### Task 1: Three restart options (schema 3)

**Files:**
- Create: `aerosuite/engine/restarts.py`
- Modify: `aerosuite/engine/models.py`, `aerosuite/engine/project.py`, `aerosuite/engine/cfg.py`, `aerosuite/engine/preflight.py`, `aerosuite/engine/jobs/local.py`, `aerosuite/web/status.py:69`, `aerosuite/web/pages/sweep.py`, `aerosuite/cli/project_cmds.py:189`
- Test: `tests/engine/test_restarts.py` (new), `tests/engine/test_project.py`, `tests/engine/test_single_case.py`, `tests/engine/test_cfg.py`, `tests/engine/test_preflight.py`, `tests/engine/test_preflight_sweep.py`, `tests/web/test_web_sweep.py`

**Interfaces:**
- Produces (`aerosuite/engine/restarts.py`): `RUNS_DIR = "runs"`; `DEFAULT_RESTART_NAME = "restart_flow"`; `find_restart_file(folder: Path) -> Optional[Path]`; `restart_file(project_dir: Path, case_name: str) -> Optional[Path]`; `own_case_of(project_dir: Path, ref: str, case_names: Iterable[str]) -> Optional[str]`.
- Produces: `models.RestartOption = Literal["none", "previous", "custom"]`; `models.SCHEMA_VERSION = 3`; `RunSettings` without `initial_restart`.
- Produces: `project.migrate(data: dict, directory: Optional[Path] = None) -> dict`; `project.parse_project(text: str, source: str = PROJECT_FILE, directory: Optional[Path] = None) -> Project`; every `MIGRATIONS` step is `step(data: dict, directory: Optional[Path]) -> dict`.
- Produces: `preflight.sweep_problems(project: Project, project_dir: Optional[Path] = None) -> list[Problem]`.
- `jobs/local.py` keeps exporting `RUNS_DIR` (now imported from `restarts`).

- [ ] **Step 1: Write the failing tests for the restart lookup — `tests/engine/test_restarts.py`**

```python
from aerosuite.engine.restarts import RUNS_DIR, find_restart_file, own_case_of, restart_file


def test_restart_file_as_written_then_dat_then_csv(tmp_path):
    folder = tmp_path / "case"
    folder.mkdir()
    assert find_restart_file(folder) is None
    (folder / "restart_flow.csv").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow.csv"
    (folder / "restart_flow.dat").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow.dat"
    (folder / "restart_flow").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow"


def test_restart_filename_comes_from_the_case_cfg(tmp_path):
    folder = tmp_path / "M0p8_a0_b0"
    folder.mkdir()
    (folder / "M0p8_a0_b0.cfg").write_text("SOLVER= RANS\nRESTART_FILENAME= my_solution\n")
    (folder / "restart_flow.dat").write_text("not this one")
    (folder / "my_solution.dat").write_text("x")
    assert find_restart_file(folder) == folder / "my_solution.dat"


def test_missing_folder_and_a_project_case(tmp_path):
    assert find_restart_file(tmp_path / "nope") is None
    assert restart_file(tmp_path, "M0p8_a0_b0") is None
    folder = tmp_path / RUNS_DIR / "M0p8_a0_b0"
    folder.mkdir(parents=True)
    (folder / "restart_flow.dat").write_text("x")
    assert restart_file(tmp_path, "M0p8_a0_b0") == folder / "restart_flow.dat"


def test_own_case_of(tmp_path):
    names = ["M0p8_a0_b0", "M0p8_a2_b0"]
    runs = tmp_path / RUNS_DIR
    assert own_case_of(tmp_path, str(runs / "M0p8_a0_b0"), names) == "M0p8_a0_b0"
    assert own_case_of(tmp_path, str(runs / "M0p8_a2_b0" / "restart_flow.dat"), names) == "M0p8_a2_b0"
    assert own_case_of(tmp_path, str(runs / "other"), names) is None
    assert own_case_of(tmp_path, str(tmp_path / "elsewhere" / "M0p8_a0_b0"), names) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/engine/test_restarts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aerosuite.engine.restarts'`

- [ ] **Step 3: Create `aerosuite/engine/restarts.py`**

```python
"""Restart files: where a case's solution is, and whether a path points into this project's runs."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

RUNS_DIR = "runs"
DEFAULT_RESTART_NAME = "restart_flow"  # SU2's default RESTART_FILENAME
_RESTART_RE = re.compile(r"^\s*RESTART_FILENAME\s*=\s*(\S+)", re.MULTILINE)


def _restart_name(folder: Path) -> str:
    """RESTART_FILENAME from the case's .cfg (the sweep script copies it into the case folder)."""
    configs = sorted(folder.glob("*.cfg"), key=lambda path: path.stem != folder.name)  # own cfg first
    for cfg in configs:
        try:
            match = _RESTART_RE.search(cfg.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if match:
            return Path(match.group(1)).name
    return DEFAULT_RESTART_NAME


def find_restart_file(folder: Path) -> Optional[Path]:
    """The restart file SU2 wrote in a case folder: the name as written, then with .dat, then .csv."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    name = _restart_name(folder)
    for candidate in (name, f"{name}.dat", f"{name}.csv"):
        path = folder / candidate
        if path.is_file():
            return path
    return None


def restart_file(project_dir: Path, case_name: str) -> Optional[Path]:
    """The restart file from the case's last run in this project, or None."""
    return find_restart_file(Path(project_dir) / RUNS_DIR / case_name)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def own_case_of(project_dir: Path, ref: str, case_names: Iterable[str]) -> Optional[str]:
    """X when `ref` is this project's runs/X folder or a file directly inside it (X a case name)."""
    runs = (Path(project_dir) / RUNS_DIR).resolve()
    path = Path(ref).resolve()
    names = set(case_names)
    for candidate in (path, path.parent):
        if candidate.name in names and _same(candidate.parent, runs):
            return candidate.name
    return None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/engine/test_restarts.py -q`
Expected: 4 passed

- [ ] **Step 5: Write the failing migration test — add to `tests/engine/test_project.py`**

```python
def test_schema_2_restarts_migrate_to_three_options(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 2
    data["run"]["initial_restart"] = "/data/init.dat"
    data["cases"] = [
        {"name": "a", "mach": 0.8, "alpha": 0, "beta": 0, "restart": "initial"},
        {"name": "b", "mach": 0.8, "alpha": 2, "beta": 0, "restart": "from_case", "restart_ref": "a"},
        {"name": "c", "mach": 0.8, "alpha": 4, "beta": 0, "restart": "from_case", "restart_ref": "a"},
        {"name": "d", "mach": 0.8, "alpha": 6, "beta": 0, "restart": "previous"},
    ]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 3
    assert [(c.restart, c.restart_ref) for c in project.cases] == [
        ("custom", "/data/init.dat"),
        ("previous", None),
        ("custom", str((tmp_path / "runs" / "a").resolve())),
        ("previous", None),
    ]
    assert "initial_restart" not in project.run.model_dump()


def test_initial_without_a_file_migrates_to_custom_without_a_path(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 2
    data["cases"] = [{"name": "a", "mach": 0.8, "alpha": 0, "beta": 0, "restart": "initial"}]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    assert [(c.restart, c.restart_ref) for c in open_project(tmp_path).cases] == [("custom", None)]
```

In the same file, the three tests that monkeypatch the schema version must move one version up (the real version is now 3). Replace them with:

```python
def test_migrations_run_in_order(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)

    def v3_to_v4(data, directory):
        data["name"] = data["name"] + "-migrated"
        return data

    monkeypatch.setattr(project_mod, "MIGRATIONS", {3: v3_to_v4})
    opened = open_project(tmp_path)
    assert opened.name.endswith("-migrated")
    assert opened.schema_version == 4
```

```python
def test_migrate_rejects_missing_migration(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(project_mod, "MIGRATIONS", {})
    with pytest.raises(ProjectError, match="No migration"):
        open_project(tmp_path)
```

```python
def test_migration_error_propagates(tmp_path, monkeypatch):
    from aerosuite.engine.project import migrate

    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)

    def broken_migration(data, directory):
        raise KeyError("boom")

    monkeypatch.setattr(project_mod, "MIGRATIONS", {3: broken_migration})
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    with pytest.raises(KeyError, match="boom"):
        migrate(data)
```

In `tests/engine/test_single_case.py::test_schema_1_projects_upgrade_to_sweep_on_without_profile`, replace `assert project.schema_version == 2` with:

```python
    assert project.schema_version == 3
```

- [ ] **Step 6: Run the migration tests to verify they fail**

Run: `uv run pytest tests/engine/test_project.py tests/engine/test_single_case.py -q`
Expected: FAIL — the new migration tests fail (`schema_version == 2`, `initial`/`from_case` still accepted), the version-moved tests fail on the migration signature.

- [ ] **Step 7: Change the model — `aerosuite/engine/models.py`**

Replace `SCHEMA_VERSION = 2` with `SCHEMA_VERSION = 3`. Replace the restart option, the `Case` comment and `RunSettings`:

```python
RestartOption = Literal["none", "previous", "custom"]


class Case(BaseModel):
    name: str
    mach: float
    alpha: float
    beta: float
    restart: RestartOption = "none"
    # custom: absolute path of a restart file, or of a case folder holding one
    restart_ref: Optional[str] = None


class RunSettings(BaseModel):
    partitions: int = Field(default=1, ge=1)
    sweep_script: str = ""  # empty = bundled resources/aoa_sweep_v8.py
    sweep_python: str = "python3"  # must be able to import SU2
```

- [ ] **Step 8: Add the migration — `aerosuite/engine/project.py`**

Add `from .restarts import RUNS_DIR` to the imports. Give `_v1_to_v2` the directory parameter, add `_v2_to_v3`, and register it:

```python
def _v1_to_v2(data: dict, directory: Optional[Path]) -> dict:
    """Schema 2 adds aircraft profiles and a sweep on/off switch; old projects keep their sweep."""
    data.setdefault("profile", None)
    sweep = data.setdefault("sweep", {})
    if isinstance(sweep, dict):
        sweep.setdefault("enabled", True)
    return data


def _v2_to_v3(data: dict, directory: Optional[Path]) -> dict:
    """Schema 3 keeps three restart options: none, previous and custom (a restart file or case folder).

    `initial` becomes `custom` with the old run.initial_restart; `from_case X` becomes `previous`
    when X is the case just before it, else `custom` pointing at this project's runs/X/.
    """
    run = data.get("run")
    initial = run.pop("initial_restart", None) if isinstance(run, dict) else None
    cases = data.get("cases")
    if not isinstance(cases, list):
        return data
    names = [case.get("name") if isinstance(case, dict) else None for case in cases]
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        option = case.get("restart")
        if option == "initial":
            case["restart"], case["restart_ref"] = "custom", initial
        elif option == "from_case":
            ref = case.get("restart_ref")
            if index > 0 and ref is not None and ref == names[index - 1]:
                case["restart"], case["restart_ref"] = "previous", None
            elif not ref:
                case["restart"], case["restart_ref"] = "custom", None
            else:
                # Without the folder (e.g. text being edited elsewhere) the path stays relative,
                # which preflight reports so the user can fix it.
                folder = Path(directory).resolve() / RUNS_DIR / ref if directory is not None else Path(RUNS_DIR) / ref
                case["restart"], case["restart_ref"] = "custom", str(folder)
    return data


# {from_version: function(data, project folder or None) -> data at from_version + 1}
MIGRATIONS: dict[int, Callable[[dict, Optional[Path]], dict]] = {1: _v1_to_v2, 2: _v2_to_v3}
```

Change `migrate`, `parse_project` and `open_project` to carry the folder:

```python
def migrate(data: dict, directory: Optional[Path] = None) -> dict:
```

and inside its loop replace `data = step(data)` with `data = step(data, directory)`.

```python
def parse_project(text: str, source: str = PROJECT_FILE, directory: Optional[Path] = None) -> Project:
    """Validate project.json text (migrating old schemas) into a Project."""
    try:
        data = json.loads(text.lstrip("﻿"))  # some editors write a UTF-8 BOM
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{source} is not valid JSON: {exc}") from exc
    try:
        return Project.model_validate(migrate(data, directory))
    except ValidationError as exc:
        raise ProjectError(f"{source} is not a valid project:\n{exc}") from exc


def open_project(directory: Path) -> Project:
    path = Path(directory) / PROJECT_FILE
    return parse_project(read_project_text(directory), str(path), directory=Path(directory))
```

In `aerosuite/cli/project_cmds.py` (`edit`), replace `engine_project.parse_project(tmp.read_text(encoding="utf-8-sig"))` with:

```python
                project = engine_project.parse_project(tmp.read_text(encoding="utf-8-sig"), directory=directory)
```

- [ ] **Step 9: Run the migration tests to verify they pass**

Run: `uv run pytest tests/engine/test_project.py tests/engine/test_single_case.py tests/engine/test_models.py -q`
Expected: all passed

- [ ] **Step 10: Write the failing config and preflight tests**

In `tests/engine/test_cfg.py`, replace `test_run_control_text` and `test_generate_configs_requires_restart_reference`:

```python
def test_run_control_text():
    cases = [
        Case(name="c1", mach=0.8, alpha=0, beta=0),
        Case(name="c2", mach=0.8, alpha=2, beta=0, restart="previous"),
        Case(name="c3", mach=0.8, alpha=4, beta=0, restart="custom", restart_ref="/r/restart.dat"),
    ]
    assert run_control_text(cases) == (
        "c1.cfg, none\n"
        "c2.cfg, previous\n"
        "c3.cfg, custom, /r/restart.dat\n"
    )
```

```python
def test_generate_configs_requires_restart_reference(tmp_path):
    (tmp_path / "template.cfg").write_text(TEMPLATE)
    project = _project(alpha=[0.0, 2.5])
    for case in project.cases:
        case.restart, case.restart_ref = "custom", None
    with pytest.raises(GenerationError, match="M0p8_a0_b0.*M0p8_a2p5_b0"):
        generate_configs(tmp_path, project)
```

In `tests/engine/test_preflight.py`, replace `test_restart_problems` and `test_relative_initial_restart_is_an_error` with:

```python
def test_restart_problems(ready_project, tmp_path):
    project_dir, project = ready_project
    a0, a2, a4 = project.cases
    a0.restart = "previous"
    a2.restart, a2.restart_ref = "custom", str(tmp_path / "missing.dat")
    a4.restart, a4.restart_ref = "custom", None
    problems = preflight(project_dir, project, "generate")
    assert any("first case" in m for m in _messages(problems, "warning"))
    errors = _messages(problems, "error")
    assert any("M0p8_a2_b0" in m and "restart path not found" in m for m in errors)
    assert any("M0p8_a4_b0" in m and "needs a restart file or case folder" in m for m in errors)


def test_custom_restart_paths(ready_project, tmp_path):
    project_dir, project = ready_project
    a0, a2, a4 = project.cases
    empty = tmp_path / "empty_case"
    empty.mkdir()
    solved = tmp_path / "solved_case"
    solved.mkdir()
    (solved / "restart_flow.dat").write_text("x")
    a0.restart, a0.restart_ref = "custom", "solution.dat"
    a2.restart, a2.restart_ref = "custom", str(empty)
    a4.restart, a4.restart_ref = "custom", str(solved)
    assert _messages(preflight(project_dir, project, "generate"), "error") == [
        "M0p8_a0_b0: restart path must be an absolute path (the sweep runs from the runs/ folder): solution.dat",
        f"M0p8_a2_b0: no restart file found in folder {empty}",
    ]


def test_custom_restart_path_with_a_comma_is_an_error(ready_project, tmp_path):
    project_dir, project = ready_project
    odd = tmp_path / "run,2"
    odd.mkdir()
    (odd / "restart_flow.dat").write_text("x")
    project.cases[0].restart, project.cases[0].restart_ref = "custom", str(odd)
    errors = _messages(preflight(project_dir, project, "generate"), "error")
    assert errors == [f"M0p8_a0_b0: restart path must not contain a comma (run_control.txt separates "
                      f"fields with commas): {odd}"]


def test_custom_restart_to_a_case_of_this_project_is_allowed_before_it_ran(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "custom"
    project.cases[2].restart_ref = str(project_dir / "runs" / "M0p8_a0_b0")
    assert _messages(preflight(project_dir, project, "generate"), "error") == []
```

In `tests/engine/test_preflight_sweep.py::test_duplicates_and_restarts`, replace the two `from_case` lines and the last assertion:

```python
def test_duplicates_and_restarts(ready_project):
    _, project = ready_project
    project.cases.append(project.cases[0].model_copy())
    project.cases[1].restart = "custom"
    project.cases[1].restart_ref = None
    messages = [m for _, m in _messages(sweep_problems(project))]
    assert any("Duplicate case names" in m for m in messages)
    assert any("M0p8_a2_b0: 'custom' restart needs a restart file or case folder" in m for m in messages)
```

- [ ] **Step 11: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_cfg.py tests/engine/test_preflight.py tests/engine/test_preflight_sweep.py -q`
Expected: FAIL — the preflight tests fail on the new messages (`needs a restart file or case folder`, `restart path not found`, the comma check); the two `test_cfg.py` tests may already pass.

- [ ] **Step 12: Update `aerosuite/engine/cfg.py`**

Replace `run_control_text` with:

```python
def run_control_text(cases: Sequence[Case]) -> str:
    """run_control.txt in the format aoa_sweep_v8.py reads (a job writes its own; see jobs/plan.py)."""
    lines = []
    for case in cases:
        fields = [f"{case.name}.cfg", case.restart]
        if case.restart == "custom":
            fields.append(case.restart_ref or "")
        lines.append(", ".join(fields))
    return "\n".join(lines) + "\n"
```

In `generate_configs`, replace the `no_ref` line with:

```python
    no_ref = [c.name for c in project.cases if c.restart == "custom" and not c.restart_ref]
```

- [ ] **Step 13: Update `aerosuite/engine/preflight.py`**

Change the imports: `from typing import Iterable, Literal, Optional`, `from .models import Case, Project`, and add `from .restarts import find_restart_file, own_case_of`. Replace `_restart_problems` and `sweep_problems`, and pass the folder from `preflight`:

```python
def _custom_problems(case: Case, names: list[str], project_dir: Optional[Path]) -> list[Problem]:
    ref = case.restart_ref
    if not ref:
        return [Problem("error", f"{case.name}: 'custom' restart needs a restart file or case folder")]
    if "," in ref:
        return [Problem("error", f"{case.name}: restart path must not contain a comma "
                                 f"(run_control.txt separates fields with commas): {ref}")]
    path = Path(ref)
    if not path.is_absolute():
        return [_not_absolute(f"{case.name}: restart path", ref)]
    if project_dir is not None and own_case_of(project_dir, ref, names) is not None:
        return []  # a case of this project: its solution may come from the same job
    if path.is_dir():
        if find_restart_file(path) is None:
            return [Problem("error", f"{case.name}: no restart file found in folder {ref}")]
        return []
    if not path.is_file():
        return [Problem("error", f"{case.name}: restart path not found: {ref}")]
    return []


def _restart_problems(project: Project, project_dir: Optional[Path]) -> list[Problem]:
    problems = []
    names = [case.name for case in project.cases]
    for index, case in enumerate(project.cases):
        if case.restart == "previous" and index == 0:
            problems.append(Problem(
                "warning", f"{case.name}: 'previous' restart on the first case will start from scratch"
            ))
        elif case.restart == "custom":
            problems += _custom_problems(case, names, project_dir)
    return problems


def sweep_problems(project: Project, project_dir: Optional[Path] = None) -> list[Problem]:
    """Problems with the sweep and its cases (the Sweep page shows these beside the case table)."""
    problems: list[Problem] = []
    if project.sweep.enabled and not project.sweep.mach:  # build_cases would silently fall back to Mach 0
        problems.append(Problem("error", "No Mach numbers in the sweep"))
    if not project.cases:
        problems.append(Problem("error", "The sweep has no cases"))
    duplicates = find_collisions(case.name for case in project.cases)
    if duplicates:
        problems.append(Problem(
            "error", "Duplicate case names (files would overwrite each other): " + ", ".join(duplicates)
        ))
    problems += _restart_problems(project, project_dir)
    return problems
```

In `preflight`, replace `problems += sweep_problems(project)` with `problems += sweep_problems(project, project_dir)`. In `aerosuite/web/status.py` (`step_badges`), replace `sweep_problems(project)` with `sweep_problems(project, project_dir)`.

In `aerosuite/engine/jobs/local.py`, replace `RUNS_DIR = "runs"` with the import `from ..restarts import RUNS_DIR` (next to the other imports) and delete the two lines that add `-r`:

```python
        if project.run.initial_restart:
            cmd += ["-r", project.run.initial_restart]
```

- [ ] **Step 14: Update the Sweep page — `aerosuite/web/pages/sweep.py`**

Replace `RESTART_OPTIONS` with `RESTART_OPTIONS = ["none", "previous", "custom"]`. In `_sweep_fields`, delete the `text_field("Initial restart file ...", ...)` call (the last statement of the function). In `_case_table`, delete the `earlier` list (`earlier: list[str] = []` and `earlier.append(case.name)`) and replace the `if case.restart == "from_case": ... elif case.restart == "custom": ... else:` block with:

```python
            if case.restart == "custom":
                text_field("Restart file or case folder", case.restart_ref,
                           lambda text, n=case.name: frame.save(
                               lambda p: _change_ref(p, n, text.strip() or None), then=after),
                           mark=f"ref-{case.name}")
            else:
                ui.label("")
```

In `tests/web/test_web_sweep.py`, replace `test_restart_choices` with:

```python
async def test_restart_choices(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await user.should_not_see(marker="initial-restart")
    select = _element(user, "restart-M0p8_a2_b0")
    assert list(select.options) == ["none", "previous", "custom"]
    with user:
        select.set_value("custom")
    assert open_project(project_dir).cases[1].restart == "custom"
    await user.should_see("'custom' restart needs a restart file or case folder")
    solution = tmp_path / "solution.dat"
    solution.write_text("x")
    user.find(marker="ref-M0p8_a2_b0").type(str(solution)).trigger("blur")
    case = open_project(project_dir).cases[1]
    assert (case.restart, case.restart_ref) == ("custom", str(solution))
    await user.should_see(marker="problems-none")
```

- [ ] **Step 15: Run the affected tests, then the full suite**

Run: `uv run pytest tests/engine/test_cfg.py tests/engine/test_preflight.py tests/engine/test_preflight_sweep.py tests/web/test_web_sweep.py -q`
Expected: all passed

Run: `uv run pytest -q`
Expected: all passed. If any other test still uses `initial`, `from_case` or `run.initial_restart` (`grep -rn "from_case\|initial_restart\|\"initial\"" tests aerosuite --include=*.py`), change it to the three options; `aerosuite/resources/aoa_sweep_v8.py` keeps its own `from_case`/`initial` support and is not edited.

- [ ] **Step 16: Commit**

```bash
git add aerosuite/engine/restarts.py aerosuite/engine/models.py aerosuite/engine/project.py aerosuite/engine/cfg.py aerosuite/engine/preflight.py aerosuite/engine/jobs/local.py aerosuite/web/status.py aerosuite/web/pages/sweep.py aerosuite/cli/project_cmds.py tests
git commit -m "feat(engine): three restart options (none, previous, custom) with schema 3 migration"
```

---

### Task 2: Browse for a restart file or case folder on the Sweep page

**Files:**
- Modify: `aerosuite/web/picker.py`, `aerosuite/web/pages/sweep.py`
- Test: `tests/web/test_web_sweep.py`

**Interfaces:**
- Consumes: `RESTART_OPTIONS` and the `custom` row from Task 1.
- Produces: `pick_path(title, *, mode: Literal["file", "folder", "any"], suffixes=(), start=None)` — `"any"` lists files (unfiltered) and folders, offers "Choose this folder", and accepts a pasted file or folder. Marker `ref-browse-<case>` on the Sweep page.

- [ ] **Step 1: Write the failing tests — add to `tests/web/test_web_sweep.py`**

```python
async def test_browse_picks_a_case_folder(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    folder = tmp_path / "earlier_study" / "runs" / "M0p8_a0_b0"
    folder.mkdir(parents=True)
    (folder / "restart_flow.dat").write_text("x")
    await _open(user, project_dir)
    with user:
        _element(user, "restart-M0p8_a2_b0").set_value("custom")
    user.find(marker="ref-browse-M0p8_a2_b0").click()
    await user.should_see(marker="picker-choose-folder")
    user.find(marker="picker-path").type(str(folder))
    user.find(marker="picker-use").click()
    await user.should_see(marker="problems-none")
    case = open_project(project_dir).cases[1]
    assert (case.restart, case.restart_ref) == ("custom", str(folder))


async def test_browse_picks_a_restart_file(user: User, ready_project, tmp_path):
    project_dir, _ = ready_project
    solution = tmp_path / "restart_flow.dat"
    solution.write_text("x")
    await _open(user, project_dir)
    with user:
        _element(user, "restart-M0p8_a2_b0").set_value("custom")
    user.find(marker="ref-browse-M0p8_a2_b0").click()
    user.find(marker="picker-entry-restart_flow.dat").click()  # the picker starts at tmp_path
    await user.should_see(marker="problems-none")
    assert open_project(project_dir).cases[1].restart_ref == str(solution)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/web/test_web_sweep.py -k browse -q`
Expected: FAIL — no `ref-browse-M0p8_a2_b0` marker.

- [ ] **Step 3: Add the `"any"` mode — `aerosuite/web/picker.py`**

Change the signature to `mode: Literal["file", "folder", "any"]`. Show "Choose this folder" for `folder` and `any`:

```python
            if mode in ("folder", "any"):
                ui.button("Choose this folder", on_click=lambda: dialog.submit(here["dir"])).mark(
                    "picker-choose-folder")
```

In `show`, list files for `file` and `any` (filtered by suffix only in `file` mode):

```python
            entries = list_entries(directory, wanted if mode == "file" else ())
```

stays as is, and replace `elif mode == "file":` in the loop with `elif mode in ("file", "any"):`. Replace `use_pasted`'s branches with:

```python
        path = Path(raw).expanduser()
        if path.is_dir():
            if mode in ("folder", "any"):
                dialog.submit(path)
            else:
                show(path)
        elif path.is_file() and (mode == "any" or (mode == "file" and (not wanted or path.name.lower().endswith(wanted)))):
            dialog.submit(path)
        else:
            what = {"folder": "folder", "file": "matching file", "any": "file or folder"}[mode]
            error.text = f"Not a {what}: {path}"
```

- [ ] **Step 4: Add the Browse button — `aerosuite/web/pages/sweep.py`**

Add `from ..picker import pick_path` to the imports. Replace the `custom` branch in `_case_table` with:

```python
            if case.restart == "custom":
                with ui.row().classes("items-start no-wrap w-full"):
                    with ui.column().classes("grow gap-0"):
                        text_field("Restart file or case folder", case.restart_ref,
                                   lambda text, n=case.name: frame.save(
                                       lambda p: _change_ref(p, n, text.strip() or None), then=after),
                                   mark=f"ref-{case.name}")
                    ui.button("Browse", on_click=lambda n=case.name: _browse_ref(frame, n, after)).props(
                        "flat dense").mark(f"ref-browse-{case.name}")
```

and add at the end of the module:

```python
async def _browse_ref(frame: ProjectFrame, name: str, after: Callable[[], None]) -> None:
    chosen = await pick_path("Restart file or case folder", mode="any")
    if chosen is None:
        return
    message = frame.save(lambda p: _change_ref(p, name, str(chosen)), then=after)
    if message:
        ui.notify(message, type="negative")
```

- [ ] **Step 5: Run the Sweep and picker tests**

Run: `uv run pytest tests/web/test_web_sweep.py tests/web/test_web_base.py -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/picker.py aerosuite/web/pages/sweep.py tests/web/test_web_sweep.py
git commit -m "feat(web): browse for a restart file or case folder on the Sweep page"
```

---

### Task 3: Job inputs — `plan_restarts` and `prepare_job`

**Files:**
- Create: `aerosuite/engine/jobs/plan.py`
- Test: `tests/engine/test_job_plan.py`

**Interfaces:**
- Consumes: `restarts.find_restart_file`, `restarts.restart_file`, `restarts.own_case_of`, `restarts.RUNS_DIR` (Task 1); `cfg.CONFIGS_DIR`, `cfg.RUN_CONTROL_FILE`, `cfg.apply_parameters`; `jobs.store.JOBS_DIR`.
- Produces (`aerosuite/engine/jobs/plan.py`):
  - `RESTART_DIR = "restart"`
  - `ControlLine(case: str, option: str, ref: Optional[str] = None, copy_from: Optional[Path] = None)` (frozen dataclass)
  - `RestartPlan(lines: list[ControlLine], warnings: list[str], missing_continue: list[str])` (frozen dataclass)
  - `plan_restarts(project_dir: Path, project: Project, cases: Sequence[str], continue_cases: Iterable[str] = ()) -> RestartPlan` — pure (no writes); raises `JobError` for unknown cases, an empty selection, or a `custom` folder without a restart file.
  - `prepare_job(project_dir: Path, project: Project, job_id: str, cases: Sequence[str], continue_cases: Iterable[str] = ()) -> Path` — returns the resolved `jobs/<id>/configs` folder.
  - Warning text: `"{case}: {other} has no restart file, so {case} starts from scratch"`.

- [ ] **Step 1: Write the failing tests — `tests/engine/test_job_plan.py`**

```python
import pytest

from aerosuite.engine.cfg import CONFIGS_DIR, RUN_CONTROL_FILE, generate_configs
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.plan import plan_restarts, prepare_job
from aerosuite.engine.restarts import RUNS_DIR

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _control(configs):
    return (configs / RUN_CONTROL_FILE).read_text().splitlines()


def _solve(project_dir, name, file="restart_flow.dat"):
    folder = project_dir / RUNS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(f"solution of {name}")
    return folder / file


def test_full_run_writes_every_case_as_its_option(ready_project):
    project_dir, project = ready_project
    project.cases[1].restart = "previous"
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j1", [A0, A2, A4])
    assert configs == project_dir.resolve() / "jobs" / "j1" / CONFIGS_DIR
    assert sorted(p.name for p in configs.glob("*.cfg")) == sorted(f"{n}.cfg" for n in (A0, A2, A4))
    assert _control(configs) == [f"{A0}.cfg, none", f"{A2}.cfg, previous", f"{A4}.cfg, none"]


def test_subset_previous_uses_the_earlier_solution_copied_aside(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "previous"  # A4's previous is A2
    generate_configs(project_dir, project)
    _solve(project_dir, A2)
    configs = prepare_job(project_dir, project, "j2", [A4])
    copy = project_dir.resolve() / "jobs" / "j2" / "restart" / A2 / "restart_flow.dat"
    assert _control(configs) == [f"{A4}.cfg, custom, {copy}"]
    assert copy.read_text() == f"solution of {A2}"
    assert [p.name for p in configs.glob("*.cfg")] == [f"{A4}.cfg"]


def test_reference_to_a_case_running_earlier_in_the_job_uses_its_fresh_solution(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "custom"
    project.cases[2].restart_ref = str(project_dir / RUNS_DIR / A0)
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j3", [A0, A2, A4])
    assert _control(configs) == [f"{A0}.cfg, none", f"{A2}.cfg, none", f"{A4}.cfg, from_case, {A0}.cfg"]
    # when the referenced case runs just before, the script's own `previous` does the same
    configs = prepare_job(project_dir, project, "j3b", [A0, A4])
    assert _control(configs) == [f"{A0}.cfg, none", f"{A4}.cfg, previous"]


def test_reference_without_a_solution_starts_fresh_with_a_warning(ready_project):
    project_dir, project = ready_project
    project.cases[2].restart = "previous"
    generate_configs(project_dir, project)
    plan = plan_restarts(project_dir, project, [A4])
    assert plan.warnings == [f"{A4}: {A2} has no restart file, so {A4} starts from scratch"]
    configs = prepare_job(project_dir, project, "j4", [A4])
    assert _control(configs) == [f"{A4}.cfg, none"]


def test_custom_folder_elsewhere_resolves_to_its_file(ready_project, tmp_path):
    project_dir, project = ready_project
    other = tmp_path / "other" / "M0p5_a0_b0"
    other.mkdir(parents=True)
    (other / "M0p5_a0_b0.cfg").write_text("RESTART_FILENAME= my_restart\n")
    (other / "my_restart.dat").write_text("x")
    project.cases[0].restart, project.cases[0].restart_ref = "custom", str(other)
    generate_configs(project_dir, project)
    configs = prepare_job(project_dir, project, "j5", [A0])
    assert _control(configs) == [f"{A0}.cfg, custom, {other / 'my_restart.dat'}"]


def test_continue_copies_the_solution_and_sets_restart_sol_in_the_job_copy(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    _solve(project_dir, A2)
    configs = prepare_job(project_dir, project, "j6", [A2], continue_cases=[A2])
    copy = project_dir.resolve() / "jobs" / "j6" / "restart" / A2 / "restart_flow.dat"
    assert _control(configs) == [f"{A2}.cfg, custom, {copy}"]
    assert "RESTART_SOL= YES" in (configs / f"{A2}.cfg").read_text()
    assert "RESTART_SOL" not in (project_dir / CONFIGS_DIR / f"{A2}.cfg").read_text()
    assert "RESTART_SOL" not in (project_dir / "template.cfg").read_text()


def test_continue_without_a_solution_fails_and_leaves_nothing(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    with pytest.raises(JobError, match=f"no solution to continue from: {A2}"):
        prepare_job(project_dir, project, "j7", [A2], continue_cases=[A2])
    assert not (project_dir / "jobs" / "j7").exists()


def test_missing_configs_unknown_and_empty_selections(ready_project):
    project_dir, project = ready_project
    with pytest.raises(JobError, match="generate configs first"):
        prepare_job(project_dir, project, "j8", [A0])
    assert not (project_dir / "jobs" / "j8").exists()
    generate_configs(project_dir, project)
    with pytest.raises(JobError, match="Unknown cases: nope"):
        prepare_job(project_dir, project, "j9", ["nope"])
    with pytest.raises(JobError, match="No cases selected"):
        prepare_job(project_dir, project, "j9", [])


def test_an_existing_job_folder_is_never_overwritten(ready_project):
    project_dir, project = ready_project
    generate_configs(project_dir, project)
    existing = project_dir / "jobs" / "j10"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(JobError, match="already exists"):
        prepare_job(project_dir, project, "j10", [A0])
    assert (existing / "keep.txt").read_text() == "keep"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_job_plan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aerosuite.engine.jobs.plan'`

- [ ] **Step 3: Create `aerosuite/engine/jobs/plan.py`**

```python
"""A job's own inputs: the selected cases' configs and a run_control.txt that restarts correctly.

Every submit runs from jobs/<id>/configs/, so rerunning some cases never touches configs/, and a
restart never silently refers to a different case than the one the user chose:
- `previous` means the case before it in the project's case list;
- a reference to a case of this project that runs earlier in the job uses its fresh solution
  (`previous` when it runs just before, else `from_case`);
- otherwise that case's current solution is copied to jobs/<id>/restart/<case>/ before anything
  runs (the sweep script deletes runs/<case>/ when that case starts) and passed as `custom`.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE, apply_parameters
from ..errors import JobError
from ..models import Case, Project
from ..restarts import find_restart_file, own_case_of, restart_file
from .store import JOBS_DIR

RESTART_DIR = "restart"


@dataclass(frozen=True)
class ControlLine:
    case: str
    option: str  # "none" | "previous" | "from_case" | "custom"
    ref: Optional[str] = None  # from_case: "<case>.cfg"; custom: a restart file outside this project's runs/
    copy_from: Optional[Path] = None  # custom: a solution in this project's runs/, copied aside first


@dataclass(frozen=True)
class RestartPlan:
    lines: list[ControlLine]
    warnings: list[str] = field(default_factory=list)
    missing_continue: list[str] = field(default_factory=list)  # continued cases with no solution


def plan_restarts(project_dir: Path, project: Project, cases: Sequence[str],
                  continue_cases: Iterable[str] = ()) -> RestartPlan:
    """How each selected case restarts in a job running `cases` (in the project's case order)."""
    names = [case.name for case in project.cases]
    unknown = [name for name in cases if name not in names]
    if unknown:
        raise JobError("Unknown cases: " + ", ".join(unknown))
    wanted = set(cases)
    selected = [name for name in names if name in wanted]
    if not selected:
        raise JobError("No cases selected")
    by_name = {case.name: case for case in project.cases}
    continued = set(continue_cases)
    lines: list[ControlLine] = []
    warnings: list[str] = []
    missing: list[str] = []
    for position, name in enumerate(selected):
        if name in continued:
            solution = restart_file(project_dir, name)
            if solution is None:
                missing.append(name)
                lines.append(ControlLine(name, "none"))
            else:
                lines.append(ControlLine(name, "custom", copy_from=solution))
            continue
        case = by_name[name]
        target = _referenced_case(project_dir, case, names)
        if target is not None:
            lines.append(_case_reference(project_dir, name, target, selected[:position], warnings))
        elif case.restart == "custom":
            lines.append(_custom_path(name, case.restart_ref or ""))
        else:
            lines.append(ControlLine(name, "none"))
    return RestartPlan(lines, warnings, missing)


def _referenced_case(project_dir: Path, case: Case, names: list[str]) -> Optional[str]:
    """The case of this project whose solution `case` restarts from, if any."""
    if case.restart == "previous":
        index = names.index(case.name)
        return names[index - 1] if index > 0 else None
    if case.restart == "custom" and case.restart_ref:
        return own_case_of(project_dir, case.restart_ref, names)
    return None


def _case_reference(project_dir: Path, name: str, target: str, earlier: list[str],
                    warnings: list[str]) -> ControlLine:
    if target in earlier:  # runs earlier in this job: restart from its fresh solution
        if earlier[-1] == target:
            return ControlLine(name, "previous")
        return ControlLine(name, "from_case", ref=f"{target}.cfg")
    solution = restart_file(project_dir, target)
    if solution is None:
        warnings.append(f"{name}: {target} has no restart file, so {name} starts from scratch")
        return ControlLine(name, "none")
    return ControlLine(name, "custom", copy_from=solution)


def _custom_path(name: str, ref: str) -> ControlLine:
    path = Path(ref)
    if path.is_dir():
        solution = find_restart_file(path)
        if solution is None:
            raise JobError(f"{name}: no restart file found in folder {ref}")
        return ControlLine(name, "custom", ref=str(solution))
    return ControlLine(name, "custom", ref=ref)


def prepare_job(project_dir: Path, project: Project, job_id: str, cases: Sequence[str],
                continue_cases: Iterable[str] = ()) -> Path:
    """Write jobs/<id>/configs/ (cfgs + run_control.txt) and copy restart solutions aside.

    Returns the configs folder. On any error nothing of this job is left behind.
    """
    project_dir = Path(project_dir).resolve()
    continued = set(continue_cases)
    plan = plan_restarts(project_dir, project, cases, continued)
    if plan.missing_continue:
        raise JobError("These cases have no solution to continue from: " + ", ".join(plan.missing_continue))
    source = project_dir / CONFIGS_DIR
    missing = [line.case for line in plan.lines if not (source / f"{line.case}.cfg").is_file()]
    if missing:
        raise JobError("Configs are missing for " + ", ".join(missing) + "; generate configs first")
    job_dir = project_dir / JOBS_DIR / job_id
    if job_dir.exists():
        raise JobError(f"{job_dir} already exists")
    configs = job_dir / CONFIGS_DIR
    try:
        configs.mkdir(parents=True)
        control = []
        for line in plan.lines:
            text = (source / f"{line.case}.cfg").read_text(encoding="utf-8")
            if line.case in continued:
                text = apply_parameters(text, {"RESTART_SOL": "YES"})
            (configs / f"{line.case}.cfg").write_text(text, encoding="utf-8", newline="\n")
            control.append(_control_line(job_dir, line))
        (configs / RUN_CONTROL_FILE).write_text("\n".join(control) + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise JobError(f"Cannot prepare job {job_id} in {job_dir}: {exc}") from exc
    return configs


def _control_line(job_dir: Path, line: ControlLine) -> str:
    fields = [f"{line.case}.cfg", line.option]
    if line.copy_from is not None:
        copy = job_dir / RESTART_DIR / line.copy_from.parent.name / line.copy_from.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(line.copy_from, copy)
        fields.append(str(copy))
    elif line.ref is not None:
        fields.append(line.ref)
    return ", ".join(fields)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_job_plan.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add aerosuite/engine/jobs/plan.py tests/engine/test_job_plan.py
git commit -m "feat(engine): build each job's own configs and restart plan"
```

---

### Task 4: `LocalRunner` submits a subset from the job's own configs

**Files:**
- Modify: `aerosuite/engine/jobs/local.py`, `aerosuite/engine/jobs/runner.py` (`Runner` protocol), `tests/fixtures/fake_sweep.py`
- Test: `tests/engine/test_local_runner.py`

**Interfaces:**
- Consumes: `prepare_job` (Task 3).
- Produces: `LocalRunner.submit(project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None, continue_cases: Iterable[str] = ()) -> JobRecord`. `cases=None` runs every project case. `JobRecord.cases` lists only the selected cases, in project order.
- The fake sweep (tests only): reads `fake_plan.json` from `-d`, else from `<cwd>/../configs/fake_plan.json`; copies each case's cfg into its folder; on success writes `restart_flow.dat`; writes the case's control line to `restart_used.txt` in its folder.

- [ ] **Step 1: Update the fake sweep — `tests/fixtures/fake_sweep.py`**

Replace the plan loading and the case loop so it matches the real script's layout and records restarts:

```python
    plan_path = Path(args.cfg_dir) / "fake_plan.json"
    if not plan_path.is_file():  # jobs run from jobs/<id>/configs; tests write the plan into configs/
        plan_path = Path.cwd().parent / "configs" / "fake_plan.json"
    plan = json.loads(plan_path.read_text()) if plan_path.is_file() else {}
    delay = float(plan.get("delay", 0.05))
    behaviour = plan.get("cases", {})
    lines = [
        line.strip()
        for line in Path(args.control_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    cfgs = [line.split(",")[0].strip() for line in lines]

    if input("Proceed with this execution plan? (yes/no): ").strip().lower() not in ("yes", "y"):
        print("Execution cancelled by user.")
        return 0

    for i, (cfg, line) in enumerate(zip(cfgs, lines), 1):
        print(f"=== Running Case {i}/{len(cfgs)}: {cfg} ===")
        name = cfg[:-4]
        folder = Path(name)
        if folder.is_dir():
            shutil.rmtree(folder)
        folder.mkdir()
        source = Path(args.cfg_dir) / cfg
        if source.is_file():
            shutil.copy(source, folder)
        (folder / "restart_used.txt").write_text(line + "\n")
        mode = behaviour.get(name, "converge")
        if mode == "exit":
            sys.stdout.flush()
            sys.exit(1)
        if mode == "hang":
            while True:
                time.sleep(0.1)
        time.sleep(delay)
        if mode == "fail":
            (folder / "error.log").write_text(f"Failed to run {cfg}:\nboom\n")
            print(f"ERROR: Simulation for {cfg} failed: boom")
            continue
        write_history(folder, diverge=(mode == "diverge"))
        (folder / "restart_flow.dat").write_text(f"solution of {name}\n")
        print("--> Iterations completed: 50")
    return 0
```

- [ ] **Step 2: Write the failing runner tests — `tests/engine/test_local_runner.py`**

Replace `test_cases_come_from_run_control` (a hand-edited `configs/run_control.txt` no longer drives a job; spec §2.2 — every submit runs from the job's own configs) with:

```python
def test_subset_runs_only_the_selected_cases(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    earlier = project_dir / RUNS_DIR / A2
    earlier.mkdir(parents=True)
    (earlier / "keep.txt").write_text("earlier run")
    runner = LocalRunner()
    job = runner.submit(project_dir, project, cases=[A4, A0])
    assert job.cases == [A0, A4]  # project order
    job = _wait(runner, project_dir, job, _finished)
    assert job.case_status == {A0: CaseState.CONVERGED, A4: CaseState.CONVERGED}
    assert (earlier / "keep.txt").read_text() == "earlier run"
    assert (project_dir / "jobs" / job.id / "configs" / "run_control.txt").is_file()


def test_continue_reruns_a_case_from_its_own_solution(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, cases={A2: "diverge"})
    runner = LocalRunner()
    first = _wait(runner, project_dir, runner.submit(project_dir, project), _finished)
    assert first.case_status[A2] is CaseState.UNCONVERGED
    _prepare(project_dir, project)  # this time it converges
    second = _wait(runner, project_dir, runner.submit(project_dir, project, cases=[A2], continue_cases=[A2]),
                   _finished)
    assert second.case_status == {A2: CaseState.CONVERGED}
    copy = project_dir.resolve() / "jobs" / second.id / "restart" / A2 / "restart_flow.dat"
    assert (project_dir / RUNS_DIR / A2 / "restart_used.txt").read_text() == f"{A2}.cfg, custom, {copy}\n"
    assert copy.read_text() == f"solution of {A2}\n"
    assert "RESTART_SOL= YES" in (project_dir / RUNS_DIR / A2 / f"{A2}.cfg").read_text()
```

Replace `test_submit_with_missing_python` with (a failed start leaves no job folder):

```python
def test_submit_with_missing_python(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project)
    project.run.sweep_python = str(project_dir / "no-such-python")
    with pytest.raises(JobError, match="Cannot start"):
        LocalRunner().submit(project_dir, project)
    assert read_lock(project_dir) is None
    assert not [p for p in (project_dir / "jobs").iterdir() if p.is_dir()]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_local_runner.py -q`
Expected: FAIL — `submit() got an unexpected keyword argument 'cases'`

- [ ] **Step 4: Rewrite `LocalRunner.submit` — `aerosuite/engine/jobs/local.py`**

Imports: add `import shutil`, `from typing import Iterable, Optional, Sequence`, `from .plan import prepare_job`; change `from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE` to `from ..cfg import RUN_CONTROL_FILE`. Replace `submit` up to (not including) the `try:  # the script asks "Proceed ..."` block with:

```python
    def submit(self, project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None,
               continue_cases: Iterable[str] = ()) -> JobRecord:
        """Run `cases` (default: every case) from the job's own configs (see jobs/plan.py)."""
        project_dir = Path(project_dir).resolve()
        if active_lock(project_dir):
            raise JobError("A job is already running for this project")
        runs = project_dir / RUNS_DIR
        for folder in (project_dir / JOBS_DIR, runs):
            try:
                folder.mkdir(exist_ok=True)
            except OSError as exc:
                raise JobError(f"Cannot create {folder}: {exc}") from exc

        selected = [case.name for case in project.cases] if cases is None else list(cases)
        job_id = new_job_id()
        configs = prepare_job(project_dir, project, job_id, selected, continue_cases)
        control = configs / RUN_CONTROL_FILE
        names = control_cases(control)
        job = JobRecord(
            id=job_id,
            backend=self.backend,
            cases=names,
            log_path=f"{JOBS_DIR}/{job_id}.log",
            case_status={name: CaseState.PENDING for name in names},
        )
        cmd = [
            resolve_sweep_python(project.run.sweep_python), str(sweep_script_path(project.run)),
            "-d", str(configs), "-c", str(control), "-n", str(project.run.partitions),
        ]
        if sys.platform == "win32":
            detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            detach = {"start_new_session": True}  # closing AeroSuite must not kill SU2
        # aoa_sweep_v8.py prints its "Running Case" banners without flushing, so with
        # stdout redirected to a file the child block-buffers; force unbuffered output
        # so the log (and therefore refresh()) reflects progress promptly.
        env = {**sweep_environment(), "PYTHONUNBUFFERED": "1"}
        try:
            with open(project_dir / job.log_path, "wb") as log:
                proc = subprocess.Popen(
                    cmd, cwd=runs, stdin=subprocess.PIPE, stdout=log,
                    stderr=subprocess.STDOUT, env=env, **detach,
                )
        except OSError as exc:
            shutil.rmtree(configs.parent, ignore_errors=True)
            raise JobError(f"Cannot start the sweep script ({' '.join(cmd)}): {exc}") from exc
```

In `aerosuite/engine/jobs/runner.py`, change the protocol:

```python
class Runner(Protocol):
    def submit(self, project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None,
               continue_cases: Iterable[str] = ()) -> JobRecord: ...
```

and import `Iterable, Sequence` from `typing` there.

- [ ] **Step 5: Run the runner and CLI run tests**

Run: `uv run pytest tests/engine/test_local_runner.py tests/cli -q`
Expected: all passed

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: all passed

```bash
git add aerosuite/engine/jobs/local.py aerosuite/engine/jobs/runner.py tests/fixtures/fake_sweep.py tests/engine/test_local_runner.py
git commit -m "feat(engine): submit selected cases, optionally continuing from their last solution"
```

---

### Task 5: Case overview, tolerant job scan and the `submit` preflight

**Files:**
- Create: `aerosuite/engine/jobs/overview.py`
- Modify: `aerosuite/engine/jobs/store.py`, `aerosuite/engine/preflight.py`
- Test: `tests/engine/test_job_overview.py` (new), `tests/engine/test_preflight.py`

**Interfaces:**
- Produces (`store.py`): `scan_jobs(project_dir: Path) -> tuple[list[JobRecord], list[str]]` — readable jobs newest first, one warning per unreadable `jobs/*.json`: `"Job record jobs/<file> can't be read; ignored"`. `list_jobs` is unchanged (strict, for the CLI).
- Produces (`overview.py`): `NOT_RUN = "NOT_RUN"`; `CaseRow(name: str, status: str, job_id: Optional[str], failure_tail: str = "")` (status is a `CaseState` value string or `NOT_RUN`); `CaseOverview(rows: list[CaseRow], problems: list[str], jobs: list[JobRecord])`; `case_overview(project_dir: Path, project: Project) -> CaseOverview`.
- Produces: `preflight(project_dir, project, action: Literal["generate", "run", "submit"])`. `"submit"` = the `generate` checks plus the environment checks (`SU2_RUN`, sweep script, sweep Python), without "configs not generated / out of date" (the Run page generates before it submits).

- [ ] **Step 1: Write the failing tests — `tests/engine/test_job_overview.py`**

```python
from datetime import datetime, timedelta

import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.overview import NOT_RUN, case_overview
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.engine.jobs.store import list_jobs, save_job

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"
T0 = datetime(2026, 9, 25, 10, 0)


def _job(project_dir, job_id, created, statuses, tails=None):
    job = JobRecord(
        id=job_id, backend="local", cases=list(statuses), log_path=f"jobs/{job_id}.log",
        created=created, state=JobState.DONE, case_status=statuses, failure_tail=tails or {},
    )
    save_job(project_dir, job)
    return job


def test_newest_job_that_ran_a_case_wins(ready_project):
    project_dir, project = ready_project
    _job(project_dir, "old", T0, {A0: CaseState.FAILED, A2: CaseState.UNCONVERGED}, {A0: "boom"})
    _job(project_dir, "new", T0 + timedelta(hours=1), {A2: CaseState.CONVERGED})
    overview = case_overview(project_dir, project)
    assert [(r.name, r.status, r.job_id, r.failure_tail) for r in overview.rows] == [
        (A0, "FAILED", "old", "boom"),
        (A2, "CONVERGED", "new", ""),
        (A4, NOT_RUN, None, ""),
    ]
    assert [job.id for job in overview.jobs] == ["new", "old"]
    assert overview.problems == []


def test_an_unreadable_job_record_is_skipped_with_a_warning(ready_project):
    project_dir, project = ready_project
    _job(project_dir, "good", T0, {A0: CaseState.CONVERGED})
    (project_dir / "jobs" / "bad.json").write_text("{not json")
    overview = case_overview(project_dir, project)
    assert [job.id for job in overview.jobs] == ["good"]
    assert overview.problems == ["Job record jobs/bad.json can't be read; ignored"]
    with pytest.raises(JobError):
        list_jobs(project_dir)  # the CLI stays strict


def test_no_jobs_yet(ready_project):
    project_dir, project = ready_project
    overview = case_overview(project_dir, project)
    assert {row.status for row in overview.rows} == {NOT_RUN}
    assert overview.jobs == [] and overview.problems == []
```

Add to `tests/engine/test_preflight.py`:

```python
def test_submit_checks_skip_the_generated_config_state(ready_project, monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")
    project_dir, project = ready_project  # configs never generated
    run_errors = _messages(preflight(project_dir, project, "run"), "error")
    assert any("Configs have not been generated" in m for m in run_errors)
    assert _messages(preflight(project_dir, project, "submit"), "error") == []
    monkeypatch.delenv("SU2_RUN")
    assert any("SU2_RUN is not set" in m for m in _messages(preflight(project_dir, project, "submit"), "error"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_job_overview.py tests/engine/test_preflight.py -q`
Expected: FAIL — `No module named 'aerosuite.engine.jobs.overview'`; the submit test fails because `"submit"` adds no environment checks.

- [ ] **Step 3: Add `scan_jobs` — `aerosuite/engine/jobs/store.py`** (after `list_jobs`)

```python
def scan_jobs(project_dir: Path) -> tuple[list[JobRecord], list[str]]:
    """Readable jobs, newest first, and a warning for each job record that cannot be read."""
    jobs_dir = Path(project_dir) / JOBS_DIR
    jobs: list[JobRecord] = []
    problems: list[str] = []
    if jobs_dir.is_dir():
        for path in sorted(jobs_dir.glob("*.json")):
            try:
                jobs.append(load_job(project_dir, path.stem))
            except JobError:
                problems.append(f"Job record {JOBS_DIR}/{path.name} can't be read; ignored")
    jobs.sort(key=lambda job: job.created, reverse=True)
    return jobs, problems
```

- [ ] **Step 4: Create `aerosuite/engine/jobs/overview.py`**

```python
"""Each case's latest outcome across every job of a project (the Run table and the Run badge)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import Project
from .runner import JobRecord
from .store import scan_jobs

NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class CaseRow:
    name: str
    status: str  # a CaseState value, or NOT_RUN
    job_id: Optional[str]  # the newest job that included the case
    failure_tail: str = ""


@dataclass(frozen=True)
class CaseOverview:
    rows: list[CaseRow]
    problems: list[str]  # job records that could not be read
    jobs: list[JobRecord]  # newest first


def case_overview(project_dir: Path, project: Project) -> CaseOverview:
    jobs, problems = scan_jobs(project_dir)
    rows = []
    for case in project.cases:
        job = next((job for job in jobs if case.name in job.case_status), None)
        if job is None:
            rows.append(CaseRow(case.name, NOT_RUN, None))
        else:
            rows.append(CaseRow(
                case.name, job.case_status[case.name].value, job.id, job.failure_tail.get(case.name, "")
            ))
    return CaseOverview(rows, problems, jobs)
```

- [ ] **Step 5: Split the run checks — `aerosuite/engine/preflight.py`**

Replace `_run_problems` with two functions (same checks, same messages):

```python
def _config_state_problems(project_dir: Path, project: Project) -> list[Problem]:
    problems = []
    if not (project_dir / CONFIGS_DIR / RUN_CONTROL_FILE).is_file():
        problems.append(Problem("error", "Configs have not been generated (configs/run_control.txt is missing)"))
    index = project_dir / CONFIGS_DIR / CASE_INDEX_FILE
    if index.is_file():
        try:
            generated = set(json.loads(index.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            generated = None
        if generated != {case.name for case in project.cases}:
            problems.append(Problem(
                "warning", "Generated configs are out of date with the sweep; regenerate before running"
            ))
    return problems


def _environment_problems(project: Project) -> list[Problem]:
    problems = []
    if not os.environ.get("SU2_RUN"):
        problems.append(Problem("error", "SU2_RUN is not set; the sweep script needs it to import SU2"))
    script = sweep_script_path(project.run)
    if not script.is_file():
        problems.append(Problem("error", f"Sweep script not found: {script}"))
    python = project.run.sweep_python
    resolved = resolve_sweep_python(python)
    search_path = sweep_environment().get("PATH", "")
    if shutil.which(resolved, path=search_path) is None and not Path(resolved).is_file():
        problems.append(Problem("error", f"Python for the sweep script not found: {python}"))
    elif is_aerosuite_python(resolved):
        problems.append(Problem(
            "warning",
            f"The sweep script would run under AeroSuite's own Python ({resolved}); "
            "SU2 is normally importable only from the system Python "
            "— set run.sweep_python to that interpreter",
        ))
    return problems
```

Change `preflight`'s signature to `action: Literal["generate", "run", "submit"]` and replace its last lines:

```python
    if action == "run":
        problems += _config_state_problems(project_dir, project)
    if action in ("run", "submit"):
        problems += _environment_problems(project)
    return problems
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/engine/test_job_overview.py tests/engine/test_preflight.py tests/cli -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add aerosuite/engine/jobs/overview.py aerosuite/engine/jobs/store.py aerosuite/engine/preflight.py tests/engine/test_job_overview.py tests/engine/test_preflight.py
git commit -m "feat(engine): per-case overview across jobs and submit preflight"
```

---

### Task 6: The server-wide `JobWatcher`

**Files:**
- Create: `aerosuite/web/jobs.py`
- Modify: `aerosuite/engine/results.py` (`HistoryReader.restarts`, new `HistoryBuffer`)
- Test: `tests/web/test_jobs.py` (new), `tests/engine/test_results.py`

**Interfaces:**
- Consumes: `LocalRunner.submit(..., cases, continue_cases)` (Task 4); `case_overview`, `CaseOverview` (Task 5).
- Produces (`engine/results.py`): `HistoryReader.restarts: int` (counts start-overs); `HistoryBuffer(path: Path)` with `.read() -> pd.DataFrame` (every row read so far; starts over when the file shrinks).
- Produces (`aerosuite/web/jobs.py`): `REFRESH_SECONDS = 2.0`, `LOG_TAIL_LINES = 40`, `LOG_TAIL_BYTES = 65536`; `JobView(latest: Optional[JobRecord], active: Optional[JobRecord], overview: CaseOverview)`; `JobWatcher(runner: Optional[LocalRunner] = None, clock: Callable[[], float] = time.monotonic)` with `state(project_dir, project) -> JobView`, `submit(project_dir, project, cases, continue_cases=()) -> JobRecord`, `cancel(project_dir, project) -> Optional[JobRecord]`, `history(project_dir, job_id, case)` (a pandas DataFrame, possibly empty), `log_tail(project_dir, job, lines=LOG_TAIL_LINES) -> Optional[str]`; module singleton `WATCHER = JobWatcher()`.

- [ ] **Step 1: Write the failing buffer test — add to `tests/engine/test_results.py`**

```python
def test_history_buffer_accumulates_and_starts_over(tmp_path, history_writer):
    from aerosuite.engine.results import HistoryBuffer

    path = history_writer(tmp_path / "case", [0.5] * 20)
    buffer = HistoryBuffer(path)
    assert len(buffer.read()) == 20
    history_writer(tmp_path / "case", [0.5] * 30)  # 10 rows appended
    assert len(buffer.read()) == 30
    history_writer(tmp_path / "case", [0.5] * 5)  # the case was re-run: the file shrank
    assert len(buffer.read()) == 5
```

- [ ] **Step 2: Write the failing watcher tests — `tests/web/test_jobs.py`**

```python
import json
import time

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import RUNS_DIR, LocalRunner
from aerosuite.engine.jobs.runner import JobRecord, JobState
from aerosuite.web.jobs import JobWatcher

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _prepare(project_dir, project, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))


class CountingRunner(LocalRunner):
    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def refresh(self, project_dir, job):
        self.refreshes += 1
        return super().refresh(project_dir, job)


def _wait_view(watcher, project_dir, project, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = watcher.state(project_dir, project)
        if until(view):
            return view
        time.sleep(0.2)
    raise AssertionError("timed out waiting for the job")


def test_state_refreshes_an_active_job_at_most_every_two_seconds(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    now = [100.0]
    runner = CountingRunner()
    watcher = JobWatcher(runner=runner, clock=lambda: now[0])
    job = watcher.submit(project_dir, project, [A0])
    for _ in range(5):
        view = watcher.state(project_dir, project)
    assert runner.refreshes == 1
    assert view.active is not None and view.active.id == job.id and view.latest.id == job.id
    now[0] += 2.0
    watcher.state(project_dir, project)
    assert runner.refreshes == 2
    watcher.cancel(project_dir, project)


def test_a_new_watcher_picks_up_a_running_job(ready_project):
    project_dir, project = ready_project
    _prepare(project_dir, project, **{A0: "hang"})
    job = JobWatcher().submit(project_dir, project, [A0])
    second = JobWatcher()  # e.g. after a server restart
    view = _wait_view(second, project_dir, project, lambda v: v.overview.rows[0].status == "RUNNING")
    assert view.active.id == job.id
    cancelled = second.cancel(project_dir, project)
    assert cancelled.state is JobState.CANCELLED
    assert second.state(project_dir, project).active is None


def test_history_is_read_per_job_and_case(ready_project, history_writer):
    project_dir, _ = ready_project
    folder = project_dir / RUNS_DIR / A0
    history_writer(folder, [0.5] * 20)
    watcher = JobWatcher()
    assert len(watcher.history(project_dir, "j1", A0)) == 20
    history_writer(folder, [0.5] * 30)
    assert len(watcher.history(project_dir, "j1", A0)) == 30
    history_writer(folder, [0.5] * 40)  # a rerun (new job) recreated the file
    assert len(watcher.history(project_dir, "j2", A0)) == 40
    assert watcher.history(project_dir, "j3", A2).empty


def test_log_tail_reads_only_the_end_of_a_big_log(ready_project):
    project_dir, _ = ready_project
    (project_dir / "jobs").mkdir()
    filler = "x" * 200 + "\n"
    (project_dir / "jobs" / "j.log").write_text(filler * 50_000 + "".join(f"line {i}\n" for i in range(100)))
    job = JobRecord(id="j", backend="local", cases=[A0], log_path="jobs/j.log")
    assert JobWatcher().log_tail(project_dir, job).splitlines() == [f"line {i}" for i in range(60, 100)]
    missing = JobRecord(id="k", backend="local", cases=[A0], log_path="jobs/k.log")
    assert JobWatcher().log_tail(project_dir, missing) is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/web/test_jobs.py tests/engine/test_results.py -q`
Expected: FAIL — `No module named 'aerosuite.web.jobs'`; `cannot import name 'HistoryBuffer'`.

- [ ] **Step 4: Add `HistoryBuffer` — `aerosuite/engine/results.py`**

In `HistoryReader.__init__` add `self.restarts = 0`, and in `read_new` count a start-over:

```python
            if self.path.stat().st_size < self._offset:
                self._offset, self.columns = 0, []
                self.restarts += 1
```

After `read_history`, add:

```python
class HistoryBuffer:
    """Every row of a history file read so far, growing incrementally (for live monitoring)."""

    def __init__(self, path: Path):
        self._reader = HistoryReader(path)
        self._restarts = 0
        self.frame = pd.DataFrame()

    def read(self) -> pd.DataFrame:
        new = self._reader.read_new()
        if self._reader.restarts != self._restarts:  # the file shrank: the case was re-run
            self._restarts = self._reader.restarts
            self.frame = pd.DataFrame()
        if not new.empty:
            self.frame = new if self.frame.empty else pd.concat([self.frame, new], ignore_index=True)
        return self.frame
```

- [ ] **Step 5: Create `aerosuite/web/jobs.py`**

```python
"""The web server's single view of jobs.

One LocalRunner for the whole server (it keeps the processes it started so it can reap them),
an active job refreshed at most every REFRESH_SECONDS per project however many tabs ask, and
one incremental history buffer per (project, job, case). No NiceGUI and no pandas import here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..engine.jobs.local import RUNS_DIR, LocalRunner
from ..engine.jobs.overview import CaseOverview, case_overview
from ..engine.jobs.runner import JobRecord
from ..engine.models import Project
from ..engine.results import HISTORY_FILE, HistoryBuffer

REFRESH_SECONDS = 2.0
LOG_TAIL_LINES = 40
LOG_TAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class JobView:
    latest: Optional[JobRecord]  # the newest job, active or not
    active: Optional[JobRecord]  # the running job, if any
    overview: CaseOverview


class JobWatcher:
    def __init__(self, runner: Optional[LocalRunner] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.runner = runner if runner is not None else LocalRunner()
        self._clock = clock
        self._refreshed: dict[tuple[Path, str], float] = {}
        self._buffers: dict[tuple[Path, str, str], HistoryBuffer] = {}

    def state(self, project_dir: Path, project: Project) -> JobView:
        directory = Path(project_dir).resolve()
        view = self._view(directory, project)
        if view.active is not None:
            key = (directory, view.active.id)
            now = self._clock()
            last = self._refreshed.get(key)
            if last is None or now - last >= REFRESH_SECONDS:
                self._refreshed[key] = now
                self.runner.refresh(directory, view.active)  # saves the job record
                view = self._view(directory, project)
        return view

    def _view(self, directory: Path, project: Project) -> JobView:
        overview = case_overview(directory, project)
        latest = overview.jobs[0] if overview.jobs else None
        active = next((job for job in overview.jobs if job.is_active), None)
        return JobView(latest, active, overview)

    def submit(self, project_dir: Path, project: Project, cases: Sequence[str],
               continue_cases: Iterable[str] = ()) -> JobRecord:
        return self.runner.submit(Path(project_dir).resolve(), project, cases=list(cases),
                                  continue_cases=list(continue_cases))

    def cancel(self, project_dir: Path, project: Project) -> Optional[JobRecord]:
        directory = Path(project_dir).resolve()
        active = self._view(directory, project).active
        if active is None:
            return None
        return self.runner.cancel(directory, active)

    def history(self, project_dir: Path, job_id: str, case: str):
        """Every history row of `case` written in job `job_id` so far (a DataFrame, maybe empty)."""
        directory = Path(project_dir).resolve()
        key = (directory, job_id, case)
        if key not in self._buffers:
            # A newer job for the same case replaces older buffers (they are never asked for again).
            for old in [k for k in self._buffers if k[0] == directory and k[2] == case]:
                del self._buffers[old]
            self._buffers[key] = HistoryBuffer(directory / RUNS_DIR / case / HISTORY_FILE)
        return self._buffers[key].read()

    def log_tail(self, project_dir: Path, job: JobRecord, lines: int = LOG_TAIL_LINES) -> Optional[str]:
        """The last `lines` lines of the job's log, reading at most LOG_TAIL_BYTES; None if unreadable."""
        path = Path(project_dir) / job.log_path
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - LOG_TAIL_BYTES))
                data = fh.read()
        except OSError:
            return None
        return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


WATCHER = JobWatcher()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_jobs.py tests/engine/test_results.py -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add aerosuite/web/jobs.py aerosuite/engine/results.py tests/web/test_jobs.py tests/engine/test_results.py
git commit -m "feat(web): add the shared job watcher with throttled refresh and live history"
```

---

### Task 7: Run page and the Run step in the sidebar

**Files:**
- Create: `aerosuite/web/pages/run.py`
- Modify: `aerosuite/web/status.py`, `aerosuite/web/layout.py`, `aerosuite/web/app.py`
- Test: `tests/web/test_web_run.py` (new), `tests/web/test_status.py`, `tests/web/test_web_frame.py`

**Interfaces:**
- Consumes: `WATCHER`, `JobView` (Task 6); `NOT_RUN`, `case_overview` (Task 5); `plan_restarts` (Task 3); `restart_file` (Task 1); `preflight(..., "submit")` (Task 5); `generate_configs`.
- Produces: page `/run?project=<folder>`; `status.Badge` gains `"running"` (and `"plain"`, used by Task 8); `step_badges(...)["run"]` ∈ `todo | running | done | attention`: `running` while `active_lock` holds, `todo` when no case has run, `done` when every case's latest status is CONVERGED, `attention` otherwise.
- Markers: `run-problem-error`, `run-problem-warning`, `run-problems-none`, `run-error`, `select-all`, `select-failed`, `select-unconverged`, `select-not-run`, `select-none`, `tick-<case>`, `status-<case>` (text: a CaseState value, or `Not run`), `job-<case>`, `tail-<case>` (expansion, FAILED cases), `continue`, `continue-missing`, `plan-warning`, `plan-error`, `submit`, `cancel`, `cancel-confirm`, `cancel-keep`, `history-none`, `history-<job id>`, `badge-run-<badge>`.

- [ ] **Step 1: Write the failing badge tests — `tests/web/test_status.py`**

In `test_ready_project`, change the expected `"run": "later", "monitor": "later"` to `"run": "todo", "monitor": "later"`. Add:

```python
def test_run_badge(ready_project):
    import os
    from datetime import datetime, timedelta

    import psutil

    from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
    from aerosuite.engine.jobs.store import clear_lock, save_job, write_lock

    project_dir, project = ready_project
    names = [case.name for case in project.cases]
    t0 = datetime(2026, 9, 25, 10, 0)
    assert step_badges(project_dir, project)["run"] == "todo"
    save_job(project_dir, JobRecord(
        id="a", backend="local", cases=names, log_path="jobs/a.log", created=t0, state=JobState.DONE,
        case_status={n: CaseState.CONVERGED for n in names}))
    assert step_badges(project_dir, project)["run"] == "done"
    save_job(project_dir, JobRecord(
        id="b", backend="local", cases=[names[1]], log_path="jobs/b.log", created=t0 + timedelta(hours=1),
        state=JobState.FAILED, case_status={names[1]: CaseState.FAILED}))
    assert step_badges(project_dir, project)["run"] == "attention"
    write_lock(project_dir, "c", os.getpid(), psutil.Process().create_time())
    try:
        assert step_badges(project_dir, project)["run"] == "running"
    finally:
        clear_lock(project_dir)
```

In `tests/web/test_web_frame.py::test_frame_shows_project_and_badges`, replace `badge-run-later` with `badge-run-todo`.

- [ ] **Step 2: Write the failing page tests — `tests/web/test_web_run.py`**

```python
import json
import time

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.editing import update_sweep
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.runner import JobState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


@pytest.fixture
def su2_env(monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")


def _plan(project_dir, **cases):
    configs = project_dir / CONFIGS_DIR
    configs.mkdir(exist_ok=True)
    (configs / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))


def _run_to_end(project_dir, project, **cases):
    """Run every case once through the engine (not the page) and wait for the job to end."""
    generate_configs(project_dir, project)
    _plan(project_dir, **cases)
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    deadline = time.monotonic() + 20
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.1)
        job = runner.refresh(project_dir, job)
    assert not job.is_active
    return job


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


async def _open(user, project_dir):
    await user.open(project_url("run", project_dir))


async def test_preflight_errors_disable_submit(user: User, ready_project, monkeypatch):
    project_dir, _ = ready_project
    monkeypatch.delenv("SU2_RUN", raising=False)
    await _open(user, project_dir)
    await user.should_see("SU2_RUN is not set")
    assert not _element(user, "submit").enabled


async def test_submit_all_runs_every_case(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    _plan(project_dir)
    await _open(user, project_dir)
    assert _text(user, f"status-{A0}") == "Not run"
    await user.should_see(marker="badge-run-todo")
    await user.should_see(marker="history-none")
    user.find(marker="submit").click()
    await eventually(lambda: all(_text(user, f"status-{n}") == "CONVERGED" for n in (A0, A2, A4)), timeout=20)
    await user.should_see(marker="badge-run-done")
    jobs = list_jobs(project_dir)
    assert len(jobs) == 1 and jobs[0].cases == [A0, A2, A4]
    await user.should_see(marker=f"history-{jobs[0].id}")


async def test_rerun_failed_and_unconverged_cases(user: User, ready_project, su2_env, eventually):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail", A4: "diverge"})
    _plan(project_dir)  # everything converges from now on
    await _open(user, project_dir)
    assert _text(user, f"status-{A2}") == "FAILED"
    await user.should_see(marker=f"tail-{A2}")
    await user.should_see(marker="badge-run-attention")

    user.find(marker="select-failed").click()
    assert _element(user, f"tick-{A2}").value and not _element(user, f"tick-{A4}").value
    assert not _element(user, "continue").enabled  # A2 failed before writing a solution
    await user.should_see(marker="continue-missing")

    user.find(marker="select-unconverged").click()
    assert _element(user, f"tick-{A4}").value and not _element(user, f"tick-{A0}").value
    assert _element(user, "continue").value is True  # UNCONVERGED with a solution: on by default
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A4}") == "CONVERGED", timeout=20)
    latest = list_jobs(project_dir)[0]
    assert latest.cases == [A4]
    control = (project_dir / "jobs" / latest.id / "configs" / "run_control.txt").read_text()
    assert control.startswith(f"{A4}.cfg, custom, ")
    assert _text(user, f"status-{A2}") == "FAILED"  # not rerun


async def test_cancel_asks_first(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    _plan(project_dir, **{A0: "hang"})
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "RUNNING", timeout=20)
    await user.should_see(marker="badge-run-running")
    assert not _element(user, "submit").enabled
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-keep")
    user.find(marker="cancel-keep").click()
    assert list_jobs(project_dir)[0].is_active
    user.find(marker="cancel").click()
    await user.should_see(marker="cancel-confirm")
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: _text(user, f"status-{A0}") == "CANCELLED", timeout=20)
    assert list_jobs(project_dir)[0].state is JobState.CANCELLED


async def test_cases_changed_on_disk_follow_into_the_table(user: User, ready_project, su2_env, eventually):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    user.find(marker="select-none").click()
    project = open_project(project_dir)
    update_sweep(project, alpha=[0.0, 6.0])  # another tab or the CLI rebuilds the sweep
    save_project(project_dir, project)
    await eventually(lambda: bool(user.find(marker="tick-M0p8_a6_b0").elements), timeout=10)
    await user.should_not_see(marker=f"tick-{A2}")
    assert not _element(user, "tick-M0p8_a6_b0").value
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/web/test_web_run.py tests/web/test_status.py tests/web/test_web_frame.py -q`
Expected: FAIL — `/run` returns 404; the Run badge is still `later`.

- [ ] **Step 4: Run badge — `aerosuite/web/status.py`**

Add imports `from ..engine.jobs.overview import NOT_RUN, case_overview` and `from ..engine.jobs.store import active_lock`. Change `Badge = Literal["done", "attention", "todo", "later", "running", "plain"]`. Add:

```python
def _run_badge(project_dir: Path, project: Project) -> Badge:
    if active_lock(project_dir):
        return "running"
    statuses = [row.status for row in case_overview(project_dir, project).rows]
    if not statuses or all(status == NOT_RUN for status in statuses):
        return "todo"
    if all(status == "CONVERGED" for status in statuses):
        return "done"
    return "attention"
```

and in `step_badges` replace `"run": "later",` with `"run": _run_badge(project_dir, project),`.

- [ ] **Step 5: Sidebar link and icons — `aerosuite/web/layout.py`**

```python
BADGE_ICONS = {
    "done": ("check_circle", "positive"),
    "attention": ("error", "warning"),
    "todo": ("radio_button_unchecked", "grey-6"),
    "later": ("schedule", "grey-4"),
    "running": ("autorenew", "primary"),
    "plain": ("insights", "grey-6"),
}
PAGE_OF_STEP = {"setup": "setup", "config": "config", "aircraft": "aircraft", "sweep": "sweep", "run": "run"}
```

- [ ] **Step 6: Create `aerosuite/web/pages/run.py`**

```python
"""Run: checks, each case's latest status, rerun selection, Submit / Cancel and job history."""
from typing import Optional

from nicegui import ui

from ...engine.cfg import generate_configs
from ...engine.errors import AeroSuiteError
from ...engine.jobs.overview import NOT_RUN
from ...engine.jobs.plan import plan_restarts
from ...engine.preflight import has_errors, preflight
from ...engine.restarts import restart_file
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session

POLL_SECONDS = 2.0
SELECTORS = [  # (label, statuses to tick; None = every case)
    ("All", None),
    ("Failed", {"FAILED"}),
    ("Unconverged", {"UNCONVERGED"}),
    ("Not run", {NOT_RUN}),
    ("None", set()),
]


def register() -> None:
    @ui.page("/run")
    def run_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "run", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            ui.label("Run").classes("text-2xl")
            pages.append(RunPage(frame))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class RunPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.ticked = {case.name for case in frame.session.project.cases}
        self.continue_choice: Optional[bool] = None  # None: the default for the ticked cases
        self.continue_cases: list[str] = []
        self.has_errors = False
        self.was_active = False
        self.holder = ui.column().classes("w-full gap-4")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)

    @property
    def directory(self):
        return self.frame.session.directory

    @property
    def project(self):
        return self.frame.session.project

    def poll(self) -> None:
        try:
            view = WATCHER.state(self.directory, self.project)
        except AeroSuiteError:
            return
        if view.active is not None or self.was_active:
            self.render(view)
            self.frame.refresh()

    def render(self, view: Optional[JobView] = None) -> None:
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.project)
            except AeroSuiteError as exc:
                self.holder.clear()
                with self.holder:
                    ui.label(f"Error: {exc}").classes("text-negative").mark("run-error")
                return
        self.was_active = view.active is not None
        self.ticked &= {case.name for case in self.project.cases}  # the cases may have been rebuilt
        self.holder.clear()
        with self.holder:
            self._checks(view)
            self._cases(view)
            self._actions(view)
            self._history(view)

    def _checks(self, view: JobView) -> None:
        ui.label("Checks").classes("text-lg")
        problems = preflight(self.directory, self.project, "submit")
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        if not found:
            ui.label("No problems found.").classes("text-positive").mark("run-problems-none")
        for severity, message in found:
            style = "text-negative" if severity == "error" else "text-warning"
            prefix = "Error" if severity == "error" else "Warning"
            ui.label(f"{prefix}: {message}").classes(style).mark(f"run-problem-{severity}")

    def _cases(self, view: JobView) -> None:
        ui.label("Cases").classes("text-lg")
        if not view.overview.rows:
            ui.label("No cases yet: set up the sweep first.").classes("text-grey-7")
            return
        with ui.row().classes("gap-2 items-center"):
            ui.label("Select:")
            for label, statuses in SELECTORS:
                ui.button(label, on_click=lambda s=statuses: self._select(view, s)).props(
                    "flat dense no-caps").mark(f"select-{label.lower().replace(' ', '-')}")
        with ui.grid(columns=4).classes("w-full items-start gap-x-4 gap-y-1"):
            for heading in ("", "Case", "Status", "Last job"):
                ui.label(heading).classes("text-bold")
            for row in view.overview.rows:
                ui.checkbox(value=row.name in self.ticked,
                            on_change=lambda e, n=row.name: self._tick(n, e.value)).mark(f"tick-{row.name}")
                ui.label(row.name)
                with ui.column().classes("gap-0"):
                    ui.label("Not run" if row.status == NOT_RUN else row.status).mark(f"status-{row.name}")
                    if row.status == "FAILED" and row.failure_tail:
                        with ui.expansion("Why it failed").mark(f"tail-{row.name}"):
                            ui.label(row.failure_tail).classes("font-mono text-xs whitespace-pre-wrap")
                ui.label(row.job_id or "—").mark(f"job-{row.name}")

    def _actions(self, view: JobView) -> None:
        ticked = [case.name for case in self.project.cases if case.name in self.ticked]
        status = {row.name: row.status for row in view.overview.rows}
        no_solution = [name for name in ticked if restart_file(self.directory, name) is None]
        default = bool(ticked) and not no_solution and all(status.get(n) == "UNCONVERGED" for n in ticked)
        chosen = (default if self.continue_choice is None else self.continue_choice) and not no_solution
        self.continue_cases = ticked if chosen else []
        box = ui.checkbox("Continue from each case's last solution", value=chosen,
                          on_change=lambda e: self._set_continue(e.value)).mark("continue")
        if no_solution:
            box.disable()
            ui.label("No solution to continue from: " + ", ".join(no_solution)).classes(
                "text-xs text-grey-7").mark("continue-missing")
        if ticked and view.active is None:
            try:
                plan = plan_restarts(self.directory, self.project, ticked, self.continue_cases)
            except AeroSuiteError as exc:
                ui.label(f"Error: {exc}").classes("text-negative").mark("plan-error")
            else:
                for warning in plan.warnings:
                    ui.label(f"Warning: {warning}").classes("text-warning").mark("plan-warning")
        with ui.row().classes("gap-2"):
            submit = ui.button(f"Submit {_plural(len(ticked), 'case')}", on_click=self.submit).mark("submit")
            submit.set_enabled(view.active is None and bool(ticked) and not self.has_errors)
            if view.active is not None:
                ui.button("Cancel", on_click=self.confirm_cancel).props("color=negative").mark("cancel")

    def _history(self, view: JobView) -> None:
        ui.label("Job history").classes("text-lg")
        if not view.overview.jobs:
            ui.label("No jobs yet.").classes("text-grey-7").mark("history-none")
            return
        for job in view.overview.jobs:
            finished = f", finished {job.finished:%Y-%m-%d %H:%M}" if job.finished else ""
            ui.label(f"{job.id} — {job.state.value}, {_plural(len(job.cases), 'case')}, "
                     f"started {job.created:%Y-%m-%d %H:%M}{finished}").mark(f"history-{job.id}")

    def _select(self, view: JobView, statuses: Optional[set]) -> None:
        rows = view.overview.rows
        self.ticked = {r.name for r in rows} if statuses is None else {r.name for r in rows if r.status in statuses}
        self.continue_choice = None
        self.render()

    def _tick(self, name: str, value: bool) -> None:
        if value:
            self.ticked.add(name)
        else:
            self.ticked.discard(name)
        self.continue_choice = None
        self.render()

    def _set_continue(self, value: bool) -> None:
        self.continue_choice = value
        self.render()

    def submit(self) -> None:
        stale = self.frame.ensure_current(notify=False)
        if stale is not None:
            if self.frame.session.load_error is not None:  # project.json on disk is invalid
                ui.notify(stale, type="negative")
            else:
                ui.notify("Project changed on disk and was reloaded; submit again", type="warning")
            return
        cases = [case.name for case in self.project.cases if case.name in self.ticked]
        errors = [p for p in preflight(self.directory, self.project, "submit") if p.severity == "error"]
        if errors:
            ui.notify(errors[0].message, type="negative")
            self.render()
            return
        try:
            generate_configs(self.directory, self.project)  # a run always uses the current settings
            WATCHER.submit(self.directory, self.project, cases, self.continue_cases)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            self.render()
            return
        ui.notify(f"Started {_plural(len(cases), 'case')}", type="positive")
        self.frame.refresh()
        self.render()

    async def confirm_cancel(self) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("Cancel the running job? Cases that have not finished are marked CANCELLED.")
            with ui.row():
                ui.button("Cancel the job", on_click=lambda: dialog.submit(True)).props(
                    "color=negative").mark("cancel-confirm")
                ui.button("Keep running", on_click=lambda: dialog.submit(False)).props("flat").mark("cancel-keep")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        try:
            job = WATCHER.cancel(self.directory, self.project)
        except AeroSuiteError as exc:
            ui.notify(str(exc), type="negative")
            return
        if job is not None:
            ui.notify(f"Job {job.id}: {job.state.value}", type="info")
        self.frame.refresh()
        self.render()
```

- [ ] **Step 7: Register the page — `aerosuite/web/app.py`**

```python
def register_pages(root: Path) -> None:
    config.set_root(root)
    from .pages import config as config_page
    from .pages import aircraft, projects, run, setup, sweep

    projects.register()
    setup.register()
    config_page.register()
    aircraft.register()
    sweep.register()
    run.register()
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_run.py tests/web/test_status.py tests/web/test_web_frame.py -q`
Expected: all passed

- [ ] **Step 9: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: all passed

```bash
git add aerosuite/web/pages/run.py aerosuite/web/status.py aerosuite/web/layout.py aerosuite/web/app.py tests/web/test_web_run.py tests/web/test_status.py tests/web/test_web_frame.py
git commit -m "feat(web): add the Run page with rerun selection, continue, cancel and job history"
```

---

### Task 8: Monitor page, the Monitor step in the sidebar and the README

**Files:**
- Create: `aerosuite/web/pages/monitor.py`
- Modify: `aerosuite/web/status.py`, `aerosuite/web/layout.py`, `aerosuite/web/app.py`, `README.md`
- Test: `tests/web/test_web_monitor.py` (new), `tests/web/test_status.py`

**Interfaces:**
- Consumes: `WATCHER`, `JobView` (Task 6); `NOT_RUN` (Task 5); `check_convergence` (engine); `CaseState`.
- Produces: page `/monitor?project=<folder>`; module functions `iteration_values(df) -> list`, `residual_columns(df) -> list[str]`, `coefficient_columns(df) -> list[str]`, `line_options(x: list, df, columns: list[str], y_name: str) -> dict`, `default_case(view: JobView, names: list[str]) -> Optional[str]`; `MAX_POINTS = 2000`; `step_badges(...)["monitor"] == "plain"`.
- Markers: `monitor-case`, `monitor-status`, `monitor-not-run`, `monitor-no-history`, `chart-residuals`, `monitor-columns`, `chart-coefficients`, `monitor-verdict` (text `Convergence: <message>`), `monitor-log`, `badge-monitor-plain`.

- [ ] **Step 1: Write the failing tests — `tests/web/test_web_monitor.py`**

```python
import json
import math
import time

import pandas as pd
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.web.layout import project_url
from aerosuite.web.pages.monitor import MAX_POINTS, line_options

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _start(project_dir, project, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))
    runner = LocalRunner()
    return runner, runner.submit(project_dir, project)


def _wait(runner, project_dir, job, until, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.refresh(project_dir, job)
        if until(job):
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out: {job.case_status}")


async def _open(user, project_dir):
    await user.open(project_url("monitor", project_dir))


async def test_a_finished_case_shows_charts_verdict_and_log(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A4  # the case that ran last
    residuals = _element(user, "chart-residuals").options
    assert [s["name"] for s in residuals["series"]] == ["rms[Rho]"]
    assert residuals["yAxis"]["name"] == "log10 residual"
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CL", "CD", "CMy"]
    assert _element(user, "monitor-verdict").text == "Convergence: Converged"
    assert "Running Case" in _element(user, "monitor-log").text
    await user.should_see(marker="badge-monitor-plain")


async def test_choosing_columns_and_cases(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    with user:
        _element(user, "monitor-columns").set_value(["CD"])
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CD"]
    with user:
        _element(user, "monitor-case").set_value(A0)
    assert _element(user, "monitor-status").text == f"CONVERGED in job {job.id}"
    assert [s["name"] for s in _element(user, "chart-coefficients").options["series"]] == ["CD"]


async def test_defaults_to_the_running_case(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project, **{A2: "hang"})
    _wait(runner, project_dir, job, lambda j: j.case_status[A2] is CaseState.RUNNING)
    try:
        await _open(user, project_dir)
        assert _element(user, "monitor-case").value == A2
        await user.should_see(marker="monitor-no-history")
    finally:
        runner.cancel(project_dir, job)


async def test_a_case_that_never_ran(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert _element(user, "monitor-case").value == A0
    await user.should_see(marker="monitor-not-run")


def test_long_histories_are_thinned_but_keep_the_last_iteration():
    n = 25_001
    df = pd.DataFrame({"Inner_Iter": range(n), "CL": [0.5] * n})
    series = line_options(list(range(n)), df, ["CL"], "value")["series"][0]["data"]
    assert len(series) <= MAX_POINTS + 1
    assert series[0][0] == 0 and series[-1][0] == n - 1


def test_nan_values_become_gaps():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.5, math.nan, 0.6]})
    data = line_options([0, 1, 2], df, ["CL"], "value")["series"][0]["data"]
    assert data == [[0, 0.5], [1, None], [2, 0.6]]
```

In `tests/web/test_status.py::test_ready_project`, change `"monitor": "later"` to `"monitor": "plain"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/web/test_web_monitor.py tests/web/test_status.py -q`
Expected: FAIL — `No module named 'aerosuite.web.pages.monitor'`.

- [ ] **Step 3: Create `aerosuite/web/pages/monitor.py`**

```python
"""Monitor: one case's residuals and coefficients against iteration, its convergence and the job log."""
import math
from typing import Optional

from nicegui import ui

from ...engine.errors import AeroSuiteError
from ...engine.jobs.runner import CaseState
from ...engine.results import check_convergence
from ..jobs import WATCHER, JobView
from ..layout import ProjectFrame, open_session

POLL_SECONDS = 2.0
ITERATION_COLUMNS = ("Inner_Iter", "Outer_Iter")
DEFAULT_COEFFICIENTS = ("CL", "CD", "CMy")
MAX_POINTS = 2000  # per series; longer histories are thinned evenly


def register() -> None:
    @ui.page("/monitor")
    def monitor_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        pages: list = []
        frame = ProjectFrame(session, "monitor", on_reload=lambda: pages[0].render() if pages else None)
        with frame.content:
            ui.label("Monitor").classes("text-2xl")
            pages.append(MonitorPage(frame))


def iteration_values(df) -> list:
    for column in ITERATION_COLUMNS:
        if column in df.columns:
            return df[column].tolist()
    return list(range(len(df)))


def residual_columns(df) -> list:
    return [column for column in df.columns if column.startswith("rms[")]


def coefficient_columns(df) -> list:
    skip = set(residual_columns(df)) | set(ITERATION_COLUMNS)
    return [column for column in df.columns if column not in skip]


def line_options(x: list, df, columns: list, y_name: str) -> dict:
    """ECharts options: one line per column against iteration, thinned to MAX_POINTS; NaN is a gap."""
    count = len(x)
    step = max(1, math.ceil(count / MAX_POINTS))
    indices = list(range(0, count, step))
    if count and indices[-1] != count - 1:
        indices.append(count - 1)
    series = []
    for column in columns:
        values = df[column].tolist()
        data = [[x[i], None if math.isnan(values[i]) else values[i]] for i in indices]
        series.append({"name": column, "type": "line", "showSymbol": False, "data": data})
    return {
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "legend": {"data": list(columns)},
        "xAxis": {"type": "value", "name": "Iteration"},
        "yAxis": {"type": "value", "name": y_name, "scale": True},
        "series": series,
    }


def default_case(view: JobView, names: list) -> Optional[str]:
    """The case running now, else the last case the newest job started, else the first case."""
    if not names:
        return None
    job = view.latest
    if job is not None:
        started = [n for n in job.cases if n in names and job.case_status.get(n, CaseState.PENDING)
                   is not CaseState.PENDING]
        running = [n for n in started if job.case_status[n] is CaseState.RUNNING]
        if running:
            return running[0]
        if started:
            return started[-1]
    return names[0]


class MonitorPage:
    def __init__(self, frame: ProjectFrame) -> None:
        self.frame = frame
        self.case: Optional[str] = None
        self.columns: Optional[list] = None  # None: the default coefficients
        self.was_running = False
        self.holder = ui.column().classes("w-full gap-4")
        self.render()
        ui.timer(POLL_SECONDS, self.poll)

    @property
    def directory(self):
        return self.frame.session.directory

    def _row(self, view: JobView):
        return next((row for row in view.overview.rows if row.name == self.case), None)

    def _running(self, view: JobView) -> bool:
        row = self._row(view)
        return row is not None and row.status == CaseState.RUNNING.value

    def poll(self) -> None:
        try:
            view = WATCHER.state(self.directory, self.frame.session.project)
        except AeroSuiteError:
            return
        if self._running(view) or self.was_running:
            self.render(view)

    def render(self, view: Optional[JobView] = None) -> None:
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.frame.session.project)
            except AeroSuiteError as exc:
                self.holder.clear()
                with self.holder:
                    ui.label(f"Error: {exc}").classes("text-negative")
                return
        names = [case.name for case in self.frame.session.project.cases]
        if self.case not in names:
            self.case = default_case(view, names)
        self.was_running = self._running(view)
        self.holder.clear()
        with self.holder:
            if not names:
                ui.label("No cases yet: set up the sweep first.").classes("text-grey-7")
                return
            ui.select(names, value=self.case, label="Case",
                      on_change=lambda e: self._choose(e.value)).classes("w-80").mark("monitor-case")
            self._case_view(view)

    def _case_view(self, view: JobView) -> None:
        row = self._row(view)
        job = next((j for j in view.overview.jobs if row is not None and j.id == row.job_id), None)
        if job is None:
            ui.label("This case has not run yet.").classes("text-grey-7").mark("monitor-not-run")
            return
        ui.label(f"{row.status} in job {job.id}").mark("monitor-status")
        df = WATCHER.history(self.directory, job.id, self.case)
        if df.empty:
            ui.label("No history yet for this case.").classes("text-grey-7").mark("monitor-no-history")
        else:
            self._charts(df)
        ui.label("Solver log").classes("text-lg")
        log = WATCHER.log_tail(self.directory, job)
        ui.label(log if log is not None else "Log not available").classes(
            "font-mono text-xs whitespace-pre-wrap").mark("monitor-log")

    def _charts(self, df) -> None:
        x = iteration_values(df)
        ui.label("Residuals").classes("text-lg")
        ui.echart(line_options(x, df, residual_columns(df), "log10 residual")).classes(
            "w-full h-72").mark("chart-residuals")
        others = coefficient_columns(df)
        wanted = self.columns if self.columns is not None else list(DEFAULT_COEFFICIENTS)
        chosen = [column for column in wanted if column in others]
        ui.label("Coefficients").classes("text-lg")
        ui.select(others, multiple=True, value=chosen, label="Columns",
                  on_change=lambda e: self._set_columns(e.value)).classes("w-full").mark("monitor-columns")
        ui.echart(line_options(x, df, chosen, "value")).classes("w-full h-72").mark("chart-coefficients")
        _converged, message = check_convergence(df)
        ui.label(f"Convergence: {message}").mark("monitor-verdict")

    def _choose(self, case: str) -> None:
        self.case = case
        self.render()

    def _set_columns(self, columns) -> None:
        self.columns = list(columns or [])
        self.render()
```

- [ ] **Step 4: Sidebar and registration**

In `aerosuite/web/status.py` (`step_badges`), replace `"monitor": "later",` with `"monitor": "plain",`. In `aerosuite/web/layout.py`, add `"monitor": "monitor"` to `PAGE_OF_STEP`. In `aerosuite/web/app.py`, import `monitor` with the other pages and call `monitor.register()` after `run.register()`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_web_monitor.py tests/web/test_status.py -q`
Expected: all passed

- [ ] **Step 6: Update `README.md`**

In the Web UI "Pages:" list, change the Sweep line and add Run and Monitor after it:

```markdown
- **Sweep** (sweep on): Mach/α/β ranges, naming, restarts, checks, Generate. Each case restarts from `none` (a fresh start), `previous` (the case before it) or `custom` (a restart file, or a case folder such as another study's `runs/M0p8_a2_b0/` — the restart file inside is found for you).
- **Run**: checks, every case's latest status, and **Submit** for all or selected cases (*Failed*, *Unconverged*, *Not run* select them for you). *Continue from each case's last solution* reruns a case from where it stopped (on by default for unconverged cases). **Cancel** stops a running job; job history is listed below. The sweep keeps running when you close the browser or stop the server.
- **Monitor**: pick a case to see its residuals and coefficients against iteration, its convergence verdict and the end of the solver log, updating live while it runs.
```

Replace the sentence "Run, Monitor and Results arrive in phase 3b; until then use `aerosuite run / status / summarize`." with:

```markdown
Results arrive later; until then use `aerosuite summarize`.
```

After the paragraph "The web UI has no login, …", add:

```markdown
Because the web UI can start and cancel jobs, anyone with an account on the workstation can reach it at 127.0.0.1 while it runs; a login token is planned before AeroSuite is used on a shared machine.
```

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: all passed

```bash
git add aerosuite/web/pages/monitor.py aerosuite/web/status.py aerosuite/web/layout.py aerosuite/web/app.py README.md tests/web/test_web_monitor.py tests/web/test_status.py
git commit -m "feat(web): add the Monitor page and document Run and Monitor"
```

---

### Task 9: Visual click-through and the workstation check (controller)

This task is done by the controller in the browser pane, not by an implementer; it changes no code unless it finds a defect (which then goes through the normal fix loop).

- [ ] **Step 1: Start the server** on a scratch folder with a fake-sweep project: `SU2_RUN` set to any value, `run.sweep_python` = the uv interpreter, `run.sweep_script` = `tests/fixtures/fake_sweep.py`, a `configs/fake_plan.json` with one `hang`, one `diverge` and one `fail` case.
- [ ] **Step 2: Click through at 1280×800, light and dark scheme, with screenshots:** Sweep restart column (three options, `custom` path + Browse); Run page before any job (checks, all ticked, Submit); a running job (status RUNNING, spinner badge, Cancel); after it ends (FAILED tail expands, UNCONVERGED, selectors, Continue default and disabled state); a rerun; job history; Monitor for the running case, a finished case and a never-run case (charts readable, log tail); sidebar order and Results greyed.
- [ ] **Step 3: Hand the workstation check to the user** (spec §5): on the SU2 workstation, run one real sweep, then rerun one unconverged case with *Continue* ticked, and confirm from `runs/<case>/` and the solver log that SU2 restarted from the copied solution (`RESTART_SOL= YES`, the `custom` path under `jobs/<id>/restart/`).

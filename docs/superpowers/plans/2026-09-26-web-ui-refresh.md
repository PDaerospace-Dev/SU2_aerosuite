# Web UI Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every web UI page the approved "clean light dashboard" look (style A): a dark top bar, a collapsible sidebar of workflow steps, breadcrumbs with an actions slot, and white cards, pills, banners and tiles. No page changes what it does.

**Architecture:** One `theme.py` holds the colour tokens and all component CSS as `as-*` classes. One `ui_kit.py` puts those classes on NiceGUI widgets (cards, pills, banners, tiles, grid tables, fields, buttons). `layout.py`'s `ProjectFrame` is rebuilt as a plain-flex page (no Quasar drawer): top bar, sidebar, breadcrumb row with `frame.actions`, then `frame.content`. Pages are then restyled one by one using only kit helpers, with every existing `.mark(...)` kept on an element of the same meaning.

**Tech Stack:** Python 3.12, NiceGUI 3.17.1 (Quasar/Vue), ECharts through `ui.echart`, pytest with NiceGUI's simulated `user` fixture (`-p nicegui.testing.user_plugin`, `main_file = tests/web/main_app.py`), uv.

**Spec:** `docs/superpowers/specs/2026-09-26-web-ui-refresh-design.md`. Mockups: `docs/superpowers/specs/assets/2026-09-26-web-ui-refresh/` (`run.png`, `run-sidebar-collapsed.png`, `setup.png`, `sweep.png`, `monitor.png`, `topbar-reference.jpg`).

## Global Constraints

- Behaviour unchanged: every page does exactly what it does today. Out of scope: dark mode, a search box, the Results page, engine or CLI changes, README changes.
- Tokens (verbatim from spec §2.1): page `#f4f5f7`; card `#ffffff`, 1px border `#e3e5e8`, radius 10px, no shadow; text `#1f2328`, muted `#6a737d`; hairline `#eef0f2`; accent `#2f6fe4` (tint `#eef2ff`, text `#2f3fbf`); top bar `#0f1b2d`, controls `#16263d` with border `#2a3a52`, secondary text `#9fb0c8`; primary button `#1f2328` with white text; danger button white with border `#ffd7d5` and text `#a40e26`. Pills: Converged/Done `#dafbe1`/`#116329`; Running `#ddf4ff`/`#0550ae` (job dot `#58a6ff`); Failed `#ffebe9`/`#a40e26` (failure box bg `#fff5f5`, border `#ffd7d5`); Unconverged `#fff8c5`/`#7a5200`; Pending/Not run `#eef0f2`/`#57606a`; Cancelled white, border `#d0d7de`, text `#57606a`. Step dots: done `#1a7f37`, attention `#bf8700`, plain `#8c959f`, later `#d0d7de`.
- Fonts: the system stack `"Segoe UI", system-ui, -apple-system, Ubuntu, sans-serif`; mono `Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace`. No web fonts, because the workstation may be offline. Icons are NiceGUI's bundled Material icons.
- Sizes: body 13px; labels/hints 12px; card titles 14px/600; tile numbers 22px/600. Page padding 24–28px, gap between cards 14–16px, card padding 16px 18px, table cells 8–10px 14px.
- Top bar 52px. Sidebar 210px, collapsed 64px. The collapsed state is kept in browser `localStorage`, not in the project.
- Every existing `.mark(...)` marker stays on an element with the same meaning. A test may change only where it asserts layout itself, and the change must be named in the task report.
- Sentence case everywhere. No uppercase Quasar buttons (`no-caps`). At most one dark primary button per page, in the breadcrumb row's actions slot. Other buttons are outlined (secondary) or danger.
- Warnings and errors are banners above the content they concern, keeping the same text as today's labels. A clean state is one green dot line.
- Monospace for job ids, paths and cfg text only.
- Only kit helpers style widgets on pages. No hex colours or `text-negative`/`text-grey-*` classes in `aerosuite/web/pages/*.py` once a page's task is done.
- No SU2, MPI or real browser in tests. Everything passes on Windows and Linux. Run tests with `uv run pytest`. Baseline: **518 passed** on `a465ea9`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A recent project whose `project.json` is invalid (hand-edited, half-written)**: `load_recent()` keeps it because the file exists. The Projects page must still list it (folder name, no tag, no pill) and not crash. Pinned in Task 7 (`test_recent_projects_survives_an_unreadable_project`).
2. **A job record that cannot be read while the lock says a job runs**: the frame's job indicator must hide itself and the page must render; navigation never breaks. Pinned in Task 2 (`test_a_broken_job_state_hides_the_indicator_and_keeps_the_page`).
3. **Statuses the kit does not know, or enum members instead of strings** (a future `CaseState`, or `JobState.DONE` passed directly): the pill falls back to the grey "pending" tone and shows the value text. Pinned in Task 1 (`test_pill_tone_falls_back_and_reads_enum_values`).
4. **Very long project names and folder paths**: the switcher, breadcrumb and recent rows truncate with an ellipsis instead of pushing the top-bar controls off screen. The full text stays in the element. Pinned in Task 2 (`test_long_names_truncate_in_the_frame`). The Task 10 demo also uses a long-named project.
5. **More plottable columns than colours** (a file with 10+ residual/coefficient columns): colours cycle, and each checkbox swatch always matches its line even after columns are unticked. Pinned in Task 4 (`test_column_colours_cycle_and_stay_with_their_column`).

---

## File map

| File | Responsibility |
|---|---|
| `aerosuite/web/theme.py` (new) | Tokens, Quasar brand colours, all `as-*` component CSS, sidebar JS snippets, `apply_theme()` |
| `aerosuite/web/ui_kit.py` (new) | NiceGUI building blocks: `card`, `card_head`, `pill`, `set_pill`, `status_dot`, `banner`, `ok_line`, `summary_tile`, `field`, `hint`, `readonly`, `path_field`, `table`, `th`, `td`, `td_box`, `failure_row`, buttons |
| `aerosuite/web/guide.py` (new) | NiceGUI-free: `app_version()`, `web_ui_guide()` (README "## Web UI" section) |
| `aerosuite/web/jobs.py` | + `JobProgress`, `job_progress(view)` |
| `aerosuite/web/status.py` | + `project_kind(project)` |
| `aerosuite/web/recent.py` | + `RecentProject`, `recent_projects()` |
| `aerosuite/web/layout.py` | Rebuilt `ProjectFrame` and `header()`; `apply_theme`/`PAGE_CSS`/`BADGE_ICONS` removed |
| `aerosuite/web/fields.py` | `text_field` styled via `ui_kit.field`; new optional `mono` |
| `aerosuite/web/checks.py` | `generate_button()` split out of `render_checks()`; banners |
| `aerosuite/web/picker.py`, `preview.py`, `reference_panel.py` | Kit look |
| `aerosuite/web/pages/*.py` | Each page restyled (Tasks 3–9) |
| `tests/web/main_app.py` | + `/_test/kit` page |
| `tests/web/test_theme.py`, `test_ui_kit.py`, `test_guide.py`, `test_web_topbar.py` (new) | Kit, theme, guide, frame tests |
| `.superpowers/sdd/visual/demo.py`, `shoot.py` (controller only, git-ignored via `sdd`) | Demo projects and screenshots |

---

### Task 0 (controller only): baseline screenshots

No code. Produces the "before" images that each page task compares against.

- [ ] **Step 1: Write the demo builder** `.superpowers/sdd/visual/demo.py`:

```python
"""Controller-only: build the demo projects the visual checks screenshot (git-ignored).

usage: python demo.py make <root>   |   python demo.py stop <root>
Run with AEROSUITE_HOME=<root>/home so the Projects page lists the demo projects.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
from conftest import FAKE_SWEEP, TEMPLATE  # noqa: E402  the test template and fake sweep

from aerosuite.engine.cfg import CONFIGS_DIR, build_cases, generate_configs  # noqa: E402
from aerosuite.engine.jobs.local import LocalRunner  # noqa: E402
from aerosuite.engine.jobs.store import list_jobs  # noqa: E402
from aerosuite.engine.models import Project  # noqa: E402
from aerosuite.engine.project import open_project, save_project, set_mesh  # noqa: E402
from aerosuite.web.recent import add_recent  # noqa: E402

SWEEP = "visual-study"
AIRCRAFT = "visual-aircraft"
LONG_NAME = "x07-high-alpha-buffet-study-with-a-deliberately-long-project-name"


def _make(root: Path, folder: str, name: str, profile=None) -> Path:
    project_dir = root / folder
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "template.cfg").write_text(TEMPLATE)
    mesh = root / "wing.su2"
    mesh.write_text("NMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    project = Project(name=name)
    project.profile = profile
    set_mesh(project, mesh)
    project.sweep.mach = [0.8]
    project.sweep.alpha = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    project.run.sweep_python = sys.executable
    project.run.sweep_script = str(FAKE_SWEEP)
    save_project(project_dir, project)
    add_recent(project_dir)
    return project_dir


def make(root: Path) -> None:
    _make(root, AIRCRAFT, LONG_NAME, profile="x07")
    sweep = _make(root, SWEEP, SWEEP)
    project = open_project(sweep)
    generate_configs(sweep, project)
    names = [case.name for case in project.cases]
    plan = {"delay": 1.0, "cases": {names[1]: "fail", names[2]: "diverge", names[4]: "hang"}}
    (sweep / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps(plan))
    job = LocalRunner().submit(sweep, project)
    print(f"demo at {root}; job {job.id} runs until `demo.py stop`")


def stop(root: Path) -> None:
    runner = LocalRunner()
    for job in list_jobs(root / SWEEP):
        if job.is_active:
            runner.cancel(root / SWEEP, job)


if __name__ == "__main__":
    {"make": make, "stop": stop}[sys.argv[1]](Path(sys.argv[2]).resolve())
```

- [ ] **Step 2: Write the screenshot script** `.superpowers/sdd/visual/shoot.py`:

```python
"""Controller-only: screenshot every web UI page of the demo with a headless Chrome/Edge (git-ignored).

usage: python shoot.py <demo root> <out dir> <tag> [port]     e.g. tag = before | after
"""
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

CANDIDATES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "google-chrome", "chromium", "chromium-browser", "msedge"]
SIZES = [(1280, 800), (1920, 1080)]


def browser() -> str:
    for candidate in CANDIDATES:
        found = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if found:
            return found
    sys.exit("no Chrome or Edge found")


def pages(root: Path) -> list[tuple[str, str]]:
    def at(page: str, folder: str) -> str:
        return f"/{page}?project={quote(str((root / folder).resolve()), safe='')}"

    return [("projects", "/"), ("setup", at("setup", "visual-study")), ("config", at("config", "visual-study")),
            ("sweep", at("sweep", "visual-study")), ("run", at("run", "visual-study")),
            ("monitor", at("monitor", "visual-study")), ("aircraft", at("aircraft", "visual-aircraft"))]


def main() -> None:
    root, out, tag = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), sys.argv[3]
    port = sys.argv[4] if len(sys.argv) > 4 else "8765"
    out.mkdir(parents=True, exist_ok=True)
    exe = browser()
    for name, path in pages(root):
        for width, height in SIZES:
            target = (out / f"{tag}-{name}-{width}x{height}.png").resolve()
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={width},{height}", "--virtual-time-budget=8000",
                            f"--screenshot={target}", f"http://127.0.0.1:{port}{path}"], check=True, timeout=90)
            print(target)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Build the demo, start the server, shoot "before"** (Git Bash):

```bash
export AEROSUITE_HOME="$PWD/.superpowers/sdd/visual/demo/home"
uv run python .superpowers/sdd/visual/demo.py make .superpowers/sdd/visual/demo
uv run aerosuite serve --root .superpowers/sdd/visual/demo --port 8765   # run_in_background
uv run python .superpowers/sdd/visual/shoot.py .superpowers/sdd/visual/demo .superpowers/sdd/visual/shots before
```

Expected: 14 PNGs in `.superpowers/sdd/visual/shots/`. If headless screenshots come out blank (the page's websocket never settles under virtual time), use the Browser pane instead (`preview_start` with the URL, `resize_window` 1280×800 / 1920×1080, `computer` screenshot) and save notes of what each page looks like. Keep the server running for later tasks, or restart it after each task (a page task changes Python code, so **restart the server before each "after" shot**).

---

### Task 1: Theme, UI kit and styled fields

**Files:**
- Create: `aerosuite/web/theme.py`, `aerosuite/web/ui_kit.py`
- Modify: `aerosuite/web/fields.py`, `tests/web/main_app.py`
- Test: `tests/web/test_theme.py`, `tests/web/test_ui_kit.py`, `tests/web/test_web_base.py`

**Interfaces:**
- Consumes: `aerosuite.engine.jobs.overview.NOT_RUN` (`"NOT_RUN"`); `aerosuite.web.picker.pick_path(title, *, mode, suffixes=(), start=None) -> Optional[Path]`.
- Produces (used by every later task):
  - `theme.apply_theme() -> None`; constants `SERIES_COLORS: list[str]`, `BADGE_COLORS: list[str]`, `HAIRLINE: str`, `SIDEBAR_KEY`, `RESTORE_SIDEBAR`, `TOGGLE_SIDEBAR: str`, `PILL_COLORS: dict[str, tuple[str, str, str]]`.
  - `ui_kit.card(title=None, subtitle=None, *, flush=False)` (context manager yielding `ui.column`); `card_head(title=None, subtitle=None) -> ui.row`; `pill(status) -> ui.label`; `set_pill(label, status)`; `pill_tone(status) -> str`; `pill_text(status) -> str`; `status_dot(state) -> ui.element`; `banner(kind, text) -> ui.label`; `ok_line(text) -> ui.label`; `summary_tile(label, value, tone=None) -> ui.label` (the value label); `field(widget, *, mono=False)` (returns widget); `hint(text="") -> ui.label`; `readonly(text, *, mono=False) -> ui.label`; `path_field(label, *, mark, browse_mark, title, mode, suffixes=()) -> ui.input`; `table(columns: str) -> ui.grid`; `th(text="")`, `td(text="", *, mono=False, strong=False) -> ui.label`; `td_box()` (context manager yielding `ui.row`); `failure_row(text) -> ui.label`; `primary_button`, `secondary_button`, `danger_button`, `flat_button(text, on_click=None, *, icon=None) -> ui.button`; `chip_button(text, on_click=None) -> ui.button`.
  - `fields.text_field(label, value, on_commit, *, mark, placeholder="", mono=False) -> ui.input` (same as today plus `mono`).

- [ ] **Step 1: Write the failing tests**

`tests/web/test_theme.py`:

```python
from aerosuite.web import theme
from aerosuite.web.ui_kit import PILL_TONES


def test_every_pill_tone_has_css():
    css = theme.component_css()
    for tone in set(PILL_TONES.values()):
        assert tone in theme.PILL_COLORS
        assert f".as-pill-{tone} " in css


def test_the_tokens_are_the_specs():
    assert theme.PAGE_BG == "#f4f5f7" and theme.CARD_BORDER == "#e3e5e8" and theme.TOPBAR == "#0f1b2d"
    assert theme.PILL_COLORS["failed"][:2] == ("#ffebe9", "#a40e26")
    assert theme.PILL_COLORS["cancelled"] == ("#ffffff", "#57606a", "#d0d7de")


def test_the_sidebar_scripts_survive_blocked_storage():
    # localStorage throws in some private windows: both snippets must swallow that.
    for script in (theme.RESTORE_SIDEBAR, theme.TOGGLE_SIDEBAR):
        assert "try" in script and "catch" in script and theme.SIDEBAR_KEY in script
    assert "as-mini" in theme.RESTORE_SIDEBAR and "as-mini" in theme.TOGGLE_SIDEBAR
```

`tests/web/test_ui_kit.py`:

```python
import pytest
from nicegui.testing import User

from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.web.ui_kit import pill_text, pill_tone

TONES = {"CONVERGED": "done", "DONE": "done", "RUNNING": "running", "FAILED": "failed",
         "UNCONVERGED": "unconverged", "PENDING": "pending", "QUEUED": "pending", "NOT_RUN": "pending",
         "CANCELLED": "cancelled"}


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


@pytest.mark.parametrize("status, tone", TONES.items())
def test_pill_tone_maps_every_case_and_job_status(status, tone):
    assert pill_tone(status) == tone


def test_pill_tone_falls_back_and_reads_enum_values():
    assert pill_tone("SOMETHING_NEW") == "pending"
    assert pill_tone(CaseState.RUNNING) == "running"
    assert pill_tone(JobState.DONE) == "done"
    assert pill_text(CaseState.RUNNING) == "RUNNING"
    assert pill_text("NOT_RUN") == "Not run"


async def test_pills_colour_every_status_and_keep_its_text(user: User):
    await user.open("/_test/kit")
    for status, tone in TONES.items():
        label = _element(user, f"t-pill-{status}")
        assert f"as-pill-{tone}" in label.classes
        assert label.text == ("Not run" if status == "NOT_RUN" else status)


async def test_banners_carry_their_kind_and_text(user: User):
    await user.open("/_test/kit")
    for kind in ("info", "warning", "error", "success"):
        label = _element(user, f"t-banner-{kind}")
        assert label.text == f"{kind} text"
        assert f"as-banner-{kind}" in label.parent_slot.parent.classes


async def test_tiles_cards_and_buttons(user: User):
    await user.open("/_test/kit")
    assert _element(user, "t-tile").text == "3"
    assert "as-tile-danger" in _element(user, "t-tile-danger").parent_slot.parent.classes
    assert "as-card" in _element(user, "t-card").classes
    assert "as-btn-primary" in _element(user, "t-primary").classes
    assert "as-btn-danger" in _element(user, "t-danger").classes
    assert _element(user, "t-ok").text == "All good"
```

Append to `tests/web/test_web_base.py`:

```python
async def test_text_fields_have_the_field_look(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(f"/_test/base?project={quote(str(project_dir), safe='')}")
    field = next(iter(user.find(marker="t-partitions").elements))
    assert "as-field" in field.classes
```

(Check the top of `test_web_base.py` for how it builds the `/_test/base` URL and reuse that helper instead of `quote` if one exists; add `from urllib.parse import quote` only if it is not already imported.)

Add to `tests/web/main_app.py`, after the `/_test/reference` page and before `ui.run(...)`:

```python
from aerosuite.web import ui_kit  # noqa: E402
from aerosuite.web.theme import apply_theme  # noqa: E402


@ui.page("/_test/kit")
def _test_kit_page() -> None:
    """Test-only page: one of each ui_kit building block."""
    apply_theme()
    for status in ("CONVERGED", "DONE", "RUNNING", "FAILED", "UNCONVERGED", "PENDING", "QUEUED", "NOT_RUN",
                   "CANCELLED"):
        ui_kit.pill(status).mark(f"t-pill-{status}")
    for kind in ("info", "warning", "error", "success"):
        ui_kit.banner(kind, f"{kind} text").mark(f"t-banner-{kind}")
    ui_kit.ok_line("All good").mark("t-ok")
    ui_kit.summary_tile("Converged", 3).mark("t-tile")
    ui_kit.summary_tile("Needs attention", 2, "danger").mark("t-tile-danger")
    with ui_kit.card("Title", "Subtitle") as box:
        box.mark("t-card")
        ui_kit.primary_button("Go").mark("t-primary")
        ui_kit.danger_button("Stop").mark("t-danger")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_theme.py tests/web/test_ui_kit.py tests/web/test_web_base.py -q`
Expected: FAIL / collection errors (`ModuleNotFoundError: No module named 'aerosuite.web.theme'`).

- [ ] **Step 3: Write `aerosuite/web/theme.py`**

```python
"""The web UI's look in one place: colour tokens, Quasar's brand colours and the component CSS.

Pages never style widgets themselves: aerosuite.web.ui_kit puts these `as-*` classes on them.
"""
from nicegui import ui

PAGE_BG = "#f4f5f7"
CARD_BORDER = "#e3e5e8"
TEXT = "#1f2328"
MUTED = "#6a737d"
HAIRLINE = "#eef0f2"
ACCENT = "#2f6fe4"
ACCENT_TINT = "#eef2ff"
ACCENT_TEXT = "#2f3fbf"
TOPBAR = "#0f1b2d"
TOPBAR_CONTROL = "#16263d"
TOPBAR_BORDER = "#2a3a52"
TOPBAR_MUTED = "#9fb0c8"
RUNNING_DOT = "#58a6ff"
FONT = '"Segoe UI", system-ui, -apple-system, Ubuntu, sans-serif'
MONO = 'Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace'

# pill tone -> (background, text, border)
PILL_COLORS = {
    "done": ("#dafbe1", "#116329", "#dafbe1"),
    "running": ("#ddf4ff", "#0550ae", "#ddf4ff"),
    "failed": ("#ffebe9", "#a40e26", "#ffebe9"),
    "unconverged": ("#fff8c5", "#7a5200", "#fff8c5"),
    "pending": ("#eef0f2", "#57606a", "#eef0f2"),
    "cancelled": ("#ffffff", "#57606a", "#d0d7de"),
}
# sidebar step badge -> dot colour ("todo" is a grey ring, drawn in BASE_CSS)
DOT_COLORS = {"done": "#1a7f37", "attention": "#bf8700", "running": RUNNING_DOT, "plain": "#8c959f",
              "later": "#d0d7de"}
# banner kind -> (background, border, text)
BANNER_COLORS = {
    "info": ("#ddf4ff", "#b6e3ff", "#0550ae"),
    "warning": ("#fff8c5", "#eed888", "#7a5200"),
    "error": ("#ffebe9", "#ffd7d5", "#a40e26"),
    "success": ("#dafbe1", "#aceebb", "#116329"),
}
# Monitor chart lines and their checkbox swatches, by column position
SERIES_COLORS = ["#2f6fe4", "#8250df", "#1a7f37", "#bf8700", "#cf222e", "#0a7ea4", "#e16f24", "#6e7781"]
# the project switcher's initials badge, picked by the project name
BADGE_COLORS = ["#8250df", "#2f6fe4", "#1a7f37", "#bf3989", "#0a7ea4", "#bc4c00"]

SIDEBAR_KEY = "aerosuite-sidebar"
# Runs in <head> before the page is drawn, so a collapsed sidebar never flashes open first.
RESTORE_SIDEBAR = ("<script>try { if (localStorage.getItem('%s') === 'mini') "
                   "document.documentElement.classList.add('as-mini'); } catch (e) {}</script>" % SIDEBAR_KEY)
TOGGLE_SIDEBAR = ("const mini = document.documentElement.classList.toggle('as-mini');"
                  "try { localStorage.setItem('%s', mini ? 'mini' : 'full'); } catch (e) {}" % SIDEBAR_KEY)

BASE_CSS = """
body { background: var(--as-page); color: var(--as-text); font-family: var(--as-font); font-size: 13px; }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.as-mono { font-family: var(--as-mono); font-size: 12px; }
.as-muted, .as-hint { color: var(--as-muted); font-size: 12px; }
.as-hint-warning { color: #7a5200; }
.as-error-text { color: #a40e26; font-size: 12px; }
.as-strong { font-weight: 500; }
.as-label { font-size: 12px; color: var(--as-muted); }
.as-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }

.as-topbar { position: sticky; top: 0; z-index: 2000; height: 52px; padding: 0 16px; gap: 14px;
  background: var(--as-topbar); color: #fff; flex-wrap: nowrap; align-items: center; }
.as-brand { width: 194px; gap: 10px; color: #fff; text-decoration: none; align-items: center; flex-wrap: nowrap; }
.as-logo-mark { width: 28px; height: 28px; border-radius: 7px; background: var(--as-accent); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; }
.as-logo-text { font-size: 16px; font-weight: 600; color: #fff; }
.as-topbar-control { background: var(--as-topbar-control); border: 1px solid var(--as-topbar-border);
  border-radius: 8px; color: #fff; }
.as-topbar-muted { color: var(--as-topbar-muted); }
.as-topbar-icon { width: 30px; height: 30px; min-height: 30px; padding: 0; border: 1px solid var(--as-topbar-border);
  border-radius: 7px; color: var(--as-topbar-muted); }
.as-topbar-icon.as-round { border-radius: 50%; }
html.as-mini .as-when-full, html:not(.as-mini) .as-when-mini { display: none; }
.as-job { padding: 6px 12px; gap: 10px; cursor: pointer; align-items: center; flex-wrap: nowrap; }
.as-job-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--as-running);
  box-shadow: 0 0 0 3px rgba(88, 166, 255, .25); }
.as-job-bar { width: 90px; height: 5px; border-radius: 3px; background: var(--as-topbar-border); overflow: hidden; }
.as-job-fill { height: 100%; background: var(--as-running); }
.as-switcher { padding: 4px 10px 4px 4px; gap: 8px; cursor: pointer; align-items: center; flex-wrap: nowrap;
  max-width: 22rem; }
.as-initials { width: 26px; height: 26px; border-radius: 6px; display: inline-flex; align-items: center;
  justify-content: center; font-weight: 600; color: #fff; flex: none; }
.as-switcher-name { font-size: 13px; line-height: 1.15; max-width: 16rem; }
.as-switcher-kind { font-size: 11px; line-height: 1.15; }

.as-body { min-height: calc(100vh - 52px); flex-wrap: nowrap; align-items: stretch; gap: 0; }
.as-sidebar { width: 210px; min-width: 210px; background: #fff; border-right: 1px solid var(--as-border);
  padding: 14px 12px; gap: 2px; transition: width .15s, min-width .15s; }
html.as-mini .as-sidebar { width: 64px; min-width: 64px; }
html.as-mini .as-step-name { display: none; }
html:not(.as-mini) .as-step-tip { display: none !important; }
.as-step { position: relative; gap: 12px; padding: 8px 10px; border-radius: 8px; color: #57606a;
  text-decoration: none; align-items: center; flex-wrap: nowrap; }
a.as-step:hover { background: #f6f8fa; }
.as-step-current, a.as-step-current:hover { background: var(--as-accent-tint); color: var(--as-accent-text);
  font-weight: 600; }
.as-step-later { color: #b0b7c0; cursor: default; }
.as-step .as-dot { position: absolute; top: 6px; left: 26px; border: 1.5px solid #fff; box-sizing: content-box; }
.as-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
.as-dot-todo { background: #fff; box-shadow: inset 0 0 0 1.5px #8c959f; }
.as-main { flex: 1; min-width: 0; padding: 14px 28px 28px; gap: 14px; }
.as-crumbs { gap: 10px; min-height: 36px; align-items: center; flex-wrap: nowrap; }
.as-crumb-link { color: var(--as-muted); text-decoration: none; }
.as-crumb-link:hover { color: var(--as-accent); }
.as-crumb-project { max-width: 24rem; }
.as-crumb-sep { color: #c4c9cf; }
.as-crumb-current { font-weight: 600; }
.as-content { gap: 14px; }
.as-page { padding: 14px 28px 28px; gap: 14px; }

.as-card { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 16px 18px;
  gap: 12px; box-shadow: none; }
.as-card-flush { padding: 0; gap: 0; overflow: hidden; }
.as-card-head { gap: 8px; align-items: center; flex-wrap: nowrap; }
.as-card-flush > .as-card-head { padding: 12px 14px; }
.as-card-title { font-size: 14px; font-weight: 600; }
.as-card-subtitle { font-size: 12px; color: var(--as-muted); }
.as-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-tile { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 16px; gap: 0; }
.as-tile-label { font-size: 12px; color: var(--as-muted); }
.as-tile-value { font-size: 22px; font-weight: 600; }
.as-tile-danger .as-tile-value { color: #a40e26; }
.as-pill { display: inline-block; padding: 1px 10px; border: 1px solid; border-radius: 999px; font-size: 12px;
  line-height: 18px; white-space: nowrap; text-transform: lowercase; }
.as-pill::first-letter { text-transform: uppercase; }
.as-tag { display: inline-block; padding: 1px 8px; border-radius: 6px; background: var(--as-hairline);
  color: #57606a; font-size: 12px; white-space: nowrap; }
.as-banner { width: 100%; padding: 8px 12px; gap: 8px; border: 1px solid; border-radius: 8px;
  align-items: flex-start; flex-wrap: nowrap; }
.as-banner .q-icon { font-size: 18px; }
.as-ok-line { gap: 8px; align-items: center; color: #116329; flex-wrap: nowrap; }
.as-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }

.as-table { display: grid; gap: 0; width: 100%; align-items: stretch; }
.as-th { padding: 9px 14px; font-size: 12px; font-weight: 500; color: var(--as-muted); }
.as-td { padding: 8px 14px; border-top: 1px solid var(--as-hairline); min-height: 40px; display: flex;
  align-items: center; flex-wrap: nowrap; gap: 8px; }
.as-td-failure { padding: 0 14px 8px; }
.as-failure { background: #fff5f5; border: 1px solid #ffd7d5; border-radius: 6px; padding: 7px 10px;
  font-family: var(--as-mono); font-size: 12px; color: #a40e26; white-space: pre-wrap; }
.as-dup { color: #a40e26; font-weight: 600; }
.as-recent-row { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: inherit;
  text-decoration: none; border-top: 1px solid var(--as-hairline); }
.as-recent-row:hover { background: #f6f8fa; }

.as-btn { text-transform: none; border-radius: 8px; font-weight: 500; min-height: 32px; padding: 0 14px; }
.as-btn-primary { background: #1f2328; color: #fff; }
.as-btn-secondary { background: #fff; color: var(--as-text); border: 1px solid var(--as-border); }
.as-btn-danger { background: #fff; color: #a40e26; border: 1px solid #ffd7d5; }
.as-btn-flat { background: transparent; color: var(--as-text); }
.as-chip { background: #fff; color: var(--as-text); border: 1px solid var(--as-border); border-radius: 6px;
  min-height: 26px; padding: 0 10px; font-weight: 400; text-transform: none; }
.as-chip:hover { background: var(--as-accent-tint); color: var(--as-accent-text); }

.as-field .q-field__control { border-radius: 8px; }
.as-field.as-mono input, .as-field.as-mono textarea { font-family: var(--as-mono); font-size: 12px; }
.as-readonly { border: 1px solid var(--as-border); border-radius: 8px; padding: 8px 10px; background: #fafbfc;
  min-height: 36px; word-break: break-all; }
.as-choice { display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-choice > div { margin: 0 !important; }
.as-choice .q-radio { width: 100%; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 12px; }
.as-choice .q-radio[aria-checked="true"] { border: 2px solid var(--as-accent); padding: 9px 11px; }
.as-choice-tile { border: 1px solid var(--as-border); border-radius: 10px; padding: 12px; background: #fff;
  cursor: pointer; gap: 2px; }
.as-choice-selected { border: 2px solid var(--as-accent); padding: 11px; }

.as-grid-2, .as-grid-3, .as-grid-form, .as-columns, .as-monitor { display: grid; gap: 14px; width: 100%;
  align-items: start; }
.as-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.as-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.as-grid-form { grid-template-columns: minmax(12rem, auto) minmax(0, 1fr); gap: 8px 14px; align-items: center; }
.as-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.as-columns-projects { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); }
.as-monitor { grid-template-columns: 250px minmax(0, 1fr); gap: 16px; }
@media (max-width: 900px) {
  .as-grid-2, .as-grid-3, .as-columns, .as-columns-projects, .as-monitor, .as-tiles { grid-template-columns: 1fr; }
}

.q-dialog .q-card { border-radius: 10px; box-shadow: 0 8px 24px rgba(31, 35, 40, .14); padding: 18px; gap: 12px; }
.as-dialog-title { font-size: 14px; font-weight: 600; }
.q-menu { border-radius: 8px; }
"""


def _variables() -> str:
    tokens = {"page": PAGE_BG, "border": CARD_BORDER, "text": TEXT, "muted": MUTED, "hairline": HAIRLINE,
              "accent": ACCENT, "accent-tint": ACCENT_TINT, "accent-text": ACCENT_TEXT, "topbar": TOPBAR,
              "topbar-control": TOPBAR_CONTROL, "topbar-border": TOPBAR_BORDER, "topbar-muted": TOPBAR_MUTED,
              "running": RUNNING_DOT, "font": FONT, "mono": MONO}
    return ":root { " + " ".join(f"--as-{name}: {value};" for name, value in tokens.items()) + " }\n"


def component_css() -> str:
    """Every rule the kit's classes need: tokens as CSS variables, the base rules, then generated colours."""
    pills = "".join(f".as-pill-{tone} {{ background: {bg}; color: {fg}; border-color: {border}; }}\n"
                    for tone, (bg, fg, border) in PILL_COLORS.items())
    dots = "".join(f".as-dot-{state} {{ background: {color}; }}\n" for state, color in DOT_COLORS.items())
    banners = "".join(f".as-banner-{kind} {{ background: {bg}; border-color: {border}; color: {fg}; }}\n"
                      for kind, (bg, border, fg) in BANNER_COLORS.items())
    return _variables() + BASE_CSS + pills + dots + banners


def apply_theme() -> None:
    """Colours, fonts and component CSS for the current page; call once per page before building it."""
    ui.colors(primary=ACCENT, secondary="#57606a", accent=ACCENT, positive="#1a7f37", negative="#a40e26",
              warning="#bf8700", info="#0550ae")
    ui.add_head_html(RESTORE_SIDEBAR)
    ui.add_css(component_css())
```

- [ ] **Step 4: Write `aerosuite/web/ui_kit.py`**

```python
"""Shared building blocks for every page (NiceGUI only): cards, pills, banners, tiles, tables, fields
and buttons. Pages use these instead of styling widgets themselves; the look lives in theme.py."""
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Literal, Optional, Sequence

from nicegui import ui

from ..engine.jobs.overview import NOT_RUN

Tone = Literal["done", "running", "failed", "unconverged", "pending", "cancelled"]
BannerKind = Literal["info", "warning", "error", "success"]

PILL_TONES: dict[str, Tone] = {
    "CONVERGED": "done", "DONE": "done",
    "RUNNING": "running",
    "FAILED": "failed",
    "UNCONVERGED": "unconverged",
    "PENDING": "pending", "QUEUED": "pending", NOT_RUN: "pending",
    "CANCELLED": "cancelled",
}
BANNER_ICONS = {"info": "info", "warning": "warning", "error": "error", "success": "check_circle"}


def _value(status: Any) -> str:
    """A CaseState/JobState member's value, or the string itself."""
    return str(getattr(status, "value", status))


def pill_tone(status: Any) -> Tone:
    """The colour family of a case or job status; unknown statuses are grey ("pending")."""
    return PILL_TONES.get(_value(status).upper(), "pending")


def pill_text(status: Any) -> str:
    """What a pill says: the status as the pages always named it ("Not run" for NOT_RUN).

    CSS shows it in sentence case ("CONVERGED" reads "Converged"); the element's text is unchanged.
    """
    value = _value(status)
    return "Not run" if value == NOT_RUN else value


def pill(status: Any) -> ui.label:
    return ui.label(pill_text(status)).classes(f"as-pill as-pill-{pill_tone(status)}")


def set_pill(label: ui.label, status: Any) -> None:
    """Change a pill in place (keeps its markers)."""
    label.set_text(pill_text(status))
    label.classes(replace=f"as-pill as-pill-{pill_tone(status)}")


def status_dot(state: str) -> ui.element:
    """A small round dot: a sidebar step badge (done, attention, todo, running, plain, later)."""
    return ui.element("span").classes(f"as-dot as-dot-{state}")


def banner(kind: BannerKind, text: str) -> ui.label:
    """A coloured message box; returns its text label, which is where markers go."""
    with ui.row().classes(f"as-banner as-banner-{kind}"):
        ui.icon(BANNER_ICONS[kind])
        return ui.label(text).classes("grow")


def ok_line(text: str) -> ui.label:
    """The clean state: one green dot and a line of text; returns the text label."""
    with ui.row().classes("as-ok-line"):
        status_dot("done")
        return ui.label(text)


@contextmanager
def card(title: Optional[str] = None, subtitle: Optional[str] = None, *,
         flush: bool = False) -> Iterator[ui.column]:
    """A white card; `flush` drops the padding for a card that holds a table."""
    with ui.column().classes("as-card w-full" + (" as-card-flush" if flush else "")) as box:
        if title is not None or subtitle is not None:
            card_head(title, subtitle)
        yield box


def card_head(title: Optional[str] = None, subtitle: Optional[str] = None) -> ui.row:
    """A card's title row; enter it (`with card_head(...):`) to add controls after the title."""
    with ui.row().classes("as-card-head w-full") as head:
        if title is not None:
            ui.label(title).classes("as-card-title")
        if subtitle is not None:
            ui.label(subtitle).classes("as-card-subtitle")
    return head


def summary_tile(label: str, value: object, tone: Optional[Literal["danger"]] = None) -> ui.label:
    """A number with a caption above it; returns the number's label."""
    with ui.column().classes("as-tile" + (f" as-tile-{tone}" if tone else "")):
        ui.label(label).classes("as-tile-label")
        return ui.label(str(value)).classes("as-tile-value")


def field(widget, *, mono: bool = False):
    """Style an input, select or textarea as a form field (outlined box, label above the value)."""
    widget.props("outlined dense stack-label").classes("as-field" + (" as-mono" if mono else ""))
    return widget


def hint(text: str = "") -> ui.label:
    return ui.label(text).classes("as-hint")


def readonly(text: str, *, mono: bool = False) -> ui.label:
    """A value shown in a field-like box that cannot be edited."""
    return ui.label(text).classes("as-readonly w-full" + (" as-mono" if mono else ""))


def path_field(label: str, *, mark: str, browse_mark: str, title: str,
               mode: Literal["file", "folder", "any"], suffixes: Sequence[str] = ()) -> ui.input:
    """An input for a workstation path with a Browse button that fills it from the picker."""
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        box = field(ui.input(label), mono=True).classes("grow").mark(mark)

        async def browse() -> None:
            from .picker import pick_path  # imported here: the picker itself uses this module's buttons

            chosen = await pick_path(title, mode=mode, suffixes=suffixes)
            if chosen is not None:
                box.value = str(chosen)

        secondary_button("Browse", on_click=browse).mark(browse_mark)
    return box


def table(columns: str) -> ui.grid:
    """A table drawn as a CSS grid: `columns` is its grid-template-columns; each direct child is a cell."""
    return ui.grid().classes("as-table").style(f"grid-template-columns: {columns}")


def th(text: str = "") -> ui.label:
    return ui.label(text).classes("as-th")


def td(text: str = "", *, mono: bool = False, strong: bool = False) -> ui.label:
    return ui.label(text).classes("as-td" + (" as-mono as-muted" if mono else "") + (" as-strong" if strong else ""))


@contextmanager
def td_box() -> Iterator[ui.row]:
    """A cell that holds widgets (a checkbox, a select, a pill)."""
    with ui.row().classes("as-td") as box:
        yield box


def failure_row(text: str) -> ui.label:
    """A red box spanning the whole table row under a failed case; returns the box (markers go on it)."""
    with ui.element("div").classes("as-td-failure").style("grid-column: 1 / -1"):
        return ui.label(text).classes("as-failure")


def _button(text: str, kind: str, on_click: Optional[Callable] = None, icon: Optional[str] = None) -> ui.button:
    return ui.button(text, on_click=on_click, icon=icon, color=None).props("unelevated no-caps").classes(
        f"as-btn as-btn-{kind}")


def primary_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    """The page's one main action (dark)."""
    return _button(text, "primary", on_click, icon)


def secondary_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "secondary", on_click, icon)


def danger_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "danger", on_click, icon)


def flat_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "flat", on_click, icon)


def chip_button(text: str, on_click: Optional[Callable] = None) -> ui.button:
    """A small filter chip (Run's All / Failed / ... selectors)."""
    return ui.button(text, on_click=on_click, color=None).props("unelevated no-caps dense").classes("as-chip")
```

- [ ] **Step 5: Style `text_field`** in `aerosuite/web/fields.py` (replace the body; the commit logic is unchanged):

```python
"""An input that autosaves: commit on blur or Enter, show the engine's error under the field."""
from typing import Callable, Optional

from nicegui import ui

from .ui_kit import field

Commit = Callable[[str], Optional[str]]  # returns an error message, or None when saved


def text_field(label: str, value: object, on_commit: Commit, *, mark: str, placeholder: str = "",
               mono: bool = False) -> ui.input:
    box = field(ui.input(label, value="" if value is None else str(value), placeholder=placeholder), mono=mono)
    box.classes("w-full").mark(mark)
    error = ui.label("").classes("as-error-text").mark(f"{mark}-error")
    last = {"text": box.value or ""}

    def commit() -> None:
        text = box.value or ""
        if text == last["text"] and not error.text:
            return
        message = on_commit(text)
        error.text = message or ""
        if message is None:
            last["text"] = text

    box.on("blur", commit)
    box.on("keydown.enter", commit)
    return box
```

- [ ] **Step 6: Run the new tests, then the whole suite**

Run: `uv run pytest tests/web/test_theme.py tests/web/test_ui_kit.py tests/web/test_web_base.py -q` → PASS.
Run: `uv run pytest -q` → all pass (518 + the new tests). `layout.apply_theme` still exists at this point; the frame switches over in Task 2.

- [ ] **Step 7: Commit**

```bash
git add aerosuite/web/theme.py aerosuite/web/ui_kit.py aerosuite/web/fields.py tests/web/main_app.py tests/web/test_theme.py tests/web/test_ui_kit.py tests/web/test_web_base.py
git commit -m "feat(web): add the refresh theme, the shared UI kit and styled text fields

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The new page frame (top bar, sidebar, breadcrumbs, job indicator, help)

**Files:**
- Create: `aerosuite/web/guide.py`
- Modify: `aerosuite/web/layout.py` (rewrite), `aerosuite/web/jobs.py`, `aerosuite/web/status.py`, and the page-title line in `aerosuite/web/pages/{run,monitor,sweep,setup,config,aircraft}.py`
- Test: `tests/web/test_guide.py`, `tests/web/test_web_topbar.py` (new); `tests/web/test_jobs.py`, `tests/web/test_status.py` (append)

**Interfaces:**
- Consumes: Task 1's `apply_theme`, `TOGGLE_SIDEBAR`, `BADGE_COLORS`, `status_dot`, `banner`; `WATCHER.state(project_dir, project) -> JobView`; `active_lock(project_dir) -> Optional[dict]` (`aerosuite.engine.jobs.store`); `load_recent() -> list[Path]`; `step_badges`, `visible_steps`, `STEPS`.
- Produces:
  - `ProjectFrame(session, active, on_reload)` with `.session`, `.active`, `.content: ui.column`, **`.actions: ui.row`** (breadcrumb-row slot for page buttons), `.refresh()`, `.ensure_current(notify=True)`, `.save(change, then=None)`. These behave as today, except `refresh()` now also redraws the switcher, the breadcrumb and the job indicator.
  - `header() -> None` (top bar for pages outside a project).
  - `layout.initials(name) -> str`, `layout.badge_color(name) -> str`, `layout.PAGE_TITLES: dict[str, str]`.
  - New markers: `project-switcher`, `project-name` (kept), `project-kind`, `project-menu`, `menu-all-projects`, `menu-recent-<folder>`, `sidebar`, `sidebar-toggle`, `step-<key>`, `badge-<key>-<badge>` (kept, now on the dot), `crumb-projects`, `crumb-project`, `crumb-page`, `page-actions`, `job-indicator`, `job-progress`, `help`, `help-menu`, `help-version`, `help-guide`, `guide-text`.
  - `guide.app_version() -> str`, `guide.web_ui_guide(readme: Path = README) -> str`, `guide.MISSING: str`.
  - `jobs.JobProgress(finished: int, total: int, current: Optional[str])` with `.text -> str` (`"4 / 6 · M0p8_a8_b0"` or `"4 / 6"`) and `.percent -> int`; `jobs.job_progress(view: JobView) -> Optional[JobProgress]`.
  - `status.project_kind(project) -> str` (`"sweep · 3 cases"`, `"sweep · 1 case"`, `"single case"`).

- [ ] **Step 1: Write the failing tests**

`tests/web/test_guide.py`:

```python
from aerosuite.web.guide import MISSING, README, app_version, web_ui_guide


def test_the_guide_is_the_readmes_web_ui_section(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n## Web UI\nStart it.\n### Sub\nMore.\n## Command line\nNot this.\n",
                      encoding="utf-8")
    assert web_ui_guide(readme) == "Start it.\n### Sub\nMore."


def test_a_missing_readme_or_section_says_so(tmp_path):
    assert web_ui_guide(tmp_path / "nope.md") == MISSING
    other = tmp_path / "README.md"
    other.write_text("# Title\n## Other\n", encoding="utf-8")
    assert web_ui_guide(other) == MISSING


def test_the_repository_readme_has_the_section():
    assert "Pages:" in web_ui_guide(README)


def test_version_is_a_string():
    assert isinstance(app_version(), str) and app_version()
```

Append to `tests/web/test_jobs.py` (reuse its existing imports; add any of these that are missing):

```python
from aerosuite.engine.jobs.overview import CaseOverview
from aerosuite.engine.jobs.runner import CaseState, JobRecord, JobState
from aerosuite.web.jobs import JobProgress, JobView, job_progress


def _job(**status):
    return JobRecord(id="j1", backend="local", cases=list(status), log_path="runs/j1.log",
                     state=JobState.RUNNING, case_status={k: CaseState(v) for k, v in status.items()})


def test_job_progress_counts_finished_cases_and_names_the_running_one():
    job = _job(a="CONVERGED", b="FAILED", c="RUNNING", d="PENDING")
    progress = job_progress(JobView(job, job, CaseOverview([], [], [job])))
    assert progress == JobProgress(2, 4, "c")
    assert progress.text == "2 / 4 · c"
    assert progress.percent == 50


def test_no_active_job_no_progress():
    assert job_progress(JobView(None, None, CaseOverview([], [], []))) is None
    assert JobProgress(0, 3, None).text == "0 / 3"
```

Append to `tests/web/test_status.py` (reuse its imports; add `Project` / `build_cases` if missing):

```python
from aerosuite.engine.cfg import build_cases
from aerosuite.engine.models import Project
from aerosuite.web.status import project_kind


def test_project_kind():
    project = Project(name="p")
    project.sweep.mach = [0.8]
    project.sweep.alpha = [0.0, 2.0]
    project.sweep.beta = [0.0]
    project.cases = build_cases(project)
    assert project_kind(project) == "sweep · 2 cases"
    project.sweep.alpha = [0.0]
    project.cases = build_cases(project)
    assert project_kind(project) == "sweep · 1 case"
    project.sweep.enabled = False
    assert project_kind(project) == "single case"
```

`tests/web/test_web_topbar.py`:

```python
import json
import re

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.errors import AeroSuiteError
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.project import open_project, save_project
from aerosuite.web import layout
from aerosuite.web.guide import app_version
from aerosuite.web.layout import badge_color, initials, project_url
from aerosuite.web.theme import BADGE_COLORS, TOGGLE_SIDEBAR

A0 = "M0p8_a0_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def test_initials_and_badge_colour():
    assert initials("visual-study") == "VS"
    assert initials("study") == "ST"
    assert initials("my big_study") == "MB"
    assert initials("--") == "?"
    assert badge_color("study") == badge_color("study") and badge_color("study") in BADGE_COLORS


async def test_the_switcher_names_the_project(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "project-name").text == "study"
    assert _element(user, "project-kind").text == "sweep · 3 cases"


async def test_the_switcher_menu_goes_to_all_projects(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    _element(user, "project-menu").open()
    user.find(marker="menu-all-projects").click()
    await user.should_see(marker="open-path")


@pytest.mark.parametrize("page, title", [("setup", "Setup"), ("config", "Config"), ("sweep", "Sweep"),
                                         ("run", "Run"), ("monitor", "Monitor")])
async def test_breadcrumbs_name_the_project_and_the_page(user: User, ready_project, page, title):
    project_dir, _ = ready_project
    await user.open(project_url(page, project_dir))
    assert _element(user, "crumb-projects").text == "Projects"
    assert _element(user, "crumb-project").text == "study"
    assert _element(user, "crumb-page").text == title
    assert "as-step-current" in _element(user, f"step-{page}").classes


async def test_long_names_truncate_in_the_frame(user: User, ready_project):
    project_dir, project = ready_project
    project.name = "a-" * 60 + "study"
    save_project(project_dir, project)
    await user.open(project_url("setup", project_dir))
    for marker in ("project-name", "crumb-project"):
        element = _element(user, marker)
        assert element.text == project.name  # the whole name: CSS truncates, not the code
        assert "as-truncate" in element.classes


async def test_the_toggle_collapses_the_sidebar(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    sent = []
    user.javascript_rules[re.compile(r".*as-mini.*", re.S)] = lambda match: sent.append(match.string)
    await user.open(project_url("setup", project_dir))
    user.find(marker="sidebar-toggle").click()
    await eventually(lambda: sent == [TOGGLE_SIDEBAR])


async def test_help_shows_the_version_and_the_web_ui_guide(user: User, ready_project, eventually):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "help-version").text == f"AeroSuite {app_version()}"
    _element(user, "help-menu").open()
    user.find(marker="help-guide").click()
    await eventually(lambda: "Pages:" in _element(user, "guide-text").content)


async def test_the_job_indicator_follows_a_job_started_elsewhere(user: User, ready_project, eventually,
                                                                  monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    project_dir, project = ready_project
    await user.open(project_url("setup", project_dir))
    assert not _element(user, "job-indicator").visible
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": {A0: "hang"}}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)  # like the CLI: not through this page
    await eventually(lambda: _element(user, "job-indicator").visible, timeout=10)
    await eventually(lambda: re.fullmatch(rf"0 / 3( · {A0})?", _element(user, "job-progress").text), timeout=10)
    runner.cancel(project_dir, runner.refresh(project_dir, job))
    await eventually(lambda: not _element(user, "job-indicator").visible, timeout=20)


async def test_a_broken_job_state_hides_the_indicator_and_keeps_the_page(user: User, ready_project, monkeypatch):
    project_dir, _ = ready_project

    def broken(*args, **kwargs):
        raise AeroSuiteError("job record unreadable")

    monkeypatch.setattr(layout, "active_lock", lambda directory: {"pid": 1})
    monkeypatch.setattr(layout.WATCHER, "state", broken)
    await user.open(project_url("setup", project_dir))
    await user.should_see(marker="partitions")
    assert not _element(user, "job-indicator").visible


async def test_the_projects_page_has_the_top_bar_without_a_switcher(user: User):
    await user.open("/")
    await user.should_see("AeroSuite")
    await user.should_see(marker="help")
    await user.should_not_see(marker="project-switcher")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_guide.py tests/web/test_web_topbar.py tests/web/test_jobs.py tests/web/test_status.py -q`
Expected: FAIL (`No module named 'aerosuite.web.guide'`, `cannot import name 'job_progress'`, etc.).

- [ ] **Step 3: Write `aerosuite/web/guide.py`**

```python
"""The help menu's content: AeroSuite's version and the README's web UI section (read from disk, so it
works offline). NiceGUI-free."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"
SECTION = "## Web UI"
MISSING = "The web UI guide is in README.md, which is not installed with this copy of AeroSuite."


def app_version() -> str:
    try:
        return version("aerosuite")
    except PackageNotFoundError:
        return "dev"


def web_ui_guide(readme: Path = README) -> str:
    """The README's "## Web UI" section without its heading, or MISSING when it cannot be read."""
    try:
        lines = Path(readme).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return MISSING
    try:
        start = lines.index(SECTION) + 1
    except ValueError:
        return MISSING
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip() or MISSING
```

- [ ] **Step 4: Add `job_progress` to `aerosuite/web/jobs.py`**

Change the runner import to `from ..engine.jobs.runner import FINAL_CASE_STATES, CaseState, JobRecord`, then add after the `JobView` dataclass:

```python
@dataclass(frozen=True)
class JobProgress:
    finished: int
    total: int
    current: Optional[str]  # the case running now, if any

    @property
    def text(self) -> str:
        text = f"{self.finished} / {self.total}"
        return f"{text} · {self.current}" if self.current else text

    @property
    def percent(self) -> int:
        return round(100 * self.finished / self.total) if self.total else 0


def job_progress(view: JobView) -> Optional[JobProgress]:
    """How far the active job is, for the top bar's job indicator; None when no job is active."""
    job = view.active
    if job is None:
        return None
    finished = sum(1 for name in job.cases if job.case_status.get(name) in FINAL_CASE_STATES)
    current = next((name for name in job.cases if job.case_status.get(name) is CaseState.RUNNING), None)
    return JobProgress(finished, len(job.cases), current)
```

- [ ] **Step 5: Add `project_kind` to `aerosuite/web/status.py`** (after `visible_steps`):

```python
def project_kind(project: Project) -> str:
    """The switcher's and the recent list's second line: "sweep · 3 cases" or "single case"."""
    if not project.sweep.enabled:
        return "single case"
    count = len(project.cases)
    return f"sweep · {count} case{'' if count == 1 else 's'}"
```

- [ ] **Step 6: Rewrite `aerosuite/web/layout.py`**

Keep `RELOADED_MESSAGE`, `STALE_MESSAGE`, `project_url`, `PAGE_OF_STEP`, and the bodies of `ensure_current`, `save`, `_check_disk` and `_reload_from_disk` exactly as they are. Remove `BADGE_ICONS`, `PAGE_CSS` and `apply_theme` (nothing else imports them). The whole new file:

```python
"""Shared page parts: the top bar, the project frame (collapsible sidebar, breadcrumbs with the page's
actions slot, job indicator, project switcher) and the outside-change watcher."""
import re
import zlib
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.store import active_lock
from .guide import app_version, web_ui_guide
from .jobs import WATCHER, job_progress
from .recent import add_recent, load_recent
from .session import Change, ProjectSession
from .status import STEPS, project_kind, step_badges, visible_steps
from .theme import BADGE_COLORS, TOGGLE_SIDEBAR, apply_theme
from .ui_kit import banner, status_dot

WATCH_SECONDS = 2.0
PAGE_OF_STEP = {"setup": "setup", "config": "config", "aircraft": "aircraft", "sweep": "sweep", "run": "run",
                "monitor": "monitor"}
PAGE_TITLES = dict(STEPS)
STEP_ICONS = {"setup": "tune", "config": "description", "aircraft": "flight", "sweep": "grid_on",
              "configs": "inventory_2", "run": "play_arrow", "monitor": "show_chart", "results": "bar_chart"}

RELOADED_MESSAGE = "Project changed on disk; reloaded"
STALE_MESSAGE = "Project changed on disk and was reloaded — your last change was not saved; enter it again"


def project_url(page: str, directory) -> str:
    return f"/{page}?project={quote(str(directory), safe='')}"


def initials(name: str) -> str:
    """Two letters for the switcher badge: the first letters of the first two words, else the first two."""
    words = [word for word in re.split(r"[\s_\-.]+", name) if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def badge_color(name: str) -> str:
    return BADGE_COLORS[zlib.crc32(name.encode("utf-8")) % len(BADGE_COLORS)]


def _brand() -> None:
    with ui.link(target="/").classes("as-brand row"):
        with ui.element("span").classes("as-logo-mark"):
            ui.icon("flight", size="18px")
        ui.label("AeroSuite").classes("as-logo-text")


def _help_button() -> None:
    """A help icon with the version and "Web UI guide" (the README's web UI section in a dialog)."""
    # Built outside the menu: a dialog created inside a menu item would be unmounted as the menu closes.
    with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Web UI guide").classes("as-dialog-title grow")
            ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark("guide-close")
        guide = ui.markdown("").classes("w-full").mark("guide-text")

    def show_guide() -> None:
        guide.set_content(web_ui_guide())
        dialog.open()

    with ui.button(icon="help_outline", color=None).props("flat dense").classes(
            "as-topbar-icon as-round").mark("help"):
        with ui.menu().mark("help-menu"):
            ui.menu_item(f"AeroSuite {app_version()}").props("disable").mark("help-version")
            ui.menu_item("Web UI guide", on_click=show_guide).mark("help-guide")


def header() -> None:
    """The top bar of pages outside a project (Projects, or a project that cannot be opened)."""
    apply_theme()
    with ui.row().classes("as-topbar w-full"):
        _brand()
        ui.space()
        _help_button()


def open_session(project: str) -> Optional[ProjectSession]:
    """Open the project named in the URL, or show why not and return None."""
    if not project:
        header()
        with ui.column().classes("as-page w-full"):
            ui.label("No project selected.")
            ui.link("Choose a project", "/")
        return None
    try:
        session = ProjectSession(Path(project))
    except AeroSuiteError as exc:
        header()
        with ui.column().classes("as-page w-full"):
            banner("error", f"Error: {exc}")
            ui.link("Back to projects", "/")
        return None
    add_recent(session.directory)
    return session


def _toggle_sidebar() -> None:
    ui.run_javascript(TOGGLE_SIDEBAR)  # fire and forget: the browser flips and remembers it


class ProjectFrame:
    """Top bar, sidebar, breadcrumb row and content column of a project page.

    `actions` (right of the breadcrumbs) holds the page's buttons, at most one of them primary;
    `content` holds its cards.
    """

    def __init__(self, session: ProjectSession, active: str, on_reload: Callable[[], None]) -> None:
        self.session = session
        self.active = active
        self._on_reload = on_reload
        apply_theme()
        self._top_bar()
        with ui.row().classes("as-body w-full"):
            self._sidebar = ui.column().classes("as-sidebar").mark("sidebar")
            with ui.column().classes("as-main"):
                with ui.row().classes("as-crumbs w-full"):
                    ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                    ui.label("›").classes("as-crumb-sep")
                    self._crumb_project = ui.link("", project_url("setup", session.directory)).classes(
                        "as-crumb-link as-crumb-project as-truncate").mark("crumb-project")
                    ui.label("›").classes("as-crumb-sep")
                    ui.label(PAGE_TITLES.get(active, active.title())).classes("as-crumb-current").mark("crumb-page")
                    ui.space()
                    self.actions = ui.row().classes("items-center gap-2 no-wrap").mark("page-actions")
                self.content = ui.column().classes("as-content w-full")
        self.refresh()
        ui.timer(WATCH_SECONDS, self._tick)

    def _top_bar(self) -> None:
        with ui.row().classes("as-topbar w-full"):
            _brand()
            with ui.button(on_click=_toggle_sidebar, color=None).props("flat dense").classes(
                    "as-topbar-icon").mark("sidebar-toggle"):
                ui.icon("keyboard_double_arrow_left").classes("as-when-full")
                ui.icon("keyboard_double_arrow_right").classes("as-when-mini")
            ui.space()
            with ui.row().classes("as-topbar-control as-job").mark("job-indicator") as self._job:
                ui.element("span").classes("as-job-dot")
                ui.label("Running")
                self._job_text = ui.label("").classes("as-topbar-muted").mark("job-progress")
                with ui.element("span").classes("as-job-bar"):
                    self._job_fill = ui.element("div").classes("as-job-fill").style("width: 0%")
            self._job.on("click", lambda: ui.navigate.to(project_url("run", self.session.directory)))
            self._job.set_visibility(False)
            _help_button()
            with ui.row().classes("as-topbar-control as-switcher").mark("project-switcher"):
                self._initials = ui.label("").classes("as-initials")
                with ui.column().classes("gap-0 min-w-0"):
                    self._name = ui.label("").classes("as-switcher-name as-truncate").mark("project-name")
                    self._kind = ui.label("").classes("as-switcher-kind as-topbar-muted").mark("project-kind")
                ui.icon("expand_more").classes("as-topbar-muted")
                with ui.menu().mark("project-menu"):
                    ui.menu_item("All projects", on_click=lambda: ui.navigate.to("/")).mark("menu-all-projects")
                    here = Path(self.session.directory).resolve()
                    for directory in load_recent():
                        if directory.resolve() != here:
                            ui.menu_item(directory.name, on_click=lambda d=directory: ui.navigate.to(
                                project_url("setup", d))).mark(f"menu-recent-{directory.name}")

    def refresh(self) -> None:
        """Redraw the project name, the sidebar's steps and badges, and the job indicator."""
        project = self.session.project
        self._name.text = project.name
        self._kind.text = project_kind(project)
        self._initials.text = initials(project.name)
        self._initials.style(f"background: {badge_color(project.name)}")
        self._crumb_project.text = project.name
        badges = step_badges(self.session.directory, project)
        self._sidebar.clear()
        with self._sidebar:
            for key, label in visible_steps(project):
                self._step(key, label, badges[key])
        self._update_job()

    def _step(self, key: str, label: str, badge: str) -> None:
        page = PAGE_OF_STEP.get(key)
        if key == "configs":
            page = "sweep" if self.session.project.sweep.enabled else "config"
        if page is None:
            item = ui.row().classes("as-step as-step-later")
        else:
            item = ui.link(target=project_url(page, self.session.directory)).classes("as-step row")
            if key == self.active:
                item.classes("as-step-current")
        item.mark(f"step-{key}")
        with item:
            ui.icon(STEP_ICONS[key], size="20px")
            status_dot(badge).mark(f"badge-{key}-{badge}")
            ui.label(label).classes("as-step-name")
            ui.tooltip(label).classes("as-step-tip")

    def _tick(self) -> None:
        self._check_disk()
        self._update_job()

    def _update_job(self) -> None:
        """Show the job indicator while a job of this project runs (started here, in another tab or the CLI).

        With nothing shown only the cheap lock check runs; job state is read only while a job is active.
        """
        try:
            if not self._job.visible and active_lock(self.session.directory) is None:
                return
            progress = job_progress(WATCHER.state(self.session.directory, self.session.project))
        except (AeroSuiteError, OSError):
            progress = None  # a broken job record must never break navigation
        if progress is None:
            self._job.set_visibility(False)
            return
        self._job_text.set_text(progress.text)
        self._job_fill.style(f"width: {progress.percent}%")
        self._job.set_visibility(True)

    # ensure_current, save, _check_disk and _reload_from_disk: copied unchanged from the old file.
```

Paste the four unchanged methods (`ensure_current`, `save`, `_check_disk`, `_reload_from_disk`, with their docstrings) at the end of the class in place of the final comment.

- [ ] **Step 7: Remove each page's big title** (the breadcrumb now names the page). Delete exactly these lines:
  - `aerosuite/web/pages/run.py`: `ui.label("Run").classes("text-2xl")`
  - `aerosuite/web/pages/monitor.py`: `ui.label("Monitor").classes("text-2xl")`
  - `aerosuite/web/pages/sweep.py`: `ui.label("Sweep").classes("text-2xl")`
  - `aerosuite/web/pages/setup.py`: `ui.label("Setup").classes("text-2xl")`
  - `aerosuite/web/pages/config.py`: `ui.label("Config").classes("text-2xl")`
  - `aerosuite/web/pages/aircraft.py`: `ui.label("Aircraft").classes("text-2xl")`

- [ ] **Step 8: Run the new tests, then the whole suite**

Run: `uv run pytest tests/web/test_guide.py tests/web/test_web_topbar.py tests/web/test_jobs.py tests/web/test_status.py -q` → PASS.
Run: `uv run pytest -q` → all pass. `badge-*` markers moved from icons to dots, and existing tests only use `should_see(marker=...)` on them, so they should pass unchanged. If `test_web_frame.py::test_frame_shows_project_and_badges` or any other test fails, fix the frame rather than the test. The only allowed test edits are layout assertions, named in the report.

If `user.find(marker="menu-all-projects")` cannot see an item of an opened `ui.menu` in the simulated user, call `.click()` via `next(iter(user.find(marker=...).elements))` after `.open()`, and say so in the report.

- [ ] **Step 9: Controller visual check.** Restart the server, open `/setup?project=…visual-study` in the Browser pane at 1280×800. The top bar should match `run.png`: logo, «, the job indicator with "Running 4 / 6 · M0p8_a8_b0", ?, and the switcher. Click « and check the sidebar becomes the 64px rail (`run-sidebar-collapsed.png`). Reload and check it stays collapsed. Click » to restore. Send the two screenshots to the user.

- [ ] **Step 10: Commit**

```bash
git add aerosuite/web/guide.py aerosuite/web/layout.py aerosuite/web/jobs.py aerosuite/web/status.py aerosuite/web/pages tests/web/test_guide.py tests/web/test_web_topbar.py tests/web/test_jobs.py tests/web/test_status.py
git commit -m "feat(web): rebuild the project frame with a dark top bar, collapsible sidebar and breadcrumbs

The top bar carries a live job indicator, a help menu with the web UI guide and a project switcher;
pages put their buttons in the breadcrumb row.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Run page

**Files:**
- Modify: `aerosuite/web/pages/run.py`
- Test: `tests/web/test_web_run.py` (append)

**Interfaces:**
- Consumes: `frame.actions`, `frame.content`; kit `banner`, `ok_line`, `summary_tile`, `card`, `card_head`, `chip_button`, `table`, `th`, `td`, `td_box`, `pill`, `failure_row`, `primary_button`, `danger_button`, `secondary_button`; `format_value` (`aerosuite.engine.naming`).
- Produces: `run.tile_counts(rows) -> tuple[int, int, int, int]` (converged, running, needs attention, pending). New markers `tile-converged`, `tile-running`, `tile-attention`, `tile-pending`. `submit`, `cancel` now live in `page-actions`. `tail-<case>` is now the always-open red failure box. All other markers unchanged.

- [ ] **Step 1: Write the failing tests** (append to `tests/web/test_web_run.py`):

```python
from aerosuite.engine.jobs.overview import CaseRow
from aerosuite.web.pages.run import tile_counts


def test_tile_counts_group_the_statuses():
    rows = [CaseRow(n, s, None) for n, s in [("a", "CONVERGED"), ("b", "RUNNING"), ("c", "FAILED"),
                                             ("d", "UNCONVERGED"), ("e", "CANCELLED"), ("f", "PENDING"),
                                             ("g", "NOT_RUN"), ("h", "CONVERGED")]]
    assert tile_counts(rows) == (2, 1, 3, 2)


async def test_tiles_pills_and_the_failure_box(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _run_to_end(project_dir, project, **{A2: "fail"})
    await _open(user, project_dir)
    assert (_text(user, "tile-converged"), _text(user, "tile-running"), _text(user, "tile-attention"),
            _text(user, "tile-pending")) == ("2", "0", "1", "0")
    assert "as-pill-failed" in _element(user, f"status-{A2}").classes
    assert "as-pill-done" in _element(user, f"status-{A0}").classes
    assert "as-failure" in _element(user, f"tail-{A2}").classes
    actions = _element(user, "page-actions")
    assert _element(user, "submit").parent_slot.parent is actions
    assert "as-btn-primary" in _element(user, "submit").classes
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_run.py -q -k "tile or failure_box"`
Expected: FAIL (`cannot import name 'tile_counts'`).

- [ ] **Step 3: Restyle `run.py`**

Imports: add `from typing import NamedTuple`, `from ...engine.naming import format_value`, and `from ..ui_kit import banner, card, card_head, chip_button, danger_button, failure_row, ok_line, pill, primary_button, secondary_button, summary_tile, table, td, td_box, th`. `register()`, `_plural`, `_snapshot`, `_answer`, `__init__` (except the holder classes), `poll`, `_select`, `_tick`, `_set_continue`, `submit` and the logic of `confirm_cancel` stay as they are.

Add at module level:

```python
def tile_counts(rows) -> tuple[int, int, int, int]:
    """(converged, running, needs attention, pending) for the summary tiles."""
    statuses = [row.status for row in rows]
    converged = statuses.count("CONVERGED")
    running = statuses.count("RUNNING")
    attention = sum(statuses.count(s) for s in ("FAILED", "UNCONVERGED", "CANCELLED"))
    pending = sum(statuses.count(s) for s in ("PENDING", NOT_RUN))
    return converged, running, attention, pending


class _Selection(NamedTuple):
    ticked: list[str]  # ticked case names, in case order
    chosen: bool  # "Continue from each case's last solution" is ticked
    no_solution: list[str]  # ticked cases with nothing to continue from
```

In `__init__`, make the holder `self.holder = ui.column().classes("as-content w-full")`. Replace `render` and the section methods with:

```python
    def render(self, view: Optional[JobView] = None) -> None:
        if view is None:
            try:
                view = WATCHER.state(self.directory, self.project)
            except AeroSuiteError as exc:
                self.holder.clear()
                self.frame.actions.clear()
                with self.holder:
                    banner("error", f"Error: {exc}").mark("run-error")
                return
        self.was_active = view.active is not None
        self.shown = _snapshot(view)
        self.ticked &= {case.name for case in self.project.cases}  # the cases may have been rebuilt
        self.holder.clear()
        self.frame.actions.clear()
        with self.holder:
            self._checks(view)
            selection = self._selection(view)
            self._plan(view, selection)
            self._tiles(view)
            self._cases(view, selection)
            self._history(view)
        with self.frame.actions:
            self._actions(view, selection)

    def _checks(self, view: JobView) -> None:
        problems = preflight(self.directory, self.project, "submit")
        if view.active is not None:  # "job ... is still running" is what the table already shows
            problems = [p for p in problems if not p.message.startswith(f"Job {view.active.id} ")]
        self.has_errors = has_errors(problems)
        found = [(p.severity, p.message) for p in problems] + [("warning", m) for m in view.overview.problems]
        if not found:
            ok_line("No problems found.").mark("run-problems-none")
        for severity, message in found:
            kind = "error" if severity == "error" else "warning"
            prefix = "Error" if severity == "error" else "Warning"
            banner(kind, f"{prefix}: {message}").mark(f"run-problem-{severity}")

    def _selection(self, view: JobView) -> _Selection:
        ticked = [case.name for case in self.project.cases if case.name in self.ticked]
        status = {row.name: row.status for row in view.overview.rows}
        no_solution = [name for name in ticked if restart_file(self.directory, name) is None]
        default = bool(ticked) and not no_solution and all(status.get(n) == "UNCONVERGED" for n in ticked)
        chosen = (default if self.continue_choice is None else self.continue_choice) and not no_solution
        self.continue_cases = ticked if chosen else []
        return _Selection(ticked, chosen, no_solution)

    def _plan(self, view: JobView, selection: _Selection) -> None:
        if not selection.ticked or view.active is not None:
            return
        try:
            plan = plan_restarts(self.directory, self.project, selection.ticked, self.continue_cases)
        except AeroSuiteError as exc:
            banner("error", f"Error: {exc}").mark("plan-error")
        else:
            for warning in plan.warnings:
                banner("warning", f"Warning: {warning}").mark("plan-warning")

    def _tiles(self, view: JobView) -> None:
        converged, running, attention, pending = tile_counts(view.overview.rows)
        with ui.element("div").classes("as-tiles"):
            summary_tile("Converged", converged).mark("tile-converged")
            summary_tile("Running", running).mark("tile-running")
            summary_tile("Needs attention", attention, "danger" if attention else None).mark("tile-attention")
            summary_tile("Pending", pending).mark("tile-pending")

    def _cases(self, view: JobView, selection: _Selection) -> None:
        with card(flush=True):
            with card_head("Cases"):
                if view.overview.rows:
                    for label, statuses in SELECTORS:
                        chip_button(label, on_click=lambda s=statuses: self._select(view, s)).mark(
                            f"select-{label.lower().replace(' ', '-')}")
                    ui.space()
                    box = ui.checkbox("Continue from each case's last solution", value=selection.chosen,
                                      on_change=lambda e: self._set_continue(e.value)).mark("continue")
                    if selection.no_solution:
                        box.disable()
            if not view.overview.rows:
                ui.label("No cases yet: set up the sweep first.").classes("as-muted px-4 pb-4")
                return
            if selection.no_solution:
                ui.label("No solution to continue from: " + ", ".join(selection.no_solution)).classes(
                    "as-hint px-4 pb-2").mark("continue-missing")
            cases = {case.name: case for case in self.project.cases}
            with table("36px minmax(10rem, 1.4fr) repeat(3, minmax(3.5rem, .5fr)) minmax(8rem, 1fr) "
                       "minmax(9rem, 1fr)"):
                for heading in ("", "Case", "Mach", "α", "β", "Status", "Last job"):
                    th(heading)
                for row in view.overview.rows:
                    case = cases.get(row.name)
                    with td_box():
                        ui.checkbox(value=row.name in self.ticked,
                                    on_change=lambda e, n=row.name: self._tick(n, e.value)).mark(f"tick-{row.name}")
                    td(row.name, strong=True)
                    td(format_value(case.mach) if case else "")
                    td(format_value(case.alpha) if case else "")
                    td(format_value(case.beta) if case else "")
                    with td_box():
                        pill(row.status).mark(f"status-{row.name}")
                    td(row.job_id or "—", mono=True).mark(f"job-{row.name}")
                    if row.status == "FAILED" and row.failure_tail:
                        failure_row(row.failure_tail).mark(f"tail-{row.name}")

    def _actions(self, view: JobView, selection: _Selection) -> None:
        if view.active is not None:
            danger_button("Cancel job", on_click=self.confirm_cancel).mark("cancel")
        submit = primary_button(f"Submit {_plural(len(selection.ticked), 'case')}", on_click=self.submit)
        submit.mark("submit").set_enabled(view.active is None and bool(selection.ticked) and not self.has_errors)

    def _history(self, view: JobView) -> None:
        with card(flush=True):
            card_head("Job history")
            if not view.overview.jobs:
                ui.label("No jobs yet.").classes("as-muted px-4 pb-4").mark("history-none")
                return
            with table("minmax(10rem, 1fr) minmax(7rem, auto) minmax(5rem, auto) minmax(9rem, 1fr) "
                       "minmax(9rem, 1fr)"):
                for heading in ("Job", "State", "Cases", "Started", "Finished"):
                    th(heading)
                for job in view.overview.jobs:
                    td(job.id, mono=True).mark(f"history-{job.id}")
                    with td_box():
                        pill(job.state)
                    td(_plural(len(job.cases), "case"))
                    td(f"{job.created:%Y-%m-%d %H:%M}")
                    td(f"{job.finished:%Y-%m-%d %H:%M}" if job.finished else "—")
```

In `confirm_cancel`, give the dialog the kit look, keeping the markers and the `_answer` calls:

```python
            with ui.dialog() as dialog, ui.card():
                ui.label("Cancel the running job? Cases that have not finished are marked CANCELLED.")
                with ui.row().classes("w-full justify-end gap-2"):
                    # (keep the existing comment about deleting the dialog in the same click)
                    secondary_button("Keep running", on_click=lambda: _answer(dialog, False)).mark("cancel-keep")
                    danger_button("Cancel the job", on_click=lambda: _answer(dialog, True)).mark("cancel-confirm")
```

- [ ] **Step 4: Run the Run tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_run.py -q` → PASS, including `test_a_poll_with_nothing_new_does_not_rebuild_the_page` (the frame's job indicator updates in place and never rebuilds the holder).
Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Controller visual check.** Restart the server, shoot `after` for run (`shoot.py … after`) and compare with `before-run-*.png` and the `run.png` mockup. Send both to the user.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/pages/run.py tests/web/test_web_run.py
git commit -m "feat(web): restyle Run with summary tiles, a cases table with pills and failure boxes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Monitor page

**Files:**
- Modify: `aerosuite/web/pages/monitor.py`
- Test: `tests/web/test_web_monitor.py` (append)

**Interfaces:**
- Consumes: kit `card`, `card_head`, `field`, `pill`, `set_pill`, `secondary_button`; `theme.SERIES_COLORS`, `theme.HAIRLINE`.
- Produces: `monitor.column_colors(columns: Sequence[str]) -> dict[str, str]`. `line_options(x, df, columns, normalize=False, colors=None)` gains an optional `colors` map (`series[i]["color"]`). `_Content` gains `status: str = ""`. New marker `monitor-status` (a pill with the case status; hidden in file mode and when there is no status). All other markers unchanged. `chart-history` stays `w-full` and `height: 70vh`.

- [ ] **Step 1: Write the failing tests** (append to `tests/web/test_web_monitor.py`):

```python
from aerosuite.web.pages.monitor import column_colors
from aerosuite.web.theme import SERIES_COLORS


def test_column_colours_cycle_and_stay_with_their_column():
    columns = [f"rms[{i}]" for i in range(10)]
    colors = column_colors(columns)
    assert colors["rms[0]"] == SERIES_COLORS[0]
    assert colors["rms[8]"] == SERIES_COLORS[0]  # past the palette: cycle
    df = pd.DataFrame({"Inner_Iter": [0, 1], "CL": [0.1, 0.2], "CD": [0.01, 0.02]})
    series = line_options([0, 1], df, ["CD"], colors=column_colors(["CL", "CD"]))["series"]
    assert series[0]["color"] == SERIES_COLORS[1]  # CD keeps its colour with CL unticked


async def test_lines_match_their_swatches_and_the_source_has_a_status_pill(user: User, ready_project):
    project_dir, project = ready_project
    runner, job = _start(project_dir, project)
    _wait(runner, project_dir, job, lambda j: not j.is_active)
    await _open(user, project_dir)
    series = _element(user, "chart-history").options["series"]
    assert [s["color"] for s in series] == SERIES_COLORS[:3]
    _element(user, "monitor-col-CL").set_value(False)
    series = _element(user, "chart-history").options["series"]
    assert [(s["name"], s["color"]) for s in series] == [("rms[Rho]", SERIES_COLORS[0]), ("CD", SERIES_COLORS[2])]
    status = _element(user, "monitor-status")
    assert status.visible and status.text == "CONVERGED" and "as-pill-done" in status.classes
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_monitor.py -q -k "colour or swatches"`
Expected: FAIL (`cannot import name 'column_colors'`).

- [ ] **Step 3: Restyle `monitor.py`**

Imports: add `from ..theme import HAIRLINE, SERIES_COLORS` and `from ..ui_kit import card, card_head, field, pill, secondary_button, set_pill`.

Add after `filtered_columns`:

```python
def column_colors(columns: Sequence[str]) -> dict:
    """Each plottable column's line (and swatch) colour, by its position; the palette cycles."""
    return {column: SERIES_COLORS[i % len(SERIES_COLORS)] for i, column in enumerate(columns)}
```

Change `line_options`: the signature becomes `def line_options(x: list, df, columns: list, normalize: bool = False, colors: Optional[dict] = None) -> dict:`. Its docstring adds "`colors` maps a column to its line colour." Build each series as:

```python
        item = {"name": column, "type": "line", "showSymbol": False, "data": data}
        if colors and column in colors:
            item["color"] = colors[column]
        series.append(item)
```

In the returned dict, add a hairline grid to both axes, leaving `axisLine` exactly as it is:

```python
        "xAxis": {"type": "value", "name": "Iteration", "nameLocation": "middle", "nameGap": 30,
                  "axisLine": {"onZero": False}, "splitLine": {"lineStyle": {"color": HAIRLINE}}},
        "yAxis": {"type": "value", "name": "residuals", "scale": True,
                  "splitLine": {"lineStyle": {"color": HAIRLINE}}},
```

Add a field to `_Content`, after `message`:

```python
    status: str = ""  # the case's status for the pill beside the source line; "" hides it
```

In `_case_content`, pass `status=row.status` on every `_Content(...)` that is built after `row` is known to be run. The first `not-run` return (row None or NOT_RUN) keeps no status:

```python
            return _Content(None, "not-run", text, "", status=row.status if status_job is not None else "")
        ...
        return _Content(df, state, text, "", status=row.status)
```

Replace the layout block in `__init__` (the `with ui.row()...` down to `self.chart_holder = ...`) with:

```python
        with ui.element("div").classes("as-monitor"):
            with card():
                self.select = field(ui.select([], label="Case", on_change=lambda e: self._choose_case(e.value)))
                self.select.classes("w-full").mark("monitor-case")
                secondary_button("Open file…", on_click=self._open_file).classes("w-full").mark("monitor-open-file")
                with ui.row().classes("items-center gap-2"):
                    self.status_pill = pill("PENDING").mark("monitor-status")
                    self.source_label = ui.label("").classes("as-hint").mark("monitor-source")
                self.status_pill.set_visibility(False)
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    self.stop_button = secondary_button("Stop", on_click=self._toggle_stop).mark("monitor-stop")
                    ui.checkbox("Normalize", on_change=lambda e: self._set_normalize(e.value)).mark(
                        "monitor-normalize")
                ui.label("Columns").classes("as-label")
                self.checkbox_holder = ui.column().classes("gap-1")
            with card():
                card_head("Convergence", f"updates every {POLL_SECONDS:g} s")
                self.chart_holder = ui.column().classes("w-full")
```

In `_apply`, after the tooltip lines, add:

```python
        if content.status:
            set_pill(self.status_pill, content.status)
            self.status_pill.set_visibility(True)
        else:
            self.status_pill.set_visibility(False)
```

`_build_checkboxes` draws a swatch before each checkbox:

```python
    def _build_checkboxes(self, columns: tuple) -> None:
        self.checkbox_holder.clear()
        colors = column_colors(columns)
        with self.checkbox_holder:
            for column in columns:
                checked = self.ticked.setdefault(column, True)  # unseen columns start ticked
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.element("span").classes("as-swatch").style(f"background: {colors[column]}")
                    ui.checkbox(column, value=checked, on_change=lambda e, c=column: self._toggle_column(
                        c, e.value)).mark(f"monitor-col-{column}")
```

`_chart_options` passes the colours of every plottable column, so a colour never moves when a column is unticked:

```python
    def _chart_options(self) -> dict:
        return line_options(iteration_values(self.df), self.df, self._ticked_columns(), self.normalize,
                            colors=column_colors(filtered_columns(self.df)))
```

Message labels: in `_build_chart_area`, replace `.classes("text-grey-7")` with `.classes("as-muted")` (three places). In `render`, the two `_show_message` calls pass `"as-error-text"` instead of `"text-negative"` and `"as-muted"` instead of `"text-grey-7"`.

- [ ] **Step 4: Run the Monitor tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_monitor.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Controller visual check.** Restart the server, shoot `after` for monitor, and compare with `monitor.png` (controls card left, Convergence card filling the rest, swatch colours equal to the lines). Send it to the user.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/pages/monitor.py tests/web/test_web_monitor.py
git commit -m "feat(web): restyle Monitor as a controls card and a convergence card with matching swatches

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Sweep page and the shared checks / Generate button

**Files:**
- Modify: `aerosuite/web/checks.py`, `aerosuite/web/pages/sweep.py`, `aerosuite/web/pages/config.py` (only the checks wiring; the full restyle comes in Task 8)
- Test: `tests/web/test_web_sweep.py`, `tests/web/test_web_config.py` (append)

**Interfaces:**
- Consumes: kit `banner`, `ok_line`, `primary_button`, `secondary_button`, `card`, `card_head`, `field`, `table`, `th`, `td`, `td_box`; `fields.text_field(..., mono=)`; `frame.actions`.
- Produces:
  - `checks.generate_button(frame, refresh: Callable[[], None]) -> ui.button`: the primary "Generate configs" button (marker `generate`), with today's generate handler. `refresh` redraws the checks.
  - `checks.render_checks(frame, button: Optional[ui.button] = None) -> None`: problems as banners (markers `problem-error` / `problem-warning`) or `ok_line` (`problems-none`). It enables `button` only when there is no error.
  - Replaces today's `render_checks(frame, refresh)`. Both callers (Sweep, Config) are updated in this task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_web_sweep.py` (reuse its `_element` helper, or define `def _element(user, marker): return next(iter(user.find(marker=marker).elements))` if it has none):

```python
async def test_generate_is_the_primary_action_and_checks_are_banners(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("sweep", project_dir))
    generate = _element(user, "generate")
    assert generate.parent_slot.parent is _element(user, "page-actions")
    assert "as-btn-primary" in generate.classes
    await user.should_see(marker="problems-none")
    user.find(marker="sweep-mach").clear().type("abc").trigger("blur")
    await user.should_see("'abc' in 'abc' is not a number")


async def test_a_custom_restart_without_a_file_is_an_error_banner(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("sweep", project_dir))
    _element(user, "restart-M0p8_a2_b0").set_value("custom")
    label = _element(user, "problem-error")
    assert "as-banner-error" in label.parent_slot.parent.classes
    assert not _element(user, "generate").enabled
```

Append to `tests/web/test_web_frame_steps.py`:

```python
async def test_sweep_off_is_an_info_banner(user: User, ready_project):
    project_dir, _ = ready_project
    _switch(project_dir, sweep=False)
    await user.open(project_url("sweep", project_dir))
    label = next(iter(user.find(marker="sweep-off").elements))
    assert "as-banner-info" in label.parent_slot.parent.classes
```

Append to `tests/web/test_web_config.py` (its helpers already switch the sweep off for "Wrote 1 config"; copy that setup):

```python
async def test_config_generate_sits_in_the_actions_when_the_sweep_is_off(user: User, ready_project):
    project_dir, project = ready_project
    project.sweep.enabled = False
    project.cases = build_cases(project)
    save_project(project_dir, project)
    await user.open(project_url("config", project_dir))
    generate = next(iter(user.find(marker="generate").elements))
    assert generate.parent_slot.parent is next(iter(user.find(marker="page-actions").elements))
```

(Add `build_cases`, `save_project` and `project_url` imports to that file if missing.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_sweep.py tests/web/test_web_frame_steps.py tests/web/test_web_config.py -q`
Expected: the new tests FAIL (the generate button is not in `page-actions`; no banner classes).

- [ ] **Step 3: Rewrite `aerosuite/web/checks.py`**

```python
"""Checks and the Generate button: shared by the Config page (sweep off) and the Sweep page."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import generate_configs
from ..engine.errors import AeroSuiteError
from ..engine.preflight import has_errors, preflight
from .layout import ProjectFrame
from .ui_kit import banner, ok_line, primary_button


def render_checks(frame: ProjectFrame, button: Optional[ui.button] = None) -> None:
    """The generate checks as banners (or one green line); `button` is enabled only when none is an error."""
    found = preflight(frame.session.directory, frame.session.project, "generate")
    if not found:
        ok_line("No problems found.").mark("problems-none")
    for problem in found:
        kind = "error" if problem.severity == "error" else "warning"
        prefix = "Error" if problem.severity == "error" else "Warning"
        banner(kind, f"{prefix}: {problem.message}").mark(f"problem-{problem.severity}")
    if button is not None:
        button.set_enabled(not has_errors(found))


def generate_button(frame: ProjectFrame, refresh: Callable[[], None]) -> ui.button:
    """The page's primary "Generate configs" button; `refresh` redraws the checks afterwards."""

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

    return primary_button("Generate configs", on_click=generate).mark("generate")
```

- [ ] **Step 4: Restyle `aerosuite/web/pages/sweep.py`**

Imports: `from ..checks import generate_button, render_checks` and `from ..ui_kit import banner, card, card_head, field, secondary_button, table, td, td_box, th`. `NAMING` labels become `"Mach", "Altitude", "α", "β", "Base name"` (flags unchanged). `_values`, `_set_naming`, `_set_case`, `_change_ref`, `_browse_ref` stay.

The inner functions of `sweep_page`:

```python
        def render_cases() -> None:
            # (keep the existing comment on why this is a plain synchronous rebuild)
            box = holders.get("cases")
            if box is None:
                return
            box.clear()
            with box:
                _case_table(frame, after)

        def render_problems() -> None:
            # (keep the existing comment)
            box = holders.get("problems")
            if box is None:
                return
            box.clear()
            with box:
                render_checks(frame, holders.get("generate"))

        def after() -> None:
            render_cases()
            render_problems()

        @ui.refreshable
        def body() -> None:
            frame.actions.clear()
            if not frame.session.project.sweep.enabled:
                holders.clear()  # render_cases / render_problems then do nothing
                banner("info", "The sweep is off for this project: it is a single case. "
                       "Switch the sweep on in Setup to run Mach/alpha/beta cases.").mark("sweep-off")
                return
            with frame.actions:
                holders["generate"] = generate_button(frame, render_problems)
            holders["problems"] = ui.column().classes("w-full gap-2")
            _sweep_fields(frame, after)
            with card(flush=True) as cases_card:
                holders["cases"] = cases_card
            render_cases()
            render_problems()

        with frame.content:
            body()
```

`_sweep_fields`:

```python
def _sweep_fields(frame: ProjectFrame, after: Callable[[], None]) -> None:
    sweep = frame.session.project.sweep
    with card("Flight conditions"):
        with ui.element("div").classes("as-grid-3"):
            for label, name in (("Mach", "mach"), ("Angle of attack α (deg)", "alpha"), ("Sideslip β (deg)", "beta")):
                with ui.column().classes("gap-1"):
                    text_field(
                        label, _values(getattr(sweep, name)),
                        lambda text, n=name: frame.save(
                            lambda p: update_sweep(p, **{n: parse_value_list(text)}), then=after),
                        mark=f"sweep-{name}", placeholder="e.g. 0.6, 0.8  or  -4:12:2",
                    )
            with ui.column().classes("gap-1"):
                text_field("Altitude label", sweep.altitude,
                           lambda text: frame.save(lambda p: update_sweep(p, altitude=text.strip()), then=after),
                           mark="sweep-altitude")
            with ui.column().classes("gap-1"):
                text_field("Base name", sweep.naming.base_name,
                           lambda text: frame.save(lambda p: update_sweep(p, base_name=text.strip()), then=after),
                           mark="sweep-base-name")
        with ui.row().classes("items-center gap-4"):
            ui.label("Name cases with").classes("as-label")
            for flag, label in NAMING:
                ui.checkbox(label, value=getattr(sweep.naming, flag),
                            on_change=lambda e, f=flag: _set_naming(frame, f, e.value, after)).mark(f"naming-{flag}")
```

`_case_table` (drawn inside the flush card):

```python
def _case_table(frame: ProjectFrame, after: Callable[[], None]) -> None:
    project = frame.session.project
    count = len(project.cases)
    card_head("Cases", f"{count} case{'' if count == 1 else 's'}")
    if not project.cases:
        ui.label("No cases yet: enter Mach numbers above.").classes("as-muted px-4 pb-4")
        return
    duplicates = set(find_collisions(case.name for case in project.cases))
    with table("minmax(10rem, 1.2fr) repeat(3, minmax(3.5rem, .4fr)) 11rem minmax(18rem, 2fr)"):
        for heading in ("Case", "Mach", "α", "β", "Restart", "Restart from"):
            th(heading)
        for case in project.cases:
            name_label = td(case.name, strong=True).mark(f"case-{case.name}")
            if case.name in duplicates:
                name_label.classes("as-dup").mark(f"case-{case.name} dup-{case.name}")
            td(format_value(case.mach))
            td(format_value(case.alpha))
            td(format_value(case.beta))
            with td_box():
                field(ui.select(
                    RESTART_OPTIONS, value=case.restart,
                    on_change=lambda e, n=case.name: _set_case(frame, n, after, restart=e.value, restart_ref=None),
                )).classes("w-full").mark(f"restart-{case.name}")
            with td_box():
                if case.restart == "custom":
                    with ui.column().classes("grow gap-0"):
                        text_field("Restart file or case folder", case.restart_ref,
                                   lambda text, n=case.name: frame.save(
                                       lambda p: _change_ref(p, n, text.strip() or None), then=after),
                                   mark=f"ref-{case.name}", mono=True)
                    secondary_button("Browse", on_click=lambda n=case.name: _browse_ref(frame, n, after)).mark(
                        f"ref-browse-{case.name}")
```

- [ ] **Step 5: Rewire Config's checks** (minimal; the full Config restyle comes in Task 8). In `aerosuite/web/pages/config.py`: import `from ..checks import generate_button, render_checks`. In `_build`, `render_checks_box` becomes:

```python
    def render_checks_box() -> None:
        box = holders.get("checks")
        if box is None:
            return
        box.clear()
        with box:
            render_checks(frame, holders.get("generate"))
```

At the start of the widget-building part of `_build` (just before `with ui.row().classes("w-full no-wrap items-start gap-6"):`), add:

```python
    frame.actions.clear()
    if not frame.session.project.sweep.enabled:
        with frame.actions:
            holders["generate"] = generate_button(frame, render_checks_box)
```

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_sweep.py tests/web/test_web_frame_steps.py tests/web/test_web_config.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Controller visual check.** Restart the server, shoot `after` for sweep, and compare with `sweep.png`. Send it to the user.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/web/checks.py aerosuite/web/pages/sweep.py aerosuite/web/pages/config.py tests/web/test_web_sweep.py tests/web/test_web_frame_steps.py tests/web/test_web_config.py
git commit -m "feat(web): restyle Sweep; checks become banners and Generate moves to the breadcrumb row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Setup page

**Files:**
- Modify: `aerosuite/web/pages/setup.py`
- Test: `tests/web/test_web_setup.py`, `tests/web/test_web_setup_study.py` (append)

**Interfaces:**
- Consumes: kit `card`, `field`, `hint`, `readonly`, `banner`, `primary_button`, `secondary_button`; `fields.text_field(..., mono=)`.
- Produces: new markers `setup-project-name`, `setup-folder`. `setup-sweep` is now a `ui.radio` with options `{True: …, False: …}` drawn as two tiles. It still has `.value`, `.set_value(bool)` and `on_change`, like the switch it replaces. All other markers unchanged. Texts `Markers: …`, `template.cfg (copied into the project)`, `Runs as: …` and `Script: …` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_web_setup.py` (reuse its `_element` helper, or define one):

```python
async def test_setup_shows_the_project_card(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "setup-project-name").text == "study"
    assert _element(user, "setup-folder").text == str(project_dir)
    assert "as-mono" in _element(user, "setup-folder").classes
```

Append to `tests/web/test_web_setup_study.py`:

```python
async def test_the_study_type_is_two_tiles(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    choice = _element(user, "setup-sweep")
    assert choice.value is True
    assert "as-choice" in choice.classes
    assert list(choice.options) == [True, False]
```

(The existing `setup-sweep` tests at `test_web_setup_study.py:132,137` call `.set_value(False/True)`. They must pass unchanged.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_setup.py tests/web/test_web_setup_study.py -q`
Expected: the two new tests FAIL (no `setup-project-name` marker; `setup-sweep` is a switch).

- [ ] **Step 3: Restyle `setup.py`**

Imports: add `from ..ui_kit import banner, card, field, hint, primary_button, readonly, secondary_button`. The page body order becomes Project, Mesh and template, Study, Run settings:

```python
        @ui.refreshable
        def body() -> None:
            _project_card(frame)
            with card("Mesh and template"):
                _mesh_section(frame)
                _template_section(frame)
            _study_section(frame)
            _run_section(frame)

        with frame.content:
            body()
```

Add:

```python
def _project_card(frame: ProjectFrame) -> None:
    with card("Project"):
        with ui.element("div").classes("as-grid-2"):
            with ui.column().classes("gap-1"):
                ui.label("Name").classes("as-label")
                readonly(frame.session.project.name).mark("setup-project-name")
            with ui.column().classes("gap-1"):
                ui.label("Folder").classes("as-label")
                readonly(str(frame.session.directory), mono=True).mark("setup-folder")
```

`_study_section`: wrap it in `with card("Study"):`. Profile problems become `banner("warning", f"Profile skipped: {problem}").mark("setup-profile-problem")`. Put the study-type choice first, then the profile row:

```python
        ui.radio({True: "Sweep · a grid of Mach, α and β cases", False: "Single case · the template as it is"},
                 value=project.sweep.enabled, on_change=lambda e: sweep(e.value)).props("inline").classes(
            "as-choice").mark("setup-sweep")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            select = field(ui.select(options, value=project.profile or "", label="Aircraft profile",
                                     on_change=lambda e: choose(e.value))).classes("w-64").mark("setup-profile")
            secondary_button("Apply profile defaults", on_click=lambda: apply_defaults()).mark("setup-apply-profile")
            secondary_button("Save as profile…", on_click=lambda: save_as()).mark("setup-save-profile")
```

Delete the old `ui.switch(...)` line. The nested `choose`, `sweep`, `apply_defaults` and `save_as` keep their logic. `sweep` must be defined before the `ui.radio` line runs its first `on_change`; the lambda resolves it at call time, so moving the `def sweep` above the radio is only for readability. Dialog restyle:
- apply dialog: text label, then `with ui.row().classes("w-full justify-end gap-2"):` containing `secondary_button("Cancel", …).mark("confirm-cancel")` and `primary_button("Apply", …).mark("confirm-apply")`;
- save-as dialog: title `.classes("as-dialog-title")`; the three inputs wrapped in `field(...)`; the error label `.classes("as-error-text")`; buttons `secondary_button("Cancel")` (`profile-cancel`), `secondary_button("Replace existing")` (`profile-replace`), `primary_button("Save")` (`profile-save`), in a right-aligned row. Keep `replace.set_visibility(False)`.

`_path_setter` (rename the local `field` variable to `box` so it does not shadow `ui_kit.field`):

```python
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        box = field(ui.input(label), mono=True).classes("grow").mark(f"{mark}-input")

        async def browse() -> None:
            chosen = await pick_path(title, mode="file", suffixes=suffixes)
            if chosen is not None:
                box.value = str(chosen)
                commit()

        secondary_button("Browse", on_click=browse).mark(f"{mark}-browse")
        secondary_button("Set", on_click=lambda: commit()).mark(f"{mark}-set")
    error = ui.label("").classes("as-error-text").mark(f"{mark}-error")

    def commit() -> None:
        text = (box.value or "").strip()
        ...  # unchanged
```

`_mesh_section`: drop the "Mesh" title label (the card has one). The summary becomes `ui.label(mesh.path or "No mesh selected").classes("as-mono as-muted").mark("mesh-path")` and `hint(f"Markers: {markers}").mark("mesh-markers")`. Call `_path_setter(...)` first, then `summary()`, so the current path and markers read as hints under the field (see `setup.png`).
`_template_section`: drop the "Master template" title and add `ui.label("Config template").classes("as-label mt-2")` above it. The summary label gets `.classes("as-hint")`. Order: `_path_setter` then `summary()`.

`_run_section`:

```python
def _run_section(frame: ProjectFrame) -> None:
    run = frame.session.project.run

    @ui.refreshable
    def python_info() -> None:
        resolved = resolve_sweep_python(frame.session.project.run.sweep_python)
        text = f"Runs as: {resolved}"
        own = is_aerosuite_python(resolved)
        if own:
            text += "  ⚠ This is AeroSuite's own Python; SU2 is normally importable only from the system Python."
        label = hint(text).mark("sweep-python-info")
        if own:
            label.classes("as-hint-warning")

    @ui.refreshable
    def script_info() -> None:
        script = frame.session.project.run.sweep_script
        text = script if script else f"bundled {BUNDLED_SWEEP_SCRIPT.name}"
        hint(f"Script: {text}").mark("sweep-script-info")

    with card("Run settings"):
        with ui.element("div").classes("as-grid-3"):
            with ui.column().classes("gap-1"):
                text_field(
                    "Python for the sweep script (must import SU2)", run.sweep_python,
                    lambda text: frame.save(
                        lambda p: setattr(p.run, "sweep_python", text.strip() or "python3"), then=python_info.refresh),
                    mark="sweep-python", mono=True,
                )
                python_info()
            with ui.column().classes("gap-1"):
                text_field(
                    "Sweep script (empty = bundled)", run.sweep_script,
                    lambda text: frame.save(lambda p: setattr(p.run, "sweep_script", text.strip()),
                                            then=script_info.refresh),
                    mark="sweep-script", mono=True,
                )
                script_info()
            with ui.column().classes("gap-1"):
                text_field(
                    "MPI partitions per case", run.partitions,
                    lambda text: frame.save(lambda p: setattr(p.run, "partitions", parse_int(text, "Partitions"))),
                    mark="partitions",
                )
```

- [ ] **Step 4: Run the Setup tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_setup.py tests/web/test_web_setup_study.py tests/web/test_web_frame.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Controller visual check.** Restart the server, shoot `after` for setup, and compare with `setup.png`. Send it to the user.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/pages/setup.py tests/web/test_web_setup.py tests/web/test_web_setup_study.py
git commit -m "feat(web): restyle Setup into project, mesh and template, study and run settings cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Projects page, recent summaries and the picker

**Files:**
- Modify: `aerosuite/web/recent.py`, `aerosuite/web/pages/projects.py`, `aerosuite/web/picker.py`
- Test: `tests/web/test_recent.py`, `tests/web/test_web_projects.py` (append)

**Interfaces:**
- Consumes: `header()`; kit `card`, `card_head`, `path_field`, `field`, `banner`, `pill`, `primary_button`, `secondary_button`, `flat_button`; `status.project_kind`; `engine.project.open_project`; `engine.jobs.store.scan_jobs(project_dir) -> tuple[list[JobRecord], list[str]]`.
- Produces: `recent.RecentProject(directory: Path, name: str, kind: str, latest: Optional[str])` (`kind` is `""` and `latest` is `None` when the project cannot be read; `latest` is the newest job's `JobState` value). `recent.recent_projects() -> list[RecentProject]`. The markers `recent-<folder>` (now on the whole row, a `ui.link`), `recent-empty`, `open-*` and `new-*` are unchanged. The picker's `picker-*` markers are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_recent.py` (reuse its imports; add these if missing):

```python
from aerosuite.engine.project import PROJECT_FILE
from aerosuite.web.recent import RecentProject, add_recent, recent_projects


def test_recent_projects_summarise_each_project(ready_project):
    project_dir, _ = ready_project
    add_recent(project_dir)
    assert recent_projects() == [RecentProject(project_dir.resolve(), "study", "sweep · 3 cases", None)]


def test_recent_projects_survives_an_unreadable_project(ready_project):
    project_dir, _ = ready_project
    add_recent(project_dir)
    (project_dir / PROJECT_FILE).write_text('{"name": "half-typed", ')
    assert recent_projects() == [RecentProject(project_dir.resolve(), project_dir.name, "", None)]
```

Append to `tests/web/test_web_projects.py`:

```python
async def test_recent_rows_show_the_kind_and_the_latest_run(user: User, ready_project):
    project_dir, project = ready_project
    add_recent(project_dir)
    await user.open("/")
    await user.should_see(marker="recent-study")
    await user.should_see("sweep · 3 cases")
    await user.should_see(str(project_dir.resolve()))


async def test_create_is_the_primary_action(user: User):
    await user.open("/")
    assert "as-btn-primary" in next(iter(user.find(marker="new-create").elements)).classes
```

(Import `add_recent` from `aerosuite.web.recent` in that file.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_recent.py tests/web/test_web_projects.py -q`
Expected: FAIL (`cannot import name 'RecentProject'`).

- [ ] **Step 3: Add `recent_projects` to `aerosuite/web/recent.py`**

```python
from dataclasses import dataclass
from typing import Optional

from ..engine.errors import AeroSuiteError
from ..engine.jobs.store import scan_jobs
from ..engine.project import PROJECT_FILE, open_project
from .status import project_kind


@dataclass(frozen=True)
class RecentProject:
    directory: Path
    name: str
    kind: str  # "sweep · 3 cases" / "single case"; "" when project.json cannot be read
    latest: Optional[str]  # the newest job's state, None without jobs or when unreadable


def recent_projects() -> list[RecentProject]:
    """The recent list with each project's name, kind and latest run; unreadable projects still listed."""
    items = []
    for directory in load_recent():
        try:
            project = open_project(directory)
        except (AeroSuiteError, OSError, ValueError):
            items.append(RecentProject(directory, directory.name, "", None))
            continue
        try:
            jobs, _ = scan_jobs(directory)
        except (AeroSuiteError, OSError):
            jobs = []
        items.append(RecentProject(directory, project.name, project_kind(project),
                                   jobs[0].state.value if jobs else None))
    return items
```

(Merge the imports with the file's existing ones. `status.py` does not import `recent.py`, so there is no cycle.)

- [ ] **Step 4: Restyle `aerosuite/web/pages/projects.py`**

Imports: `from ..recent import add_recent, recent_projects` (drop `load_recent`), `from ..ui_kit import banner, card, card_head, field, path_field, pill, primary_button, secondary_button`. Remove `_path_row` and the `pick_path` import. `_go_to` and `_is_plain_name` are unchanged, and so is the body of `create()`.

```python
def register() -> None:
    @ui.page("/")
    def projects_page() -> None:
        header()
        with ui.column().classes("as-page w-full"):
            with ui.row().classes("as-crumbs w-full"):
                ui.label("Projects").classes("as-crumb-current")
            with ui.element("div").classes("as-columns as-columns-projects"):
                with ui.column().classes("gap-4 w-full"):
                    _recent_list()
                with ui.column().classes("gap-4 w-full"):
                    _open_form()
                    _new_form()


def _recent_list() -> None:
    with card(flush=True):
        card_head("Recent projects")
        recent = recent_projects()
        if not recent:
            ui.label("No recent projects yet.").classes("as-muted px-4 pb-4").mark("recent-empty")
            return
        for item in recent:
            with ui.link(target=project_url("setup", item.directory)).classes("as-recent-row").mark(
                    f"recent-{item.directory.name}"):
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(item.name).classes("as-strong as-truncate")
                    ui.label(str(item.directory)).classes("as-mono as-muted as-truncate")
                if item.kind:
                    ui.label(item.kind).classes("as-tag")
                if item.latest:
                    pill(item.latest)


def _open_form() -> None:
    with card("Open a project"):
        path = path_field("Project folder", mark="open-path", browse_mark="open-browse",
                          title="Open a project folder", mode="folder")
        error = ui.label("").classes("as-error-text").mark("open-error")
        with ui.row().classes("w-full justify-end"):
            secondary_button("Open", on_click=lambda: open_it()).mark("open-button")

    def open_it() -> None:
        ...  # unchanged body


def _kind_card(title: str, text: str, mark: str, on_choose) -> ui.column:
    tile = ui.column().classes("as-choice-tile").mark(mark)
    tile.on("click", lambda _: on_choose())
    with tile:
        ui.label(title).classes("as-strong")
        ui.label(text).classes("as-muted")
    return tile


def _new_form() -> None:
    profiles, problems = list_profiles()
    state = {"kind": "general"}

    def choose(kind: str) -> None:
        state["kind"] = kind
        for tile, name in ((general, "general"), (aircraft, "aircraft")):
            if name == kind:
                tile.classes(add="as-choice-selected")
            else:
                tile.classes(remove="as-choice-selected")
        profile.set_visibility(kind == "aircraft")
        use_reference.set_visibility(kind == "general")

    with card("New project"):
        for problem in problems:
            banner("warning", f"Profile skipped: {problem}").mark("profile-problem")
        with ui.element("div").classes("as-grid-2"):
            general = _kind_card("General case", "One config from a template, edited as text with SU2's "
                                 "reference beside it. One case.", "new-kind-general", lambda: choose("general"))
            aircraft = _kind_card("Aircraft study", "Aircraft Aero form with profile defaults, "
                                  "placeholders and a Mach/alpha/beta sweep.", "new-kind-aircraft",
                                  lambda: choose("aircraft"))
        profile = field(ui.select({p.id: p.name for p in profiles}, label="Aircraft profile",
                                  value=profiles[0].id if profiles else None)).classes("w-full").mark("new-profile")
        parent = path_field("Parent folder", mark="new-parent", browse_mark="new-browse",
                            title="Choose the parent folder", mode="folder")
        name = field(ui.input("Project name")).classes("w-full").mark("new-name")
        template = path_field("Template (.cfg)", mark="new-template", browse_mark="new-template-browse",
                              title="Choose the template", mode="file", suffixes=(".cfg",))
        use_reference = ui.checkbox("Start from SU2's config_template.cfg").mark("new-use-reference")
        mesh = path_field("Mesh (.su2, optional)", mark="new-mesh", browse_mark="new-mesh-browse",
                          title="Choose the mesh", mode="file", suffixes=(".su2", ".cgns"))
        error = ui.label("").classes("as-error-text").mark("new-error")
        with ui.row().classes("w-full justify-end"):
            primary_button("Create project", on_click=lambda: create()).mark("new-create")
    choose("general")

    def create() -> None:
        ...  # unchanged body
```

Two notes. First, `open_it` and `create` must be defined inside their functions after the widgets they read, exactly as today; paste the old bodies. Second, the old `choose` added `border-2 border-primary`; if any test asserts those classes, update it to `as-choice-selected` and name that in the report.

- [ ] **Step 5: Restyle the picker** (`aerosuite/web/picker.py`). Import `from .ui_kit import field, flat_button, primary_button, secondary_button`; the logic is unchanged:

```python
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label(title).classes("as-dialog-title")
        location = ui.label("").classes("as-mono as-muted").mark("picker-location")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            pasted = field(ui.input("Paste a path"), mono=True).classes("grow").mark("picker-path")
            secondary_button("Use", on_click=lambda: use_pasted()).mark("picker-use")
        error = ui.label("").classes("as-error-text").mark("picker-error")
        listing = ui.column().classes("w-full gap-0 max-h-80 overflow-auto")
        with ui.row().classes("w-full items-center gap-2"):
            flat_button("Up", on_click=lambda: go_up(), icon="arrow_upward").mark("picker-up")
            ui.space()
            secondary_button("Cancel", on_click=lambda: dialog.submit(None)).mark("picker-cancel")
            if mode in ("folder", "any"):
                primary_button("Choose this folder", on_click=lambda: dialog.submit(here["dir"])).mark(
                    "picker-choose-folder")
```

The entry buttons keep `.props("flat no-caps align=left").classes("w-full")`.

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_recent.py tests/web/test_web_projects.py tests/web/test_web_new_study.py tests/web/test_web_base.py tests/web/test_web_shell.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Controller visual check.** Restart the server, shoot `after` for projects (two columns; the long-named aircraft project truncates). Open a picker from Browse in the Browser pane and screenshot the dialog. Send both to the user.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/web/recent.py aerosuite/web/pages/projects.py aerosuite/web/picker.py tests/web/test_recent.py tests/web/test_web_projects.py
git commit -m "feat(web): restyle Projects with a recent-projects list and open/new cards; picker in the card look

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Config page, reference panel and preview

**Files:**
- Modify: `aerosuite/web/pages/config.py`, `aerosuite/web/reference_panel.py`, `aerosuite/web/preview.py`
- Test: `tests/web/test_web_config.py`, `tests/web/test_web_reference.py` (append)

**Interfaces:**
- Consumes: `generate_button`, `render_checks` (Task 5); kit `card`, `field`, `banner`, `hint`, `secondary_button`, `flat_button`.
- Produces: the same `reference_panel(on_insert, in_config) -> Callable[[], None]` and `preview_section(frame) -> Callable[[], None]`. The panel no longer draws its own "Reference" title (its caller's card does). Markers unchanged: `config-text`, `config-text-error`, `config-warning` (now on banner labels), `config-checks`, all `ref-*` and `preview*` markers.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_web_config.py`:

```python
async def test_template_warnings_are_banners_above_the_editor(user: User, ready_project):
    project_dir, _ = ready_project
    (project_dir / "template.cfg").write_text("AOA= 0.0\nAOA= 2.0\n")
    await user.open(project_url("config", project_dir))
    label = next(iter(user.find(marker="config-warning").elements))
    assert "as-banner-warning" in label.parent_slot.parent.classes
    assert "as-field" in next(iter(user.find(marker="config-text").elements)).classes
```

(If a duplicated `AOA` is not a template warning in this engine, use the input the existing test at `test_web_config.py:49`, "AOA is set on lines", uses to produce a warning.)

Append to `tests/web/test_web_reference.py`:

```python
async def test_in_config_is_a_done_pill(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("SOLVER")
    label = next(iter(user.find(marker="ref-in-config-SOLVER").elements))
    assert "as-pill-done" in label.classes
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_web_config.py tests/web/test_web_reference.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Restyle Config's `_build`** (`aerosuite/web/pages/config.py`). Imports: `from ..ui_kit import banner, card, field`. `show_warnings` becomes:

```python
    def show_warnings(warnings: list[str]) -> None:
        box = holders["warnings"]
        box.clear()
        with box:
            for warning in warnings:
                banner("warning", warning).mark("config-warning")
```

Replace the widget-building part (from `frame.actions.clear()`, added in Task 5, through the end of the two columns) with:

```python
    frame.actions.clear()
    if not frame.session.project.sweep.enabled:
        with frame.actions:
            holders["generate"] = generate_button(frame, render_checks_box)
        holders["checks"] = ui.column().classes("w-full gap-2").mark("config-checks")
    holders["warnings"] = ui.column().classes("w-full gap-2")
    with ui.element("div").classes("as-columns"):
        with card("Template", "Saved automatically · template.cfg"):
            editor = field(ui.textarea(value=initial), mono=True).props('input-style="height: 70vh"').classes(
                "w-full").mark("config-text")
            if load_error:
                editor.props("readonly")
            holders["editor"] = editor
            state["editor"] = editor
            holders["error"] = ui.label(load_error or "").classes("as-error-text").mark("config-text-error")
            editor.on("blur", commit)
            holders["preview"] = preview_section(frame)
        with card("SU2 reference"):
            holders["reference"] = reference_panel(
                on_insert=insert, in_config=lambda: keys_in(holders["editor"].value or ""))
    show_warnings(template_warnings(initial))
    render_checks_box()
```

(`holders["warnings"]` must exist before `show_warnings` runs. It now sits above the columns; the old in-column `warnings` column is removed.)

- [ ] **Step 4: Restyle `reference_panel.py`.** Import `from .ui_kit import field, flat_button, hint, secondary_button`. The changes:
  - delete `ui.label("Reference").classes("text-lg")`;
  - `source = hint("config_template.cfg").mark("ref-source")`;
  - `error = ui.label("").classes("as-error-text").mark("ref-error")`;
  - `field(ui.input("Search options", on_change=lambda e: on_search(e.value))).classes("w-full").mark("ref-search")`;
  - `note = hint("").mark("ref-insert-note")`;
  - in `render_results`: `ui.label("No options match").classes("as-muted")`; each result row gets `.classes("w-full items-start no-wrap gap-2 py-2")` with `.style("border-top: 1px solid var(--as-hairline)")`; the option line `.classes("as-mono")`; the description `.classes("as-hint")`; the section `.classes("as-hint")`; "In config" becomes `ui.label("In config").classes("as-pill as-pill-done").mark(...)`; Insert becomes `secondary_button("Insert", on_click=lambda o=option: insert(o), icon="add").props("dense").mark(...)`;
  - `ui.label("Find in the full file").classes("as-label mt-2")`; `find_box = field(ui.input("Find")).classes("grow").mark("ref-find")`; `flat_button("Find next", on_click=lambda: find_next()).mark("ref-find-next")`; `status = hint("").mark("ref-find-status")`;
  - `flat_button("Load another reference…", on_click=load_other).mark("ref-load")`.

- [ ] **Step 5: Restyle `preview.py`.** Import `from .ui_kit import banner, field`. The case select becomes `field(ui.select(...)).mark("preview-case")`. The error becomes `banner("error", f"Error: {exc}").mark("preview-error")`. The code block gets `.classes("w-full as-mono")`.

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_config.py tests/web/test_web_reference.py tests/web/test_web_aircraft.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Controller visual check.** Restart the server, shoot `after` for config, and send it to the user.

- [ ] **Step 8: Commit**

```bash
git add aerosuite/web/pages/config.py aerosuite/web/reference_panel.py aerosuite/web/preview.py tests/web/test_web_config.py tests/web/test_web_reference.py
git commit -m "feat(web): restyle Config as template and SU2 reference cards with banner checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Aircraft page

**Files:**
- Modify: `aerosuite/web/pages/aircraft.py`
- Test: `tests/web/test_web_aircraft.py` (append)

**Interfaces:**
- Consumes: kit `card`, `field`, `table`, `th`, `td`, `td_box`, `secondary_button`; `fields.text_field(..., mono=)`.
- Produces: markers unchanged (`<group>-<name>`, `numerics-<name>`, `marker-<KEY>-include`, `marker-<KEY>-value`, `override-<KEY>-value`, `override-<KEY>-delete`, `override-new-key`, `override-new-value`, `override-add`, `override-add-error`, `aircraft-none`). The "Placeholders" section keeps its name, so the messages "Added X to Placeholders" / "already in Placeholders" are unchanged. It is drawn as the option / value / delete table the spec calls "Extra SU2 options". **No new read-only placeholders list is added:** nothing like that exists on the page today, and adding it would be new behaviour. Report this to the user as a spec deviation.

- [ ] **Step 1: Write the failing test** (append to `tests/web/test_web_aircraft.py`, reusing how that file opens an aircraft project):

```python
async def test_aircraft_sections_are_cards(user: User, aircraft_project):
    project_dir = aircraft_project
    await user.open(project_url("aircraft", project_dir))
    await user.should_see("Mesh markers: farfield, wall")
    select = next(iter(user.find(marker="numerics-conv_method").elements))
    assert "as-field" in select.classes
```

Replace `aircraft_project` with the fixture or setup the existing tests in that file use (e.g. `ready_project` plus setting `profile="x07"` and saving). Copy it exactly.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/web/test_web_aircraft.py -q`
Expected: the new test FAILS (no `as-field` class on the select).

- [ ] **Step 3: Restyle `aircraft.py`.** Imports: `from ..ui_kit import card, field, secondary_button, table, td, td_box, th`. `_build`:

```python
def _build(frame: ProjectFrame) -> None:
    hints = _hints(frame.session.project)
    holders: dict = {}

    def after() -> None:
        holders["preview"]()
        holders["reference"]()

    with ui.element("div").classes("as-columns"):
        with ui.column().classes("gap-4 w-full"):
            for title, rows in NUMBER_FIELDS.items():
                with card(title):
                    with ui.element("div").classes("as-grid-3"):
                        for label, group, name, kind in rows:
                            with ui.column().classes("gap-1"):
                                _number_field(frame, hints, label, group, name, kind, after)
            with card("Numerics"):
                with ui.element("div").classes("as-grid-3"):
                    for label, name, options in DROPDOWNS:
                        with ui.column().classes("gap-1"):
                            _dropdown(frame, label, name, options, after)
                    for label, name, kind in NUMERIC_TEXT:
                        with ui.column().classes("gap-1"):
                            _number_field(frame, hints, label, "numerics", name, kind, after)
            holders["markers"] = _markers(frame, hints, after)
            holders["overrides"] = _placeholders(frame, after)
            with card("Preview"):
                holders["preview"] = preview_section(frame)
        with card("SU2 reference"):
            holders["reference"] = reference_panel(
                on_insert=lambda option: _insert(frame, option, holders, after),
                in_config=lambda: _rendered_keys(frame))
```

`_dropdown`: `field(ui.select(...)).classes("w-full").mark(f"numerics-{name}")`.

`_markers`: replace the title and mesh labels and the box with:

```python
    mesh = ", ".join(frame.session.project.mesh.markers) or "(no .su2 mesh markers)"
    with card("Markers", f"Mesh markers: {mesh}"):
        box = ui.column().classes("w-full gap-2")
```

and `render()` draws the rows as a grid:

```python
    def render() -> None:
        # Plain synchronous rebuild: tests read these rows right after a change.
        box.clear()
        markers = frame.session.project.settings.markers
        keys = MARKER_ROWS + sorted(k for k in markers if k not in MARKER_ROWS)
        with box:
            with ui.element("div").classes("as-grid-form"):
                for key in keys:
                    value = markers.get(key, "")
                    ui.checkbox(key, value=value is not None,
                                on_change=lambda e, k=key: include(k, e.value)).mark(f"marker-{key}-include")
                    with ui.column().classes("gap-0"):
                        text_field("Value", value or "", lambda text, k=key: set_value(k, text),
                                   mark=f"marker-{key}-value", placeholder=hints.get(key, "template value"),
                                   mono=True)
```

`_placeholders`: replace the title and subtitle labels, the box, and the add row with:

```python
    with card("Placeholders", "Any other SU2 option, written into every config.", flush=True):
        box = ui.column().classes("w-full gap-0")
        with ui.row().classes("w-full items-start no-wrap gap-2 px-4 pt-3 pb-2"):
            key_box = field(ui.input("Option"), mono=True).classes("w-48").mark("override-new-key")
            value_box = field(ui.input("Value")).classes("grow").mark("override-new-value")
            secondary_button("Add", on_click=lambda: add()).mark("override-add")
        error = ui.label("").classes("as-error-text px-4 pb-3").mark("override-add-error")
```

and its `render()` becomes:

```python
    def render() -> None:
        box.clear()
        items = sorted(frame.session.project.settings.overrides.items())
        if not items:
            return
        with box:
            with table("minmax(10rem, 14rem) minmax(0, 1fr) 56px"):
                for heading in ("Option", "Value", ""):
                    th(heading)
                for key, value in items:
                    td(key, mono=True)
                    with td_box():
                        with ui.column().classes("grow gap-0"):
                            text_field("Value", value,
                                       lambda text, k=key: frame.save(
                                           lambda p: set_parameter(p.settings, k, text), then=after),
                                       mark=f"override-{key}-value", mono=True)
                    with td_box():
                        ui.button(icon="delete", on_click=lambda k=key: forget(k), color=None).props(
                            "flat round dense").mark(f"override-{key}-delete")
```

`aircraft-none` in `register()` becomes `banner("info", "This project has no aircraft profile. Choose one in Setup to use the Aircraft Aero form.").mark("aircraft-none")` (import `banner`).

- [ ] **Step 4: Run the Aircraft tests, then the whole suite**

Run: `uv run pytest tests/web/test_web_aircraft.py -q` → PASS.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Controller visual check.** Restart the server, shoot `after` for aircraft, and send it to the user.

- [ ] **Step 6: Commit**

```bash
git add aerosuite/web/pages/aircraft.py tests/web/test_web_aircraft.py
git commit -m "feat(web): restyle Aircraft into numerics, markers, placeholders and reference cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10 (controller): Visual pass over every page, and the final gate

- [ ] **Step 1: Leftover-styling sweep.** Run:

```bash
grep -nE "text-negative|text-warning|text-positive|text-grey|text-2xl|text-lg|#[0-9a-fA-F]{6}" aerosuite/web/pages/*.py aerosuite/web/*.py | grep -v "aerosuite/web/theme.py"
```

Expected: no output. Fix any hit by switching it to a kit helper or class, re-running that page's tests, and committing as `style(web): …`.

- [ ] **Step 2: Full suite.** `uv run pytest -q`. Expected: all pass: 518 at the start plus every test added in Tasks 1–9. Record the count.

- [ ] **Step 3: After shots of all pages at both sizes.** Restart the server, then run `shoot.py … after` for all 7 pages × 2 sizes. In the Browser pane, check:
  - the sidebar collapse persists across a reload;
  - the job indicator links to Run;
  - the help dialog opens;
  - the switcher menu lists the other demo project;
  - at a 700px-wide window, the columns stack into one.

- [ ] **Step 4: Send the before/after set to the user.** Send them with SendUserFile, page by page. Name any spec deviations:
  - the mesh markers show as a hint line ("Markers: …"), not chips, because a test asserts that text;
  - Aircraft has no separate read-only placeholders list;
  - the clean-checks line keeps "No problems found.".

- [ ] **Step 5: Stop the demo.** Run `uv run python .superpowers/sdd/visual/demo.py stop .superpowers/sdd/visual/demo`, then stop the server.

- [ ] **Step 6: Final review** via superpowers:requesting-code-review over `a465ea9..HEAD`, then superpowers:finishing-a-development-branch. The branch is stacked on `feat/web-run-monitor`; leave pushing and merging to the user.

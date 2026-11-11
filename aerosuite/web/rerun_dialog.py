"""The Run page's "Rerun with changes…": a lower CFL, a first-order start, the iterations, and where it starts from
(the Run page's three ways, each saying which solution, or another solution), for one job only (engine/jobs/rerun.py); and "Keep" afterwards, which writes what a case ran with into
its config (the template, or the form field or placeholder that writes the line)."""
import re
from pathlib import Path
from typing import Optional

from nicegui import ui

from ..engine.cfg import case_layers, read_template, render_case
from ..engine.config_edit import apply_changes
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.jobs.plan import last_solution, preview_starts
from ..engine.jobs.rerun import describe, rerun_changes
from ..engine.models import Project
from ..engine.naming import format_value
from .layout import ProjectFrame
from .session import parse_optional_int, parse_optional_number
from .starts_view import MODE_LABELS, SINGLE_LABELS, start_text
from .template_edit import write_template_params
from .ui_kit import hint, primary_button, secondary_button


def _value(config: str, key: str) -> Optional[str]:
    match = re.search(rf"^\s*{key}\s*=\s*([^%\n]*?)\s*(?:%.*)?$", config, re.MULTILINE)
    return match.group(1) if match else None


def _answer(dialog: ui.dialog, value) -> None:
    dialog.submit(value)


async def ask_rerun(directory: Path, project: Project, name: str, kind: str,
                    sources: Optional[dict[str, str]] = None, chosen: Optional[str] = None
                    ) -> Optional[tuple[dict, str]]:
    """Ask how to rerun `name` after a failure of `kind` (jobs/diagnose.py; "unconverged" too). `sources` are more
    solutions it can start from ({path: label}, e.g. the one its failed run started from), `chosen` the one to
    offer first. Returns (the config changes, where it starts: "last", "sweep", "scratch" or a solution's path), or
    None when cancelled."""
    sources = sources or {}
    case = next(c for c in project.cases if c.name == name)
    try:
        config = render_case(read_template(directory, project), project, case)
    except AeroSuiteError:
        config = ""
    cfl = _value(config, "CFL_NUMBER") or "1"
    adaptive = (_value(config, "CFL_ADAPT") or "NO").upper() == "YES"
    iterations = _value(config, "ITER") or ""
    last = last_solution(directory, name)
    has_solution = last is not None
    diverged = kind == "diverged"
    try:
        lower = format_value(round(float(cfl) / 2, 6)) if diverged else cfl
    except ValueError:
        lower = cfl
    with ui.dialog() as dialog, ui.card().style("min-width: 26rem").mark("rerun-dialog"):
        ui.label(f"Rerun {name}").classes("as-dialog-title")
        hint("For this run only: the template and the other cases stay as they are.")
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            change_cfl = ui.checkbox("CFL", value=diverged).mark("rerun-cfl-on")
            cfl_box = ui.input(value=lower).props("dense outlined").classes("w-24").mark("rerun-cfl")
            hint(f"fixed (adaptation off); now {cfl}{' adaptive' if adaptive else ''}")
        first = ui.checkbox("Start first-order (MUSCL_FLOW and MUSCL_TURB off)", value=diverged).mark(
            "rerun-first-order")
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.label("Iterations").classes("as-label")
            iter_box = ui.input(value=iterations).props("dense outlined").classes("w-28").mark("rerun-iter")
        options = {"last": _choice(directory, project, name, "last") if has_solution else
                   f"{SINGLE_LABELS['last']} (none yet)",
                   "sweep": _choice(directory, project, name, "sweep"),
                   **{path: label for path, label in sources.items() if last is None or Path(path) != last},
                   "scratch": SINGLE_LABELS["scratch"]}
        others = [path for path in options if path not in ("last", "sweep", "scratch")]
        first_choice = chosen or (others[0] if others and kind != "unconverged" else None)
        ui.label("Starts from").classes("as-run-head")
        start = ui.radio(options, value=first_choice or ("last" if has_solution else "scratch")).props(
            "dense").classes("as-start-choice").mark("rerun-start")
        error = ui.label("").classes("as-error-text").mark("rerun-error")

        def confirm() -> None:
            try:
                value = parse_optional_number(cfl_box.value, "CFL") if change_cfl.value else None
                count = parse_optional_int(iter_box.value, "Iterations")
            except ProjectError as exc:
                error.text = str(exc)
                return
            if change_cfl.value and (value is None or value <= 0):
                error.text = "The CFL must be greater than 0"
                return
            if count is not None and count <= 0:
                error.text = "Iterations must be greater than 0"
                return
            same_iter = count is not None and str(count) == iterations
            changes = rerun_changes(cfl=value, first_order=first.value, iterations=None if same_iter else count)
            if start.value == "last" and not has_solution:
                error.text = "It has no solution yet: start from scratch, or from another solution"
                return
            _answer(dialog, (changes, start.value))

        with ui.row().classes("w-full justify-end gap-2"):
            secondary_button("Cancel", on_click=lambda: _answer(dialog, None)).mark("rerun-cancel")
            primary_button("Rerun", icon="replay", on_click=confirm).mark("rerun-confirm")
    return await dialog


def _choice(directory: Path, project: Project, name: str, mode: str) -> str:
    """A start's label with what it means for this case, e.g. "As set up · M0p3_20km_a5's solution"."""
    label = MODE_LABELS["sweep"] if mode == "sweep" and len(project.cases) > 1 else SINGLE_LABELS[mode]
    try:
        start = preview_starts(directory, project, [name], mode)[0]
    except AeroSuiteError:
        return label
    return f"{label} · {start_text(start)}"


def kept(config: str, changes: dict) -> bool:
    """Whether the config already has every changed line (then there is nothing to keep)."""
    return all(_value(config, key) == value for key, value in changes.items())


def keep_changes(frame: ProjectFrame, name: str, changes: dict) -> Optional[str]:
    """Write what `name` last ran with into its config: lines a layer writes into that layer (config_edit), the
    rest into the template. Returns an error message, or None."""
    project = frame.session.project
    case = next((c for c in project.cases if c.name == name), None)
    if case is None:
        return f"Case {name} no longer exists"
    try:
        template = read_template(frame.session.directory, project)
    except AeroSuiteError as exc:
        return str(exc)
    layers = case_layers(template, project, case)
    to_template = {key: value for key, value in changes.items() if key not in layers}
    to_layers = {key: value for key, value in changes.items() if key in layers}
    if to_template:
        message = write_template_params(frame, to_template)
        if message:
            return message
    if to_layers:
        notes: list = []

        def change(p) -> None:
            own = next(c for c in p.cases if c.name == name)
            notes.extend(apply_changes(p, own, template, to_layers)[1])

        message = frame.save(change)
        if message:
            return message
        if notes:
            return "; ".join(notes)
    ui.notify(f"Kept {describe(changes)} in the config", type="positive")
    return None

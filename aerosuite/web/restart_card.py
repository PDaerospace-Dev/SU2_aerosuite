"""A single case's Restart card (Aircraft and CFG setup with the sweep off): a fresh start, or from a solution —
one of this project's runs, or another file or folder. It sets the case's restart as the Sweep page's Cases tab
does for a sweep case: `none`, or `custom` with the path (a case folder is enough: its restart file is found)."""
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from nicegui import ui

from ..engine.errors import ProjectError
from ..engine.jobs.overview import run_solutions
from ..engine.models import Project
from .fields import text_field
from .layout import ProjectFrame
from .picker import pick_path
from .ui_kit import card, hint, pill, secondary_button


def _set(p: Project, restart: str, ref: Optional[str]) -> None:
    if len(p.cases) != 1:
        raise ProjectError("The restart here is for a single case; with the sweep on, set it on the Sweep page")
    p.cases[0].restart, p.cases[0].restart_ref = restart, ref


def _same_place(ref: Optional[str], folder: Path) -> bool:
    if not ref:
        return False
    path = Path(ref).expanduser()
    try:
        path, folder = path.resolve(), folder.resolve()
    except OSError:
        return False
    return path == folder or path.parent == folder  # the folder, or its restart file


def restart_card(frame: ProjectFrame, after: Callable[[], None]) -> Callable[[], None]:
    """Build the card; returns its redraw."""
    state = {"other": False}  # "Another file or folder" chosen, before a path is given
    with card("Restart", "How this case starts", fold="single-restart") as whole:
        whole.mark("restart-card")
        box = ui.column().classes("w-full gap-2")

    def save(restart: str, ref: Optional[str], other: bool = False) -> None:
        state["other"] = other
        message = frame.save(lambda p: _set(p, restart, ref), then=both)
        if message:
            ui.notify(message, type="negative")

    def both() -> None:
        render()
        after()

    async def browse() -> None:
        chosen = await pick_path("Restart file or case folder", mode="any")
        if chosen is not None:
            save("custom", str(chosen), other=True)

    def render() -> None:
        box.clear()
        project = frame.session.project
        if len(project.cases) != 1:
            return
        case = project.cases[0]
        from_solution = case.restart == "custom"
        runs = run_solutions(frame.session.directory, exclude=[case.name])
        listed = next((run for run in runs if _same_place(case.restart_ref, run.folder)), None)
        other = from_solution and (state["other"] or (listed is None and bool(case.restart_ref)) or not runs)
        with box:
            with ui.element("div").classes("as-grid-2"):
                for key, title, small in (("fresh", "Fresh start", "From the freestream"),
                                          ("solution", "From a solution", "Another run's restart file")):
                    on = from_solution == (key == "solution")
                    with ui.column().classes("as-choice-tile gap-0" + (" as-choice-selected" if on else "")).props(
                            "tabindex=0 role=button").mark(f"restart-{key}") as tile:
                        ui.label(title).classes("as-strong")
                        ui.label(small).classes("as-muted")
                    tile.on("click", (lambda: save("none", None)) if key == "fresh" else
                            (lambda: None if from_solution else
                             save("custom", str(runs[0].folder)) if runs else save("custom", None, other=True)))
            if not from_solution:
                hint("To carry on this case from where it stopped, tick Continue from the last solution on the Run "
                     "page.").mark("restart-continue-note")
                return
            if runs:
                ui.label("This project's runs with a solution").classes("as-label")
            for run in runs:
                on = listed is not None and run.name == listed.name and not other
                with ui.row().classes("as-choice-tile as-rule items-center gap-2 no-wrap w-full" + (
                        " as-choice-selected" if on else "")).mark(f"restart-run-{run.name}") as row:
                    ui.icon("radio_button_checked" if on else "radio_button_unchecked")
                    ui.label(run.name).classes("as-mono grow")
                    if run.status:
                        pill(run.status)
                    ui.label(datetime.fromtimestamp(run.modified).strftime("%d %b %H:%M")).classes("as-muted")
                row.on("click", lambda _, folder=run.folder: save("custom", str(folder)))
            if runs:
                with ui.row().classes("as-choice-tile as-rule items-center gap-2 no-wrap w-full" + (
                        " as-choice-selected" if other else "")).mark("restart-other") as row:
                    ui.icon("radio_button_checked" if other else "radio_button_unchecked")
                    ui.label("Another file or folder…").classes("grow")
                row.on("click", lambda: save("custom", None if listed is not None else case.restart_ref, other=True))
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                with ui.column().classes("grow gap-0"):
                    text_field("Restart file or case folder", case.restart_ref,
                               lambda text: frame.save(lambda p: _set(p, "custom", text.strip() or None), then=both),
                               mark="restart-ref", mono=True)
                secondary_button("Browse", icon="folder", on_click=browse).mark("restart-browse")
            hint("A folder is enough: the restart file inside is found for you. The mesh must be the same.")
            hint("To carry on this case from where it stopped, tick Continue from the last solution on the Run page."
                 ).mark("restart-continue-note")

    render()
    return render

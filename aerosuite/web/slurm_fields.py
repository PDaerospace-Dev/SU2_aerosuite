"""A study's Slurm options as fields — partition and tasks per case, saved with the project — and the time limit,
which the Settings page sets for every study. Used by the Setup page's Run settings step and the Run page."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.jobs.executors import slurm_options
from ..engine.settings import AppSettings
from .fields import text_field
from .session import parse_int
from .ui_kit import hint


def run_text(project, settings: AppSettings, backend: str) -> str:
    """One line on where and how a study runs: 'Slurm · node1 · 96 tasks per case', 'This machine · 8 partitions'."""
    if backend == "slurm":
        options = slurm_options(project, settings)
        limit = f" · limit {options.time_limit}" if options.time_limit else ""
        return f"Slurm · {options.partition} · {options.ntasks} tasks per case{limit}"
    count = project.run.partitions
    return f"This machine · {count} MPI partition{'' if count == 1 else 's'} per case"


def slurm_fields(frame, settings: AppSettings, on_change: Callable[[], None], mark: str,
                 columns: bool = False, compact: bool = False) -> None:
    """The three fields with a hint under each; `on_change` runs after a value is saved (redraw); `columns` lays them
    out side by side (as-grid-3) instead of one under another. `compact`: only partition and tasks, side by side with
    one line under them (the time limit is shown by the caller)."""
    project = frame.session.project
    options = slurm_options(project, settings)
    partition = settings.slurm.partition(options.partition)
    names = [p.name for p in settings.slurm.partitions]
    if options.partition not in names:
        names.append(options.partition)

    def set_partition(name: str) -> None:
        if name == options.partition:
            return

        def change(p) -> None:
            p.run.slurm.partition = name
            p.run.slurm.ntasks = None  # each partition has its own default

        message = frame.save(change)
        if message is not None:
            ui.notify(message, type="negative")
        on_change()

    def set_ntasks(text: str) -> Optional[str]:
        message = frame.save(lambda p: setattr(p.run.slurm, "ntasks", parse_int(text, "Tasks per case")))
        if message is None:
            on_change()
        return message

    if compact:
        _compact(options, partition, names, set_partition, set_ntasks, mark)
        return
    box = ui.element("div").classes("as-grid-3 w-full") if columns else ui.column().classes("w-full gap-2")
    with box:
        with ui.column().classes("gap-1 w-full"):
            ui.select(names, value=options.partition, label="Partition", on_change=lambda e: set_partition(e.value)
                      ).classes("w-full").props("dense").mark(f"{mark}-partition")
            if partition is None:
                hint("Not in the settings: choose another partition").classes("as-hint-warning").mark(
                    f"{mark}-partition-note")
            else:
                hint(f"{partition.default_ntasks} tasks by default · {partition.memory_limit_mb / 1024:.0f} GB "
                     "memory limit").mark(f"{mark}-partition-note")
        with ui.column().classes("gap-1 w-full"):
            text_field("Tasks per case (MPI ranks)", options.ntasks, set_ntasks, mark=f"{mark}-ntasks")
            note = ("1 node per case" + (", exclusive" if options.exclusive else ""))
            warn = partition is not None and partition.ntasks_warn_above and options.ntasks > partition.ntasks_warn_above
            if warn:
                note = f"{partition.name} gains nothing above about {partition.ntasks_warn_above} tasks"
            label = hint(note).mark(f"{mark}-node-note")
            if warn:
                label.classes("as-hint-warning")
        with ui.column().classes("gap-1 w-full"):
            ui.label("Time limit").classes("as-stat-label")
            ui.label(options.time_limit or "none").classes("as-stat-value").mark(f"{mark}-time-limit")
            hint("Set for every study on the Settings page (bottom left); Slurm stops a case that runs "
                 "longer (TIMEOUT)").mark(f"{mark}-time-note")


def _compact(options, partition, names, set_partition, set_ntasks, mark: str) -> None:
    """Partition and tasks in one row, then one line: the memory limit and nodes per case (or the warning)."""
    with ui.element("div").classes("as-grid-2 w-full"):
        ui.select(names, value=options.partition, label="Partition", on_change=lambda e: set_partition(e.value)
                  ).classes("w-full").props("dense").mark(f"{mark}-partition")
        text_field("Tasks per case", options.ntasks, set_ntasks, mark=f"{mark}-ntasks")
    if partition is None:
        hint("Not in the settings: choose another partition").classes("as-hint-warning").mark(f"{mark}-partition-note")
        return
    hint(f"{partition.memory_limit_mb / 1024:.0f} GB limit · {partition.default_ntasks} tasks by default · 1 node "
         "per case" + (", exclusive" if options.exclusive else "")
         + (f" · time limit {options.time_limit}" if options.time_limit else "")).mark(f"{mark}-partition-note")
    if partition.ntasks_warn_above and options.ntasks > partition.ntasks_warn_above:
        hint(f"{partition.name} gains nothing above about {partition.ntasks_warn_above} tasks").classes(
            "as-hint-warning").mark(f"{mark}-node-note")

"""The Resubmit dialog for a NODE_FAIL / OUT_OF_MEMORY case: where to run it again (another partition is proposed
after OUT_OF_MEMORY), the pre-submit checks, then the resubmit in a worker thread. Used by the Run and Cluster pages."""
from pathlib import Path
from typing import Optional

from nicegui import run, ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.executors import slurm_options
from ..engine.jobs.runner import JobRecord
from ..engine.models import Project
from ..engine.preflight import preflight
from ..engine.settings import load_settings
from .cluster_view import suggested_partition
from .jobs import WATCHER
from .ui_kit import hint, primary_button, secondary_button


def _answer(dialog: ui.dialog, value: bool) -> None:
    dialog.submit(value)
    dialog.delete()


async def resubmit_case(directory: Path, project: Project, job: JobRecord, case: str) -> Optional[JobRecord]:
    settings, _warnings = load_settings()
    partitions = [p.name for p in settings.slurm.partitions]
    limits = {p.name: p.memory_limit_mb for p in settings.slurm.partitions}
    sc = job.slurm[case]
    chosen = {"partition": suggested_partition(job, case, partitions, limits)}
    with ui.dialog() as dialog, ui.card().classes("gap-3"):
        ui.label(f"Resubmit {case}?").classes("as-strong")
        why = "It ran out of memory" if sc.state == "OUT_OF_MEMORY" else "Its node failed"
        ui.label(f"{why} on {sc.partition} (Slurm job {sc.job_id}). It runs again in the same job, with the cases "
                 "waiting for its solution.").classes("as-muted")
        if chosen["partition"] != sc.partition:
            hint(f"Suggested: {chosen['partition']}, which has more memory.").mark("resubmit-suggestion")
        ui.select(partitions, value=chosen["partition"], label="Partition",
                  on_change=lambda e: chosen.update(partition=e.value)).classes("w-full").mark("resubmit-partition")
        with ui.row().classes("w-full justify-end gap-2"):
            secondary_button("Keep it failed", on_click=lambda: _answer(dialog, False)).mark("resubmit-keep")
            primary_button("Resubmit", on_click=lambda: _answer(dialog, True)).mark("resubmit-confirm")
    if not await dialog:
        return None
    partition = chosen["partition"]
    options = slurm_options(project, settings, partition=partition,
                            ntasks=sc.ntasks if partition == sc.partition else None, time_limit=sc.time_limit)
    errors = [p for p in preflight(directory, project, "run", cases=[case], options=options, settings=settings)
              if p.severity == "error" and not p.message.startswith(f"Job {job.id} ")]
    if errors:
        ui.notify(errors[0].message, type="negative")
        return None
    try:
        updated = await run.io_bound(WATCHER.resubmit, directory, project, job.id, [case], options)
    except AeroSuiteError as exc:
        ui.notify(str(exc), type="negative")
        return None
    ui.notify(f"Resubmitted {case} to {partition}", type="positive")
    return updated

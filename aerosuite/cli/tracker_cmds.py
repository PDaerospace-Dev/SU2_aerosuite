"""`aerosuite tracker`: keep a run-matrix workbook's Status column in step with the projects' jobs."""
from pathlib import Path
from typing import Annotated, List, Optional

import typer

from ..engine import project as engine_project
from ..engine.errors import TrackerError
from ..engine.naming import format_value
from ..engine.tracker import collect_statuses, elevator_of, plan_changes, read_matrix, write_statuses
from .app import app, engine_errors

tracker_app = typer.Typer(help="Keep a run-matrix workbook (.xlsx) in step with the projects' jobs.",
                          no_args_is_help=True)
app.add_typer(tracker_app, name="tracker")


def _project(text: str) -> tuple[Path, float]:
    """FOLDER or FOLDER=DEGREES."""
    folder, sep, degrees = text.rpartition("=") if "=" in text else (text, "", "")
    if sep:
        try:
            elevator = float(degrees)
        except ValueError:
            raise TrackerError(f"{text!r}: the elevator deflection after '=' must be a number") from None
    else:
        elevator = elevator_of(Path(folder))
    engine_project.open_project(Path(folder))  # fails clearly if this is not a project
    return Path(folder), elevator


def _run(key) -> str:
    mach, altitude, aoa, elevator, beta = (format_value(v) for v in key)
    return f"M {mach}, {altitude} km, AoA {aoa}, elev {elevator}, beta {beta}"


def _line(change, arrow: str) -> str:
    source = change.source
    return (f"{change.row.run_id}  {_run(change.row.key)}: {change.row.status or '(blank)'} {arrow} {change.status}"
            f"  [{source.project} {source.case}, job {source.job_id}]")


@tracker_app.command()
@engine_errors
def sync(
    workbook: Annotated[Path, typer.Argument(help="The run-matrix workbook (.xlsx)")],
    sheet: Annotated[str, typer.Argument(help="The sheet to update, e.g. X07-80E_supersonic_1st")],
    projects: Annotated[List[str], typer.Argument(
        help="Project folders, one per elevator deflection, read from the name (del0, del20p, del30m) "
             "unless given as FOLDER=DEGREES")],
    tag: Annotated[Optional[List[str]], typer.Option(
        "--tag", help="Only jobs whose note has this #tag (repeatable: any of them)")] = None,
    skip_tag: Annotated[Optional[List[str]], typer.Option(
        "--skip-tag", help="Leave out jobs whose note has this #tag (repeatable)")] = None,
    overwrite: Annotated[bool, typer.Option(
        "--overwrite", help="Let a job's verdict replace one entered by hand (Converged, Not Converged, Failed)")]
    = False,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Show what would change, and each verdict kept; leave the workbook alone")] = False,
) -> None:
    """Set each run's Status from the newest job that ran its case. Notes and every other cell are left alone, and
    so is a verdict entered by hand that a job disagrees with (see --overwrite)."""
    pairs = [_project(text) for text in projects]
    matrix = read_matrix(workbook, sheet)
    statuses, warnings = collect_statuses(pairs, tags=tag or (), skip_tags=skip_tag or ())
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)
    plan = plan_changes(matrix, statuses, overwrite=overwrite)
    for change in plan.changes:
        typer.echo(_line(change, "->"))
    if dry_run:
        for change in plan.kept:
            typer.echo(_line(change, "kept, the job says"))
    no_job = len(matrix.rows) - len(plan.changes) - plan.unchanged - len(plan.kept)
    typer.echo(f"{sheet}: {len(plan.changes)} run(s) to change, {plan.unchanged} unchanged, {no_job} with no job.")
    if plan.kept:
        typer.echo(f"{len(plan.kept)} verdict(s) entered by hand differ from the job's and are kept"
                   f"{'' if dry_run else ' (--dry-run lists them)'}; --overwrite replaces them.")
    if plan.outside:
        names = ", ".join(f"{entry.project}/{entry.case}" for entry in plan.outside[:5])
        typer.echo(f"Warning: {len(plan.outside)} case(s) are not in the sheet's run matrix: "
                   f"{names}{' ...' if len(plan.outside) > 5 else ''}", err=True)
    if dry_run:
        typer.echo("Dry run: the workbook was not changed.")
        return
    if not plan.changes:
        return
    backup = write_statuses(workbook, sheet, matrix.status_column,
                            {change.row.row: change.status for change in plan.changes})
    typer.echo(f"Saved {workbook} (the previous version is {backup.name})")

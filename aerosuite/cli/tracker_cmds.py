"""`aerosuite tracker`: keep a run-matrix workbook's Status column in step with the projects' jobs, and add a sheet to
it from its template."""
from pathlib import Path
from typing import Annotated, List, Optional

import typer

from ..engine import project as engine_project
from ..engine.errors import TrackerError
from ..engine.naming import format_value
from ..engine.tracker import (collect_statuses, completion_date, detail_value, elevator_of, parse_values, plan_changes,
                              project_levels, read_matrix, read_template, sheet_name_problem, template_sheets,
                              write_statuses)
from ..engine.tracker_links import Link, LinkedProject, create_sheet
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
    completed = completion_date(matrix, plan, statuses)
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
    if completed:
        typer.echo(f"Every run has a verdict: Completed on ({matrix.completed_on}) is set to {completed:%Y-%m-%d}.")
    if dry_run:
        typer.echo("Dry run: the workbook was not changed.")
        return
    if not plan.changes and not completed:
        return
    backup = write_statuses(workbook, sheet, matrix.status_column,
                            {change.row.row: change.status for change in plan.changes},
                            {matrix.completed_on: completed} if completed else None)
    typer.echo(f"Saved {workbook} (the previous version is {backup.name})")


_AXES = ("Mach", "altitude (km)", "AoA (deg)", "elevator (deg)", "sideslip (deg)")


@tracker_app.command("new-sheet")
@engine_errors
def new_sheet_command(
    workbook: Annotated[Path, typer.Argument(help="The run-matrix workbook (.xlsx)")],
    name: Annotated[str, typer.Argument(help="The new sheet's name, e.g. X07-80E_transonic_1st")],
    projects: Annotated[List[str], typer.Argument(
        help="Project folders whose cases the sheet tracks, one per elevator deflection, read from the name (del0, "
             "del20p, del30m) unless given as FOLDER=DEGREES")],
    template: Annotated[Optional[str], typer.Option(
        "--template", help="The sheet to copy (default: the last visible sheet named ...template...)")] = None,
    mach: Annotated[Optional[str], typer.Option("--mach", help="Mach numbers, e.g. 0.3,0.6,0.9 (default: the "
                                                                "projects' cases)")] = None,
    altitude: Annotated[Optional[str], typer.Option("--altitude", help="Altitudes in km")] = None,
    aoa: Annotated[Optional[str], typer.Option("--aoa", help="Angles of attack in degrees")] = None,
    elevator: Annotated[Optional[str], typer.Option("--elevator", help="Elevator deflections in degrees (default: "
                                                                       "the projects')")] = None,
    beta: Annotated[Optional[str], typer.Option("--beta", help="Sideslip angles in degrees")] = None,
    detail: Annotated[Optional[List[str]], typer.Option(
        "--detail", help="A case detail as LABEL=VALUE, e.g. 'Notes=2nd order runs' (the label's start is enough; "
                         "repeatable). Others keep the template's.")] = None,
    tag: Annotated[Optional[List[str]], typer.Option(
        "--tag", help="The link counts only jobs whose note has this #tag (repeatable)")] = None,
    skip_tag: Annotated[Optional[List[str]], typer.Option(
        "--skip-tag", help="The link leaves out jobs whose note has this #tag (repeatable)")] = None,
    link: Annotated[bool, typer.Option(
        "--link/--no-link", help="Link the new sheet to the projects, so the web UI writes its Status")] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the sheet it would make; leave the workbook "
                                                            "alone")] = False,
) -> None:
    """Add a sheet to the workbook, a copy of its template sheet with the case details and the sweep filled in. The
    sweep comes from the projects' cases unless given; the formulas then lay out the run matrix as usual."""
    problem = sheet_name_problem(workbook, name)
    if problem:
        raise TrackerError(problem)
    pairs = [_project(text) for text in projects]
    if template is None:
        found = template_sheets(workbook)
        if not found:
            raise TrackerError(f"{workbook.name} has no sheet named ...template...; give one with --template")
        template = found[0]
    layout = read_template(workbook, template)
    levels = project_levels(pairs)
    for i, given in enumerate((mach, altitude, aoa, elevator, beta)):
        if given is not None:
            levels[i] = parse_values(given, f"--{('mach', 'altitude', 'aoa', 'elevator', 'beta')[i]}")
    details = {}
    for text in detail or []:
        label, sep, value = text.partition("=")
        if not sep:
            raise TrackerError(f"--detail {text!r}: give it as LABEL=VALUE")
        matches = [d for d in layout.details if d.label.lower().startswith(label.strip().lower())]
        if len(matches) != 1:
            labels = ", ".join(d.label for d in layout.details)
            raise TrackerError(f"--detail {label!r} matches {len(matches)} of {template}'s details: {labels}")
        details[matches[0].row] = detail_value(matches[0], value)
    runs = 1
    for axis, values in zip(_AXES, levels):
        typer.echo(f"{axis}: {', '.join(format_value(v) for v in values) or '(none)'}")
        runs *= max(1, len(values))
    typer.echo(f"{name}: a copy of {template}, {runs} runs (it has rows for {layout.runs}).")
    if dry_run:
        typer.echo("Dry run: the workbook was not changed.")
        return
    new_link = Link(workbook=str(workbook.resolve()), sheet=name, tags=tag or [], skip_tags=skip_tag or [],
                    projects=[LinkedProject(path=str(folder.resolve()), elevator=value) for folder, value in pairs])
    backup = create_sheet(new_link, template, details, levels, keep=link)
    typer.echo(f"Saved {workbook} (the previous version is {backup.name})")
    if link:
        typer.echo("Linked: the web UI's Run matrix page writes its Status as the cases run.")

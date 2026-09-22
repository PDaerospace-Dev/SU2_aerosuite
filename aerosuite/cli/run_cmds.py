"""Commands that generate configs, run sweeps and report on them."""
import time
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..engine import project as engine_project
from ..engine import results as engine_results
from ..engine.cfg import CONFIGS_DIR, generate_configs
from ..engine.jobs.local import LocalRunner, RUNS_DIR
from ..engine.jobs.runner import CaseState, JobRecord, JobState
from ..engine.jobs.store import list_jobs, load_job
from ..engine.preflight import has_errors, preflight
from .app import ProjectDir, app, engine_errors, print_problems


@app.command()
@engine_errors
def generate(directory: ProjectDir) -> None:
    """Check the project, then write configs/<case>.cfg, run_control.txt and cases.json."""
    project = engine_project.open_project(directory)
    problems = preflight(directory, project, "generate")
    print_problems(problems)
    if has_errors(problems):
        raise typer.Exit(1)
    written = generate_configs(directory, project)
    typer.echo(f"Wrote {len(written)} configs to {Path(directory) / CONFIGS_DIR}")


@app.command()
@engine_errors
def run(
    directory: ProjectDir,
    partitions: Annotated[Optional[int], typer.Option("-n", "--partitions", min=1, help="MPI partitions per case")] = None,
) -> None:
    """Start the sweep in the background and return; it keeps running after you log out."""
    project = engine_project.open_project(directory)
    if partitions is not None and partitions != project.run.partitions:
        project.run.partitions = partitions
        engine_project.save_project(directory, project)
    problems = preflight(directory, project, "run")
    print_problems(problems)
    if has_errors(problems):
        raise typer.Exit(1)
    job = LocalRunner().submit(directory, project)
    typer.echo(f"Started job {job.id}: {len(job.cases)} cases, log {Path(directory) / job.log_path}")
    typer.echo(f"Follow it with: aerosuite status {directory} --watch")


FAILURE_LINES = 10


def job_lines(job: JobRecord) -> list[str]:
    """The job header, one line per case, then the last log lines of failed cases."""
    lines = [f"Job {job.id}  {job.state.value}  (started {job.created:%Y-%m-%d %H:%M:%S})"]
    width = max((len(name) for name in job.cases), default=0)
    for name in job.cases:
        state = job.case_status.get(name, CaseState.PENDING)
        lines.append(f"  {name.ljust(width)}  {state.value}")
    for name, tail in job.failure_tail.items():
        lines.append(f"  --- {name} (last log lines) ---")
        lines += [f"    {line}" for line in tail.splitlines()[-FAILURE_LINES:]]
    return lines


def _echo_job(job: JobRecord) -> None:
    for line in job_lines(job):
        typer.echo(line)


def _snapshot(job: JobRecord) -> tuple:
    return job.state, dict(job.case_status)


@app.command()
@engine_errors
def status(
    directory: ProjectDir,
    watch: Annotated[bool, typer.Option("--watch", help="Keep refreshing until the job ends")] = False,
    interval: Annotated[float, typer.Option(hidden=True, min=0.0)] = 2.0,
) -> None:
    """Show the latest job and the state of each case."""
    jobs = list_jobs(directory)
    if not jobs:
        typer.echo(f"No jobs yet. Start one with: aerosuite run {directory}")
        return
    runner = LocalRunner()
    job = runner.refresh(directory, jobs[0])
    _echo_job(job)
    if len(jobs) > 1:
        typer.echo(f"({len(jobs) - 1} earlier job(s) in {Path(directory) / 'jobs'})")
    if not watch:
        return
    shown = _snapshot(job)
    try:
        while job.is_active:
            time.sleep(interval)
            job = runner.refresh(directory, job)
            if _snapshot(job) != shown:
                _echo_job(job)
                shown = _snapshot(job)
    except KeyboardInterrupt:
        typer.echo("Stopped watching; the job keeps running.")
        return
    typer.echo(f"Job {job.id} finished: {job.state.value}")


@app.command()
@engine_errors
def cancel(
    directory: ProjectDir,
    job_id: Annotated[Optional[str], typer.Argument(help="Job id (default: the running job)")] = None,
) -> None:
    """Stop a running job: the sweep script, mpirun and every SU2 process."""
    if job_id is not None:
        job = load_job(directory, job_id)
    else:
        active = [job for job in list_jobs(directory) if job.is_active]
        if not active:
            typer.echo("No running job to cancel.", err=True)
            raise typer.Exit(1)
        job = active[0]
    job = LocalRunner().cancel(directory, job)
    if job.state is JobState.CANCELLED:
        typer.echo(f"Cancelled job {job.id}.")
    else:
        typer.echo(f"Job {job.id} had already finished: {job.state.value}.")
    _echo_job(job)


@app.command()
@engine_errors
def summarize(
    directory: ProjectDir,
    last: Annotated[int, typer.Option(min=1, help="Average the last N iterations of each case")] = 100,
    columns: Annotated[str, typer.Option(help="Comma-separated history columns")] = "CL,CD,CMy",
) -> None:
    """Average each case's history into results/summary.csv and print it."""
    project_dir = Path(directory)
    engine_project.open_project(project_dir)  # fails clearly if this is not a project
    wanted = [col.strip() for col in columns.split(",") if col.strip()]
    index = engine_results.load_case_index(project_dir / CONFIGS_DIR)
    summary, warnings = engine_results.summarize(project_dir / RUNS_DIR, wanted, last, index)
    for warning in warnings:
        typer.echo(f"Warning: {warning}")
    if summary.empty:
        typer.echo(f"Error: No results found in {project_dir / RUNS_DIR}", err=True)
        raise typer.Exit(1)
    path = engine_results.write_summary(project_dir, summary)
    typer.echo(summary.to_string(index=False))
    typer.echo(f"Saved {path}")

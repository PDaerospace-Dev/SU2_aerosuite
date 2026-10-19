"""Commands that generate configs, run sweeps and report on them."""
import time
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..engine import project as engine_project
from ..engine import results as engine_results
from ..engine.cfg import CONFIGS_DIR, generate_configs
from ..engine.jobs.executors import backend_of, runner_for, runner_of, slurm_options
from ..engine.jobs.local import LocalRunner, RUNS_DIR
from ..engine.jobs.runner import CaseState, JobRecord, JobState
from ..engine.jobs.store import list_jobs, load_job
from ..engine.preflight import has_errors, preflight
from ..engine.settings import load_settings
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
    partitions: Annotated[Optional[int], typer.Option("-n", "--partitions", min=1,
                                                      help="MPI partitions per case (local)")] = None,
    backend: Annotated[Optional[str], typer.Option(
        help="local (mpirun on this machine) or slurm (one batch job per case); saved with the project")] = None,
    partition: Annotated[Optional[str], typer.Option(help="Slurm partition, e.g. node2")] = None,
    ntasks: Annotated[Optional[int], typer.Option(min=1, help="Slurm tasks (MPI ranks) per case")] = None,
    time_limit: Annotated[Optional[str], typer.Option("--time", help="Slurm time limit, e.g. 12:00:00")] = None,
) -> None:
    """Start the sweep and return: in the background here (local) or as Slurm jobs (slurm)."""
    project = engine_project.open_project(directory)
    settings, warnings = load_settings()
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)
    if backend is not None and backend not in ("local", "slurm"):
        typer.echo(f"Error: --backend must be local or slurm, not {backend!r}", err=True)
        raise typer.Exit(1)
    chosen = backend or backend_of(project, settings)
    slurm_given = [name for name, value in (("--partition", partition), ("--ntasks", ntasks), ("--time", time_limit))
                   if value is not None]
    if chosen == "local" and slurm_given:
        typer.echo(f"Error: {', '.join(slurm_given)} {'is' if len(slurm_given) == 1 else 'are'} for the Slurm "
                   "backend; for a local run use -n (MPI partitions)", err=True)
        raise typer.Exit(1)
    if chosen == "slurm" and partitions is not None:
        typer.echo("Error: -n is for the local backend; for Slurm use --ntasks (tasks per case)", err=True)
        raise typer.Exit(1)
    changed = False
    if backend is not None and backend != project.run.backend:
        project.run.backend, changed = backend, True
    if partitions is not None and partitions != project.run.partitions:
        project.run.partitions, changed = partitions, True
    if chosen == "slurm":
        slurm = project.run.slurm
        if partition is not None and partition != slurm.partition:
            slurm.partition, changed = partition, True
            if ntasks is None and slurm.ntasks is not None:  # another partition: its own default
                slurm.ntasks = None
        if ntasks is not None and ntasks != slurm.ntasks:
            slurm.ntasks, changed = ntasks, True
        if time_limit is not None and time_limit != slurm.time_limit:
            slurm.time_limit, changed = time_limit, True
    if changed:
        engine_project.save_project(directory, project)
    options = slurm_options(project, settings) if chosen == "slurm" else None
    problems = preflight(directory, project, "run", options=options, settings=settings)
    print_problems(problems)
    if has_errors(problems):
        raise typer.Exit(1)
    if chosen == "local":
        job = LocalRunner().submit(directory, project)
        typer.echo(f"Started job {job.id}: {len(job.cases)} cases, log {Path(directory) / job.log_path}")
    else:
        job = runner_for("slurm").submit(directory, project, options=options)
        ids = ", ".join(job.slurm[name].job_id for name in job.cases)
        typer.echo(f"Submitted job {job.id}: {len(job.cases)} cases to Slurm partition {options.partition}, "
                   f"{options.ntasks} tasks each (Slurm jobs {ids}); log {Path(directory) / job.log_path}")
    typer.echo(f"Follow it with: aerosuite status {directory} --watch")


FAILURE_LINES = 10


def job_lines(job: JobRecord) -> list[str]:
    """The job header, one line per case, then the last log lines of failed cases."""
    lines = [f"Job {job.id}  {job.state.value}  (started {job.created:%Y-%m-%d %H:%M:%S})"]
    if job.backend_ref.get("outage"):
        lines.append(f"  Slurm unreachable since {job.backend_ref.get('outage_since', '?')}; states may be stale: "
                     f"{job.backend_ref['outage']}")
    width = max((len(name) for name in job.cases), default=0)
    for name in job.cases:
        state = job.case_status.get(name, CaseState.PENDING)
        lines.append(f"  {name.ljust(width)}  {state.value}" + _slurm_text(job, name))
    for name, tail in job.failure_tail.items():
        lines.append(f"  --- {name} (last log lines) ---")
        lines += [f"    {line}" for line in tail.splitlines()[-FAILURE_LINES:]]
    return lines


def _slurm_text(job: JobRecord, name: str) -> str:
    """'  Slurm 101 RUNNING on hpc1 1:02:03', '... PENDING (Dependency)', '... OUT_OF_MEMORY exit 0:125'; '' if local."""
    sc = job.slurm.get(name)
    if sc is None:
        return ""
    text = f"  Slurm {sc.job_id} {sc.state}"
    if sc.state in ("RUNNING", "COMPLETING") and sc.node:
        text += f" on {sc.node} {sc.elapsed}"
    elif sc.reason:
        text += f" ({sc.reason})"
    if sc.exit_code and sc.state not in ("RUNNING", "PENDING"):
        text += f" exit {sc.exit_code}" + (f" on {sc.node}" if sc.node else "")
    return text


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
    interval: Annotated[Optional[float], typer.Option(hidden=True, min=0.0)] = None,
) -> None:
    """Show the latest job and the state of each case."""
    engine_project.open_project(directory)  # fails clearly if this is not a project
    jobs = list_jobs(directory)
    if not jobs:
        typer.echo(f"No jobs yet. Start one with: aerosuite run {directory}")
        return
    runner = runner_of(jobs[0])
    job = runner.refresh(directory, jobs[0])
    _echo_job(job)
    if job.backend == "slurm" and interval is None:
        interval = load_settings()[0].slurm.poll_seconds  # one squeue per poll interval, as the web
    interval = 2.0 if interval is None else interval
    if len(jobs) > 1:
        typer.echo(f"({len(jobs) - 1} earlier job(s) in {Path(directory) / 'jobs'})")
    if not watch:
        if job.backend_ref.get("outage"):
            raise typer.Exit(1)
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
    """Stop a running job: the sweep script, mpirun and every SU2 process (Slurm: scancel its jobs)."""
    engine_project.open_project(directory)  # fails clearly if this is not a project
    if job_id is not None:
        job = load_job(directory, job_id)
    else:
        active = [job for job in list_jobs(directory) if job.is_active]
        if not active:
            typer.echo("No running job to cancel.", err=True)
            raise typer.Exit(1)
        job = active[0]
    job = runner_of(job).cancel(directory, job)
    if job.state is JobState.CANCELLED:
        typer.echo(f"Cancelled job {job.id}.")
    else:
        typer.echo(f"Job {job.id} had already finished: {job.state.value}.")
    _echo_job(job)


@app.command()
@engine_errors
def resubmit(
    directory: ProjectDir,
    cases: Annotated[Optional[list[str]], typer.Argument(help="Cases (default: every NODE_FAIL / OUT_OF_MEMORY case "
                                                               "of the latest Slurm job)")] = None,
    partition: Annotated[Optional[str], typer.Option(help="Slurm partition (default: as before)")] = None,
    ntasks: Annotated[Optional[int], typer.Option(min=1, help="Slurm tasks per case (default: as before)")] = None,
) -> None:
    """Submit cases that ended NODE_FAIL or OUT_OF_MEMORY again, inside the same job, with the cases blocked behind
    them."""
    project = engine_project.open_project(directory)
    job = next((job for job in list_jobs(directory) if job.backend == "slurm"), None)
    if job is None:
        typer.echo("Error: No Slurm job to resubmit from.", err=True)
        raise typer.Exit(1)
    runner = runner_for("slurm")
    job = runner.refresh(directory, job)
    names = list(cases) if cases else runner.resubmittable(job)
    if not names:
        typer.echo(f"Error: No case of job {job.id} ended NODE_FAIL or OUT_OF_MEMORY.", err=True)
        raise typer.Exit(1)
    settings, _warnings = load_settings()
    first = job.slurm[names[0]] if names[0] in job.slurm else None
    options = slurm_options(project, settings, partition=partition or (first.partition if first else None),
                            ntasks=ntasks or (None if partition else (first.ntasks if first else None)),
                            time_limit=first.time_limit if first else None)
    problems = [p for p in preflight(directory, project, "run", cases=names, options=options, settings=settings)
                if not p.message.startswith(f"Job {job.id} ")]
    print_problems(problems)
    if has_errors(problems):
        raise typer.Exit(1)
    job = runner.resubmit(directory, project, job, names, options=options)
    typer.echo(f"Resubmitted to {options.partition}, {options.ntasks} tasks:")
    _echo_job(job)


@app.command()
@engine_errors
def summarize(
    directory: ProjectDir,
    last: Annotated[Optional[int], typer.Option(
        min=1, help="Average the last N iterations of each case (default: the Results page's setting)")] = None,
    columns: Annotated[Optional[str], typer.Option(
        help="Comma-separated history columns, instead of the Results page's parameters")] = None,
) -> None:
    """Average each case's history into results/summary.csv (with the Results page's parameters, derived values
    and characteristic values unless --columns is given) and print it."""
    project_dir = Path(directory)
    project = engine_project.open_project(project_dir)  # fails clearly if this is not a project
    if columns is None:
        _summarize_as_the_page(project_dir, project, last)
        return
    wanted = [col.strip() for col in columns.split(",") if col.strip()]
    last = last or 100
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


def _summarize_as_the_page(project_dir: Path, project, last: Optional[int]) -> None:
    from ..engine.packages import effective
    from ..engine.study_results import study_results, summary_frame, write_results

    definitions = effective(project.results, engine_results.history_columns(project_dir, project))
    result = study_results(project_dir, definitions, last or project.results.average_last)
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    for note in result.notes:
        typer.echo(f"Note: {note}")
    if result.table.empty:
        typer.echo(f"Error: No results found in {project_dir / RUNS_DIR}", err=True)
        raise typer.Exit(1)
    paths = write_results(project_dir, result, definitions.parameters)
    typer.echo(summary_frame(result, definitions.parameters).to_string(index=False))
    for path in paths:
        typer.echo(f"Saved {path}")

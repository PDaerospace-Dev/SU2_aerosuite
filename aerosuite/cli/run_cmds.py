"""Commands that generate configs, run sweeps and report on them."""
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..engine import project as engine_project
from ..engine.cfg import CONFIGS_DIR, generate_configs
from ..engine.jobs.local import LocalRunner
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

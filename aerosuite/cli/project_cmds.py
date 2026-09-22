"""Commands that create, inspect and change a project."""
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..engine import project as engine_project
from ..engine.cfg import settings_parameters
from ..engine.errors import ProjectError, TemplateError
from ..engine.jobs.runner import BUNDLED_SWEEP_SCRIPT
from ..engine.models import Project
from ..engine.naming import format_value
from .app import ProjectDir, app, engine_errors


def _values(values: list[float]) -> str:
    return ", ".join(format_value(v) for v in values) or "(none)"


def describe(project_dir: Path, project: Project) -> list[str]:
    """Human-readable summary lines for `show`."""
    template_ok = (Path(project_dir) / project.template).is_file()
    lines = [
        f"Project:   {project.name}",
        f"Template:  {project.template}" + ("" if template_ok else "  (missing)"),
        f"Mesh:      {project.mesh.path or '(none)'}",
    ]
    if project.mesh.markers:
        lines.append(f"Markers:   {', '.join(project.mesh.markers)}")
    sweep = project.sweep
    lines += [
        f"Mach:      {_values(sweep.mach)}",
        f"Alpha:     {_values(sweep.alpha)}",
        f"Beta:      {_values(sweep.beta)}",
        f"Altitude:  {sweep.altitude}",
    ]
    params = settings_parameters(project.settings)
    if params:
        lines.append("Settings:")
        lines += [f"  {key}= {'(line removed)' if value is None else value}" for key, value in params.items()]
    run = project.run
    script = run.sweep_script or f"bundled {BUNDLED_SWEEP_SCRIPT.name}"
    lines.append(f"Run:       {run.partitions} partitions, python {run.sweep_python}, script {script}")
    lines.append(f"Cases ({len(project.cases)}):")
    for case in project.cases:
        if case.restart == "none":
            lines.append(f"  {case.name}")
        else:
            detail = case.restart + (f" {case.restart_ref}" if case.restart_ref else "")
            lines.append(f"  {case.name}  [restart: {detail}]")
    return lines


@app.command()
@engine_errors
def new(
    directory: ProjectDir,
    template: Annotated[Optional[Path], typer.Option(help="Master .cfg template to copy in")] = None,
    mesh: Annotated[Optional[Path], typer.Option(help="Mesh file (.su2 markers are read)")] = None,
    name: Annotated[Optional[str], typer.Option(help="Project name (default: folder name)")] = None,
) -> None:
    """Create a new project folder."""
    # Check inputs first so a failure leaves no half-created project behind.
    if template is not None and not template.is_file():
        raise TemplateError(f"Template not found: {template}")
    if mesh is not None and not mesh.is_file():
        raise ProjectError(f"Mesh not found: {mesh}")
    project = engine_project.create_project(directory, name)
    if template is not None:
        engine_project.set_template(directory, project, template)
    if mesh is not None:
        engine_project.set_mesh(project, mesh)
    engine_project.save_project(directory, project)
    typer.echo(f"Created project '{project.name}' in {directory}")


@app.command()
@engine_errors
def show(directory: ProjectDir) -> None:
    """Print the project's settings, sweep and cases."""
    project = engine_project.open_project(directory)
    for line in describe(directory, project):
        typer.echo(line)

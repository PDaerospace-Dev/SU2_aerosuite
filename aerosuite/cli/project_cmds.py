"""Commands that create, inspect and change a project."""
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, List, Optional

import typer

from ..engine import project as engine_project
from ..engine.cfg import build_cases, settings_parameters
from ..engine.editing import parse_key_value, parse_value_list, set_parameter, unset_parameter, update_sweep
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


ValuesOption = Annotated[
    Optional[str], typer.Option(help="Comma/space-separated values; start:stop:step expands, e.g. -4:12:2")
]


@app.command("set")
@engine_errors
def set_(
    directory: ProjectDir,
    mach: ValuesOption = None,
    alpha: ValuesOption = None,
    beta: ValuesOption = None,
    altitude: Annotated[Optional[str], typer.Option(help="Altitude label used in case names")] = None,
    base_name: Annotated[Optional[str], typer.Option(help="Base name used in case names")] = None,
    template: Annotated[Optional[Path], typer.Option(help="Replace the master template")] = None,
    mesh: Annotated[Optional[Path], typer.Option(help="Replace the mesh")] = None,
    partitions: Annotated[Optional[int], typer.Option(min=1, help="MPI partitions per case")] = None,
    sweep_python: Annotated[Optional[str], typer.Option(help="Python that can import SU2")] = None,
    key: Annotated[Optional[List[str]], typer.Option(
        "--key", help="SU2 option KEY=VALUE (repeatable); MARKER_X=none removes that line")] = None,
    unset: Annotated[Optional[List[str]], typer.Option(
        "--unset", help="Forget an option so the template value applies again (repeatable)")] = None,
) -> None:
    """Change project settings; changing the sweep rebuilds the cases."""
    project = engine_project.open_project(directory)
    # Parse everything first so bad input changes nothing.
    mach_values = parse_value_list(mach) if mach is not None else None
    alpha_values = parse_value_list(alpha) if alpha is not None else None
    beta_values = parse_value_list(beta) if beta is not None else None
    pairs = [parse_key_value(item) for item in key or []]

    changes: list[str] = []
    for k, v in pairs:
        set_parameter(project.settings, k, v)
        changes.append(k)
    for k in unset or []:
        unset_parameter(project.settings, k)
        changes.append(f"{k.strip().upper()} (unset)")
    sweep_changed = update_sweep(
        project, mach=mach_values, alpha=alpha_values, beta=beta_values,
        altitude=altitude, base_name=base_name,
    )
    if sweep_changed:
        changes.append("sweep")
    if partitions is not None:
        project.run.partitions = partitions
        changes.append("partitions")
    if sweep_python is not None:
        project.run.sweep_python = sweep_python
        changes.append("sweep python")
    if mesh is not None:
        engine_project.set_mesh(project, mesh)
        changes.append("mesh")
    if template is not None:  # last: it copies a file into the project
        engine_project.set_template(directory, project, template)
        changes.append("template")

    if not changes:
        typer.echo("Nothing to change; see `aerosuite set --help`.")
        return
    engine_project.save_project(directory, project)
    typer.echo(f"Updated: {', '.join(changes)}.")
    if sweep_changed:
        typer.echo(f"The sweep now has {len(project.cases)} cases.")


def editor_command() -> list[str]:
    """$VISUAL, then $EDITOR, else nano (notepad on Windows), split into argv."""
    raw = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not raw:
        return ["notepad"] if sys.platform == "win32" else ["nano"]
    if Path(raw).is_file():  # an unquoted path that contains spaces
        return [raw]
    return [part.strip('"') for part in shlex.split(raw, posix=sys.platform != "win32")]


def _run_editor(path: Path) -> None:
    cmd = editor_command() + [str(path)]
    try:
        subprocess.run(cmd, check=False)
    except OSError as exc:
        raise ProjectError(f"Cannot start editor {cmd[0]!r} ({exc}); set the EDITOR variable") from exc


@app.command()
@engine_errors
def edit(directory: ProjectDir) -> None:
    """Edit project.json in your editor; it is saved only if it is valid."""
    original = engine_project.open_project(directory)
    fd, tmp_name = tempfile.mkstemp(prefix="aerosuite-project-", suffix=".json")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(engine_project.read_project_text(directory), encoding="utf-8")
        while True:
            _run_editor(tmp)
            try:
                project = engine_project.parse_project(tmp.read_text(encoding="utf-8-sig"), directory=directory)
                break
            except (ProjectError, UnicodeDecodeError) as exc:
                message = "the edited file is not UTF-8 text" if isinstance(exc, UnicodeDecodeError) else exc
                typer.echo(f"Error: {message}", err=True)
                if not typer.confirm("Re-open the editor to fix it?", default=True):
                    typer.echo("Discarded your changes; project.json is unchanged.")
                    raise typer.Exit(1)
        if project == original:
            typer.echo("No changes.")
            return
        if project.sweep != original.sweep:
            project.cases = build_cases(project)
            typer.echo(f"The sweep changed; cases rebuilt ({len(project.cases)}).")
        engine_project.save_project(directory, project)
        typer.echo("Saved project.json.")
    finally:
        tmp.unlink(missing_ok=True)

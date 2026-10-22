"""`aerosuite settings`: the server-wide settings (backend, Slurm) in $AEROSUITE_HOME/settings.json."""
from typing import Annotated

import typer

from ..engine.settings import load_settings, save_settings, set_value, settings_path
from .app import app, engine_errors

settings_app = typer.Typer(help="Show or change the server-wide settings (backend, Slurm).", no_args_is_help=False,
                           invoke_without_command=True)
app.add_typer(settings_app, name="settings")


def _lines(settings) -> list[str]:
    slurm = settings.slurm
    lines = [f"backend = {settings.backend}", f"ssh_address = {settings.ssh_address!r}"]
    for name, value in slurm.model_dump().items():
        if name != "partitions":
            lines.append(f"slurm.{name} = {value!r}" if isinstance(value, str) else f"slurm.{name} = {value}")
    for partition in slurm.partitions:
        for name, value in partition.model_dump().items():
            if name != "name":
                lines.append(f"slurm.partitions.{partition.name}.{name} = {value}")
    return lines


@settings_app.callback()
@engine_errors
def show(ctx: typer.Context) -> None:
    """Print where the settings are and every value."""
    if ctx.invoked_subcommand is not None:
        return
    settings, warnings = load_settings()
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)
    typer.echo(f"# {settings_path()}")
    for line in _lines(settings):
        typer.echo(line)


@settings_app.command("set")
@engine_errors
def set_(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. backend, slurm.poll_seconds, "
                                            "slurm.partitions.node2.default_ntasks")],
    value: Annotated[str, typer.Argument(help="The new value ('' or none to clear an optional one)")],
) -> None:
    """Change one setting and save."""
    settings, warnings = load_settings()
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)
    path = save_settings(set_value(settings, key, value))
    typer.echo(f"Saved {key} = {value} to {path}")

"""`aerosuite service`: the web UI as an always-on systemd user service, and the launcher for a PC."""
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..engine import service
from ..engine.remote import local_url, ssh_address, tunnel_command, unix_launcher, windows_launcher
from ..engine.settings import load_settings
from .app import app, engine_errors

service_app = typer.Typer(help="Keep the web UI running without a terminal (a systemd user service).",
                          no_args_is_help=True)
app.add_typer(service_app, name="service")


def _how_to_open(port: int) -> None:
    address = ssh_address(load_settings()[0])
    typer.echo(f"On this machine: open {local_url(port)}")
    typer.echo(f"From your PC:    {tunnel_command(address, port)}  then open {local_url(port)}")
    typer.echo("                 or `aerosuite service launcher` for a file that does both on a double-click")


@service_app.command()
@engine_errors
def install(
    root: Annotated[Optional[Path], typer.Option(help="Folder the file picker starts in (default: home)")] = None,
    port: Annotated[int, typer.Option(min=1, max=65535, help="Port to listen on (127.0.0.1 only)")] = 8080,
) -> None:
    """Install and start the service: it starts at boot, restarts after a crash, and runs while you are logged out.
    Run it again to change --root or --port."""
    for line in service.install(root or Path.home(), port):
        typer.echo(line)
    _how_to_open(port)


@service_app.command()
@engine_errors
def status() -> None:
    """Whether the service runs, and how to open it."""
    typer.echo(service.status_text())
    port = service.installed_port()
    if port is not None:
        typer.echo("")
        _how_to_open(port)


@service_app.command()
@engine_errors
def restart() -> None:
    """Restart the server, e.g. to run new code after an update. Running sweeps and Slurm jobs go on."""
    service.restart()
    typer.echo("Restarted")


@service_app.command()
@engine_errors
def stop() -> None:
    """Stop the server until the next restart, boot or `aerosuite service restart`."""
    service.stop()
    typer.echo("Stopped")


@service_app.command()
@engine_errors
def uninstall() -> None:
    """Stop the service and remove it."""
    for line in service.uninstall():
        typer.echo(line)


@service_app.command()
@engine_errors
def logs(lines: Annotated[int, typer.Option("-n", min=1, help="How many lines")] = 50) -> None:
    """The server's latest output."""
    typer.echo(service.logs(lines), nl=False)


@service_app.command()
@engine_errors
def launcher(
    kind: Annotated[str, typer.Option("--for", help="windows (AeroSuite.bat) or mac (aerosuite.command, also Linux)")]
    = "windows",
    output: Annotated[Optional[Path], typer.Option("-o", "--output", help="Write it here (default: print it)")] = None,
    port: Annotated[Optional[int], typer.Option(min=1, max=65535, help="Port (default: the service's)")] = None,
) -> None:
    """A file for your PC that opens the SSH tunnel and then AeroSuite in the browser."""
    if kind not in ("windows", "mac"):
        typer.echo("Error: --for must be windows or mac", err=True)
        raise typer.Exit(1)
    port = port or service.installed_port() or 8080
    address = ssh_address(load_settings()[0])
    text = windows_launcher(address, port) if kind == "windows" else unix_launcher(address, port)
    if output is None:
        typer.echo(text, nl=False)
        return
    output.write_text(text, encoding="utf-8", newline="")
    if kind == "mac":
        output.chmod(0o755)
    typer.echo(f"Wrote {output}: copy it to your PC and double-click it")

"""`aerosuite serve`: the browser UI."""
from pathlib import Path
from typing import Annotated, Optional

import typer

from .app import app, engine_errors

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@app.command()
@engine_errors
def serve(
    root: Annotated[Optional[Path], typer.Option(help="Folder the file picker starts in (default: home)")] = None,
    host: Annotated[str, typer.Option(help="Address to listen on")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="Port to listen on")] = 8080,
    i_understand_no_auth: Annotated[bool, typer.Option(
        "--i-understand-no-auth", help="Allow a non-local --host (the web UI has no login)")] = False,
) -> None:
    """Start the web UI. Over SSH, tunnel it: ssh -L 8080:127.0.0.1:8080 you@workstation."""
    if host not in LOCAL_HOSTS and not i_understand_no_auth:
        typer.echo(
            f"Error: refusing to listen on {host}: the web UI has no login. "
            "Use an SSH tunnel, or pass --i-understand-no-auth.",
            err=True,
        )
        raise typer.Exit(1)
    root_dir = (root or Path.home()).expanduser()
    if not root_dir.is_dir():
        typer.echo(f"Error: --root {root_dir} is not a folder", err=True)
        raise typer.Exit(1)
    from ..web import server  # imported here so the other commands start without loading NiceGUI

    shown = f"[{host}]" if ":" in host else host  # an IPv6 address goes in brackets in a URL
    typer.echo(f"AeroSuite web UI on http://{shown}:{port}  (Ctrl-C to stop)")
    server.run_server(root_dir, host, port)

"""Opening the web UI from another PC: the SSH tunnel command and a launcher file that opens it with the browser.

The server listens on 127.0.0.1 only (it has no login), so the tunnel is the way in: `ssh -N -L 8080:127.0.0.1:8080
user@host` on the PC, then http://localhost:8080 there.
"""
from __future__ import annotations

import getpass
import socket

from .settings import AppSettings


def default_ssh_address() -> str:
    """user@hostname of this machine, the address a PC on the same network uses unless Settings says otherwise."""
    return f"{getpass.getuser()}@{socket.gethostname()}"


def ssh_address(settings: AppSettings) -> str:
    return settings.ssh_address or default_ssh_address()


def tunnel_command(address: str, port: int) -> str:
    return f"ssh -N -L {port}:127.0.0.1:{port} {address}"


def local_url(port: int) -> str:
    return f"http://localhost:{port}"


def windows_launcher(address: str, port: int) -> str:
    """AeroSuite.bat: opens the tunnel in its window and the browser 3 s later; closing the window disconnects."""
    url = local_url(port)
    lines = ["@echo off",
             "title AeroSuite tunnel - close this window to disconnect",
             f"echo Connecting to {address}; AeroSuite opens in your browser at {url}",
             "echo Close this window to disconnect.",
             f"start \"\" /min powershell -NoProfile -Command \"Start-Sleep 3; Start-Process '{url}'\"",
             f"ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 -L {port}:127.0.0.1:{port} {address}",
             "echo.",
             f"echo The tunnel closed. If it said 'Address already in use', AeroSuite may already be open at {url}.",
             "pause"]
    return "\r\n".join(lines) + "\r\n"


def unix_launcher(address: str, port: int) -> str:
    """aerosuite.command (macOS: double-click; Linux: run it): the same as the .bat."""
    url = local_url(port)
    return "\n".join([
        "#!/bin/sh",
        f"# AeroSuite on {address}: opens the tunnel and, 3 s later, the browser. Ctrl-C or closing it disconnects.",
        f"echo 'Connecting to {address}; AeroSuite opens in your browser at {url}'",
        f"(sleep 3; open '{url}' 2>/dev/null || xdg-open '{url}' >/dev/null 2>&1) &",
        f"exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 -L {port}:127.0.0.1:{port} {address}",
    ]) + "\n"

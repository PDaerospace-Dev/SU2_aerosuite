"""The web UI as an always-on systemd user service: it starts at boot, restarts if it stops, and needs no terminal.

`aerosuite service install` writes ~/.config/systemd/user/aerosuite.service and starts it; `loginctl enable-linger`
keeps a user's services running while the user is logged out (and starts them at boot). The service runs
`aerosuite serve` through a login shell, so it sees the same PATH, modules and environment as a terminal.
KillMode=process: stopping or restarting it stops the server only, never a local sweep it started.
"""
from __future__ import annotations

import getpass
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .errors import ServiceError

SERVICE = "aerosuite.service"
NO_BUS = "Failed to connect to user scope bus"


def unit_path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "systemd" / "user" / SERVICE


def serve_command(root: Path, port: int) -> str:
    """The command the service runs: this environment's Python (not resolved: the venv's python is a link out of
    the venv), so it runs the AeroSuite installed here."""
    python = os.path.abspath(sys.executable)
    return " ".join(shlex.quote(part) for part in
                    (python, "-m", "aerosuite.cli", "serve", "--root", str(root), "--port", str(port)))


def unit_text(root: Path, port: int) -> str:
    command = serve_command(root, port)
    return "\n".join([
        "# Written by `aerosuite service install`; change it with that command (or edit, then",
        "# `systemctl --user daemon-reload` and `aerosuite service restart`).",
        "[Unit]",
        f"Description=AeroSuite web UI on http://127.0.0.1:{port}",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        "WorkingDirectory=%h",
        # A login shell: the same PATH, modules and AEROSUITE_* settings as a terminal.
        # systemd expands % and $ itself: doubled, they reach bash as written.
        "ExecStart=/bin/bash -lc " + shlex.quote("exec " + command).replace("%", "%%").replace("$", "$$"),
        "Restart=on-failure",
        "RestartSec=5",
        # Only the server: local sweeps it started run on (they are in this service's cgroup).
        "KillMode=process",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]) + "\n"


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    if shutil.which(args[0]) is None:
        raise ServiceError(f"{args[0]} was not found: the always-on service needs systemd")
    done = subprocess.run(args, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise ServiceError(f"{' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
    return done


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = _run(["systemctl", "--user", *args], check=False)
    if done.returncode != 0 and NO_BUS in (done.stderr or ""):
        # The user manager's own socket refused (seen on hpc1, 2026-10-22): reach it through the system bus.
        done = _run(["systemctl", "--user", f"--machine={getpass.getuser()}@.host", *args], check=False)
    if check and done.returncode != 0:
        raise ServiceError(f"systemctl --user {' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
    return done


def is_active() -> bool:
    return _systemctl("is-active", "--quiet", SERVICE, check=False).returncode == 0


def is_installed() -> bool:
    return unit_path().is_file()


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def lingering() -> Optional[bool]:
    """Whether this user's services run while logged out; None when loginctl cannot tell."""
    if shutil.which("loginctl") is None:
        return None
    done = subprocess.run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger", "--value"],
                          capture_output=True, text=True)
    return None if done.returncode != 0 else done.stdout.strip() == "yes"


def install(root: Path, port: int) -> list[str]:
    """Write the unit and start it; returns what was done, one line each."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ServiceError(f"--root {root} is not a folder")
    if port_in_use(port) and not is_active():
        raise ServiceError(f"Port {port} is in use, probably by an `aerosuite serve` started by hand: stop it "
                           f"(Ctrl-C in its terminal), or install on another --port")
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_text(root, port), encoding="utf-8")
    except OSError as exc:
        raise ServiceError(f"Cannot write {path}: {exc}") from exc
    done = [f"Wrote {path}"]
    _systemctl("daemon-reload")
    _systemctl("enable", SERVICE)
    _systemctl("restart", SERVICE)  # restart, not start: a reinstall with a new port or root takes effect
    done.append(f"Started; it starts again at boot and after a crash (http://127.0.0.1:{port})")
    if lingering() is False:
        linger = subprocess.run(["loginctl", "enable-linger", getpass.getuser()], capture_output=True, text=True)
        if linger.returncode == 0:
            done.append("Enabled lingering: the service keeps running when you log out")
        else:
            done.append(f"Could not enable lingering ({(linger.stderr or linger.stdout).strip()}): the service "
                        f"stops when you log out. Ask an admin to run: sudo loginctl enable-linger {getpass.getuser()}")
    return done


def restart() -> None:
    _require()
    _systemctl("restart", SERVICE)


def stop() -> None:
    _require()
    _systemctl("stop", SERVICE)


def uninstall() -> list[str]:
    _require()
    _systemctl("disable", "--now", SERVICE)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")
    return [f"Stopped and removed {unit_path()}"]


def status_text() -> str:
    _require()
    return _systemctl("status", "--no-pager", "--lines=0", SERVICE, check=False).stdout.strip()


def logs(lines: int = 50) -> str:
    return _run(["journalctl", "--user", "-u", SERVICE, "-n", str(lines), "--no-pager"], check=False).stdout


def installed_port() -> Optional[int]:
    """The --port in the installed unit, or None."""
    try:
        words = shlex.split(unit_path().read_text(encoding="utf-8").split("ExecStart=", 1)[1].splitlines()[0])
        inner = shlex.split(words[-1])
        return int(inner[inner.index("--port") + 1])
    except (OSError, IndexError, ValueError):
        return None


def _require() -> None:
    if not is_installed():
        raise ServiceError("The service is not installed: run `aerosuite service install --root /data`")

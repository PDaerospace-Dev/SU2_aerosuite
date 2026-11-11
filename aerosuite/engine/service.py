"""The web UI as an always-on systemd user service: it starts at boot, restarts if it stops, and needs no terminal.

`aerosuite service install` writes ~/.config/systemd/user/aerosuite.service and starts it; `loginctl enable-linger`
keeps a user's services running while the user is logged out (and starts them at boot). The service runs
`aerosuite serve` through a login shell, so it sees the same PATH, modules and environment as a terminal.
KillMode=process: stopping or restarting it stops the server only, never a local sweep it started.

The service runs from a copy of its own (`aerosuite service release`): <repository>-live beside the development
checkout, a git worktree at one commit with its own environment. Work in the development checkout, finished or not,
never reaches the running server (not at a restart, not after a crash); the live copy moves only on a release.
"""
from __future__ import annotations

import getpass
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .errors import ServiceError

SERVICE = "aerosuite.service"
NO_BUS = "Failed to connect to user scope bus"


def unit_path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "systemd" / "user" / SERVICE


def serve_command(root: Path, port: int, python: Optional[Path] = None) -> str:
    """The command the service runs: this environment's Python (not resolved: the venv's python is a link out of
    the venv), so it runs the AeroSuite installed here; or `python`, the live copy's."""
    python = os.path.abspath(python or sys.executable)
    return " ".join(shlex.quote(part) for part in
                    (str(python), "-m", "aerosuite.cli", "serve", "--root", str(root), "--port", str(port)))


def unit_text(root: Path, port: int, python: Optional[Path] = None) -> str:
    command = serve_command(root, port, python)
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
        raise ServiceError(f"{args[0]} was not found" + (
            ": the always-on service needs systemd" if args[0] in ("systemctl", "journalctl") else ""))
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
    linked = link_command()
    if linked:
        done.append(linked)
    if lingering() is False:
        linger = subprocess.run(["loginctl", "enable-linger", getpass.getuser()], capture_output=True, text=True)
        if linger.returncode == 0:
            done.append("Enabled lingering: the service keeps running when you log out")
        else:
            done.append(f"Could not enable lingering ({(linger.stderr or linger.stdout).strip()}): the service "
                        f"stops when you log out. Ask an admin to run: sudo loginctl enable-linger {getpass.getuser()}")
    return done


def link_command(python: Optional[Path] = None, move: bool = False) -> Optional[str]:
    """Make `aerosuite` work in any terminal: link ~/.local/bin/aerosuite to this environment's script (or the one
    beside `python`). Returns what was done, or None when there was nothing to do; never replaces a file that is not
    that link, except, with `move`, a link to another environment's aerosuite script (a release moves it to the
    live copy, so the command and the server run the same code)."""
    script = Path(os.path.abspath(python or sys.executable)).parent / "aerosuite"
    if not script.is_file():
        return None
    folder = Path.home() / ".local" / "bin"
    link = folder / "aerosuite"
    if link.is_symlink() and Path(os.readlink(link)) == script:
        return None
    if move and link.is_symlink() and Path(os.readlink(link)).name == "aerosuite":
        link.unlink()
    elif link.exists() or link.is_symlink():
        return f"Left {link} as it is (it is not a link to {script}); `aerosuite` may run another copy"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        link.symlink_to(script)
    except OSError as exc:
        return f"Could not link {link} ({exc}): run AeroSuite commands with `uv run aerosuite ...`"
    on_path = str(folder) in os.environ.get("PATH", "").split(os.pathsep)
    return f"Linked {link} to {script}: the aerosuite command works in any terminal" + (
        "" if on_path else f" once {folder} is on your PATH (add it in ~/.bashrc)")


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


def installed_root() -> Optional[Path]:
    """The --root in the installed unit, or None."""
    try:
        words = shlex.split(unit_path().read_text(encoding="utf-8").split("ExecStart=", 1)[1].splitlines()[0])
        inner = shlex.split(words[-1])
        return Path(inner[inner.index("--root") + 1])
    except (OSError, IndexError, ValueError):
        return None


def installed_python() -> Optional[Path]:
    """The Python the installed unit runs, or None."""
    try:
        words = shlex.split(unit_path().read_text(encoding="utf-8").split("ExecStart=", 1)[1].splitlines()[0])
        inner = shlex.split(words[-1])
        return Path(inner[1] if inner[0] == "exec" else inner[0])
    except (OSError, IndexError, ValueError):
        return None


# --- the live copy -----------------------------------------------------------------------------------------------

LIVE_SUFFIX = "-live"
START_SECONDS = 60  # how long a release waits for the restarted server to answer


def source_dir() -> Path:
    """The checkout this code runs from."""
    return Path(__file__).resolve().parents[2]


def _git(folder: Path, *args: str) -> str:
    done = _run(["git", "-C", str(folder), *args], check=False)
    if done.returncode != 0:
        raise ServiceError(f"git {' '.join(args)} failed in {folder}: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


def live_dir(source: Optional[Path] = None) -> Path:
    """Where the live copy is: <repository>-live beside the repository's main checkout (whichever of its worktrees
    `source` is)."""
    source = Path(source or source_dir())
    common = Path(_git(source, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    main = common.parent
    return main.with_name(main.name + LIVE_SUFFIX)


def _describe(folder: Path, commit: str = "HEAD") -> str:
    return _git(folder, "log", "-1", "--format=%h %cd %s", "--date=format:%Y-%m-%d %H:%M", commit)


def sync_environment(live: Path) -> None:
    """The live copy's own environment (.venv), exactly as uv.lock says, without the development tools."""
    if shutil.which("uv") is None:
        raise ServiceError("uv was not found on PATH: the live copy's environment is made with `uv sync`")
    done = subprocess.run(["uv", "sync", "--frozen", "--no-dev"], cwd=live, capture_output=True, text=True)
    if done.returncode != 0:
        raise ServiceError(f"uv sync failed in {live}: {(done.stderr or done.stdout).strip()[-600:]}")


def live_python(live: Path) -> Path:
    return live / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def live_text() -> str:
    """What the service runs, in a line: the live copy and its commit, or the checkout it runs straight from."""
    python = installed_python()
    if python is None:
        return ""
    checkout = python.parent.parent.parent  # <checkout>/.venv/bin/python
    try:
        what = _describe(checkout)
        branch = _git(checkout, "rev-parse", "--abbrev-ref", "HEAD")
    except ServiceError:
        return f"Runs {python}"
    if checkout.name.endswith(LIVE_SUFFIX):
        return f"Live copy {checkout} at {what}"
    return (f"Runs straight from {checkout} ({branch}, at {what}): edits there go live at the next restart. "
            f"`aerosuite service release` gives the server a copy of its own.")


def release(ref: str = "HEAD", root: Optional[Path] = None, port: Optional[int] = None,
            restart: bool = True) -> list[str]:
    """Put commit `ref` of this checkout into the live copy, bring its environment up to date and (with `restart`)
    run the service from it. Returns what was done, one line each; the last names the commit to release to go back.
    Only commits are released: uncommitted changes stay where they are."""
    source = source_dir()
    commit = _git(source, "rev-parse", "--verify", f"{ref}^{{commit}}")
    live = live_dir(source)
    done = []
    if _git(source, "status", "--porcelain"):
        done.append(f"Note: {source} has uncommitted changes; they are not part of the release")
    previous = ""
    if (live / ".git").exists():
        if _git(live, "status", "--porcelain", "--untracked-files=no"):  # its .venv is not a change
            raise ServiceError(f"The live copy {live} has changes of its own; look at them (git -C {live} status) "
                               f"and undo them before a release")
        previous = _git(live, "rev-parse", "HEAD")
        if previous != commit:
            _git(live, "checkout", "--detach", commit)
    elif live.exists():
        raise ServiceError(f"{live} exists and is not the live copy: move it away first")
    else:
        _git(source, "worktree", "add", "--detach", str(live), commit)
    done.append(f"Live copy {live} is at {_describe(live)}")
    sync_environment(live)
    python = live_python(live)
    if not python.is_file():
        raise ServiceError(f"{python} is missing after uv sync")
    root = Path(root or installed_root() or Path.home()).expanduser().resolve()
    port = port or installed_port() or 8080
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_text(root, port, python), encoding="utf-8")
    except OSError as exc:
        raise ServiceError(f"Cannot write {path}: {exc}") from exc
    _systemctl("daemon-reload")
    if restart:
        _systemctl("enable", SERVICE)
        _systemctl("restart", SERVICE)
        deadline = time.monotonic() + START_SECONDS
        while not port_in_use(port) and time.monotonic() < deadline:
            time.sleep(0.5)
        done.append(f"Restarted: http://127.0.0.1:{port} runs the live copy" if port_in_use(port) else
                    f"Restarted, but nothing answers on port {port} after {START_SECONDS} s: see "
                    f"`aerosuite service logs`")
        linked = link_command(python, move=True)
        if linked:
            done.append(linked)
    else:
        done.append("Not restarted: the server keeps running what it runs until `aerosuite service restart`")
    if previous and previous != commit:
        done.append(f"It was at {_describe(live, previous)}. To go back: aerosuite service release {previous[:10]}")
    return done


def _require() -> None:
    if not is_installed():
        raise ServiceError("The service is not installed: run `aerosuite service install --root /data`")

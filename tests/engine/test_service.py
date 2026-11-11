"""The always-on service (systemctl faked) and the PC launcher."""
import os
import subprocess
import sys

import pytest

from aerosuite.engine import remote, service
from aerosuite.engine.errors import ServiceError
from aerosuite.engine.settings import AppSettings, SettingsError, set_value


@pytest.fixture
def systemd(tmp_path, monkeypatch):
    """systemctl recorded instead of run; the unit goes under tmp_path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # install links ~/.local/bin/aerosuite
    calls = []
    state = {"active": False}

    def systemctl(*args, check=True):
        calls.append(list(args))
        if args[0] in ("restart", "enable"):
            state["active"] = True
        if args[0] == "disable":
            state["active"] = False
        code = 0 if args[0] != "is-active" or state["active"] else 3
        return type("Done", (), {"returncode": code, "stdout": "aerosuite.service - active", "stderr": ""})()

    monkeypatch.setattr(service, "_systemctl", systemctl)
    monkeypatch.setattr(service, "lingering", lambda: True)
    monkeypatch.setattr(service, "port_in_use", lambda port: False)
    return calls


def test_the_unit_runs_this_python_in_a_login_shell_and_never_stops_a_sweep(tmp_path):
    text = service.unit_text(tmp_path, 8081)
    assert f"ExecStart=/bin/bash -lc 'exec {os.path.abspath(sys.executable)} -m aerosuite.cli serve --root " \
           f"{tmp_path} --port 8081'" in text
    assert "KillMode=process" in text and "Restart=on-failure" in text and "WantedBy=default.target" in text


def test_percent_and_dollar_reach_bash_as_written(tmp_path):
    root = tmp_path / "50%_$HOME"
    line = next(text for text in service.unit_text(root, 8080).splitlines() if text.startswith("ExecStart="))
    assert "50%%_$$HOME" in line


def test_install_writes_enables_and_starts_it(systemd, tmp_path):
    lines = service.install(tmp_path, 8081)
    assert service.unit_path().is_file() and service.installed_port() == 8081
    assert systemd == [["daemon-reload"], ["enable", "aerosuite.service"], ["restart", "aerosuite.service"]]
    assert any("starts again at boot" in line for line in lines)
    assert service.is_active()


def test_install_refuses_a_port_a_hand_started_server_holds(systemd, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "port_in_use", lambda port: True)
    with pytest.raises(ServiceError, match="Port 8080 is in use"):
        service.install(tmp_path, 8080)
    assert not service.unit_path().exists()


def test_the_other_commands_need_it_installed(systemd):
    for action in (service.restart, service.stop, service.uninstall, service.status_text):
        with pytest.raises(ServiceError, match="not installed"):
            action()


def test_uninstall_stops_and_removes_it(systemd, tmp_path):
    service.install(tmp_path, 8080)
    service.uninstall()
    assert not service.unit_path().exists() and ["disable", "--now", "aerosuite.service"] in systemd


def test_the_tunnel_command_and_launchers_name_the_address_and_port():
    command = remote.tunnel_command("me@hpc1", 8081)
    assert command == "ssh -N -L 8081:127.0.0.1:8081 me@hpc1"
    bat = remote.windows_launcher("me@hpc1", 8081)
    assert "\r\n" in bat and "-L 8081:127.0.0.1:8081 me@hpc1" in bat and "Start-Process 'http://localhost:8081'" in bat
    mac = remote.unix_launcher("me@hpc1", 8081)
    assert mac.startswith("#!/bin/sh\n") and "exec ssh -N" in mac and "-L 8081:127.0.0.1:8081 me@hpc1" in mac


def test_the_ssh_address_setting(monkeypatch):
    monkeypatch.setattr(remote, "default_ssh_address", lambda: "me@hpc1")
    assert remote.ssh_address(AppSettings()) == "me@hpc1"
    settings = set_value(AppSettings(), "ssh_address", "pdas-hpc1@100.106.223.105")
    assert remote.ssh_address(settings) == "pdas-hpc1@100.106.223.105"
    with pytest.raises(SettingsError, match="user@host"):
        set_value(AppSettings(), "ssh_address", "me@hpc1; rm -rf /")


def test_systemctl_falls_back_to_the_system_bus(monkeypatch):
    calls = []

    def run(args, check=True):
        calls.append(args)
        refused = "--machine" not in " ".join(args)
        return type("Done", (), {"returncode": 1 if refused else 0, "stdout": "",
                                 "stderr": "Failed to connect to user scope bus via local transport" if refused else ""})()

    monkeypatch.setattr(service, "_run", run)
    monkeypatch.setattr(service.getpass, "getuser", lambda: "me")
    assert service._systemctl("daemon-reload").returncode == 0
    assert calls == [["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "--machine=me@.host", "daemon-reload"]]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", str(tmp_path / "home" / ".local" / "bin") + os.pathsep + "/usr/bin")
    return tmp_path / "home"


def test_install_links_the_command_into_local_bin(systemd, home, tmp_path):
    script = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "aerosuite")
    lines = service.install(tmp_path, 8080)
    link = home / ".local" / "bin" / "aerosuite"
    assert link.is_symlink() and os.readlink(link) == script
    assert any(line.startswith(f"Linked {link}") and line.endswith("works in any terminal") for line in lines)
    assert not any("Linked" in line for line in service.install(tmp_path, 8080))  # already there: nothing to say


def test_the_link_says_when_local_bin_is_not_on_path(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    assert service.link_command().endswith("is on your PATH (add it in ~/.bashrc)")


def test_the_link_never_replaces_another_file(home):
    folder = home / ".local" / "bin"
    folder.mkdir(parents=True)
    (folder / "aerosuite").write_text("#!/bin/sh\necho mine\n")
    assert service.link_command().startswith(f"Left {folder / 'aerosuite'} as it is")
    assert (folder / "aerosuite").read_text() == "#!/bin/sh\necho mine\n"


# --- the live copy ---------------------------------------------------------------------------------------------------

def _git(folder, *args):
    subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True)


@pytest.fixture
def checkout(tmp_path, monkeypatch, systemd):
    """A development checkout with one commit; `uv sync` replaced by a python and an aerosuite script appearing."""
    source = tmp_path / "repo"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    (source / "code.py").write_text("version = 1\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "first")

    def sync(live):
        folder = live / ".venv" / "bin"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("python", "aerosuite"):
            (folder / name).write_text("")

    monkeypatch.setattr(service, "source_dir", lambda: source)
    monkeypatch.setattr(service, "sync_environment", sync)
    monkeypatch.setattr(service, "port_in_use", lambda port: True)  # the restarted server answers
    return source


def _commit(source, text, message):
    (source / "code.py").write_text(text)
    _git(source, "commit", "-q", "-am", message)


def test_a_release_runs_the_service_from_a_copy_of_its_own(checkout, tmp_path, systemd):
    lines = service.release(root=tmp_path, port=8081)
    live = tmp_path / "repo-live"
    assert service.live_dir(checkout) == live and (live / "code.py").read_text() == "version = 1\n"
    assert service.installed_python() == live / ".venv" / "bin" / "python"
    assert (service.installed_port(), service.installed_root()) == (8081, tmp_path)
    assert systemd[-3:] == [["daemon-reload"], ["enable", "aerosuite.service"], ["restart", "aerosuite.service"]]
    assert any("first" in line and "Live copy" in line for line in lines)
    assert any("runs the live copy" in line for line in lines)
    assert "Live copy" in service.live_text() and "first" in service.live_text()
    link = tmp_path / "home" / ".local" / "bin" / "aerosuite"
    assert os.readlink(link) == str(live / ".venv" / "bin" / "aerosuite")  # the command is the live copy's too


def test_work_in_the_checkout_reaches_the_server_only_on_a_release(checkout, tmp_path):
    service.release(root=tmp_path, port=8081)
    live = tmp_path / "repo-live"
    _commit(checkout, "version = 2\n", "second")
    (checkout / "code.py").write_text("half an edit")  # and unfinished work on top
    assert (live / "code.py").read_text() == "version = 1\n"
    lines = service.release()  # the root and port as installed
    assert (live / "code.py").read_text() == "version = 2\n" and service.installed_port() == 8081
    assert any("uncommitted changes" in line for line in lines)
    back = lines[-1]
    assert "It was at" in back and "first" in back and "To go back: aerosuite service release " in back
    service.release(back.rsplit(" ", 1)[1])  # going back
    assert (live / "code.py").read_text() == "version = 1\n"


def test_a_release_can_leave_the_running_server_alone(checkout, tmp_path, systemd):
    lines = service.release(root=tmp_path, port=8081, restart=False)
    assert ["restart", "aerosuite.service"] not in systemd
    assert any("Not restarted" in line for line in lines)


def test_a_live_copy_that_was_edited_is_not_released_over(checkout, tmp_path):
    service.release(root=tmp_path, port=8081)
    (tmp_path / "repo-live" / "code.py").write_text("patched in place")
    with pytest.raises(ServiceError, match="has changes of its own"):
        service.release()
    with pytest.raises(ServiceError, match="rev-parse"):
        service.release("no-such-commit")


def test_a_service_running_from_the_checkout_is_told_so(systemd, tmp_path, monkeypatch):
    checkout_python = tmp_path / "repo" / ".venv" / "bin" / "python"
    service.unit_path().parent.mkdir(parents=True)
    service.unit_path().write_text(service.unit_text(tmp_path, 8080, checkout_python))
    (tmp_path / "repo").mkdir()
    _git(tmp_path / "repo", "init", "-q", "-b", "dev")
    (tmp_path / "repo" / "a").write_text("")
    _git(tmp_path / "repo", "add", ".")
    _git(tmp_path / "repo", "commit", "-q", "-m", "work")
    assert "Runs straight from" in service.live_text() and "aerosuite service release" in service.live_text()

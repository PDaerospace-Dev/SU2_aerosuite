"""The always-on service (systemctl faked) and the PC launcher."""
import os
import sys

import pytest

from aerosuite.engine import remote, service
from aerosuite.engine.errors import ServiceError
from aerosuite.engine.settings import AppSettings, SettingsError, set_value


@pytest.fixture
def systemd(tmp_path, monkeypatch):
    """systemctl recorded instead of run; the unit goes under tmp_path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
    line = next(l for l in service.unit_text(root, 8080).splitlines() if l.startswith("ExecStart="))
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

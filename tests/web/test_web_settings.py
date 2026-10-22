import json

from nicegui.testing import User

from aerosuite.engine.settings import load_settings, settings_path


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def _commit(user, marker, value):
    with user:
        _element(user, marker).set_value(value)
    user.find(marker=marker).trigger("keydown.enter")


async def test_shows_the_defaults(user: User):
    await user.open("/settings")
    await user.should_see("Execution")
    assert _element(user, "settings-backend").value == "local"
    assert _element(user, "settings-shared_root").value == "/data"
    assert _element(user, "settings-default_partition").value == "node1"
    assert _element(user, "partition-1-name").value == "node2"
    assert _element(user, "partition-1-default_ntasks").value == "48"
    assert _element(user, "partition-1-block").value is True
    assert not _element(user, "partition-0-remove").enabled  # the default partition stays


async def test_edits_are_saved(user: User):
    await user.open("/settings")
    with user:
        _element(user, "settings-backend").set_value("slurm")
    await user.should_see("Execution")
    await _commit(user, "settings-poll_seconds", "15")
    await _commit(user, "partition-1-default_ntasks", "32")
    await _commit(user, "settings-default_time_limit", "12:00:00")
    settings, _ = load_settings()
    assert settings.backend == "slurm"
    assert settings.slurm.poll_seconds == 15
    assert settings.slurm.partition("node2").default_ntasks == 32
    assert settings.slurm.default_time_limit == "12:00:00"


async def test_invalid_values_are_refused(user: User):
    await user.open("/settings")
    await _commit(user, "settings-default_time_limit", "soon")
    await user.should_see("time limit 'soon' is not in a Slurm format")
    await _commit(user, "partition-0-memory_limit_mb", "lots")
    await user.should_see("'lots' is not a whole number")
    assert not settings_path().exists()


async def test_add_rename_and_remove_partitions(user: User):
    await user.open("/settings")
    user.find(marker="partition-add").click()
    await user.should_see(marker="partition-2-name")
    assert [p.name for p in load_settings()[0].slurm.partitions] == ["node1", "node2", "node3"]
    await _commit(user, "partition-0-name", "big")
    settings, _ = load_settings()
    assert settings.slurm.default_partition == "big" and settings.slurm.partitions[0].name == "big"
    user.find(marker="partition-2-remove").click()
    await user.should_not_see(marker="partition-2-name")
    assert [p.name for p in load_settings()[0].slurm.partitions] == ["big", "node2"]


async def test_an_unreadable_file_is_reported(user: User):
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps({"backend": "pbs"}))
    await user.open("/settings")
    await user.should_see(marker="settings-warning")


async def test_the_gear_opens_the_settings(user: User):
    await user.open("/")
    user.find(marker="settings").click()
    await user.should_see(marker="settings-backend")


async def test_open_from_your_pc_gives_the_tunnel_and_launchers(user: User, monkeypatch):
    from aerosuite.engine import remote, service
    from aerosuite.web.pages import settings as settings_page

    monkeypatch.setattr(settings_page, "default_ssh_address", lambda: "me@hpc1")
    monkeypatch.setattr(remote, "default_ssh_address", lambda: "me@hpc1")
    monkeypatch.setattr(service, "is_installed", lambda: False)
    from aerosuite.web import serving

    monkeypatch.setitem(serving.PORT, "value", 8080)  # another test's server may have set it
    await user.open("/settings")
    assert _element(user, "remote-command").text == "ssh -N -L 8080:127.0.0.1:8080 me@hpc1"
    assert "aerosuite service install --root /data --port 8080" in _element(user, "remote-service").text
    await user.should_see(marker="remote-windows")
    await user.should_see(marker="remote-mac")
    await _commit(user, "settings-ssh_address", "pdas@100.106.223.105")
    assert load_settings()[0].ssh_address == "pdas@100.106.223.105"
    assert _element(user, "remote-command").text == "ssh -N -L 8080:127.0.0.1:8080 pdas@100.106.223.105"
    await _commit(user, "settings-ssh_address", "bad address")
    assert load_settings()[0].ssh_address == "pdas@100.106.223.105"

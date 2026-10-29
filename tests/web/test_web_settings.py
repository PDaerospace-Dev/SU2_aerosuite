import json

from nicegui.testing import User

from aerosuite.engine.settings import load_settings, settings_path


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def _commit(user, marker, value):
    with user:
        _element(user, marker).set_value(value)
    user.find(marker=marker).trigger("keydown.enter")


async def _choose(user, index):
    """Open a partition's settings under the cards."""
    user.find(marker=f"partition-card-{index}").click()
    await user.should_see(marker=f"partition-detail-{index}")


async def test_shows_the_defaults(user: User):
    await user.open("/settings")
    await user.should_see("Execution")
    assert _element(user, "settings-backend").value == "local"
    assert _element(user, "settings-shared_root").value == "/data"
    assert _element(user, "settings-default_partition").value == "node1"
    assert not _element(user, "partition-0-remove").enabled  # the default partition stays
    await _choose(user, 1)
    assert _element(user, "partition-1-name").value == "node2"
    assert _element(user, "partition-1-default_ntasks").value == "48"
    assert _element(user, "partition-1-block").value is True
    assert _element(user, "partition-1-remove").enabled


async def test_edits_are_saved(user: User):
    await user.open("/settings")
    with user:
        _element(user, "settings-backend").set_value("slurm")
    await user.should_see("Execution")
    await _commit(user, "settings-poll_seconds", "15")
    await _choose(user, 1)
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
    await user.should_see(marker="partition-3-name")  # the new partition opens
    assert [p.name for p in load_settings()[0].slurm.partitions] == ["node1", "node2", "node0", "node4"]
    await _choose(user, 0)
    await _commit(user, "partition-0-name", "big")
    await user.should_see("big", marker="partition-card-0")  # the card follows the form
    settings, _ = load_settings()
    assert settings.slurm.default_partition == "big" and settings.slurm.partitions[0].name == "big"
    await _choose(user, 3)
    user.find(marker="partition-3-remove").click()
    await user.should_not_see(marker="partition-card-3")
    assert [p.name for p in load_settings()[0].slurm.partitions] == ["big", "node2", "node0"]


async def test_an_unreadable_file_is_reported(user: User):
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps({"backend": "pbs"}))
    await user.open("/settings")
    await user.should_see(marker="settings-warning")


async def test_the_settings_button_opens_the_settings(user: User):
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


async def test_a_partitions_launch_command_and_environment_are_edited_and_saved(user: User):
    await user.open("/settings?tab=partitions")
    await _choose(user, 2)
    assert _element(user, "partition-2-launch_command").value == 'mpirun --bind-to core -np "$SLURM_NTASKS" SU2_CFD'
    assert _element(user, "partition-2-path").value == "/usr/local/bin:/usr/bin:/bin"
    assert _element(user, "partition-2-unset_vars").value == "LD_LIBRARY_PATH"
    assert _element(user, "partition-2-login_shell").value is False
    assert _element(user, "partition-2-exclusive").value == "no"
    await _commit(user, "partition-2-job_env", "OMPI_MCA_btl=self,vader")
    assert load_settings()[0].slurm.partition("node0").job_env == "OMPI_MCA_btl=self,vader"
    await _commit(user, "partition-2-unset_vars", "LD_LIBRARY_PATH 1BAD")
    assert load_settings()[0].slurm.partition("node0").unset_vars == "LD_LIBRARY_PATH"  # refused, not saved


async def test_a_partitions_own_job_script_shows_with_its_launch_command(user: User):
    await user.open("/settings?tab=partitions")
    assert _element(user, "settings-tabs").value == "partitions"
    await _choose(user, 1)  # node2: the Slurm-wide job script
    assert _element(user, "partition-1-launch_command").value == ""
    await user.should_see(marker="partition-1-slurm-wide")
    await user.should_not_see(marker="partition-1-path")
    await _commit(user, "partition-1-launch_command", "mpirun SU2_CFD")
    await user.should_see(marker="partition-1-path")
    await user.should_see("own script", marker="partition-card-1")
    assert load_settings()[0].slurm.partition("node2").launch_command == "mpirun SU2_CFD"


async def test_another_partition_is_made_the_default(user: User):
    await user.open("/settings?tab=partitions&partition=node0")
    await user.should_see(marker="partition-detail-2")
    user.find(marker="partition-2-make-default").click()
    await user.should_not_see(marker="partition-2-make-default")
    assert load_settings()[0].slurm.default_partition == "node0"
    assert not _element(user, "partition-2-remove").enabled

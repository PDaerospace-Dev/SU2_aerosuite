import json

import pytest

from aerosuite.engine.settings import (
    AppSettings,
    SettingsError,
    load_settings,
    save_settings,
    set_value,
    settings_path,
    valid_time_limit,
    validated,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_defaults_when_no_file(home):
    settings, warnings = load_settings()
    assert warnings == []
    assert settings.backend == "local"
    slurm = settings.slurm
    assert slurm.shared_root == "/data"
    assert [p.name for p in slurm.partitions] == ["node1", "node2"]
    assert slurm.partition(None).name == "node1"
    node2 = slurm.partition("node2")
    assert (node2.default_ntasks, node2.memory_limit_mb, node2.ntasks_warn_above, node2.block_over_memory) == (
        48, 62000, 48, True)
    assert slurm.partition("node1").memory_limit_mb == 122880
    assert slurm.partition("nope") is None
    assert slurm.exclusive and slurm.gb_per_million_cells == 3.9
    assert slurm.module_line == "module load mpi/openmpi-x86_64"
    assert slurm.su2_bin == "/opt/su2/bin"
    assert slurm.srun_command == "srun --mpi=pmix SU2_CFD"
    assert slurm.account == "pdas" and slurm.default_time_limit == ""
    assert 10 <= slurm.poll_seconds <= 15


def test_path_follows_aerosuite_home(home):
    assert settings_path() == home / "settings.json"


def test_round_trip(home):
    settings = set_value(AppSettings(), "backend", "slurm")
    path = save_settings(settings)
    assert path == home / "settings.json"
    assert not path.with_name("settings.json.tmp").exists()
    loaded, warnings = load_settings()
    assert warnings == [] and loaded == settings


@pytest.mark.parametrize("text", ["{not json", json.dumps({"backend": "pbs"}), json.dumps([1, 2])])
def test_unusable_file_gives_defaults_and_a_warning(home, text):
    home.mkdir()
    (home / "settings.json").write_text(text)
    settings, warnings = load_settings()
    assert settings == AppSettings()
    assert len(warnings) == 1 and "settings.json" in warnings[0] and "default" in warnings[0]


@pytest.mark.parametrize("text", ["", "30", "30:00", "12:00:00", "2-00", "2-00:30", "2-00:00:00", "UNLIMITED"])
def test_good_time_limits(text):
    assert valid_time_limit(text)


@pytest.mark.parametrize("text", ["abc", "1:2:3:4", "-5", "12h", "1-2-3", "12:00:00\n#SBATCH -p x"])
def test_bad_time_limits(text):
    assert not valid_time_limit(text)


def _data(**slurm):
    data = AppSettings().model_dump()
    data["slurm"].update(slurm)
    return data


@pytest.mark.parametrize("change, message", [
    (dict(shared_root="data"), "absolute"),
    (dict(default_partition="node3"), "node3"),
    (dict(default_time_limit="soon"), "time limit"),
    (dict(account="pdas\n#SBATCH -p x"), "account"),
    (dict(module_line="module load a\nrm -rf /"), "single line"),
    (dict(partitions=[]), "at least one partition"),
    (dict(poll_seconds=1), "poll_seconds"),
])
def test_invalid_settings_are_rejected(change, message):
    with pytest.raises(SettingsError, match=message):
        validated(_data(**change))


def test_duplicate_partition_names_rejected():
    data = _data()
    data["slurm"]["partitions"][1]["name"] = "node1"
    with pytest.raises(SettingsError, match="unique"):
        validated(data)


def test_partition_name_must_be_safe():
    data = _data()
    data["slurm"]["partitions"][1]["name"] = "node 2"
    with pytest.raises(SettingsError, match="partition name"):
        validated(data)


def test_set_value_parses_by_type():
    settings = AppSettings()
    settings = set_value(settings, "slurm.poll_seconds", "15")
    settings = set_value(settings, "slurm.partitions.node2.default_ntasks", "32")
    settings = set_value(settings, "slurm.partitions.node1.ntasks_warn_above", "64")
    settings = set_value(settings, "slurm.partitions.node2.ntasks_warn_above", "none")
    settings = set_value(settings, "slurm.exclusive", "false")
    settings = set_value(settings, "slurm.default_time_limit", "12:00:00")
    settings = set_value(settings, "slurm.account", "")
    assert settings.slurm.poll_seconds == 15
    assert settings.slurm.partition("node2").default_ntasks == 32
    assert settings.slurm.partition("node2").ntasks_warn_above is None
    assert settings.slurm.partition("node1").ntasks_warn_above == 64
    assert settings.slurm.exclusive is False
    assert settings.slurm.default_time_limit == "12:00:00"
    assert settings.slurm.account == ""


@pytest.mark.parametrize("key", ["slurm.nope", "nope", "slurm.partitions.node9.default_ntasks",
                                 "slurm.partitions.node1.name", "slurm.partitions"])
def test_set_value_unknown_key(key):
    with pytest.raises(SettingsError, match="Unknown setting"):
        set_value(AppSettings(), key, "1")


def test_set_value_invalid_value():
    with pytest.raises(SettingsError, match="default_ntasks"):
        set_value(AppSettings(), "slurm.partitions.node1.default_ntasks", "0")
    with pytest.raises(SettingsError, match="backend"):
        set_value(AppSettings(), "backend", "pbs")

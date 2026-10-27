"""Server-wide settings: which backend runs jobs and how Slurm is used ($AEROSUITE_HOME/settings.json).

The defaults are the cluster's facts (two single-node partitions, /data shared over NFS, SU2 in /opt/su2/bin);
nothing else in the code names a partition, a path or a limit.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .errors import AeroSuiteError

SETTINGS_FILE = "settings.json"
Backend = Literal["local", "slurm"]
BACKENDS = ("local", "slurm")

# Slurm's --time formats: M, M:S, H:M:S, D-H, D-H:M, D-H:M:S (and no limit).
_TIME_RE = re.compile(r"^(\d+|\d+:\d{1,2}|\d+:\d{1,2}:\d{1,2}|\d+-\d+|\d+-\d+:\d{1,2}|\d+-\d+:\d{1,2}:\d{1,2}"
                      r"|UNLIMITED|INFINITE)$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ADDRESS_RE = re.compile(r"^[A-Za-z0-9_.-]+@?[A-Za-z0-9_.:-]*$")


class SettingsError(AeroSuiteError):
    """A setting has a value AeroSuite cannot use."""


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_pairs(text: str) -> list[tuple[str, str]]:
    """'A=1 B=x' -> [('A', '1'), ('B', 'x')]; ValueError for anything that is not NAME=value."""
    pairs = []
    for item in text.split():
        name, sep, value = item.partition("=")
        if not sep or not _ENV_NAME_RE.match(name):
            raise ValueError(f"job environment must be NAME=value pairs separated by spaces, not {item!r}")
        pairs.append((name, value))
    return pairs


def valid_time_limit(text: str) -> bool:
    """True for "" (no limit) and Slurm's --time formats, e.g. "30", "12:00:00", "2-00:00:00"."""
    return text == "" or bool(_TIME_RE.match(text))


class PartitionSettings(BaseModel):
    name: str
    default_ntasks: int = Field(ge=1)
    # What a job may use before Slurm kills it (OUT_OF_MEMORY); for an --exclusive job.
    memory_limit_mb: int = Field(ge=1)
    ntasks_warn_above: Optional[int] = Field(default=None, ge=1)  # no speed-up beyond this many tasks
    block_over_memory: bool = False  # an estimate over the limit blocks the submit (else a warning)
    # How a job on this partition starts SU2. With launch_command empty the job script uses the Slurm-wide module
    # line, su2_bin, job_env and srun_command; with it set, the script uses only the fields below (and never
    # --export, so the job keeps the submitting user's environment).
    launch_command: str = ""  # followed by the case's .cfg, e.g. mpirun --bind-to core -np "$SLURM_NTASKS" SU2_CFD
    module_line: str = ""  # "" = none
    path: str = ""  # exported as PATH, replacing it; "" = PATH is left alone
    unset_vars: str = ""  # names unset in the script, separated by spaces, e.g. LD_LIBRARY_PATH
    job_env: str = ""  # NAME=value pairs exported in the script, separated by spaces
    login_shell: bool = True  # #!/bin/bash -l; False: #!/bin/bash
    exclusive: Optional[bool] = None  # None: the Slurm-wide setting

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"partition name {value!r} must be letters, digits, '_', '.' or '-'")
        return value

    @field_validator("job_env")
    @classmethod
    def _env(cls, value: str) -> str:
        env_pairs(value)  # raises ValueError
        return value

    @field_validator("unset_vars")
    @classmethod
    def _unset(cls, value: str) -> str:
        for name in value.split():
            if not _ENV_NAME_RE.match(name):
                raise ValueError(f"unset_vars must be variable names separated by spaces, not {name!r}")
        return value

    @field_validator("launch_command", "module_line", "path")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("must be a single line")
        return value.strip()


def _default_partitions() -> list[PartitionSettings]:
    return [
        PartitionSettings(name="node1", default_ntasks=96, memory_limit_mb=122880),
        PartitionSettings(name="node2", default_ntasks=48, memory_limit_mb=62000, ntasks_warn_above=48,
                          block_over_memory=True),
        # hpc0, the old Ubuntu workstation: its own SU2 and Open MPI (PMIx 5; the nodes have pmix_v4, so no
        # srun --mpi=pmix), started with mpirun. Not --exclusive: the workstation is also used by hand.
        PartitionSettings(name="node0", default_ntasks=32, memory_limit_mb=235000, ntasks_warn_above=64,
                          block_over_memory=True,
                          launch_command='mpirun --bind-to core -np "$SLURM_NTASKS" SU2_CFD',
                          path="/usr/local/bin:/usr/bin:/bin", unset_vars="LD_LIBRARY_PATH", login_shell=False,
                          exclusive=False),
    ]


class SlurmSettings(BaseModel):
    shared_root: str = "/data"  # case folders must be under it: every node mounts it
    partitions: list[PartitionSettings] = Field(default_factory=_default_partitions)
    default_partition: str = "node1"
    exclusive: bool = True  # one job per node: two jobs sharing a node gave no extra throughput
    gb_per_million_cells: float = Field(default=3.9, gt=0)
    module_line: str = "module load mpi/openmpi-x86_64"
    su2_bin: str = "/opt/su2/bin"
    srun_command: str = "srun --mpi=pmix SU2_CFD"
    # Exported in the job script, NAME=value separated by spaces. OMPI_MCA_osc=^ucx: Open MPI 5 prints one "OSC UCX
    # component priority" error per rank at start-up otherwise (harmless; checked on hpc1 2026-10-20).
    job_env: str = "OMPI_MCA_osc=^ucx"
    poll_seconds: float = Field(default=12.0, ge=5, le=120)
    default_time_limit: str = ""  # "" = no -t
    account: str = "pdas"  # "" = no -A

    @field_validator("shared_root")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not os.path.isabs(value):
            raise ValueError(f"shared_root must be an absolute path: {value!r}")
        return value

    @field_validator("default_time_limit")
    @classmethod
    def _time(cls, value: str) -> str:
        if not valid_time_limit(value):
            raise ValueError(f"time limit {value!r} is not in a Slurm format such as 12:00:00 or 2-00:00:00")
        return value

    @field_validator("account")
    @classmethod
    def _account(cls, value: str) -> str:
        if value and not _NAME_RE.match(value):
            raise ValueError(f"account {value!r} must be letters, digits, '_', '.' or '-'")
        return value

    @field_validator("job_env")
    @classmethod
    def _env(cls, value: str) -> str:
        env_pairs(value)  # raises ValueError
        return value

    @field_validator("module_line", "su2_bin", "srun_command")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("must be a single line")
        return value

    @model_validator(mode="after")
    def _partitions(self) -> "SlurmSettings":
        names = [p.name for p in self.partitions]
        if not names:
            raise ValueError("at least one partition is needed")
        if len(set(names)) != len(names):
            raise ValueError("partition names must be unique")
        if self.default_partition not in names:
            raise ValueError(f"default_partition {self.default_partition!r} is not one of {', '.join(names)}")
        return self

    def partition(self, name: Optional[str]) -> Optional[PartitionSettings]:
        """The partition called `name` (None: the default one), or None when there is no such partition."""
        wanted = name or self.default_partition
        return next((p for p in self.partitions if p.name == wanted), None)


class AppSettings(BaseModel):
    backend: Backend = "local"  # for projects that do not choose
    slurm: SlurmSettings = Field(default_factory=SlurmSettings)
    # How a PC reaches this machine over SSH, for the tunnel command and launcher ("" = <user>@<hostname>)
    ssh_address: str = ""
    check_with_su2: bool = True  # each case's config through `SU2_CFD -d` before Generate and Submit

    @field_validator("ssh_address")
    @classmethod
    def _address(cls, value: str) -> str:
        value = value.strip()
        if value and not _ADDRESS_RE.match(value):
            raise ValueError(f"ssh_address {value!r} must look like user@host (letters, digits and . _ - @ : only)")
        return value


def settings_path() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return (Path(home) if home else Path.home() / ".aerosuite") / SETTINGS_FILE


def _messages(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        where = ".".join(str(item) for item in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


def load_settings() -> tuple[AppSettings, list[str]]:
    """The saved settings, or the defaults; a file that cannot be used gives the defaults and a warning."""
    path = settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppSettings(), []
    except OSError as exc:
        return AppSettings(), [f"Cannot read {path} ({exc}); using the default settings"]
    try:
        return AppSettings.model_validate_json(text), []
    except ValidationError as exc:
        return AppSettings(), [f"{path} has invalid settings ({_messages(exc)}); using the default settings"]


def current_settings() -> AppSettings:
    return load_settings()[0]


def save_settings(settings: AppSettings) -> Path:
    path = settings_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise SettingsError(f"Cannot save settings to {path}: {exc}") from exc
    return path


def validated(data: dict) -> AppSettings:
    """Settings from plain data, or SettingsError with every problem."""
    try:
        return AppSettings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(_messages(exc)) from None


def _parse(text: str, current: Any) -> Any:
    if isinstance(current, str):
        return text
    if text.strip().lower() in ("", "none", "null"):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text  # pydantic reports what is wrong with it


def setting_keys(settings: AppSettings) -> list[str]:
    """Every dotted key `set_value` accepts, e.g. slurm.poll_seconds, slurm.partitions.node2.default_ntasks."""
    keys = ["backend", "ssh_address", "check_with_su2"]
    for name, value in settings.slurm.model_dump().items():
        if name == "partitions":
            for partition in value:
                keys += [f"slurm.partitions.{partition['name']}.{field}" for field in partition if field != "name"]
        else:
            keys.append(f"slurm.{name}")
    return keys


def set_value(settings: AppSettings, key: str, text: str) -> AppSettings:
    """A copy of `settings` with the dotted `key` set from `text` (as typed on a command line)."""
    data = settings.model_dump()
    parts = key.split(".")
    if parts in (["backend"], ["ssh_address"]):
        data[parts[0]] = text
    elif parts == ["check_with_su2"]:
        data["check_with_su2"] = _parse(text, data["check_with_su2"])
    elif len(parts) == 2 and parts[0] == "slurm" and parts[1] in data["slurm"] and parts[1] != "partitions":
        data["slurm"][parts[1]] = _parse(text, data["slurm"][parts[1]])
    elif len(parts) == 4 and parts[:2] == ["slurm", "partitions"]:
        partition = next((p for p in data["slurm"]["partitions"] if p["name"] == parts[2]), None)
        if partition is None or parts[3] not in partition or parts[3] == "name":
            raise SettingsError(f"Unknown setting {key!r}; known: {', '.join(setting_keys(settings))}")
        partition[parts[3]] = _parse(text, partition[parts[3]])
    else:
        raise SettingsError(f"Unknown setting {key!r}; known: {', '.join(setting_keys(settings))}")
    return validated(data)

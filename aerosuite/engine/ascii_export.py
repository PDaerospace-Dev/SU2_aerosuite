"""A case's flow field written again as ParaView ASCII files (flow.vtk, surface_flow.vtk) from its restart file, by
SU2_SOL, e.g. after a sweep that wrote binary .vtu (much smaller) or no volume file at all.

The case's own config is copied to to_ascii.cfg with: its own restart as SOLUTION_FILENAME (a case that continued
from another names that one), ASCII ParaView output only, and the files written to a scratch folder on the node's
own disk (a large ASCII write straight onto the shared /data is where a case once hung). to_ascii.sh then runs
SU2_SOL, moves the files into the case folder and removes the scratch folder. With Slurm it is a batch job on the
study's partition, started as that partition starts SU2_CFD and limited to TIME_LIMIT; else it runs on this machine.
"""
from __future__ import annotations

import dataclasses
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from . import slurm as sl
from .errors import JobError
from .jobs.executors import backend_of, slurm_options
from .jobs.runner import sweep_environment
from .jobs.slurm import job_name, script_head
from .models import Project
from .restarts import RUNS_DIR, find_restart_file
from .settings import AppSettings

ASCII_CFG = "to_ascii.cfg"
ASCII_SCRIPT = "to_ascii.sh"
ASCII_LOG = "to_ascii.log"  # this machine's run; a Slurm one writes to_ascii-<job id>.out
TIME_LIMIT = "2:00:00"  # SU2_SOL takes minutes: a job still running after this has hung
TIME_LIMIT_TEXT = "2 h"
OUTPUT_FILES = "PARAVIEW_ASCII, SURFACE_PARAVIEW_ASCII"
SCRATCH_ROOT = "/tmp"
DEFAULTS = {"VOLUME_FILENAME": "flow", "SURFACE_FILENAME": "surface_flow"}  # SU2's own defaults
_SU2_CFD = re.compile(r"(?<![\w/.-])((?:\S*/)?)SU2_CFD(?![\w.-])")


def _option(text: str, key: str) -> Optional[str]:
    match = re.search(rf"^\s*{key}\s*=\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if match else None


def _set(text: str, key: str, value: str) -> str:
    """`key= value` in place of the option's line, or added at the end when the config has none."""
    line = f"{key}= {value}"
    pattern = re.compile(rf"^\s*{key}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text.rstrip("\n") + f"\n{line}\n"


def solution_name(restart: Path) -> str:
    """SOLUTION_FILENAME for a restart file: SU2 adds the .dat or .csv itself."""
    return str(restart.with_suffix("")) if restart.suffix in (".dat", ".csv") else str(restart)


def ascii_config(cfg_text: str, restart: Path, scratch: str) -> str:
    """The case's config for SU2_SOL: its restart in, ASCII ParaView files out into `scratch`."""
    text = _set(cfg_text, "SOLUTION_FILENAME", solution_name(restart))
    text = _set(text, "OUTPUT_FILES", OUTPUT_FILES)
    for key, default in DEFAULTS.items():
        text = _set(text, key, f"{scratch}/{Path(_option(text, key) or default).name}")
    return text


def sol_launch(launch: str) -> str:
    """A launch command that starts SU2_CFD, starting SU2_SOL instead (srun --mpi=pmix SU2_CFD -> ... SU2_SOL)."""
    if not _SU2_CFD.search(launch):
        raise JobError(f"Cannot tell how to start SU2_SOL: the launch command {launch!r} does not run SU2_CFD")
    return _SU2_CFD.sub(lambda m: f"{m.group(1)}SU2_SOL", launch, count=1)


def _body(launch: str, scratch: str) -> list[str]:
    quoted = shlex.quote(scratch)
    return [f"mkdir -p {quoted}",
            f"{sol_launch(launch)} {ASCII_CFG}",
            "code=$?",
            f'if [ $code = 0 ]; then mv -f {quoted}/* . && echo "AeroSuite: ASCII files written"; fi',
            f"rm -rf {quoted}",
            "exit $code"]


def ascii_script(study: str, case: str, options, slurm, scratch: str) -> str:
    """The batch script: the study's partition and environment, SU2_SOL limited to TIME_LIMIT."""
    options = dataclasses.replace(options, time_limit=TIME_LIMIT)
    lines, launch = script_head(f"{job_name(study, case)}-ascii", options, slurm,
                                f"# Written by AeroSuite: {case}'s ASCII ParaView files from its restart.",
                                out="to_ascii-%j.out")
    return "\n".join(lines + _body(launch, scratch)) + "\n"


def local_script(processes: int, scratch: str) -> str:
    """This machine's script: SU2_SOL on `processes` MPI ranks (one without mpirun)."""
    launch = f"mpirun -np {int(processes)} SU2_CFD" if processes > 1 else "SU2_CFD"
    return "\n".join(["#!/bin/bash", 'cd "$(dirname "$0")"'] + _body(launch, scratch)) + "\n"


def _case_config(folder: Path, case: str) -> Path:
    own = folder / f"{case}.cfg"
    if own.is_file():
        return own
    found = [path for path in sorted(folder.glob("*.cfg")) if path.name != ASCII_CFG]
    if not found:
        raise JobError(f"{case} has no config in {folder}")
    return found[0]


def write_ascii(project_dir: Path, project: Project, case: str, settings: AppSettings) -> str:
    """Start writing `case`'s ASCII files from its restart; returns what was started, for the user."""
    folder = Path(project_dir) / RUNS_DIR / case
    restart = find_restart_file(folder)
    if restart is None:
        raise JobError(f"{case} has no restart file to write the ASCII files from")
    scratch = f"{SCRATCH_ROOT}/aerosuite-ascii-{re.sub(r'[^A-Za-z0-9_.-]', '_', project.name)}-{case}"
    config = ascii_config(_case_config(folder, case).read_text(encoding="utf-8", errors="replace"), restart, scratch)
    try:
        (folder / ASCII_CFG).write_text(config, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise JobError(f"Cannot write {folder / ASCII_CFG}: {exc}") from exc
    if backend_of(project, settings) == "slurm":
        options = slurm_options(project, settings)
        script = ascii_script(project.name, case, options, settings.slurm, scratch)
        (folder / ASCII_SCRIPT).write_text(script, encoding="utf-8", newline="\n")
        job_id = sl.parse_sbatch(sl.run_sync(sl.sbatch_args(ASCII_SCRIPT), cwd=str(folder), env=sweep_environment()))
        return f"Slurm job {job_id} on {options.partition} is writing {case}'s ASCII files (to_ascii-{job_id}.out)"
    (folder / ASCII_SCRIPT).write_text(local_script(project.run.partitions, scratch), encoding="utf-8", newline="\n")
    try:
        with open(folder / ASCII_LOG, "wb") as log:
            subprocess.Popen(["bash", str(folder / ASCII_SCRIPT)], cwd=folder, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, env=sweep_environment(), start_new_session=True)
    except OSError as exc:
        raise JobError(f"Could not start SU2_SOL: {exc}") from exc
    return f"Writing {case}'s ASCII files on this machine ({ASCII_LOG} in its folder)"

"""What this machine has and how busy it is right now: cores, load, memory, running SU2 solvers, and which
programs (whose) are using the cores."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional

import psutil

SU2_PROCESS = "SU2_CFD"
_GB = 1024 ** 3


@dataclass(frozen=True)
class Machine:
    cores: int  # logical: what MPI partitions can use
    physical_cores: int
    load: float  # the 1-minute load average: about how many cores are busy
    memory_total_gb: float
    memory_free_gb: float  # available to new programs
    su2_processes: int  # SU2_CFD processes running now, anyone's

    @property
    def busy_cores(self) -> int:
        return min(self.cores, round(self.load))

    @property
    def free_cores(self) -> int:
        return self.cores - self.busy_cores


def machine() -> Machine:
    cores = psutil.cpu_count() or 1
    memory = psutil.virtual_memory()
    try:
        load = psutil.getloadavg()[0]
    except (AttributeError, OSError):
        load = 0.0
    solvers = 0
    for process in psutil.process_iter(["name"]):
        if (process.info.get("name") or "").startswith(SU2_PROCESS):
            solvers += 1
    return Machine(cores=cores, physical_cores=psutil.cpu_count(logical=False) or cores, load=load,
                   memory_total_gb=memory.total / _GB, memory_free_gb=memory.available / _GB, su2_processes=solvers)


def partitions_note(partitions: int, here: Machine) -> Optional[str]:
    """What to say when a case asks for more than the machine has, or has free right now."""
    if partitions > here.cores:
        return f"{partitions} partitions asked, the machine has {here.cores} cores"
    if partitions > here.free_cores:
        return (f"{partitions} partitions asked, about {here.free_cores} cores free now: the run will share cores "
                "and be slow")
    return None


@dataclass(frozen=True)
class Usage:
    user: str
    program: str
    cores: float  # how many cores its processes are using together
    processes: int


MIN_CORES = 0.5  # programs using less are not worth a line
_PRIME_SECONDS = 0.3


def summarize_usage(rows: Iterable[tuple], top: int = 5) -> list[Usage]:
    """(user, program, CPU percent) per process -> the programs using the most cores, per user, biggest first."""
    totals: dict[tuple, list] = {}
    for user, program, percent in rows:
        if not user or not program:
            continue
        entry = totals.setdefault((user, program), [0.0, 0])
        entry[0] += percent / 100
        entry[1] += 1
    found = [Usage(user, program, round(cores, 1), count) for (user, program), (cores, count) in totals.items()
             if cores >= MIN_CORES]
    return sorted(found, key=lambda u: -u.cores)[:top]  # stable: equal ones keep their order


def usage_text(item: Usage) -> str:
    times = f" × {item.processes}" if item.processes > 1 else ""
    cores = f"{item.cores:g} core{'' if item.cores == 1 else 's'}"
    return f"{item.user} · {item.program}{times} · {cores}"


_primed = False


def usage(top: int = 5) -> list[Usage]:
    """Who is using the cores now. psutil measures each process since the last call, so the first call waits a
    moment to have something to measure; later calls (the Run page asks every few seconds) do not."""
    global _primed
    processes = list(psutil.process_iter(["name", "username"]))
    if not _primed:
        for process in processes:
            _percent(process)
        time.sleep(_PRIME_SECONDS)
        _primed = True
    rows = [(p.info.get("username"), p.info.get("name"), _percent(p)) for p in processes]
    return summarize_usage(rows, top)


def _percent(process) -> float:
    try:
        return process.cpu_percent(None)
    except (psutil.Error, OSError):
        return 0.0

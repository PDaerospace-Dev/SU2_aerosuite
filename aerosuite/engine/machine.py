"""What this machine has and how busy it is right now: cores, load, memory, running SU2 solvers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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

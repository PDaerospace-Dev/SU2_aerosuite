"""Shared pytest configuration and fixtures."""
import json
import os
import sys
from pathlib import Path
from typing import Optional

import matplotlib
import psutil
import pytest

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

from aerosuite.engine.cfg import build_cases  # noqa: E402
from aerosuite.engine.jobs.store import kill_tree, list_jobs  # noqa: E402
from aerosuite.engine.models import Project  # noqa: E402
from aerosuite.engine.project import save_project, set_mesh  # noqa: E402

HISTORY_HEADER = '"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"'


@pytest.fixture(autouse=True)
def _isolated_aerosuite_home(tmp_path, monkeypatch):
    """Never read the real ~/.aerosuite: its settings.json could switch the tests to the Slurm backend."""
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "aerosuite-home"))


@pytest.fixture
def history_writer():
    """Write an SU2-style history.csv whose CL column follows `cl`."""

    def write(folder: Path, cl: list[float]) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [HISTORY_HEADER]
        for i, value in enumerate(cl):
            lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {value:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
        path = folder / "history.csv"
        path.write_text("\n".join(lines) + "\n")
        return path

    return write


FAKE_SWEEP = Path(__file__).resolve().parent / "fixtures" / "fake_sweep.py"

TEMPLATE = """\
MACH_NUMBER= 0.3
AOA= 0.0
SIDESLIP_ANGLE= 0.0
MARKER_FAR= ( farfield )
MARKER_HEATFLUX= ( wall, 0.0 )
MESH_FILENAME= mesh.su2
"""


def _kill_project_jobs(project_dir: Path) -> None:
    """Kill the process tree of every job recorded in the project; never raises."""
    try:
        jobs = list_jobs(project_dir)
    except Exception:
        return
    for job in jobs:
        pid = job.backend_ref.get("pid")
        if pid:
            try:
                kill_tree(int(pid))  # harmless for a pid that has already exited
            except Exception:
                pass


@pytest.fixture
def kill_project_jobs():
    return _kill_project_jobs


def _stray_sweeps(folder: Path) -> list[psutil.Process]:
    """Fake sweep processes still running whose command line names a path under `folder`."""
    folder = Path(folder).resolve()
    strays = []
    for proc in psutil.process_iter(["cmdline", "status"]):
        args = proc.info["cmdline"] or []  # None: a process we may not inspect
        if proc.info["status"] == psutil.STATUS_ZOMBIE or not any(Path(a).name == FAKE_SWEEP.name for a in args):
            continue
        if any(folder in Path(a).parents for a in args):
            strays.append(proc)
    return strays


def _kill_strays(folder: Path) -> list[str]:
    """Kill every fake sweep left under `folder`; one line (pid and command) for each."""
    lines = []
    for proc in _stray_sweeps(folder):
        try:
            lines.append(f"  pid {proc.pid}: {' '.join(proc.cmdline())}")
            kill_tree(proc.pid)
        except psutil.Error:
            pass  # it ended meanwhile
    return lines


@pytest.fixture
def stray_sweeps():
    return _stray_sweeps


@pytest.fixture(scope="session", autouse=True)
def no_fake_sweep_outlives_the_session(tmp_path_factory):
    """Kill and report any fake sweep of this session's temp folder that is still running at the end.

    Only this session's: fake sweeps under another pytest session's folder are left alone.
    """
    yield
    killed = _kill_strays(tmp_path_factory.getbasetemp())
    if killed:
        pytest.fail("Fake sweeps were still running at the end of the session (killed now):\n" + "\n".join(killed))


@pytest.fixture
def ready_project(tmp_path):
    """A saved project with template, mesh, three cases and the fake sweep script.

    On teardown every job the test started is killed, so no fake sweep outlives its test. A fake sweep
    that is still running after that belongs to no job record (e.g. a cancel that missed it): it is
    killed and the test fails.
    """
    project_dir = tmp_path / "study"
    project_dir.mkdir()
    (project_dir / "template.cfg").write_text(TEMPLATE)
    mesh = tmp_path / "wing.su2"
    mesh.write_text("NMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    project = Project(name="study")
    set_mesh(project, mesh)
    project.sweep.mach = [0.8]
    project.sweep.alpha = [0.0, 2.0, 4.0]
    project.sweep.beta = [0.0]
    project.sweep.naming.include_altitude = False
    project.sweep.naming.include_base = False
    project.cases = build_cases(project)
    project.run.sweep_python = sys.executable
    project.run.sweep_script = str(FAKE_SWEEP)
    save_project(project_dir, project)
    yield project_dir, project
    _kill_project_jobs(project_dir)
    killed = _kill_strays(tmp_path)
    if killed:
        pytest.fail("Fake sweeps outlived the test and its job records (killed now):\n" + "\n".join(killed))


FAKE_SLURM = Path(__file__).resolve().parent / "fixtures" / "fake_slurm.py"
SLURM_COMMANDS = ("sbatch", "squeue", "sinfo", "scancel", "sacct", "seff")
SEFF_TEXT = """Job ID: {job_id}
Cluster: pdas-cfd
User/Group: pdas-hpc1/pdas-hpc1
State: {state} (exit code 0)
Nodes: 1
Cores per node: 192
CPU Utilized: {cpu}
CPU Efficiency: 49.49% of 9-15:24:48 core-walltime
Job Wall-clock time: {wall}
Memory Utilized: {memory}
Memory Efficiency: 51.62% of 120.00 GB (640.00 MB/core)
"""


class FakeSlurm:
    """The fake cluster's state file, and helpers to move its jobs along (see tests/fixtures/fake_slurm.py)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.write({
            "next_id": 101, "sbatch_count": 0, "sbatch_fail_after": None, "sbatch_suffix": "",
            "jobs": {}, "calls": [], "controller_down": False, "accounting_down": False,
            "partitions": ["node1*|up|1|idle|0/192/0/192", "node2|up|1|idle|0/192/0/192"],
            "reasons": [],
        })

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    def update(self, **values) -> None:
        state = self.read()
        state.update(values)
        self.write(state)

    def job(self, job_id: str) -> dict:
        return self.read()["jobs"][job_id]

    def jobs(self) -> dict:
        return self.read()["jobs"]

    def set_job(self, job_id: str, **values) -> None:
        state = self.read()
        state["jobs"][job_id].update(values)
        self.write(state)

    def run(self, job_id: str, node: str = "hpc1", time: str = "0:05") -> None:
        self.set_job(job_id, state="RUNNING", node=node, time=time, reason="None")

    def finish(self, job_id: str, state: str = "COMPLETED", exit_code: str = "0:0", elapsed: str = "00:10:00",
               node: str = "hpc1", accounted: bool = True, memory: str = "57.90 GB", cpu: str = "15:50:00") -> None:
        seff = SEFF_TEXT.format(job_id=job_id, state=state, cpu=cpu, wall=elapsed, memory=memory)
        self.set_job(job_id, state=state, exit_code=exit_code, elapsed=elapsed, node=node, in_queue=False,
                     accounted=accounted, seff=seff)

    def calls(self, command: Optional[str] = None) -> list[list[str]]:
        calls = self.read()["calls"]
        return [call for call in calls if command is None or call[0] == command]

    def clear_calls(self) -> None:
        self.update(calls=[])


@pytest.fixture
def fake_slurm(tmp_path, monkeypatch):
    """Fake sbatch/squeue/sinfo/scancel/sacct/seff first on PATH, sharing one state file (POSIX only)."""
    if sys.platform == "win32":
        pytest.skip("the fake Slurm commands are shell scripts")
    bin_dir = tmp_path / "fake-slurm-bin"
    bin_dir.mkdir()
    for name in SLURM_COMMANDS:
        shim = bin_dir / name
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE_SLURM}" {name} "$@"\n')
        shim.chmod(0o755)
    fake = FakeSlurm(tmp_path / "fake-slurm.json")
    monkeypatch.setenv("FAKE_SLURM_STATE", str(fake.path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return fake

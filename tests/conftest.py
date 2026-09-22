"""Shared pytest configuration and fixtures."""
import sys
from pathlib import Path

import matplotlib
import pytest

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

from aerosuite.engine.cfg import build_cases  # noqa: E402
from aerosuite.engine.jobs.store import kill_tree, list_jobs  # noqa: E402
from aerosuite.engine.models import Project  # noqa: E402
from aerosuite.engine.project import save_project, set_mesh  # noqa: E402

HISTORY_HEADER = '"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"'


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


@pytest.fixture
def ready_project(tmp_path):
    """A saved project with template, mesh, three cases and the fake sweep script.

    On teardown every job the test started is killed, so no fake sweep outlives its test.
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

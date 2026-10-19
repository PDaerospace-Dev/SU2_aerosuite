"""Shared set-up for the SlurmRunner tests: a Slurm-ready study under a shared root, and a runner."""
import pytest

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.slurm import SlurmRunner
from aerosuite.engine.project import save_project
from aerosuite.engine.settings import AppSettings, set_value

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"
STEADY = [0.5] * 30
WOBBLY = [0.5 + (0.1 if i % 2 else -0.1) for i in range(30)]


def slurm_settings(root, **values):
    settings = set_value(AppSettings(), "slurm.shared_root", str(root))
    settings = set_value(settings, "backend", "slurm")
    for key, value in values.items():
        settings = set_value(settings, key, value)
    return settings


@pytest.fixture
def slurm_study(ready_project, tmp_path, fake_slurm):
    """(project_dir, project, runner, fake): three cases, configs generated, the fake Slurm on PATH."""
    project_dir, project = ready_project
    project.run.backend = "slurm"
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    settings = slurm_settings(tmp_path)
    runner = SlurmRunner(settings_loader=lambda: settings)
    return project_dir, project, runner, fake_slurm


def out_file(project_dir, case, job_id, text):
    path = project_dir / "runs" / case / f"slurm-{job_id}.out"
    path.write_text(text)
    return path

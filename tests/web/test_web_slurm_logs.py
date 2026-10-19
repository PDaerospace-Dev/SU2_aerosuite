"""Monitor and the log panel follow a Slurm job's cases through their slurm-<id>.out files."""
import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url
from aerosuite.web.slurm_watch import WATCH

A0, A2 = "M0p8_a0_b0", "M0p8_a2_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


@pytest.fixture
def running(ready_project, tmp_path, fake_slurm, history_writer):
    """A Slurm job of two cases, the first running with some history and solver output."""
    project_dir, project = ready_project
    save_settings(set_value(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)), "backend", "slurm"))
    generate_configs(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake_slurm.run("101", node="hpc1")
    history_writer(project_dir / "runs" / A0, [0.5 + 0.01 * i for i in range(20)])
    (project_dir / "runs" / A0 / "slurm-101.out").write_text(
        "AeroSuite: Slurm job 101 on hpc1, 96 ranks\n|  Inner_Iter|   rms[Rho]|\n|          19|  -3.9|\n")
    return project_dir, project, job


async def test_the_log_panel_shows_the_job_log_and_the_running_cases_output(user: User, running, eventually):
    project_dir, _project, job = running
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await user.open(project_url("run", project_dir))
    user.find(marker="log-open").click()
    await eventually(lambda: "slurm-101.out" in _element(user, "log-text").text)
    text = _element(user, "log-text").text
    assert f"{A0} -> Slurm job 101 on node1" in text  # the job log: submits and states
    assert f"── {A0}: slurm-101.out ──" in text and "|          19|  -3.9|" in text


async def test_monitor_follows_a_running_slurm_case(user: User, running):
    project_dir, _project, job = running
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await user.open(project_url("monitor", project_dir))
    assert _element(user, "monitor-case").value == A0
    assert _element(user, "monitor-source").text == f"{A0} · job {job.id}"
    series = _element(user, "chart-history").options["series"]
    assert "CL" in [s["name"] for s in series]

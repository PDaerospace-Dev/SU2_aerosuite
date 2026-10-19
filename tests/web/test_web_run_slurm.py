import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import open_project, save_project, set_mesh
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url
from aerosuite.web.slurm_watch import WATCH

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


def _settings(root, **values):
    settings = set_value(AppSettings(), "slurm.shared_root", str(root))
    for key, value in values.items():
        settings = set_value(settings, key, value)
    save_settings(settings)


@pytest.fixture
def slurm_project(ready_project, tmp_path, fake_slurm):
    project_dir, project = ready_project
    _settings(tmp_path, backend="slurm")
    generate_configs(project_dir, project)
    return project_dir, project, fake_slurm


async def _open(user, project_dir):
    await user.open(project_url("run", project_dir))


async def test_slurm_mode_shows_the_cluster_and_the_slurm_fields(user: User, slurm_project):
    project_dir, _project, fake = slurm_project
    fake.update(partitions=["node1*|up|1|mix|96/96/0/192", "node2|up|1|idle|0/192/0/192"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    WATCH.hide_cluster()
    await _open(user, project_dir)
    await user.should_see("Cluster")
    await user.should_not_see(marker="run-machine")
    await user.should_not_see(marker="run-partitions")
    assert _element(user, "run-backend").value == "slurm"
    assert _element(user, "run-partition").value == "node1"
    assert _element(user, "run-ntasks").value == "96"
    assert _text(user, "cluster-node1-cpus") == "96 / 192 CPUs busy"
    assert _text(user, "cluster-node2-state") == "1 idle"
    assert _text(user, "submit") == "Submit 3 cases to Slurm"
    assert WATCH.viewers == 1  # this page asks the poller for sinfo


async def test_the_backend_toggle_is_saved_with_the_project(user: User, ready_project, tmp_path, fake_slurm):
    project_dir, _ = ready_project
    _settings(tmp_path)  # server default: local
    await _open(user, project_dir)
    await user.should_see(marker="run-machine")
    with user:
        _element(user, "run-backend").set_value("slurm")
    await user.should_see("Cluster")
    assert open_project(project_dir).run.backend == "slurm"
    with user:
        _element(user, "run-backend").set_value("local")
    await user.should_see(marker="run-machine")
    assert open_project(project_dir).run.backend == "local"
    assert WATCH.viewers == 0


async def test_another_partition_brings_its_own_tasks_and_the_warnings(user: User, slurm_project, tmp_path):
    project_dir, project, _fake = slurm_project
    mesh = tmp_path / "wing.su2"
    mesh.write_text("NDIME= 3\nNELEM= 15000000\nNMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    await _open(user, project_dir)
    assert "≈ 58 GB of 120 GB on node1" in _text(user, "run-memory")
    with user:
        _element(user, "run-partition").set_value("node2")
    await user.should_see("Tasks per case")
    assert _element(user, "run-ntasks").value == "48"
    saved = open_project(project_dir).run.slurm
    assert (saved.partition, saved.ntasks) == ("node2", None)
    assert "of 61 GB on node2" in _text(user, "run-memory")
    with user:
        box = _element(user, "run-ntasks")
        box.set_value("96")
    user.find(marker="run-ntasks").trigger("keydown.enter")
    await user.should_see("node2 gains nothing above about 48 tasks; 96 asked")
    assert open_project(project_dir).run.slurm.ntasks == 96
    assert _element(user, "submit").enabled


async def test_outside_the_shared_root_blocks_submit(user: User, slurm_project, tmp_path):
    project_dir, _project, _fake = slurm_project
    _settings(tmp_path / "elsewhere", backend="slurm")
    await _open(user, project_dir)
    await user.should_see("Case folders must be under")
    assert not _element(user, "submit").enabled


async def test_submit_then_follow_the_poller(user: User, slurm_project, eventually):
    project_dir, _project, fake = slurm_project
    await _open(user, project_dir)
    user.find(marker="submit").click()
    await eventually(lambda: list_jobs(project_dir) and list_jobs(project_dir)[0].state is JobState.RUNNING, 10)
    job = list_jobs(project_dir)[0]
    assert {name: sc.job_id for name, sc in job.slurm.items()} == {A0: "101", A2: "102", A4: "103"}
    await eventually(lambda: _text(user, f"slurm-{A0}") == "Slurm 101", 5)
    fake.run("101", node="hpc1", time="0:42")
    fake.set_job("102", reason="Resources")
    await WATCH.poll_once()
    await eventually(lambda: _text(user, f"status-{A0}") == "RUNNING", 5)
    assert _text(user, f"slurm-{A0}") == "Slurm 101 · RUNNING on hpc1 · 0:42"
    assert _text(user, f"slurm-{A2}") == "Slurm 102 · PENDING (Resources)"


async def test_drained_node_and_controller_down(user: User, slurm_project):
    project_dir, _project, fake = slurm_project
    fake.update(partitions=["node1*|up|1|idle|0/192/0/192", "node2|up|1|drain|0/0/192/192"],
                reasons=["hpc2|drain|bad DIMM"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    await _open(user, project_dir)
    assert _text(user, "cluster-node2-state") == "1 drain"
    await user.should_see("hpc2 (drain): bad DIMM")
    fake.update(controller_down=True)
    await WATCH.poll_once()
    WATCH.hide_cluster()
    await _open(user, project_dir)
    await user.should_see(marker="cluster-outage")
    assert "Slurm controller unreachable" in _text(user, "cluster-outage")


async def test_cancel_a_slurm_job(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    runner_for("slurm").submit(project_dir, project)
    await _open(user, project_dir)
    user.find(marker="cancel").click()
    await eventually(lambda: bool(user.find(marker="cancel-confirm").elements))
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].state is JobState.CANCELLED, 10)
    assert fake.calls("scancel") == [["scancel", "101", "102", "103"]]
    await eventually(lambda: _text(user, f"status-{A0}") == "CANCELLED", 5)


async def test_resubmit_out_of_memory_proposes_more_memory(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    project.run.slurm.partition = "node2"
    save_project(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101", node="hpc2")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    fake.finish("101", "OUT_OF_MEMORY", "0:125", node="hpc2")
    await WATCH.poll_once()
    assert list_jobs(project_dir)[0].case_status[A0] is CaseState.FAILED
    await _open(user, project_dir)
    assert "OUT_OF_MEMORY" in _text(user, f"slurm-{A0}")
    user.find(marker=f"resubmit-{A0}").click()
    await eventually(lambda: bool(user.find(marker="resubmit-confirm").elements))
    assert _element(user, "resubmit-partition").value == "node1"
    await user.should_see(marker="resubmit-suggestion")
    user.find(marker="resubmit-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].slurm[A0].attempts == ["101"], 10)
    job = list_jobs(project_dir)[0]
    assert job.slurm[A0].partition == "node1" and job.slurm[A0].ntasks == 96 and job.is_active


async def test_a_blocked_case_shows_why(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    project.cases[1].restart = "previous"
    save_project(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.finish("101", "FAILED", "1:0")
    fake.finish("102", "CANCELLED", elapsed="00:00:00")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    assert _text(user, f"status-{A2}") == "BLOCKED"
    user.find(marker=f"status-{A2}").click()
    await eventually(lambda: bool(user.find(marker=f"tail-{A2}").elements))
    assert f"Not run: {A0} ended FAILED" in _text(user, f"tail-{A2}")

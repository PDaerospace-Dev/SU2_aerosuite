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


async def test_the_backend_toggle_is_saved_with_the_project(user: User, ready_project, tmp_path, fake_slurm):
    project_dir, _ = ready_project
    _settings(tmp_path)  # server default: local
    await _open(user, project_dir)
    await user.should_see(marker="run-machine")
    with user:
        _element(user, "run-backend").set_value("slurm")
    await user.should_see(marker="run-cluster-summary")
    assert open_project(project_dir).run.backend == "slurm"
    with user:
        _element(user, "run-backend").set_value("local")
    await user.should_see(marker="run-machine")
    assert open_project(project_dir).run.backend == "local"


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


async def test_job_history_folds(user: User, slurm_project):
    project_dir, project, _fake = slurm_project
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    await _open(user, project_dir)
    with user:
        _element(user, "run-tabs").set_value("history")
    await user.should_see(marker="fold-run-history")
    history = _element(user, "fold-run-history").parent_slot.parent.parent_slot.parent
    assert "as-card-folded" not in history.classes
    user.find(marker="fold-run-history").click()
    assert "as-card-folded" in history.classes
    user.find(marker="fold-run-history").click()
    assert "as-card-folded" not in history.classes


async def test_add_cases_to_the_running_job_on_the_other_node(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])  # node1
    fake.run("101", node="hpc1")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    await user.should_see(marker="run-add")
    assert _element(user, "add-partition").value == "node2"  # the node this job does not use
    assert _element(user, "add-ntasks").value == "48"
    assert _text(user, "add-cases") == "Add 1 case to the running job"  # A0 and A2 are busy
    assert _text(user, "add-skipped") == "2 ticked cases are already queued or running in this job: skipped"
    user.find(marker="add-cases").click()
    await eventually(lambda: A4 in list_jobs(project_dir)[0].slurm, 10)
    job = list_jobs(project_dir)[0]
    assert len(list_jobs(project_dir)) == 1
    assert (job.slurm[A4].job_id, job.slurm[A4].partition, job.slurm[A4].ntasks) == ("103", "node2", 48)
    assert open_project(project_dir).run.slurm.partition is None  # not saved with the study
    await eventually(lambda: _text(user, "add-cases") == "Add 0 cases to the running job", 5)
    assert not _element(user, "add-cases").enabled


async def test_no_add_block_for_a_local_job_or_without_a_job(user: User, slurm_project):
    project_dir, _project, _fake = slurm_project
    await _open(user, project_dir)
    await user.should_not_see(marker="run-add")


async def test_slurm_mode_shows_a_cluster_summary_and_the_slurm_fields(user: User, slurm_project):
    project_dir, _project, fake = slurm_project
    fake.update(nodes=["hpc1|node1*|mix|96/96/0/192|125000|101000|48.0|none",
                       "hpc2|node2|idle|0/192/0/192|62000|57000|0.2|none"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    await _open(user, project_dir)
    await user.should_not_see(marker="run-machine")
    await user.should_not_see(marker="run-partitions")
    assert _text(user, "run-cluster-summary") == "node1 96/192 busy · node2 free"
    assert _element(user, "run-cluster-link").props["href"].startswith("/cluster?back=%2Frun%3Fproject%3D")
    assert _element(user, "run-backend").value == "slurm"
    assert _element(user, "run-partition").value == "node1"
    assert _element(user, "run-ntasks").value == "96"
    assert _text(user, "submit") == "Submit 3 cases to Slurm"


async def test_the_summary_turns_red_for_a_drained_node_or_an_outage(user: User, slurm_project, eventually):
    project_dir, _project, fake = slurm_project
    fake.update(nodes=["hpc1|node1*|idle|0/192/0/192|125000|101000|0.0|none",
                       "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    WATCH.show_cluster()
    await WATCH.poll_once()
    await _open(user, project_dir)
    summary = _element(user, "run-cluster-summary")
    assert summary.text == "node1 free · node2 1 drain, 0/192 busy" and "as-error-text" in summary.classes
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: _text(user, "run-cluster-summary") == "Slurm controller unreachable", 5)

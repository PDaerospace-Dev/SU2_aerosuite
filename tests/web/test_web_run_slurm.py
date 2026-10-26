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
    assert _element(user, "resubmit-partition").value == "node0"  # the most memory now: node0, 235 GB
    await user.should_see(marker="resubmit-suggestion")
    user.find(marker="resubmit-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].slurm[A0].attempts == ["101"], 10)
    job = list_jobs(project_dir)[0]
    assert job.slurm[A0].partition == "node0" and job.slurm[A0].ntasks == 32 and job.is_active


async def test_a_blocked_case_shows_why(user: User, slurm_project, eventually):
    from aerosuite.engine.jobs.store import save_job

    project_dir, project, fake = slurm_project
    project.cases[1].restart = "previous"
    save_project(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    job.slurm[A2].scratch_fallback = False  # a job submitted before the fallback: afterok
    save_job(project_dir, job)
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
    assert _text(user, "run-node-node1") == "node1 50%" and _text(user, "run-node-node2") == "node2 free"
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
    assert _text(user, "run-node-node1") == "node1 free"
    bad = _element(user, "run-node-node2")
    assert bad.text == "node2 drain" and "as-error-text" in bad.classes
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: _text(user, "run-cluster-message") == "Slurm controller unreachable", 5)


DIVERGED_OUT = """AeroSuite: Slurm job 101 on hpc1, 96 ranks, start 2026-10-22T11:43:00+09:00
|         591|    3.584994|  3.8582e+00|  1.0000e+00|    0.922846|    0.978883|
|         592|    3.600066|  3.8578e+00|  1.0000e+00|    0.922425|    0.977734|

Error in "void CSolver::SetResidual_RMS(const CGeometry*, const CConfig*)":
-------------------------------------------------------------------------
SU2 has diverged (NaN detected).
------------------------------ Error Exit -------------------------------
srun: error: hpc1: tasks 31,33,35: Exited with exit code 1
AEROSUITE_EXIT 1 2026-10-22T11:53:15+09:00
"""


async def test_a_failed_case_says_why_in_words_and_what_to_try(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    (project_dir / "runs" / A0 / "slurm-101.out").write_text(DIVERGED_OUT)
    fake.finish("101", "FAILED", "1:0")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    assert _text(user, f"why-{A0}") == "Diverged at iteration 592 (SU2 found NaN)"
    user.find(marker=f"status-{A0}").click()
    await eventually(lambda: bool(user.find(marker=f"advice-{A0}").elements))
    assert "lower CFL or a first-order start" in _text(user, f"advice-{A0}")
    await user.should_see(marker=f"monitor-{A0}")
    assert "SU2 has diverged" in _text(user, f"tail-{A0}")  # the output, folded below
    assert "Diverged at iteration 592" in (project_dir / job.log_path).read_text()


async def test_a_time_limit_offers_to_continue_from_the_last_solution(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    (project_dir / "runs" / A0 / "restart_flow.dat").write_text("solution")  # written as it ran
    fake.finish("101", "TIMEOUT", "0:15")
    fake.finish("102", "COMPLETED", "0:0")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    assert _text(user, f"why-{A0}").startswith("Stopped at the time limit")
    user.find(marker=f"status-{A0}").click()
    await eventually(lambda: bool(user.find(marker=f"fix-{A0}").elements))
    user.find(marker=f"fix-{A0}").click()
    assert _element(user, f"tick-{A0}").value and not _element(user, f"tick-{A2}").value
    assert _element(user, "continue").value


async def test_rerun_a_diverged_case_with_changes_then_keep_them(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    (project_dir / "runs" / A0 / "slurm-101.out").write_text(DIVERGED_OUT)
    (project_dir / "runs" / A0 / "restart_flow.dat").write_text("solution at iteration 500")
    fake.finish("101", "FAILED", "1:0")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    user.find(marker=f"status-{A0}").click()
    await eventually(lambda: bool(user.find(marker=f"rerun-{A0}").elements))
    user.find(marker=f"rerun-{A0}").click()
    await eventually(lambda: bool(user.find(marker="rerun-dialog").elements))
    assert _element(user, "rerun-cfl").value == "0.5"  # half of 1, for a divergence
    assert _element(user, "rerun-first-order").value and _element(user, "rerun-start").value == "last"
    user.find(marker="rerun-confirm").click()
    await eventually(lambda: len(list_jobs(project_dir)) == 2, 10)
    rerun = list_jobs(project_dir)[0]
    assert rerun.changes == {A0: {"CFL_NUMBER": "0.5", "CFL_ADAPT": "NO", "MUSCL_FLOW": "NO", "MUSCL_TURB": "NO"}}
    cfg = (project_dir / "runs" / A0 / f"{A0}.cfg").read_text()
    assert "CFL_NUMBER= 0.5" in cfg and "MUSCL_FLOW= NO" in cfg and "RESTART_SOL= YES" in cfg  # from its solution
    template = (project_dir / "template.cfg").read_text()
    assert "CFL_NUMBER= 0.5" not in template  # this job only
    await _open(user, project_dir)
    assert _text(user, f"ran-with-{A0}") == "ran with CFL 0.5 (fixed), first order"
    user.find(marker=f"keep-{A0}").click()
    template = (project_dir / "template.cfg").read_text()
    assert "CFL_NUMBER= 0.5" in template and "MUSCL_FLOW= NO" in template and "CFL_ADAPT= NO" in template
    await user.should_not_see(marker=f"keep-{A0}")  # kept: nothing more to keep


async def test_rerun_can_be_cancelled(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    (project_dir / "runs" / A0 / "slurm-101.out").write_text(DIVERGED_OUT)
    fake.finish("101", "FAILED", "1:0")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    user.find(marker=f"status-{A0}").click()
    await eventually(lambda: bool(user.find(marker=f"rerun-{A0}").elements))
    user.find(marker=f"rerun-{A0}").click()
    await eventually(lambda: bool(user.find(marker="rerun-dialog").elements))
    assert _element(user, "rerun-start").value == "scratch"  # no solution to continue from
    user.find(marker="rerun-cancel").click()
    assert len(list_jobs(project_dir)) == 1


async def test_a_failed_continuation_reruns_from_the_solution_it_started_from(user: User, slurm_project, eventually):
    project_dir, project, fake = slurm_project
    first_order = project_dir / "runs" / A0 / "restart_flow.dat"
    first_order.parent.mkdir(parents=True)
    first_order.write_text("first-order solution")
    job = runner_for("slurm").submit(project_dir, project, cases=[A0], continue_cases=[A0])
    (project_dir / "runs" / A0 / "slurm-101.out").write_text(DIVERGED_OUT)  # its folder was emptied: no solution
    fake.finish("101", "FAILED", "1:0")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    user.find(marker=f"status-{A0}").click()
    await user.should_see(marker=f"kept-start-{A0}")
    user.find(marker=f"rerun-{A0}").click()
    await eventually(lambda: bool(user.find(marker="rerun-dialog").elements))
    kept = _element(user, "rerun-start").value
    assert kept.endswith("restart_flow.dat") and "/jobs/" in kept  # offered first
    user.find(marker="rerun-confirm").click()
    await eventually(lambda: len(list_jobs(project_dir)) == 2, 10)
    rerun = list_jobs(project_dir)[0]
    control = (project_dir / "jobs" / rerun.id / "configs" / "run_control.txt").read_text()
    assert control.startswith(f"{A0}.cfg, custom, ") and "first-order" not in control
    assert (project_dir / "runs" / A0 / f"{A0}.cfg").read_text().count("RESTART_SOL= YES") == 1


async def test_earlier_attempts_restart_from_and_make_current(user: User, slurm_project, eventually, history_writer):
    project_dir, project, fake = slurm_project
    runs = project_dir / "runs" / A0
    first = runner_for("slurm").submit(project_dir, project, cases=[A0])
    history_writer(runs, [0.5] * 30)
    (runs / "restart_flow.dat").write_text("first order")
    fake.finish("101", "COMPLETED", "0:0")
    WATCH.track(project_dir, first.id)
    await WATCH.poll_once()
    second = runner_for("slurm").submit(project_dir, project, cases=[A0])  # its run becomes attempt 1
    (runs / "slurm-102.out").write_text(DIVERGED_OUT)
    history_writer(runs, [0.5] * 12)  # a diverged run leaves its history
    fake.finish("102", "FAILED", "1:0")
    WATCH.track(project_dir, second.id)
    await WATCH.poll_once()
    await _open(user, project_dir)
    assert _text(user, f"attempts-{A0}") == "1 earlier attempt"
    user.find(marker=f"attempts-{A0}").click()
    await user.should_see(marker=f"attempt-{A0}-1")
    assert "30 iterations" in _element(user, f"attempt-{A0}-1").default_slot.children[-3].text

    user.find(marker=f"attempt-restart-{A0}-1").click()  # Restart from this: its solution is chosen
    await eventually(lambda: bool(user.find(marker="rerun-dialog").elements))
    assert "/attempts/" in _element(user, "rerun-start").value
    user.find(marker="rerun-cancel").click()

    user.find(marker=f"attempt-current-{A0}-1").click()
    await eventually(lambda: bool(user.find(marker="current-confirm").elements))
    user.find(marker="current-confirm").click()
    await eventually(lambda: (runs / "restart_flow.dat").is_file()
                     and (runs / "restart_flow.dat").read_text() == "first order", 5)
    await _open(user, project_dir)
    assert _text(user, f"status-{A0}") == "CONVERGED"  # the first run's outcome again
    assert _text(user, f"attempts-{A0}") == "1 earlier attempt"  # the failed one, kept in its place


async def test_cases_the_sweep_no_longer_makes_stay_in_view_while_their_job_runs(user: User, slurm_project):
    from aerosuite.engine.editing import update_sweep

    project_dir, project, fake = slurm_project
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101", node="hpc1")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()
    project = open_project(project_dir)
    update_sweep(project, alpha=[10.0])  # the sweep changed while the job runs: A0 and A2 are no longer made
    save_project(project_dir, project)
    await _open(user, project_dir)
    await user.should_see(marker="run-others")
    await user.should_see(marker=f"other-{A0}")
    assert _text(user, f"status-{A0}") == "RUNNING" and _text(user, f"status-{A2}") == "PENDING"
    await user.should_not_see(marker=f"tick-{A0}")  # the job's: not ticked or submitted from here
    assert f"case={A0}" in _element(user, f"monitor-{A0}").props["href"]
    await user.open(project_url("monitor", project_dir) + f"&case={A0}")
    select = _element(user, "monitor-case")
    assert A0 in select.options and "M0p8_a10_b0" in select.options and select.value == A0

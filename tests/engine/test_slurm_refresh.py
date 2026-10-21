import json

import pytest

from aerosuite.engine import slurm as sl
from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.engine.jobs.slurm import FALLBACK_POLLS, case_stats
from aerosuite.engine.jobs.store import active_lock, load_job
from aerosuite.engine.project import save_project

from slurm_helpers import A0, A2, A4, STEADY, WOBBLY, out_file, slurm_study  # noqa: F401  (fixture)


def _submit(slurm_study, cases=None, previous=False):
    project_dir, project, runner, fake = slurm_study
    if previous:
        for case in project.cases[1:]:
            case.restart = "previous"
        save_project(project_dir, project)
    return runner.submit(project_dir, project, cases=cases)


def test_queued_states(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study)
    fake.run("101", node="hpc1", time="12:34")
    fake.set_job("102", reason="Resources")
    fake.set_job("103", state="CONFIGURING")
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.RUNNING, A2: CaseState.PENDING, A4: CaseState.PENDING}
    assert (job.slurm[A0].node, job.slurm[A0].elapsed, job.slurm[A0].started) == ("hpc1", "12:34", True)
    assert job.slurm[A2].reason == "Resources" and job.slurm[A4].state == "CONFIGURING"
    assert runner.started_cases(project_dir, job) == [A0]
    assert runner.case_log(project_dir, job, A0) == project_dir / "runs" / A0 / "slurm-101.out"
    fake.set_job("101", state="COMPLETING")
    assert runner.refresh(project_dir, job).case_status[A0] is CaseState.RUNNING
    assert load_job(project_dir, job.id).case_status[A0] is CaseState.RUNNING


def test_one_squeue_and_one_sacct_per_refresh(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study)
    for slurm_id in ("101", "102"):
        fake.finish(slurm_id)
    fake.clear_calls()
    runner.refresh(project_dir, job)
    names = [call[0] for call in fake.calls() if call[0] != "seff"]
    assert names == ["squeue", "sacct"]
    sacct = fake.calls("sacct")[0]
    assert sacct[sacct.index("-j") + 1] == "101,102"


def test_completed_cases_are_judged_from_their_history(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study)
    history_writer(project_dir / "runs" / A0, STEADY)
    history_writer(project_dir / "runs" / A2, WOBBLY)
    for slurm_id in ("101", "102", "103"):
        fake.finish(slurm_id, elapsed="00:10:00")
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.CONVERGED, A2: CaseState.UNCONVERGED, A4: CaseState.FAILED}
    assert "No history.csv" in job.failure_tail[A4]
    assert job.slurm[A0].exit_code == "0:0" and job.slurm[A0].state == "COMPLETED"
    assert job.state is JobState.FAILED and job.finished is not None
    assert active_lock(project_dir) is None


def test_a_job_where_every_case_ran_is_done_and_releases_everything(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    solution = project_dir / "runs" / A0 / "restart_flow.dat"
    solution.parent.mkdir(parents=True)
    solution.write_text("x")
    project.cases[1].restart = "previous"
    save_project(project_dir, project)
    job = runner.submit(project_dir, project, cases=[A2])
    assert (project_dir / "jobs" / job.id / "restart").is_dir()
    history_writer(project_dir / "runs" / A2, STEADY)
    fake.finish("101")
    job = runner.refresh(project_dir, job)
    assert job.state is JobState.DONE
    assert not (project_dir / "jobs" / job.id / "restart").exists()
    assert active_lock(project_dir) is None
    assert f"Job {job.id} ended: DONE" in (project_dir / job.log_path).read_text()


@pytest.mark.parametrize("state, exit_code", [("FAILED", "1:0"), ("TIMEOUT", "0:15"), ("OUT_OF_MEMORY", "0:125"),
                                              ("NODE_FAIL", "0:0")])
def test_failed_slurm_states(slurm_study, state, exit_code):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    fake.run("101", node="hpc2")
    runner.refresh(project_dir, job)
    out_file(project_dir, A0, "101", "AeroSuite: Slurm job 101 on hpc2\nSU2 says hello\nkilled\n")
    fake.finish("101", state, exit_code, node="hpc2")
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.FAILED
    tail = job.failure_tail[A0]
    assert tail.startswith(f"Slurm: {state} (exit {exit_code}) on hpc2.") and "SU2 says hello" in tail
    assert job.slurm[A0].state == state and job.slurm[A0].exit_code == exit_code
    assert runner.resubmittable(job) == ([A0] if state in ("OUT_OF_MEMORY", "NODE_FAIL") else [])


def test_cancelled_outside_aerosuite(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    fake.finish("101", "CANCELLED", "0:15", elapsed="00:00:00")
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.CANCELLED and job.state is JobState.CANCELLED


def test_a_failed_case_blocks_the_chain_behind_it(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, previous=True)
    fake.run("101")
    job = runner.refresh(project_dir, job)
    assert job.case_status[A2] is CaseState.PENDING and job.slurm[A2].reason == "Dependency"
    # A fails; Slurm (--kill-on-invalid-dep) cancels B, then C
    fake.finish("101", "OUT_OF_MEMORY", "0:125")
    fake.finish("102", "CANCELLED", "0:0", elapsed="00:00:00")
    fake.finish("103", "CANCELLED", "0:0", elapsed="00:00:00")
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.BLOCKED, A4: CaseState.BLOCKED}
    assert job.failure_tail[A2].startswith(f"Not run: {A0} ended OUT_OF_MEMORY")
    assert job.failure_tail[A4].startswith(f"Not run: {A2} ended BLOCKED")
    assert not job.is_active


def test_a_cancelled_dependent_waits_for_the_case_it_depends_on(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0, A2], previous=True)
    fake.finish("101", "FAILED", "1:0", accounted=False)  # slurmdbd has no row for it yet
    fake.finish("102", "CANCELLED", "0:0", elapsed="00:00:00")
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.PENDING, A2: CaseState.PENDING}
    fake.set_job("101", accounted=True)
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.BLOCKED}


def test_dependency_never_satisfied_is_cancelled_and_blocked(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0, A2], previous=True)
    fake.finish("101", "FAILED", "1:0")
    fake.set_job("102", reason=sl.NEVER_SATISFIED)
    job = runner.refresh(project_dir, job)
    assert fake.calls("scancel") == [["scancel", "102"]]
    assert job.case_status == {A0: CaseState.FAILED, A2: CaseState.BLOCKED}
    assert not job.is_active


def test_no_accounting_row_waits_then_the_files_decide(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0, A2])
    history_writer(project_dir / "runs" / A0, STEADY)
    out_file(project_dir, A0, "101", "...\nExit Success (SU2_CFD)\nAEROSUITE_EXIT 0 2026-10-19T12:00:00\n")
    out_file(project_dir, A2, "102", "...\nkilled\n")
    fake.finish("101", accounted=False)
    fake.finish("102", "OUT_OF_MEMORY", accounted=False)
    for _ in range(FALLBACK_POLLS - 1):
        job = runner.refresh(project_dir, job)
        assert job.case_status == {A0: CaseState.PENDING, A2: CaseState.PENDING}
    job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.CONVERGED, A2: CaseState.FAILED}
    assert "reason (out of memory, node failure, time limit) is unknown" in job.failure_tail[A2]


@pytest.mark.parametrize("text, expected", [
    ("Exit Success (SU2_CFD)\nAEROSUITE_EXIT 0 now\n", CaseState.CONVERGED),
    ("Exit Success (SU2_CFD)\n", CaseState.CONVERGED),
    ("Error in SU2\nAEROSUITE_EXIT 1 now\n", CaseState.FAILED),
])
def test_accounting_down_reads_the_out_file(slurm_study, history_writer, text, expected):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    history_writer(project_dir / "runs" / A0, STEADY)
    out_file(project_dir, A0, "101", text)
    fake.finish("101")
    fake.update(accounting_down=True)
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is expected
    log = (project_dir / job.log_path).read_text()
    assert "accounting unreachable" in log
    if expected is CaseState.FAILED:
        assert "SU2 exited with code 1" in job.failure_tail[A0]


def test_accounting_down_without_an_exit_line_waits(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    out_file(project_dir, A0, "101", "running...\n")
    fake.finish("101", "NODE_FAIL")
    fake.update(accounting_down=True)
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.PENDING
    fake.update(accounting_down=False)
    job = runner.refresh(project_dir, job)
    assert job.case_status[A0] is CaseState.FAILED and job.slurm[A0].state == "NODE_FAIL"


def test_controller_down_changes_nothing_and_logs_once(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0, A2])
    fake.run("101")
    job = runner.refresh(project_dir, job)
    fake.finish("101")  # it finished meanwhile, but squeue cannot say so
    fake.update(controller_down=True)
    for _ in range(FALLBACK_POLLS + 2):
        job = runner.refresh(project_dir, job)
    assert job.case_status == {A0: CaseState.RUNNING, A2: CaseState.PENDING}
    assert "Unable to contact slurm controller" in job.backend_ref["outage"]
    log = (project_dir / job.log_path).read_text()
    assert log.count("Slurm unreachable") == 1
    assert [call[0] for call in fake.calls()].count("sacct") == 0
    fake.update(controller_down=False)
    job = runner.refresh(project_dir, job)
    assert "outage" not in job.backend_ref
    assert "Slurm reachable again" in (project_dir / job.log_path).read_text()
    assert job.case_status[A0] is CaseState.FAILED  # no history.csv in the fake


def test_a_snapshot_from_before_the_submit_is_ignored(slurm_study):
    project_dir, project, runner, fake = slurm_study
    old = sl.Snapshot(taken=1.0)
    job = _submit(slurm_study, cases=[A0])
    job = runner.apply_snapshot(project_dir, job, old)
    assert job.case_status[A0] is CaseState.PENDING and job.slurm[A0].checks == 0


def test_the_same_snapshot_is_applied_once(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    fake.finish("101", accounted=False)
    snap = sl.snapshot_sync(runner.watched_ids(job))
    for _ in range(5):
        job = runner.apply_snapshot(project_dir, job, snap)
    assert job.slurm[A0].checks == 1


def test_stats_file_with_seff(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    history_writer(project_dir / "runs" / A0, STEADY)  # iterations 0..29
    fake.run("101", node="hpc1")
    runner.refresh(project_dir, job)
    fake.finish("101", elapsed="00:10:00", memory="57.90 GB", cpu="15:12:00")
    job = runner.refresh(project_dir, job)
    stats = case_stats(project_dir, A0)
    assert stats["job_id"] == "101" and stats["node"] == "hpc1" and stats["ntasks"] == 96
    assert stats["elapsed_s"] == 600 and stats["iterations"] == 30 and stats["s_per_iter"] == 20
    assert stats["peak_memory_gb"] == pytest.approx(57.9)
    assert stats["cpu_use_per_rank"] == pytest.approx((15 * 3600 + 12 * 60) / (600 * 96))
    assert stats["state"] == "COMPLETED" and stats["attempts"] == []
    assert not job.slurm[A0].stats_pending


def test_stats_without_seff(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    history_writer(project_dir / "runs" / A0, STEADY)
    fake.finish("101", elapsed="00:05:00")
    fake.set_job("101", seff=None)  # seff has nothing
    for _ in range(3):
        job = runner.refresh(project_dir, job)
        runner.add_seff(project_dir, job, A0, None)
    stats = json.loads((project_dir / "runs" / A0 / "slurm_stats.json").read_text())
    assert stats["elapsed_s"] == 300 and stats["peak_memory_gb"] is None and stats["cpu_use_per_rank"] is None
    assert not load_job(project_dir, job.id).slurm[A0].stats_pending


def test_s_per_iter_comes_from_su2s_own_timer(slurm_study):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    folder = project_dir / "runs" / A0
    rows = ['"Inner_Iter","Time(sec)","Time(sec)","rms[Rho]","CL","CD","CMy"']
    rows += [f"{i},{4.0 + (i % 2)},{4.5},{-3 - 0.01 * i},0.5,0.02,-0.01" for i in range(50)]
    (folder / "history.csv").write_text("\n".join(rows) + "\n")
    fake.finish("101", elapsed="00:06:32")  # 392 s, of which SU2 iterated 50 x 4.5 s
    runner.refresh(project_dir, job)
    stats = case_stats(project_dir, A0)
    assert stats["s_per_iter"] == pytest.approx(4.5) and stats["s_per_iter_source"] == "su2"
    assert stats["elapsed_s"] == 392 and stats["iterations"] == 50


def test_s_per_iter_falls_back_to_elapsed_without_a_timer(slurm_study, history_writer):
    project_dir, project, runner, fake = slurm_study
    job = _submit(slurm_study, cases=[A0])
    history_writer(project_dir / "runs" / A0, STEADY)  # no Time(sec) column
    fake.finish("101", elapsed="00:10:00")
    runner.refresh(project_dir, job)
    stats = case_stats(project_dir, A0)
    assert stats["s_per_iter"] == 20 and stats["s_per_iter_source"] == "elapsed"

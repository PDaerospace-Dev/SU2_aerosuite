import asyncio
import shutil

import pytest

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.jobs.slurm import SlurmRunner, case_stats
from aerosuite.engine.jobs.store import load_job
from aerosuite.engine.project import open_project, save_project
from aerosuite.engine.settings import AppSettings, set_value
from aerosuite.web.jobs import JobWatcher
from aerosuite.web.slurm_watch import SlurmWatch

A0, A2 = "M0p8_a0_b0", "M0p8_a2_b0"


@pytest.fixture
def two_studies(ready_project, tmp_path, fake_slurm):
    project_dir, project = ready_project
    project.run.backend = "slurm"
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    other = tmp_path / "study2"
    shutil.copytree(project_dir, other)
    settings = set_value(AppSettings(), "slurm.shared_root", str(tmp_path))
    runner = SlurmRunner(settings_loader=lambda: settings)
    watch = SlurmWatch(runner_provider=lambda: runner, settings_loader=lambda: settings)
    return [(project_dir, project), (other, open_project(other))], runner, watch, fake_slurm


async def test_idle_without_jobs_or_viewers(two_studies):
    _studies, _runner, watch, fake = two_studies
    await watch.poll_once()
    assert fake.calls() == [] and watch.snapshot is None


async def test_one_squeue_and_one_sacct_for_every_project(two_studies):
    studies, runner, watch, fake = two_studies
    jobs = [runner.submit(directory, project, cases=[A0, A2]) for directory, project in studies]
    for directory, job in zip((s[0] for s in studies), jobs):
        watch.track(directory, job.id)
    fake.run("101")
    fake.finish("103", "OUT_OF_MEMORY", "0:125")
    fake.clear_calls()
    await watch.poll_once()
    assert [call[0] for call in fake.calls() if call[0] != "seff"] == ["squeue", "sacct"]
    sacct = fake.calls("sacct")[0]
    assert sacct[sacct.index("-j") + 1] == "103"
    first = load_job(studies[0][0], jobs[0].id)
    second = load_job(studies[1][0], jobs[1].id)
    assert first.case_status[A0] is CaseState.RUNNING
    assert second.case_status[A0] is CaseState.FAILED and second.slurm[A0].state == "OUT_OF_MEMORY"
    assert watch.snapshot.ok and watch.last_ok == watch.snapshot.taken


async def test_sinfo_only_while_a_page_shows_the_cluster(two_studies):
    _studies, _runner, watch, fake = two_studies
    watch.show_cluster()
    await watch.poll_once()
    assert [call[0] for call in fake.calls()] == ["squeue", "sinfo"]
    assert [p.name for p in watch.cluster.partitions] == ["node1", "node2"]
    fake.update(partitions=["node1*|up|1|idle|0/192/0/192", "node2|up|1|drain|0/0/192/192"],
                reasons=["hpc2|drain|bad DIMM"])
    fake.clear_calls()
    await watch.poll_once()
    assert [call[0:2] for call in fake.calls()] == [["squeue", "--me"], ["sinfo", "-h"], ["sinfo", "-R"]]
    assert watch.cluster.reasons["hpc2"].reason == "bad DIMM"
    watch.hide_cluster()
    fake.clear_calls()
    await watch.poll_once()
    assert fake.calls() == []


async def test_controller_down_keeps_the_states(two_studies):
    studies, runner, watch, fake = two_studies
    directory, project = studies[0]
    job = runner.submit(directory, project, cases=[A0])
    watch.track(directory, job.id)
    watch.show_cluster()
    fake.run("101")
    await watch.poll_once()
    ok_time = watch.last_ok
    fake.update(controller_down=True)
    await watch.poll_once()
    assert not watch.snapshot.ok and "Unable to contact" in watch.snapshot.error
    assert watch.cluster.error is not None and watch.last_ok == ok_time
    assert load_job(directory, job.id).case_status[A0] is CaseState.RUNNING


async def test_seff_is_fetched_once_for_a_finished_case(two_studies, history_writer):
    studies, runner, watch, fake = two_studies
    directory, project = studies[0]
    job = runner.submit(directory, project, cases=[A0])
    watch.track(directory, job.id)
    history_writer(directory / "runs" / A0, [0.5] * 30)
    fake.finish("101", elapsed="00:10:00", memory="12.5 GB")
    await watch.poll_once()
    assert len(fake.calls("seff")) == 1
    assert case_stats(directory, A0)["peak_memory_gb"] == pytest.approx(12.5)
    assert not load_job(directory, job.id).slurm[A0].stats_pending
    fake.clear_calls()
    await watch.poll_once()
    assert fake.calls() == []  # the job ended and its figures are in: nothing left to watch


async def test_a_failing_poll_never_stops_the_loop(two_studies, monkeypatch):
    _studies, _runner, watch, _fake = two_studies
    calls = []

    async def broken():
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(watch, "poll_once", broken)
    monkeypatch.setattr(watch, "interval", lambda: 0.0)
    task = asyncio.get_running_loop().create_task(watch.run_forever())
    await asyncio.sleep(2.5)
    assert len(calls) >= 2 and not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_job_watcher_never_runs_slurm_commands_for_a_page(two_studies):
    studies, runner, watch, fake = two_studies
    directory, project = studies[0]
    watcher = JobWatcher(slurm_runner=runner, slurm_watch=watch)
    job = watcher.submit(directory, project, [A0, A2])
    assert job.backend == "slurm"
    fake.run("101")
    fake.clear_calls()
    for _ in range(3):
        view = watcher.state(directory, project)
    assert fake.calls() == []
    assert view.active.id == job.id and view.active.case_status[A0] is CaseState.PENDING
    await watch.poll_once()  # the poller brings the record up to date
    assert watcher.state(directory, project).active.case_status[A0] is CaseState.RUNNING
    assert watcher.case_log(directory, view.active, A0) == directory.resolve() / "runs" / A0 / "slurm-101.out"
    cancelled = watcher.cancel(directory, project)
    assert cancelled.case_status == {A0: CaseState.CANCELLED, A2: CaseState.CANCELLED}
    assert fake.calls("scancel") == [["scancel", "101", "102"]]

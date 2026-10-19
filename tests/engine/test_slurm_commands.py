import asyncio
import subprocess

import pytest

from aerosuite.engine import slurm
from aerosuite.engine.slurm import (
    SlurmUnavailable,
    parse_duration,
    parse_sacct,
    parse_sbatch,
    parse_seff,
    parse_sinfo,
    parse_sinfo_reasons,
    parse_squeue,
    run_async,
    run_sync,
    snapshot_async,
    snapshot_sync,
)

# Captured on hpc1 (2026-10-19): `seff 11` and `sacct -X` / without -X for jobs 8-11.
SEFF_11 = """Job ID: 11
Cluster: pdas-cfd
User/Group: pdas-hpc1/pdas-hpc1
State: COMPLETED (exit code 0)
Nodes: 1
Cores per node: 192
CPU Utilized: 4-18:31:21
CPU Efficiency: 49.49% of 9-15:24:48 core-walltime
Job Wall-clock time: 01:12:19
Memory Utilized: 61.95 GB
Memory Efficiency: 51.62% of 120.00 GB (640.00 MB/core)
The task which had the largest memory consumption differs by 113.89% from the average task max memory consumption
"""
SACCT_X = "9|COMPLETED|0:0|00:00:00||hpc2\n8|FAILED|1:0|00:00:01||hpc1\n11|COMPLETED|0:0|01:12:19||hpc1\n"
SACCT_STEPS = "11|COMPLETED|0:0|01:12:19||hpc1\n11.batch|COMPLETED|0:0|01:12:19|18816K|hpc1\n" \
              "11.0|COMPLETED|0:0|01:12:18|770632K|hpc1\n"


def test_sbatch_id():
    assert parse_sbatch("123\n") == "123"
    assert parse_sbatch("123;pdas-cfd\n") == "123"
    with pytest.raises(SlurmUnavailable, match="job id"):
        parse_sbatch("Submitted batch job 123\n")
    with pytest.raises(SlurmUnavailable):
        parse_sbatch("")


def test_squeue_rows():
    rows = parse_squeue("101|RUNNING|hpc1|1:02:03|hpc1\n102|PENDING||0:00|(Dependency)\n"
                        "103|PENDING||0:00|(DependencyNeverSatisfied)\n\nnot a row\n")
    assert set(rows) == {"101", "102", "103"}
    assert (rows["101"].state, rows["101"].node, rows["101"].time) == ("RUNNING", "hpc1", "1:02:03")
    assert rows["102"].reason == "Dependency" and rows["102"].node == ""
    assert rows["103"].reason == slurm.NEVER_SATISFIED


def test_sacct_rows_from_hpc1():
    rows = parse_sacct(SACCT_X)
    assert set(rows) == {"8", "9", "11"}
    assert (rows["8"].state, rows["8"].exit_code, rows["8"].node) == ("FAILED", "1:0", "hpc1")
    assert rows["11"].elapsed == "01:12:19" and rows["11"].max_rss == ""  # -X: no memory on the allocation
    assert set(parse_sacct(SACCT_STEPS)) == {"11"}  # steps are skipped


def test_sacct_cancelled_by_and_out_of_memory():
    rows = parse_sacct("5|CANCELLED by 1000|0:15|00:01:00||hpc1\n6|OUT_OF_MEMORY|0:125|00:20:00||hpc2\n")
    assert rows["5"].state == "CANCELLED"
    assert (rows["6"].state, rows["6"].exit_code) == ("OUT_OF_MEMORY", "0:125")


def test_sinfo_rows():
    rows = parse_sinfo("node1*|up|1|idle|0/192/0/192\nnode2|up|1|drain|0/0/192/192\nnode2|up|1|mix|96/96/0/192\n")
    assert [(r.name, r.default, r.state) for r in rows] == [
        ("node1", True, "idle"), ("node2", False, "drain"), ("node2", False, "mix")]
    assert (rows[0].allocated, rows[0].idle, rows[0].other, rows[0].total) == (0, 192, 0, 192)
    assert [r.bad for r in rows] == [False, True, False]
    assert parse_sinfo("node1|down|1|down*|0/0/192/192\n")[0].bad


def test_sinfo_reasons():
    reasons = parse_sinfo_reasons("hpc2|drain|memory test | by admin\n")
    assert reasons["hpc2"].state == "drain" and reasons["hpc2"].reason == "memory test | by admin"


def test_durations():
    assert parse_duration("01:12:19") == 4339
    assert parse_duration("4-18:31:21") == 4 * 86400 + 18 * 3600 + 31 * 60 + 21
    assert parse_duration("12:05") == 725
    assert parse_duration("00:02.500") == 2.5
    assert parse_duration("") is None and parse_duration("n/a") is None


def test_seff_from_hpc1():
    stats = parse_seff(SEFF_11)
    assert stats.state == "COMPLETED"
    assert stats.wall_s == 4339
    assert stats.cpu_utilized_s == 4 * 86400 + 18 * 3600 + 31 * 60 + 21
    assert stats.memory_gb == pytest.approx(61.95)
    assert parse_seff("Memory Utilized: 512.00 MB\n").memory_gb == pytest.approx(0.5)
    assert parse_seff("Memory Utilized: 1.50 TB\n").memory_gb == pytest.approx(1536)
    assert parse_seff("nothing useful").memory_gb is None


def test_run_sync_reports_missing_failing_and_slow_commands(monkeypatch, tmp_path):
    with pytest.raises(SlurmUnavailable, match="not found on PATH"):
        run_sync(["no-such-slurm-command-xyz"])
    with pytest.raises(SlurmUnavailable, match="false failed"):
        run_sync(["false"])
    assert run_sync(["echo", "hi"]) == "hi\n"

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(SlurmUnavailable, match="did not answer"):
        run_sync(["echo", "hi"], timeout=1)


def test_run_async():
    assert asyncio.run(run_async(["echo", "hi"])) == "hi\n"
    with pytest.raises(SlurmUnavailable, match="not found on PATH"):
        asyncio.run(run_async(["no-such-slurm-command-xyz"]))
    with pytest.raises(SlurmUnavailable, match="did not answer"):
        asyncio.run(run_async(["sleep", "5"], timeout=0.2))
    with pytest.raises(SlurmUnavailable, match="sh failed: boom"):
        asyncio.run(run_async(["sh", "-c", "echo boom >&2; exit 3"]))


# -- through the fake -----------------------------------------------------------------------------------

def _script(folder, *lines):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "su2_job.sh"
    path.write_text("#!/bin/bash -l\n" + "".join(f"#SBATCH {line}\n" for line in lines))
    return path


def test_fake_sbatch_and_squeue(fake_slurm, tmp_path):
    script = _script(tmp_path / "a", "-J s/a", "-p node1", "-n 96")
    out = run_sync(slurm.sbatch_args(script.name), cwd=str(script.parent))
    assert parse_sbatch(out) == "101"
    job = fake_slurm.job("101")
    assert (job["name"], job["partition"], job["ntasks"], job["cwd"]) == ("s/a", "node1", "96", str(tmp_path / "a"))
    fake_slurm.run("101")
    rows = parse_squeue(run_sync(slurm.squeue_args()))
    assert rows["101"].state == "RUNNING" and rows["101"].node == "hpc1"


def test_snapshot_makes_one_squeue_and_one_sacct_for_jobs_that_left(fake_slurm, tmp_path):
    for name in "abc":
        run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / name, "-p node1").parent))
    fake_slurm.run("101")
    fake_slurm.finish("102", "OUT_OF_MEMORY", "0:125", node="hpc2")
    fake_slurm.finish("103", "COMPLETED")
    fake_slurm.clear_calls()
    snap = snapshot_sync(["101", "102", "103"])
    assert snap.ok and set(snap.queue) == {"101"}
    assert snap.accounting["102"].state == "OUT_OF_MEMORY" and snap.accounting["103"].state == "COMPLETED"
    calls = fake_slurm.calls()
    assert [call[0] for call in calls] == ["squeue", "sacct"]
    assert calls[1][calls[1].index("-j") + 1] == "102,103"
    assert "-X" in calls[1]


def test_snapshot_without_jobs_that_left_skips_sacct(fake_slurm, tmp_path):
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a").parent))
    fake_slurm.clear_calls()
    snap = snapshot_sync(["101"])
    assert snap.ok and [call[0] for call in fake_slurm.calls()] == ["squeue"]


def test_snapshot_when_the_controller_is_down(fake_slurm):
    fake_slurm.update(controller_down=True)
    snap = snapshot_sync(["101"])
    assert not snap.ok and "Unable to contact slurm controller" in snap.error
    assert snap.queue == {} and [call[0] for call in fake_slurm.calls()] == ["squeue"]


def test_snapshot_when_accounting_is_down(fake_slurm, tmp_path):
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a").parent))
    fake_slurm.finish("101")
    fake_slurm.update(accounting_down=True)
    snap = snapshot_sync(["101"])
    assert snap.ok and snap.accounting == {} and "database" in snap.accounting_error


def test_snapshot_async_matches(fake_slurm, tmp_path):
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a").parent))
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "b").parent))
    fake_slurm.finish("102", "NODE_FAIL", "0:0")
    snap = asyncio.run(snapshot_async(["101", "102"]))
    assert set(snap.queue) == {"101"} and snap.accounting["102"].state == "NODE_FAIL"


def test_fake_scancel_and_sinfo(fake_slurm, tmp_path):
    run_sync(slurm.sbatch_args("su2_job.sh"), cwd=str(_script(tmp_path / "a").parent))
    run_sync(slurm.scancel_args(["101"]))
    assert fake_slurm.job("101")["state"] == "CANCELLED"
    rows = parse_sinfo(run_sync(slurm.sinfo_args()))
    assert [r.name for r in rows] == ["node1", "node2"]
    fake_slurm.update(reasons=["hpc2|drain|bad DIMM"])
    assert parse_sinfo_reasons(run_sync(slurm.sinfo_reason_args()))["hpc2"].reason == "bad DIMM"

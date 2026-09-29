"""`aerosuite run` in a real process returns at once and leaves the sweep running."""
import os
import subprocess
import sys

from typer.testing import CliRunner

from aerosuite.cli import app
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.store import kill_tree, list_jobs, process_alive

runner = CliRunner()


def test_run_returns_and_the_sweep_keeps_running(ready_project, fake_plan):
    project_dir, _ = ready_project
    result = runner.invoke(app, ["generate", str(project_dir)])
    assert result.exit_code == 0, result.output
    fake_plan(project_dir, M0p8_a0_b0="hang")
    env = dict(os.environ, SU2_RUN="/opt/su2/bin")
    try:
        done = subprocess.run(
            [sys.executable, "-m", "aerosuite.cli", "run", str(project_dir)],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "Started job" in done.stdout
        job = LocalRunner().refresh(project_dir, list_jobs(project_dir)[0])
        assert job.is_active
        assert process_alive(job.backend_ref["pid"], job.backend_ref["create_time"])
    finally:
        for job in list_jobs(project_dir):
            if job.backend_ref.get("pid"):
                kill_tree(job.backend_ref["pid"])

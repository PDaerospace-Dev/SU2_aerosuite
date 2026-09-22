"""Fixtures for CLI tests that run the fake sweep."""
import json
import time

import pytest

from aerosuite.engine.cfg import CONFIGS_DIR
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.store import list_jobs


@pytest.fixture
def su2_env(monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")


@pytest.fixture
def fake_plan():
    def write(project_dir, delay=0.05, **cases):
        path = project_dir / CONFIGS_DIR / "fake_plan.json"
        path.write_text(json.dumps({"delay": delay, "cases": cases}))

    return write


@pytest.fixture
def wait_job():
    def wait(project_dir, until=None, timeout=20):
        runner = LocalRunner()
        deadline = time.monotonic() + timeout
        job = None
        while time.monotonic() < deadline:
            job = runner.refresh(project_dir, list_jobs(project_dir)[0])
            if (until(job) if until else not job.is_active):
                return job
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for job: {job}")

    return wait

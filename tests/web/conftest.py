"""Fixtures for web UI tests."""
import asyncio
import time

import pytest


@pytest.fixture(autouse=True)
def web_env(tmp_path, monkeypatch):
    """Point the picker root and the recent-projects store at this test's temp folder."""
    monkeypatch.setenv("AEROSUITE_WEB_ROOT", str(tmp_path))
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "aerosuite-home"))


@pytest.fixture
def eventually():
    """Wait (without blocking the event loop) until condition() is true, e.g. after an awaited dialog."""

    async def wait(condition, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError("condition not met in time")
            await asyncio.sleep(0.02)

    return wait

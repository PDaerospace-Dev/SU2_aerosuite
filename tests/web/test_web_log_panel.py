"""The log panel at the bottom of every project page, and the Run page's Job history tab."""
import json
import time

import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import CONFIGS_DIR, generate_configs
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.web import layout, log_panel
from aerosuite.web.layout import project_url

A0 = "M0p8_a0_b0"


@pytest.fixture
def su2_env(monkeypatch):
    monkeypatch.setenv("SU2_RUN", "/opt/su2/bin")


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _shown(user, marker) -> bool:
    try:
        return bool(user.find(marker=marker).elements)
    except AssertionError:
        return False


def _run(project_dir, project, wait=True, **cases):
    generate_configs(project_dir, project)
    (project_dir / CONFIGS_DIR / "fake_plan.json").write_text(json.dumps({"delay": 0.05, "cases": cases}))
    runner = LocalRunner()
    job = runner.submit(project_dir, project)
    deadline = time.monotonic() + 20
    while wait and job.is_active and time.monotonic() < deadline:
        time.sleep(0.1)
        job = runner.refresh(project_dir, job)
    return runner, job


async def test_the_log_opens_from_the_bottom_and_shows_the_latest_job(user: User, ready_project):
    project_dir, project = ready_project
    _, job = _run(project_dir, project)
    await user.open(project_url("setup", project_dir))
    await user.should_not_see(marker="log-panel")
    user.find(marker="log-open").click()
    await user.should_see(marker="log-panel")
    assert _element(user, "log-job").value == job.id
    assert f"Running Case 1/3: {A0}.cfg" in _element(user, "log-text").text
    await user.should_not_see(marker="log-open")  # the button hides while the panel is open
    user.find(marker="log-close").click()
    await user.should_not_see(marker="log-panel")
    await user.should_see(marker="log-open")


async def test_the_log_can_show_any_earlier_job(user: User, ready_project):
    project_dir, project = ready_project
    _, first = _run(project_dir, project)
    (project_dir / first.log_path).write_text("the first job's log\n")
    _, second = _run(project_dir, project)
    await user.open(project_url("setup", project_dir))
    user.find(marker="log-open").click()
    select = _element(user, "log-job")
    assert select.value == second.id and set(select.options) == {first.id, second.id}
    with user:
        select.set_value(first.id)
    assert _element(user, "log-text").text == "the first job's log"


async def test_without_jobs_the_log_says_so(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    user.find(marker="log-open").click()
    await user.should_see("No jobs yet")


async def test_the_running_indicator_opens_the_log_of_the_running_job(user: User, ready_project, su2_env,
                                                                     eventually, monkeypatch):
    monkeypatch.setattr(layout, "WATCH_SECONDS", 0.1)
    monkeypatch.setattr(log_panel, "POLL_SECONDS", 0.1)
    project_dir, project = ready_project
    await user.open(project_url("setup", project_dir))
    runner, job = _run(project_dir, project, wait=False, **{A0: "hang"})
    try:
        await eventually(lambda: _shown(user, "job-indicator"), timeout=10)
        user.find(marker="job-indicator").click()
        await user.should_see(marker="log-panel")
        assert _element(user, "log-job").value == job.id
        await eventually(lambda: f"Running Case 1/3: {A0}.cfg" in _element(user, "log-text").text, timeout=10)
    finally:
        runner.cancel(project_dir, runner.refresh(project_dir, job))


async def test_job_history_is_its_own_tab_and_opens_a_jobs_log(user: User, ready_project, su2_env):
    project_dir, project = ready_project
    _, job = _run(project_dir, project)
    await user.open(project_url("run", project_dir))
    tabs = _element(user, "run-tabs")
    assert tabs.value == "cases"
    await user.should_not_see(marker="history-none")
    await user.should_see(marker=f"status-{A0}")
    await user.should_not_see(marker=f"history-{job.id}")
    with user:
        tabs.set_value("history")
    await user.should_see(marker=f"history-{job.id}")
    await user.should_not_see(marker=f"status-{A0}")
    user.find(marker=f"history-log-{job.id}").click()
    await user.should_see(marker="log-panel")
    assert _element(user, "log-job").value == job.id

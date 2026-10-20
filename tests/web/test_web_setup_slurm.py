"""Setup's Run settings step follows the study's backend: local MPI settings, or Slurm partition, tasks, limit."""
from nicegui.testing import User

from aerosuite.engine.project import open_project, save_project
from aerosuite.web.layout import project_url


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


async def _commit(user, marker, value):
    with user:
        _element(user, marker).set_value(value)
    user.find(marker=marker).trigger("keydown.enter")


async def test_local_by_default(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    assert _element(user, "setup-backend").value == "local"
    await user.should_see(marker="partitions")
    await user.should_see(marker="run-advanced")
    await user.should_not_see(marker="setup-partition")
    assert _text(user, "ready-run") == "This machine · 1 MPI partition per case"


async def test_switching_to_slurm_shows_its_fields_and_saves(user: User, ready_project):
    project_dir, _ = ready_project
    await user.open(project_url("setup", project_dir))
    with user:
        _element(user, "setup-backend").set_value("slurm")
    await user.should_see(marker="setup-partition")
    await user.should_not_see(marker="partitions")
    await user.should_not_see(marker="run-advanced")
    assert open_project(project_dir).run.backend == "slurm"
    assert _element(user, "setup-partition").value == "node1"
    assert _element(user, "setup-ntasks").value == "96"
    assert _text(user, "setup-partition-note") == "96 tasks by default · 120 GB memory limit"
    assert _text(user, "setup-node-note") == "1 node per case, exclusive"
    assert _text(user, "ready-run") == "Slurm · node1 · 96 tasks per case"
    with user:
        _element(user, "setup-backend").set_value("local")
    await user.should_see(marker="partitions")
    assert open_project(project_dir).run.backend == "local"


async def test_partition_tasks_and_the_settings_time_limit(user: User, ready_project):
    project_dir, project = ready_project
    project.run.backend = "slurm"
    save_project(project_dir, project)
    await user.open(project_url("setup", project_dir))
    with user:
        _element(user, "setup-partition").set_value("node2")
    await user.should_see("48 tasks by default · 61 GB memory limit")
    assert _element(user, "setup-ntasks").value == "48"
    assert _text(user, "ready-run") == "Slurm · node2 · 48 tasks per case"
    await _commit(user, "setup-ntasks", "96")
    await user.should_see("node2 gains nothing above about 48 tasks")
    assert open_project(project_dir).run.slurm.ntasks == 96
    assert _text(user, "setup-time-limit") == "none"  # shown, set on the Settings page only
    await user.should_not_see(marker="setup-time-limit-error")


async def test_the_time_limit_comes_from_the_settings(user: User, ready_project):
    from aerosuite.engine.settings import AppSettings, save_settings, set_value

    project_dir, project = ready_project
    project.run.backend = "slurm"
    project.run.slurm.time_limit = "1:00:00"  # an old per-study value: ignored now
    save_project(project_dir, project)
    save_settings(set_value(AppSettings(), "slurm.default_time_limit", "2-00:00:00"))
    await user.open(project_url("setup", project_dir))
    assert _text(user, "setup-time-limit") == "2-00:00:00"
    assert _text(user, "ready-run") == "Slurm · node1 · 96 tasks per case · limit 2-00:00:00"

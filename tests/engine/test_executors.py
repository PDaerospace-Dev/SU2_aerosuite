import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.executors import backend_of, runner_for, runner_of, slurm_options
from aerosuite.engine.jobs.local import LocalRunner
from aerosuite.engine.jobs.runner import JobRecord
from aerosuite.engine.models import Project
from aerosuite.engine.settings import AppSettings, save_settings, set_value


def test_backend_is_the_projects_choice_else_the_server_default():
    project = Project(name="p")
    assert backend_of(project) == "local"
    save_settings(set_value(AppSettings(), "backend", "slurm"))
    assert backend_of(project) == "slurm"
    project.run.backend = "local"
    assert backend_of(project) == "local"


def test_one_runner_per_backend():
    assert isinstance(runner_for("local"), LocalRunner)
    assert runner_for("local") is runner_for("local")
    job = JobRecord(id="j", backend="local", cases=[], log_path="jobs/j.log")
    assert runner_of(job) is runner_for("local")
    with pytest.raises(JobError, match="Unknown backend"):
        runner_for("pbs")


def test_slurm_options_resolve_given_then_project_then_settings():
    settings = AppSettings()
    project = Project(name="p")
    options = slurm_options(project, settings)
    assert (options.partition, options.ntasks, options.time_limit, options.exclusive, options.account) == (
        "node1", 96, "", True, "pdas")
    assert slurm_options(project, settings, partition="node2").ntasks == 48
    project.run.slurm.partition = "node2"
    project.run.slurm.time_limit = "1:00:00"  # ignored: the settings' limit applies
    options = slurm_options(project, settings)
    assert (options.partition, options.ntasks, options.time_limit) == ("node2", 48, "")
    assert slurm_options(project, settings, time_limit="1:00:00").time_limit == "1:00:00"  # one run
    project.run.slurm.ntasks = 32
    assert slurm_options(project, settings).ntasks == 32
    assert slurm_options(project, settings, ntasks=16, time_limit="").ntasks == 16
    assert slurm_options(project, settings, time_limit="").time_limit == ""
    assert slurm_options(project, settings, partition="nope").partition == "nope"  # the checks report it

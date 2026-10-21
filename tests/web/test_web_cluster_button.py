from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url
from aerosuite.web.slurm_watch import WATCH


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_no_button_without_slurm(user: User):
    await user.open("/")
    await user.should_not_see(marker="cluster")


async def test_the_button_dot_and_count(user: User, fake_slurm, ready_project, tmp_path, eventually):
    project_dir, project = ready_project
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)))
    project.run.backend = "slurm"
    generate_configs(project_dir, project)
    runner_for("slurm").submit(project_dir, project)
    fake_slurm.run("101")
    fake_slurm.run("102", node="hpc2")
    await user.open(project_url("run", project_dir))
    await user.should_see(marker="cluster")
    assert WATCH.viewers >= 1  # the button asks the poller for sinfo -N
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-green" in _element(user, "cluster-dot").classes, 5)
    assert _element(user, "cluster-count").text == "· 2"
    fake_slurm.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|101000|96.0|none",
                             "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-amber" in _element(user, "cluster-dot").classes, 5)
    assert "hpc2 drain: bad DIMM" in _element(user, "cluster-dot").props["title"]
    fake_slurm.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: "as-dot-red" in _element(user, "cluster-dot").classes, 5)
    user.find(marker="cluster").click()
    await user.should_see(marker="cluster-page")

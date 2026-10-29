import pytest
from nicegui.testing import User

from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import runner_for
from aerosuite.engine.jobs.runner import CaseState
from aerosuite.engine.jobs.store import list_jobs
from aerosuite.engine.project import save_project
from aerosuite.engine.settings import AppSettings, save_settings, set_value
from aerosuite.web.layout import project_url
from aerosuite.web.slurm_watch import WATCH

A0, A2, A4 = "M0p8_a0_b0", "M0p8_a2_b0", "M0p8_a4_b0"


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _text(user, marker):
    return _element(user, marker).text


def _card_order(user):
    """The node cards from first to last."""
    grid = _element(user, "node-card-hpc1").parent_slot.parent
    return [next(m for m in card._markers if m.startswith("node-card-")).removeprefix("node-card-")
            for card in grid.default_slot.children]


@pytest.fixture
def cluster_study(ready_project, tmp_path, fake_slurm):
    project_dir, project = ready_project
    save_settings(set_value(AppSettings(), "slurm.shared_root", str(tmp_path)))
    project.run.backend = "slurm"
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    return project_dir, project, fake_slurm


async def _open(user):
    import asyncio

    await user.open("/cluster")
    await user.should_see(marker="cluster-page")
    await WATCH.poll_once()  # the page asked for nodes and the recent history
    await asyncio.sleep(2.2)  # the page's 2 s tick tracks the cases it found (the live server polls again at once)
    await WATCH.poll_once()  # ... and the poller brings their records up to date


async def test_nodes_and_my_jobs_without_the_queue(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101", node="hpc1")
    fake.add_job("900", user="ana", state="PENDING", node="", reason="Resources", name="ana/x")
    fake.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|20000|96.0|none",
                       "hpc2|node2|drain|0/0/192/192|62000|57000|0.0|bad DIMM"])
    await _open(user)
    assert WATCH.pages == 1
    await eventually(lambda: _text(user, "node-hpc2-note") == "bad DIMM", 5)
    assert _text(user, "node-hpc1-cpus") == "CPU · 192 / 192" and _text(user, "node-hpc1-memory") == "Memory · 122 GB"
    assert _text(user, "node-hpc1-state") == "Full" and _text(user, "node-hpc2-state") == "Drained"
    assert "as-node-bad" in _element(user, "node-card-hpc2").classes
    assert _text(user, "tile-nodes-value") == "1 of 2 up" and _text(user, "tile-nodes-sub") == "hpc2 drained"
    assert _text(user, "tile-cpus-value") == "192 / 384"
    await user.should_not_see(marker="queue-card")  # everyone's queue is not shown
    await eventually(lambda: _text(user, "job-101-state") == "Running", 5)  # the page re-renders every 2 s
    assert _text(user, "job-102-state").startswith("Pending")
    await user.should_not_see(marker="job-900")  # someone else's


async def test_a_node_card_shows_the_study_job_running_there(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101", node="hpc1")
    fake.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|20000|96.0|none",
                       "hpc2|node2|idle|0/192/0/192|62000|57000|0.0|none"])
    await _open(user)
    marker = f"node-hpc1-job-{job.id}"
    await eventually(lambda: bool(user.find(marker=marker).elements), 5)
    assert _text(user, f"{marker}-done") == "0 / 2"  # the whole job, as Run's job bar
    assert _text(user, f"{marker}-time") == f"Now {A0} · time left shown after the first case"
    assert _element(user, marker).props["href"] == project_url("run", project_dir)  # opens the study's Run page
    await user.should_see(marker="node-hpc2-nojob")
    assert _text(user, "tile-running-value") == "1 study" and _text(user, "tile-running-sub") == "on hpc1"
    assert _text(user, "tile-left-value") == "2"


async def test_a_node_card_shows_a_study_job_queued_for_it(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])  # node1: hpc1, every case waits
    fake.update(nodes=["hpc1|node1*|alloc|192/0/0/192|125000|20000|96.0|none",
                       "hpc2|node2|idle|0/192/0/192|62000|57000|0.0|none"])
    await _open(user)
    marker = f"node-hpc1-job-{job.id}"
    await eventually(lambda: bool(user.find(marker=marker).elements), 5)
    assert _text(user, f"{marker}-done") == "2 cases"
    assert _text(user, f"{marker}-time") == "Waiting in the Slurm queue"  # nothing of the user's runs there
    assert _text(user, "tile-queued-value") == "1 study" and _text(user, "tile-running-value") == "None"
    await user.should_see(marker="node-hpc2-nojob")


async def test_dragging_a_node_card_moves_it_and_keeps_the_order(user: User, cluster_study, eventually):
    from aerosuite.engine.settings import load_settings

    fake = cluster_study[2]
    fake.update(nodes=["hpc1|node1*|idle|0/192/0/192|125000|20000|0.0|none",
                       "hpc2|node2|idle|0/192/0/192|62000|57000|0.0|none",
                       "hpc0|node0|idle|0/64/0/64|229000|209000|0.0|none"])
    await _open(user)
    await eventually(lambda: bool(user.find(marker="node-card-hpc0").elements), 5)

    assert _card_order(user) == ["hpc1", "hpc2", "hpc0"]  # the default partition's first
    user.find(marker="node-card-hpc0").trigger("dragstart")
    user.find(marker="node-card-hpc1").trigger("drop")
    await eventually(lambda: _card_order(user) == ["hpc0", "hpc1", "hpc2"], 5)
    assert load_settings()[0].slurm.node_order == ["hpc0", "hpc1", "hpc2"]  # kept for the next visit
    user.find(marker="node-card-hpc0").trigger("dragstart")
    user.find(marker="node-card-hpc2").trigger("drop")  # moving down: after the card it is dropped on
    await eventually(lambda: _card_order(user) == ["hpc1", "hpc2", "hpc0"], 5)


async def test_my_jobs_show_when_cases_started_and_ended_and_group_by_job(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.finish("101", elapsed="00:30:00")
    fake.set_job("101", start="2026-10-28T22:00:00", end="2026-10-28T22:30:00")
    fake.finish("102", elapsed="00:30:00")
    fake.set_job("102", start="2026-10-28T22:30:00", end="2026-10-28T23:00:00")
    WATCH.track(project_dir, job.id)
    from aerosuite.web.pages import cluster as cluster_page

    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-102-ended").elements), 5)
    assert _text(user, "job-101-started") == "28 Oct 22:00" and _text(user, "job-101-ended") == "28 Oct 22:30"
    user.find(marker="jobs-group").click()
    assert cluster_page._GROUP["on"] == cluster_page.GROUPED_AT_FIRST  # a fresh server groups them
    key = f"{project.name}-{job.id}"
    await eventually(lambda: bool(user.find(marker=f"group-{key}").elements), 5)
    assert _text(user, f"group-{key}-done") == "2 / 2"
    assert _text(user, f"group-{key}-started") == "28 Oct 22:00" and _text(user, f"group-{key}-ended") == "28 Oct 23:00"
    await eventually(lambda: _text(user, f"group-{key}-took") == "took 1 h", 5)
    await user.should_not_see(marker="job-101-study")  # the group's line names the study
    assert _text(user, f"group-{key}-folded") == "2 cases folded"  # an ended job starts folded
    await user.should_not_see(marker="job-101")
    user.find(marker=f"group-{key}").click()
    await user.should_see(marker="job-101")
    assert _text(user, "job-101-ended") == "28 Oct 22:30"
    await user.should_not_see(marker=f"group-{key}-folded")
    user.find(marker=f"group-{key}").click()  # and shut again
    await user.should_not_see(marker="job-101")
    user.find(marker="jobs-group").click()
    await user.should_see(marker="job-101-study")


async def test_an_ascii_job_shows_as_its_case_with_its_own_log(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    folder = project_dir / "runs" / A0
    folder.mkdir(parents=True)
    (folder / "to_ascii-700.out").write_text("AeroSuite: ASCII files written\n")
    fake.add_job("700", user=WATCH.user, name=f"{project.name}/{A0}-ascii", cwd=str(folder))
    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-700-task").elements), 5)
    assert _text(user, "job-700") == A0 and _text(user, "job-700-task") == "ASCII files"
    await user.should_not_see(marker="cancel-700")  # not a case of a job record
    user.find(marker="log-700").click()
    await eventually(lambda: "ASCII files written" in _text(user, "log-dialog-text"), 5)


async def test_filters(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    fake.finish("102", "OUT_OF_MEMORY", "0:125")
    WATCH.track(project_dir, job.id)
    await _open(user)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="job-102").elements), 5)
    user.find(marker="jobs-filter-active").click()
    await user.should_not_see(marker="job-102")
    await user.should_see(marker="job-101")
    user.find(marker="jobs-filter-failed").click()
    await user.should_see(marker="job-102")
    await user.should_not_see(marker="job-101")


async def test_cancel_one_case(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    fake.run("101")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="cancel-102").elements), 5)
    user.find(marker="cancel-102").click()
    await eventually(lambda: bool(user.find(marker="cancel-confirm").elements))
    user.find(marker="cancel-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].case_status[A2] is CaseState.CANCELLED, 10)
    assert fake.calls("scancel") == [["scancel", "102"]]
    assert list_jobs(project_dir)[0].case_status[A0] is CaseState.RUNNING


async def test_resubmit_from_the_cluster_page(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    project.run.slurm.partition = "node2"
    save_project(project_dir, project)
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.finish("101", "OUT_OF_MEMORY", "0:125", node="hpc2")
    WATCH.track(project_dir, job.id)
    await _open(user)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="resubmit-101").elements), 5)
    user.find(marker="resubmit-101").click()
    await eventually(lambda: bool(user.find(marker="resubmit-confirm").elements))
    assert _element(user, "resubmit-partition").value == "node0"  # after OUT_OF_MEMORY: the most memory (235 GB)
    user.find(marker="resubmit-confirm").click()
    await eventually(lambda: list_jobs(project_dir)[0].slurm[A0].attempts == ["101"], 10)


async def test_log_dialog(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    (project_dir / "runs" / A0 / "slurm-101.out").write_text("AeroSuite: Slurm job 101\n|   12|  -4.1|\n")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="log-101").elements), 5)
    user.find(marker="log-101").click()
    await eventually(lambda: "|   12|  -4.1|" in _text(user, "log-dialog-text"), 5)


async def test_controller_down_shows_stale_data_and_disables_actions(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="cancel-101").elements), 5)
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="cluster-outage").elements), 5)
    assert "Slurm controller unreachable" in _text(user, "cluster-outage")
    assert not _element(user, "cancel-101").enabled


async def test_accounting_down_lists_active_cases_only(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    fake.update(accounting_down=True)
    await _open(user)
    await eventually(lambda: bool(user.find(marker="jobs-accounting").elements), 5)
    await user.should_see(marker="job-101")


async def test_my_jobs_fold_and_stay_folded(user: User, cluster_study, eventually):
    from aerosuite.web.pages import cluster as cluster_page

    cluster_page._COLLAPSED.clear()
    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-101").elements), 5)
    user.find(marker="jobs-card-toggle").click()
    await user.should_not_see(marker="job-101")
    await user.open("/cluster")  # a new page: the sections stay folded
    await user.should_see(marker="jobs-card-toggle")
    await user.should_not_see(marker="job-101")
    user.find(marker="jobs-card-toggle").click()
    await eventually(lambda: bool(user.find(marker="job-101").elements), 5)
    cluster_page._COLLAPSED.clear()


async def test_more_than_the_cap_says_so(user: User, cluster_study, monkeypatch, eventually):
    from aerosuite.web.pages import cluster as cluster_page

    project_dir, project, fake = cluster_study
    monkeypatch.setattr(cluster_page, "MAX_ROWS", 1)
    runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    await _open(user)
    await eventually(lambda: _text(user, "jobs-more") == "1 older job not shown", 5)


async def test_a_brief_disconnect_keeps_the_page_counted(user: User, cluster_study):
    await user.open("/cluster")
    await user.should_see(marker="cluster-page")
    assert (WATCH.viewers, WATCH.pages) == (1, 1)  # the top-bar button and the page
    for handler in list(user.client.disconnect_handlers):  # a Wi-Fi blip: the socket drops and comes back
        user.client.safe_invoke(handler)
    assert (WATCH.viewers, WATCH.pages) == (1, 1)
    for handler in list(user.client.delete_handlers):  # the tab is really gone
        user.client.safe_invoke(handler)
    assert (WATCH.viewers, WATCH.pages) == (0, 0)


async def test_the_log_dialog_stays_open_and_follows_new_output(user: User, cluster_study, eventually):
    import asyncio

    project_dir, project, fake = cluster_study
    runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.run("101")
    out = project_dir / "runs" / A0 / "slurm-101.out"
    out.write_text("AeroSuite: Slurm job 101\n|   12|  -4.1|\n")
    await _open(user)
    await eventually(lambda: bool(user.find(marker="log-101").elements), 5)
    user.find(marker="log-101").click()
    await eventually(lambda: "|   12|  -4.1|" in _text(user, "log-dialog-text"), 5)
    assert _element(user, "log-dialog-follow").value is True
    fake.run("101", time="0:30")  # something on the page changes: it is drawn again
    await WATCH.poll_once()
    await asyncio.sleep(2.5)
    out.write_text(out.read_text() + "|   13|  -4.2|\n")
    await eventually(lambda: "|   13|  -4.2|" in _text(user, "log-dialog-text"), 5)


async def test_the_page_is_not_redrawn_when_nothing_visible_changed(user: User, cluster_study, monkeypatch):
    import asyncio

    from aerosuite.web.pages import cluster as cluster_page

    renders = []
    real = cluster_page.ClusterPage.render
    monkeypatch.setattr(cluster_page.ClusterPage, "render", lambda self, *a: renders.append(1) or real(self, *a))
    await _open(user)
    count = len(renders)
    for _ in range(2):  # new polls, same cluster
        await WATCH.poll_once()
        await asyncio.sleep(2.2)
    assert len(renders) == count


async def test_an_outage_keeps_the_last_known_nodes(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    await _open(user)
    await eventually(lambda: bool(user.find(marker="node-card-hpc1").elements), 5)
    fake.update(controller_down=True)
    await WATCH.poll_once()
    await eventually(lambda: bool(user.find(marker="cluster-outage").elements), 5)
    assert _element(user, "node-card-hpc1") is not None
    assert "as of" in _text(user, "nodes-summary")


def _order(user, markers):
    """The given markers in the order their elements appear on the page."""
    found = []
    for element in user.client.layout.descendants():
        for marker in element._markers:
            if marker in markers and marker not in found:
                found.append(marker)
    return found


async def test_my_jobs_show_when_each_case_was_submitted_and_sort(user: User, cluster_study, eventually):
    from datetime import datetime

    from aerosuite.web.pages import cluster as cluster_page

    cluster_page._SORT.update(key="submitted", descending=True)
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0, A2])
    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-102").elements), 5)
    expected = datetime.fromtimestamp(job.slurm[A0].submitted).strftime("%d %b %H:%M")
    assert _text(user, "job-101-submitted") == expected
    assert _order(user, ["job-101", "job-102"]) == ["job-102", "job-101"]  # newest first
    assert "↓" in _text(user, "sort-submitted")
    user.find(marker="sort-case").click()
    await eventually(lambda: _order(user, ["job-101", "job-102"]) == ["job-101", "job-102"], 5)  # A0 before A2
    assert "↑" in _text(user, "sort-case") and "↓" not in _text(user, "sort-submitted")
    user.find(marker="sort-case").click()
    await eventually(lambda: _order(user, ["job-101", "job-102"]) == ["job-102", "job-101"], 5)
    assert "↓" in _text(user, "sort-case")
    await user.open("/cluster")  # the choice is kept while the server runs
    await eventually(lambda: bool(user.find(marker="sort-case").elements), 5)
    assert "↓" in _text(user, "sort-case")
    cluster_page._SORT.update(key="submitted", descending=True)


async def test_close_goes_back_to_the_page_you_came_from(user: User, cluster_study):
    project_dir, _project, _fake = cluster_study
    await user.open("/settings")
    user.find(marker="cluster").click()  # the top-bar button remembers where you were
    await user.should_see(marker="cluster-page")
    user.find(marker="cluster-close").click()
    await user.should_see(marker="settings-backend")


async def test_close_never_leaves_aerosuite(user: User, cluster_study):
    await user.open("/cluster?back=//evil.example/x")
    await user.should_see(marker="cluster-page")
    user.find(marker="cluster-close").click()
    await user.should_not_see(marker="cluster-page")
    await user.should_see(marker="recent-empty")  # the Projects page, not another site


async def test_a_failed_job_says_why(user: User, cluster_study, eventually):
    project_dir, project, fake = cluster_study
    job = runner_for("slurm").submit(project_dir, project, cases=[A0])
    fake.finish("101", "NODE_FAIL", "0:0", node="hpc2")
    WATCH.track(project_dir, job.id)
    await WATCH.poll_once()  # the record learns how it ended
    await _open(user)
    await eventually(lambda: bool(user.find(marker="job-101-why").elements), 8)
    assert _text(user, "job-101-why") == "The node failed"

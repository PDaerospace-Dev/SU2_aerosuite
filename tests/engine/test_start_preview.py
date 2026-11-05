"""What each case of a run about to start begins from (plan.preview_starts), and the Run page's words for it."""
import pytest

from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.plan import Start, mode_starts, preview_starts
from aerosuite.engine.restarts import RUNS_DIR
from aerosuite.web.starts_view import start_groups, start_text, summary

from slurm_helpers import A0, A2, A4


def _solution(project_dir, name, text="solution"):
    folder = project_dir / RUNS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "restart_flow.dat").write_text(text)


@pytest.fixture
def chained(ready_project):
    """Each case continues from the previous one (A0 from scratch)."""
    project_dir, project = ready_project
    for case in project.cases[1:]:
        case.restart = "previous"
    return project_dir, project


def test_as_the_sweep_says(chained):
    project_dir, project = chained
    _solution(project_dir, A0)
    assert preview_starts(project_dir, project, [A2, A4], "sweep") == [
        Start(A2, "case", A0), Start(A4, "after", A2)]
    assert preview_starts(project_dir, project, [A2], "sweep", busy={A0}) == [Start(A2, "running", A0)]
    assert preview_starts(project_dir, project, [A4], "sweep") == [Start(A4, "scratch", A2)]  # A2 has none yet


def test_each_cases_own_last_solution_and_from_scratch(chained):
    project_dir, project = chained
    _solution(project_dir, A0)
    assert preview_starts(project_dir, project, [A0, A2], "last") == [Start(A0, "own", A0), Start(A2, "none")]
    assert preview_starts(project_dir, project, [A0, A2], "scratch") == [Start(A0, "scratch"), Start(A2, "scratch")]
    assert preview_starts(project_dir, project, [A2], "sweep", starts={A2: None}) == [Start(A2, "scratch")]


def test_the_modes_for_prepare_job():
    assert mode_starts("sweep", [A0, A2]) == ([], {})
    assert mode_starts("last", [A0, A2]) == ([A0, A2], {})
    assert mode_starts("scratch", [A0, A2]) == ([], {A0: None, A2: None})
    with pytest.raises(JobError):
        mode_starts("fresh", [A0])


def test_the_preview_in_groups_and_words():
    starts = [Start("a10", "kept", "1058"), Start("a15", "kept", "1058"), Start("b10", "case", "b5"),
              Start("b15", "after", "b10"), Start("c0", "kept", "0954")]
    groups = start_groups(starts)
    assert [(g.kind, g.cases) for g in groups] == [("kept", ["a10", "a15"]), ("case", ["b10"]), ("after", ["b15"]),
                                                   ("kept", ["c0"])]
    assert groups[0].text == "the solution their failed run started from, kept by job 1058"
    assert groups[3].text == "the solution its failed run started from, kept by job 0954"
    assert summary(starts) == "3 kept · 1 from case · 1 after it runs"
    assert start_text(Start("b15", "after", "b10")) == "b10's, once it has run in this batch"
    assert start_text(Start("x", "scratch", "w")) == "from scratch: w has no solution yet"

from aerosuite.engine.models import Case, Project
from aerosuite.engine.preflight import sweep_problems


def _messages(problems):
    return [(p.severity, p.message) for p in problems]


def test_clean_sweep_has_no_problems(ready_project):
    _, project = ready_project
    assert sweep_problems(project) == []


def test_empty_sweep():
    assert _messages(sweep_problems(Project(name="t"))) == [
        ("error", "No Mach numbers in the sweep"),
        ("error", "The sweep has no cases"),
    ]


def test_duplicates_and_restarts(ready_project):
    _, project = ready_project
    project.cases.append(project.cases[0].model_copy())
    project.cases[1].restart = "custom"
    project.cases[1].restart_ref = None
    messages = [m for _, m in _messages(sweep_problems(project))]
    assert any("Duplicate case names" in m for m in messages)
    assert any("M0p8_a2_b0: 'custom' restart needs a restart file or case folder" in m for m in messages)

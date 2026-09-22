import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.project import PROJECT_FILE, open_project, save_project
from aerosuite.web.session import ProjectSession, parse_int, parse_optional_int, parse_optional_number


def test_apply_saves_valid_changes(ready_project):
    project_dir, _ = ready_project
    session = ProjectSession(project_dir)
    assert session.apply(lambda p: setattr(p.run, "partitions", 64)) is None
    assert session.project.run.partitions == 64
    assert open_project(project_dir).run.partitions == 64
    assert not session.changed_on_disk()


def test_apply_reports_engine_errors_and_saves_nothing(ready_project):
    project_dir, _ = ready_project
    session = ProjectSession(project_dir)
    before = (project_dir / PROJECT_FILE).read_bytes()

    def bad(p):
        p.run.partitions = 99  # a partial change that must not leak
        raise ProjectError("nope")

    assert session.apply(bad) == "nope"
    assert session.project.run.partitions == 1
    assert (project_dir / PROJECT_FILE).read_bytes() == before


def test_apply_reports_validation_errors(ready_project):
    project_dir, _ = ready_project
    session = ProjectSession(project_dir)
    message = session.apply(lambda p: setattr(p.run, "partitions", 0))
    assert message is not None
    assert "run.partitions" in message and "greater than or equal to 1" in message
    assert open_project(project_dir).run.partitions == 1


def test_outside_changes_are_noticed_and_reloaded(ready_project):
    project_dir, _ = ready_project
    session = ProjectSession(project_dir)
    other = open_project(project_dir)
    other.name = "renamed-somewhere-else"
    save_project(project_dir, other)
    assert session.changed_on_disk()
    session.reload()
    assert session.project.name == "renamed-somewhere-else"
    assert not session.changed_on_disk()


def test_failed_reload_is_acknowledged(ready_project):
    project_dir, _ = ready_project
    session = ProjectSession(project_dir)
    (project_dir / PROJECT_FILE).write_text("{broken")
    assert session.changed_on_disk()
    with pytest.raises(ProjectError):
        session.reload()
    assert not session.changed_on_disk()


def test_parsers():
    assert parse_optional_number(" 2.5 ", "CFL") == 2.5
    assert parse_optional_number("", "CFL") is None
    assert parse_optional_number(None, "CFL") is None
    with pytest.raises(ProjectError, match="CFL: 'x' is not a number"):
        parse_optional_number("x", "CFL")
    assert parse_optional_int("64", "Iterations") == 64
    assert parse_optional_int("", "Iterations") is None
    with pytest.raises(ProjectError, match="not a whole number"):
        parse_optional_int("6.5", "Iterations")
    assert parse_int("8", "Partitions") == 8
    with pytest.raises(ProjectError, match="Partitions is required"):
        parse_int(" ", "Partitions")

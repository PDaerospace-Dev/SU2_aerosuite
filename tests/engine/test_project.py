import json

import pytest

from aerosuite.engine import models, project as project_mod
from aerosuite.engine.errors import ProjectError, TemplateError
from aerosuite.engine.project import (
    PROJECT_FILE,
    TEMPLATE_FILE,
    create_project,
    open_project,
    save_project,
    set_mesh,
    set_template,
)


def test_create_then_open(tmp_path):
    folder = tmp_path / "study"
    created = create_project(folder)
    assert created.name == "study"
    assert (folder / PROJECT_FILE).is_file()
    opened = open_project(folder)
    assert opened.name == "study"


def test_create_refuses_existing_project(tmp_path):
    create_project(tmp_path)
    with pytest.raises(ProjectError):
        create_project(tmp_path)


def test_open_missing_or_invalid(tmp_path):
    with pytest.raises(ProjectError, match="No project"):
        open_project(tmp_path)
    (tmp_path / PROJECT_FILE).write_text("{not json")
    with pytest.raises(ProjectError):
        open_project(tmp_path)


def test_save_updates_modified_and_persists(tmp_path):
    project = create_project(tmp_path)
    before = project.modified
    project.sweep.mach = [0.85]
    save_project(tmp_path, project)
    assert project.modified >= before
    assert open_project(tmp_path).sweep.mach == [0.85]
    assert not list(tmp_path.glob("*.tmp"))


def test_newer_schema_is_refused(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = models.SCHEMA_VERSION + 1
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    with pytest.raises(ProjectError, match="newer"):
        open_project(tmp_path)


def test_schema_2_restarts_migrate_to_three_options(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 2
    data["run"]["initial_restart"] = "/data/init.dat"
    data["cases"] = [
        {"name": "a", "mach": 0.8, "alpha": 0, "beta": 0, "restart": "initial"},
        {"name": "b", "mach": 0.8, "alpha": 2, "beta": 0, "restart": "from_case", "restart_ref": "a"},
        {"name": "c", "mach": 0.8, "alpha": 4, "beta": 0, "restart": "from_case", "restart_ref": "a"},
        {"name": "d", "mach": 0.8, "alpha": 6, "beta": 0, "restart": "previous"},
    ]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert project.schema_version == 3
    assert [(c.restart, c.restart_ref) for c in project.cases] == [
        ("custom", "/data/init.dat"),
        ("previous", None),
        ("custom", str((tmp_path / "runs" / "a").resolve())),
        ("previous", None),
    ]
    assert "initial_restart" not in project.run.model_dump()


def test_initial_without_a_file_migrates_to_custom_without_a_path(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 2
    data["cases"] = [{"name": "a", "mach": 0.8, "alpha": 0, "beta": 0, "restart": "initial"}]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    assert [(c.restart, c.restart_ref) for c in open_project(tmp_path).cases] == [("custom", None)]


def test_migrations_run_in_order(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)

    def v3_to_v4(data, directory):
        data["name"] = data["name"] + "-migrated"
        return data

    monkeypatch.setattr(project_mod, "MIGRATIONS", {3: v3_to_v4})
    opened = open_project(tmp_path)
    assert opened.name.endswith("-migrated")
    assert opened.schema_version == 4


def test_set_template_copies_into_project(tmp_path):
    project = create_project(tmp_path / "p")
    source = tmp_path / "master.cfg"
    source.write_text("AOA= 0\n")
    set_template(tmp_path / "p", project, source)
    assert (tmp_path / "p" / TEMPLATE_FILE).read_text() == "AOA= 0\n"
    assert project.template == TEMPLATE_FILE
    with pytest.raises(TemplateError):
        set_template(tmp_path / "p", project, tmp_path / "missing.cfg")


def test_set_mesh_reads_markers(tmp_path):
    project = create_project(tmp_path / "p")
    mesh = tmp_path / "wing.su2"
    mesh.write_text("MARKER_TAG= farfield\nMARKER_TAG= wall\n")
    set_mesh(project, mesh)
    assert project.mesh.path == str(mesh.resolve())
    assert project.mesh.markers == ["farfield", "wall"]
    with pytest.raises(ProjectError):
        set_mesh(project, tmp_path / "missing.su2")


def test_migrate_rejects_invalid_schema_version(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = "abc"
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    with pytest.raises(ProjectError, match="Invalid schema_version"):
        open_project(tmp_path)


def test_migrate_rejects_missing_migration(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(project_mod, "MIGRATIONS", {})
    with pytest.raises(ProjectError, match="No migration"):
        open_project(tmp_path)


def test_migrate_rejects_null_schema_version(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = None
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    with pytest.raises(ProjectError, match="Invalid schema_version"):
        open_project(tmp_path)


def test_migration_error_propagates(tmp_path, monkeypatch):
    from aerosuite.engine.project import migrate

    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 4)

    def broken_migration(data, directory):
        raise KeyError("boom")

    monkeypatch.setattr(project_mod, "MIGRATIONS", {3: broken_migration})
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    with pytest.raises(KeyError, match="boom"):
        migrate(data)


def test_save_project_os_error_is_a_project_error(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    with pytest.raises(ProjectError, match="Cannot save"):
        save_project(blocker / "study", models.Project(name="x"))


def test_set_template_os_error_is_a_template_error(tmp_path):
    source = tmp_path / "master.cfg"
    source.write_text("AOA= 0\n")
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    with pytest.raises(TemplateError, match="Cannot copy"):
        set_template(blocker, models.Project(name="x"), source)


def test_migrate_rejects_non_object():
    with pytest.raises(ProjectError, match="must contain a JSON object"):
        project_mod.migrate([1, 2])


def test_open_project_with_list_json(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("[]")
    with pytest.raises(ProjectError, match="must contain a JSON object"):
        open_project(tmp_path)

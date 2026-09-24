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


def test_migrations_run_in_order(tmp_path, monkeypatch):
    create_project(tmp_path)
    monkeypatch.setattr(models, "SCHEMA_VERSION", 2)

    def v1_to_v2(data):
        data["name"] = data["name"] + "-migrated"
        return data

    monkeypatch.setattr(project_mod, "MIGRATIONS", {1: v1_to_v2})
    opened = open_project(tmp_path)
    assert opened.name.endswith("-migrated")
    assert opened.schema_version == 2


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
    monkeypatch.setattr(models, "SCHEMA_VERSION", 2)
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
    monkeypatch.setattr(models, "SCHEMA_VERSION", 2)

    def broken_migration(data):
        raise KeyError("boom")

    monkeypatch.setattr(project_mod, "MIGRATIONS", {1: broken_migration})
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

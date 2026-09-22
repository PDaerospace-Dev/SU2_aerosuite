import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.project import create_project
from aerosuite.web.files import list_entries, parent_of


def test_listing_order_filter_and_projects(tmp_path):
    (tmp_path / "zeta").mkdir()
    create_project(tmp_path / "Alpha")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "wing.SU2").write_text("")
    (tmp_path / "notes.txt").write_text("")
    (tmp_path / "base.cfg").write_text("")
    everything = list_entries(tmp_path)
    assert [e.name for e in everything] == ["Alpha", "zeta", "base.cfg", "notes.txt", "wing.SU2"]
    assert [e.is_project for e in everything[:2]] == [True, False]
    meshes = list_entries(tmp_path, (".su2",))
    assert [e.name for e in meshes] == ["Alpha", "zeta", "wing.SU2"]


def test_missing_folder(tmp_path):
    with pytest.raises(ProjectError, match="Cannot open"):
        list_entries(tmp_path / "missing")


def test_parent_of(tmp_path):
    assert parent_of(tmp_path / "a") == tmp_path
    root = tmp_path.anchor
    assert parent_of(type(tmp_path)(root)) is None

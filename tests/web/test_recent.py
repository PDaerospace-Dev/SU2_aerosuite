import json

from aerosuite.engine.project import create_project
from aerosuite.web.recent import MAX_RECENT, add_recent, load_recent, store_path


def test_empty_and_order(tmp_path):
    assert load_recent() == []
    a = tmp_path / "a"
    b = tmp_path / "b"
    create_project(a)
    create_project(b)
    add_recent(a)
    add_recent(b)
    assert load_recent() == [b.resolve(), a.resolve()]
    add_recent(a)
    assert load_recent() == [a.resolve(), b.resolve()]


def test_missing_folders_dropped_and_capped(tmp_path):
    folders = []
    for i in range(MAX_RECENT + 3):
        folder = tmp_path / f"p{i}"
        create_project(folder)
        add_recent(folder)
        folders.append(folder)
    assert len(load_recent()) == MAX_RECENT
    (folders[-1] / "project.json").unlink()
    assert folders[-1].resolve() not in load_recent()


def test_corrupt_store_is_ignored(tmp_path):
    store_path().parent.mkdir(parents=True, exist_ok=True)
    store_path().write_text("{not a list")
    assert load_recent() == []
    store_path().write_text(json.dumps([1, None, str(tmp_path / "nowhere")]))
    assert load_recent() == []

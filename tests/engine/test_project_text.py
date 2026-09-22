import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.project import (
    PROJECT_FILE,
    create_project,
    open_project,
    parse_project,
    read_project_text,
)


def test_read_and_parse_round_trip(tmp_path):
    created = create_project(tmp_path, "demo")
    text = read_project_text(tmp_path)
    assert parse_project(text) == created


def test_read_project_text_missing(tmp_path):
    with pytest.raises(ProjectError, match="No project"):
        read_project_text(tmp_path)


@pytest.mark.parametrize(
    "text, match",
    [
        ("{not json", "not valid JSON"),
        ("[]", "JSON object"),
        ('{"name": "x", "run": {"partitions": 0}}', "not a valid project"),
    ],
)
def test_parse_project_errors(text, match):
    with pytest.raises(ProjectError, match=match):
        parse_project(text)


def test_project_file_with_a_utf8_bom_opens(tmp_path):
    created = create_project(tmp_path, "demo")
    path = tmp_path / PROJECT_FILE
    path.write_bytes(b"\xef\xbb\xbf" +path.read_bytes())
    assert open_project(tmp_path) == created


def test_project_file_that_is_not_utf8(tmp_path):
    (tmp_path / PROJECT_FILE).write_bytes(b"\xff\xfe{}")
    with pytest.raises(ProjectError, match="is not UTF-8 text"):
        read_project_text(tmp_path)

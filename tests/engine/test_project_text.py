import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.project import create_project, parse_project, read_project_text


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

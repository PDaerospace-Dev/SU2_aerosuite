from aerosuite.web.guide import MISSING, README, app_version, web_ui_guide


def test_the_guide_is_the_readmes_web_ui_section(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n## Web UI\nStart it.\n### Sub\nMore.\n## Command line\nNot this.\n",
                      encoding="utf-8")
    assert web_ui_guide(readme) == "Start it.\n### Sub\nMore."


def test_a_missing_readme_or_section_says_so(tmp_path):
    assert web_ui_guide(tmp_path / "nope.md") == MISSING
    other = tmp_path / "README.md"
    other.write_text("# Title\n## Other\n", encoding="utf-8")
    assert web_ui_guide(other) == MISSING


def test_the_repository_readme_has_the_section():
    assert "Pages:" in web_ui_guide(README)


def test_version_is_a_string():
    assert isinstance(app_version(), str) and app_version()

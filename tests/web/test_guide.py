from aerosuite.web.guide import (MISSING, README, SECTION_OF_PAGE, app_version, guide_sections, section_for,
                                 web_ui_guide)


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


def test_the_guide_is_cut_into_its_sections(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("## Web UI\nLead.\n### One\nFirst.\n```\n### not a heading\n```\n### Two\nSecond.\n",
                      encoding="utf-8")
    assert guide_sections(readme) == [("One", "Lead.\nFirst.\n```\n### not a heading\n```"), ("Two", "Second.")]


def test_a_guide_without_sections_is_one(tmp_path):
    assert guide_sections(tmp_path / "nope.md") == [("Web UI guide", MISSING)]


def test_a_page_opens_the_guide_on_its_section():
    titles = ["Getting started", "Setup", "Run", "Settings"]
    assert section_for("run", titles) == 2
    assert section_for("settings", titles) == 3
    assert section_for("nowhere", titles) == 0


def test_the_repository_readme_has_a_section_for_every_page():
    titles = [title for title, _ in guide_sections(README)]
    assert titles[0] == "Getting started"
    for page, wanted in SECTION_OF_PAGE.items():
        assert titles[section_for(page, titles)].startswith(wanted), page


def test_version_is_a_string():
    assert isinstance(app_version(), str) and app_version()

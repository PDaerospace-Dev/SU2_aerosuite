from aerosuite.web.guide import (GUIDE, MISSING, SECTION_OF_PAGE, app_version, guide_sections, section_for,
                                 web_ui_guide)


def test_the_guide_is_the_file_without_its_title(tmp_path):
    guide = tmp_path / "WEB_UI.md"
    guide.write_text("# Title\nStart it.\n### Sub\nMore.\n", encoding="utf-8")
    assert web_ui_guide(guide) == "Start it.\n### Sub\nMore."


def test_a_missing_or_empty_guide_says_so(tmp_path):
    assert web_ui_guide(tmp_path / "nope.md") == MISSING
    empty = tmp_path / "WEB_UI.md"
    empty.write_text("# Title\n", encoding="utf-8")
    assert web_ui_guide(empty) == MISSING


def test_the_guide_is_cut_into_its_sections(tmp_path):
    readme = tmp_path / "WEB_UI.md"
    readme.write_text("Lead.\n### One\nFirst.\n```\n### not a heading\n```\n### Two\nSecond.\n",
                      encoding="utf-8")
    assert guide_sections(readme) == [("One", "Lead.\nFirst.\n```\n### not a heading\n```"), ("Two", "Second.")]


def test_a_guide_without_sections_is_one(tmp_path):
    assert guide_sections(tmp_path / "nope.md") == [("Web UI guide", MISSING)]


def test_a_page_opens_the_guide_on_its_section():
    titles = ["Getting started", "Setup", "Run", "Settings"]
    assert section_for("run", titles) == 2
    assert section_for("settings", titles) == 3
    assert section_for("nowhere", titles) == 0


def test_the_repository_guide_has_a_section_for_every_page():
    titles = [title for title, _ in guide_sections(GUIDE)]
    assert titles[0] == "Getting started"
    for page, wanted in SECTION_OF_PAGE.items():
        assert titles[section_for(page, titles)].startswith(wanted), page


def test_version_is_a_string():
    assert isinstance(app_version(), str) and app_version()

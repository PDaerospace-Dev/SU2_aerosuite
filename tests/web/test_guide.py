from aerosuite.web.guide import (GUIDE, MISSING, SECTION_OF_PAGE, app_version, guide_groups, guide_sections,
                                 search_sections, section_for, web_ui_guide)


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


def test_group_headings_name_the_sections_under_them(tmp_path):
    readme = tmp_path / "WEB_UI.md"
    readme.write_text("Lead.\n## Start\n### One\nFirst.\n```\n## not a group\n```\n## Tools\n### Two\nSecond.\n"
                      "### Three\nThird.\n", encoding="utf-8")
    assert [title for title, _ in guide_sections(readme)] == ["One", "Two", "Three"]
    assert guide_sections(readme)[0][1] == "Lead.\nFirst.\n```\n## not a group\n```"
    assert guide_groups(readme) == [("Start", 0), ("Tools", 1)]


def test_searching_finds_the_sections_with_every_word():
    sections = [("Run", "Submit the cases."), ("Monitor", "Residuals of a running case."),
                ("Command line", "aerosuite run")]
    assert search_sections(sections, "") == [0, 1, 2]
    assert search_sections(sections, "RUN") == [0, 1, 2]  # titles too, any case
    assert search_sections(sections, "case residuals") == [1]
    assert search_sections(sections, "nothing") == []


def test_a_guide_without_sections_is_one(tmp_path):
    assert guide_sections(tmp_path / "nope.md") == [("Web UI guide", MISSING)]


def test_a_page_opens_the_guide_on_its_section():
    titles = ["Getting started", "Setup", "Run", "Settings"]
    assert section_for("run", titles) == 2
    assert section_for("settings", titles) == 3
    assert section_for("nowhere", titles) == 0


def test_the_repository_guide_has_a_section_for_every_page():
    titles = [title for title, _ in guide_sections(GUIDE)]
    assert titles[0] == "Getting started" and "Command line" in titles
    assert [name for name, _ in guide_groups(GUIDE)][0] == "Start here"
    for page, wanted in SECTION_OF_PAGE.items():
        assert titles[section_for(page, titles)].startswith(wanted), page


def test_version_is_a_string():
    assert isinstance(app_version(), str) and app_version()

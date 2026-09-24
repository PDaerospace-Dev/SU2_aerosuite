from nicegui.testing import User


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


async def test_search_and_insert(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("marker_euler")
    await user.should_see(marker="ref-result-MARKER_EULER")
    user.find(marker="ref-insert-MARKER_EULER").click()
    assert _element(user, "t-inserted").text == "MARKER_EULER"
    await user.should_see("Inserted MARKER_EULER")
    await user.should_see(marker="ref-in-config-MARKER_EULER")


async def test_options_already_in_the_config_are_marked(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("solver")
    await user.should_see(marker="ref-in-config-SOLVER")
    await user.should_not_see(marker="ref-insert-SOLVER")


async def test_no_results(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-search").type("zzzzqqq")
    await user.should_see(marker="ref-no-results")


async def test_find_in_the_full_file(user: User):
    await user.open("/_test/reference")
    user.find(marker="ref-find").type("MARKER_EULER")
    user.find(marker="ref-find-next").click()
    status = _element(user, "ref-find-status").text
    assert status.startswith("Match 1 of ")
    assert "MARKER_EULER" in _element(user, "ref-window").content
    user.find(marker="ref-find-next").click()
    assert _element(user, "ref-find-status").text.startswith("Match 2 of ")
    user.find(marker="ref-find").clear().type("zzzzqqq")
    user.find(marker="ref-find-next").click()
    assert _element(user, "ref-find-status").text == "No match"


async def test_load_another_reference(user: User, tmp_path, eventually):
    (tmp_path / "old_su2.cfg").write_text("% Old option\nOLD_THING= 1\n")
    (tmp_path / "empty.cfg").write_text("% nothing\n")
    await user.open("/_test/reference")
    user.find(marker="ref-load").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-old_su2.cfg").click()
    await eventually(lambda: _element(user, "ref-source").text == "old_su2.cfg")
    user.find(marker="ref-search").type("old")
    await user.should_see(marker="ref-result-OLD_THING")

    user.find(marker="ref-load").click()
    await user.should_see(marker="picker-location")
    user.find(marker="picker-entry-empty.cfg").click()
    await eventually(lambda: "no SU2 options" in _element(user, "ref-error").text)
    assert _element(user, "ref-source").text == "old_su2.cfg"

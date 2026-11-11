"""A tag written in a note without its #: found, and written with it."""
import pytest

from aerosuite.engine import tags
from aerosuite.engine.tags import bare_tags, hashed, likely_tags
from aerosuite.engine.tracker_links import Link, save_link

KNOWN = ["2nd_order", "wing-v2", "1st_order"]


@pytest.mark.parametrize("note, found, fixed", [
    ("2nd_order", ["2nd_order"], "#2nd_order"),
    ("2nd order run on the fine mesh", ["2nd_order"], "#2nd_order run on the fine mesh"),
    ("Wing V2 and 1st-order", ["wing-v2", "1st_order"], "#wing-v2 and #1st_order"),
    ("check #wing-v2x 2nd_order.", ["2nd_order"], "check #wing-v2x #2nd_order."),
    ("#2nd_order", [], "#2nd_order"),
    ("again 2nd_order, #2nd_order", [], "again 2nd_order, #2nd_order"),  # it has the tag already
    ("x2nd_order and 2nd_orders", [], "x2nd_order and 2nd_orders"),  # other words
    ("", [], ""),
])
def test_a_known_tag_without_its_hash_is_found_and_fixed(note, found, fixed):
    assert bare_tags(note, KNOWN) == found
    assert hashed(note, found) == fixed


def test_the_tags_worth_pointing_out(tmp_path):
    """What a run-matrix sheet filters on, and tags in use that are not an everyday word."""
    tags.load_index()
    for note in ("#fine #cfl-low", "#mesh3"):
        tags.note_changed(tmp_path, "", note)
    save_link(Link(workbook="m.xlsx", sheet="S", tags=["Coarse"], skip_tags=["#old"]))
    assert likely_tags(tmp_path) == ["2nd_order", "coarse", "old", "cfl-low", "mesh3"]  # not "fine"

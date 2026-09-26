from aerosuite.web import theme
from aerosuite.web.ui_kit import PILL_TONES


def test_every_pill_tone_has_css():
    css = theme.component_css()
    for tone in set(PILL_TONES.values()):
        assert tone in theme.PILL_COLORS
        assert f".as-pill-{tone} " in css


def test_the_tokens_are_the_specs():
    assert theme.PAGE_BG == "#f4f5f7" and theme.CARD_BORDER == "#e3e5e8" and theme.TOPBAR == "#0f1b2d"
    assert theme.PILL_COLORS["failed"][:2] == ("#ffebe9", "#a40e26")
    assert theme.PILL_COLORS["cancelled"] == ("#ffffff", "#57606a", "#d0d7de")


def test_the_sidebar_scripts_survive_blocked_storage():
    # localStorage throws in some private windows: both snippets must swallow that.
    for script in (theme.RESTORE_SIDEBAR, theme.TOGGLE_SIDEBAR):
        assert "try" in script and "catch" in script and theme.SIDEBAR_KEY in script
    assert "as-mini" in theme.RESTORE_SIDEBAR and "as-mini" in theme.TOGGLE_SIDEBAR


def test_recent_rows_fill_their_card_so_long_paths_truncate():
    # A card is a flex column that sizes children to their content: without width 100% a long path
    # widens the row past the card and pushes its tag and pill out of view.
    css = theme.component_css()
    row = css[css.index(".as-recent-row {"):]
    assert "width: 100%" in row[:row.index("}")]
    assert ".as-recent-row > .as-tag, .as-recent-row > .as-pill { flex: none; }" in css


def test_truncated_text_is_capped_at_its_parents_width():
    # In a flex column a label is as wide as its text, so overflow: hidden alone clips nothing.
    css = theme.component_css()
    rule = css[css.index(".as-truncate {"):]
    assert "max-width: 100%" in rule[:rule.index("}")]

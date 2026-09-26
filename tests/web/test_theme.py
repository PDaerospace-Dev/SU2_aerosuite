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

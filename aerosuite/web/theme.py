"""The web UI's look in one place: colour tokens, Quasar's brand colours and the component CSS.

Pages never style widgets themselves: aerosuite.web.ui_kit puts these `as-*` classes on them.
"""
from nicegui import ui

PAGE_BG = "#f4f5f7"
CARD_BORDER = "#e3e5e8"
TEXT = "#1f2328"
MUTED = "#6a737d"
HAIRLINE = "#eef0f2"
ACCENT = "#2f6fe4"
ACCENT_TINT = "#eef2ff"
ACCENT_TEXT = "#2f3fbf"
TOPBAR = "#0f1b2d"
TOPBAR_CONTROL = "#16263d"
TOPBAR_BORDER = "#2a3a52"
TOPBAR_MUTED = "#9fb0c8"
RUNNING_DOT = "#58a6ff"
FONT = '"Segoe UI", system-ui, -apple-system, Ubuntu, sans-serif'
MONO = 'Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace'

# pill tone -> (background, text, border)
PILL_COLORS = {
    "done": ("#dafbe1", "#116329", "#dafbe1"),
    "running": ("#ddf4ff", "#0550ae", "#ddf4ff"),
    "failed": ("#ffebe9", "#a40e26", "#ffebe9"),
    "unconverged": ("#fff8c5", "#7a5200", "#fff8c5"),
    "pending": ("#eef0f2", "#57606a", "#eef0f2"),
    "cancelled": ("#ffffff", "#57606a", "#d0d7de"),
}
# sidebar step badge -> dot colour ("todo" is a grey ring, drawn in BASE_CSS)
DOT_COLORS = {"done": "#1a7f37", "attention": "#bf8700", "running": RUNNING_DOT, "plain": "#8c959f",
              "later": "#d0d7de"}
# banner kind -> (background, border, text)
BANNER_COLORS = {
    "info": ("#ddf4ff", "#b6e3ff", "#0550ae"),
    "warning": ("#fff8c5", "#eed888", "#7a5200"),
    "error": ("#ffebe9", "#ffd7d5", "#a40e26"),
    "success": ("#dafbe1", "#aceebb", "#116329"),
}
# Monitor chart lines and their checkbox swatches, by column position
SERIES_COLORS = ["#2f6fe4", "#8250df", "#1a7f37", "#bf8700", "#cf222e", "#0a7ea4", "#e16f24", "#6e7781"]
# the project switcher's initials badge, picked by the project name
BADGE_COLORS = ["#8250df", "#2f6fe4", "#1a7f37", "#bf3989", "#0a7ea4", "#bc4c00"]

SIDEBAR_KEY = "aerosuite-sidebar"
# Runs in <head> before the page is drawn, so a collapsed sidebar never flashes open first.
RESTORE_SIDEBAR = ("<script>try { if (localStorage.getItem('%s') === 'mini') "
                   "document.documentElement.classList.add('as-mini'); } catch (e) {}</script>" % SIDEBAR_KEY)
TOGGLE_SIDEBAR = ("const mini = document.documentElement.classList.toggle('as-mini');"
                  "try { localStorage.setItem('%s', mini ? 'mini' : 'full'); } catch (e) {}" % SIDEBAR_KEY)

BASE_CSS = """
body { background: var(--as-page); color: var(--as-text); font-family: var(--as-font); font-size: 13px; }
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.as-mono { font-family: var(--as-mono); font-size: 12px; }
.as-muted, .as-hint { color: var(--as-muted); font-size: 12px; }
.as-hint-warning { color: #7a5200; }
.as-error-text { color: #a40e26; font-size: 12px; }
.as-strong { font-weight: 500; }
.as-label { font-size: 12px; color: var(--as-muted); }
.as-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 100%; }

.as-topbar { position: sticky; top: 0; z-index: 2000; height: 52px; padding: 0 16px; gap: 14px;
  background: var(--as-topbar); color: #fff; flex-wrap: nowrap; align-items: center; }
.as-brand { width: 194px; gap: 10px; color: #fff; text-decoration: none; align-items: center; flex-wrap: nowrap; }
.as-logo-mark { width: 28px; height: 28px; border-radius: 7px; background: var(--as-accent); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; }
.as-logo-text { font-size: 16px; font-weight: 600; color: #fff; }
.as-topbar-control { background: var(--as-topbar-control); border: 1px solid var(--as-topbar-border);
  border-radius: 8px; color: #fff; }
.as-topbar-muted { color: var(--as-topbar-muted); }
.as-topbar-icon { width: 30px; height: 30px; min-height: 30px; padding: 0; border: 1px solid var(--as-topbar-border);
  border-radius: 7px; color: var(--as-topbar-muted); }
.as-topbar-icon.as-round { border-radius: 50%; }
html.as-mini .as-when-full, html:not(.as-mini) .as-when-mini { display: none; }
.as-job { padding: 6px 12px; gap: 10px; cursor: pointer; align-items: center; flex-wrap: nowrap; }
.as-job-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--as-running);
  box-shadow: 0 0 0 3px rgba(88, 166, 255, .25); }
.as-job-bar { width: 90px; height: 5px; border-radius: 3px; background: var(--as-topbar-border); overflow: hidden; }
.as-job-fill { height: 100%; background: var(--as-running); }
.as-switcher { padding: 4px 10px 4px 4px; gap: 8px; cursor: pointer; align-items: center; flex-wrap: nowrap;
  max-width: 22rem; }
.as-initials { width: 26px; height: 26px; border-radius: 6px; display: inline-flex; align-items: center;
  justify-content: center; font-weight: 600; color: #fff; flex: none; }
.as-switcher-name { font-size: 13px; line-height: 1.15; max-width: 16rem; }
.as-switcher-kind { font-size: 11px; line-height: 1.15; }

.as-body { min-height: calc(100vh - 52px); flex-wrap: nowrap; align-items: stretch; gap: 0; }
.as-sidebar { width: 210px; min-width: 210px; background: #fff; border-right: 1px solid var(--as-border);
  padding: 14px 12px; gap: 2px; transition: width .15s, min-width .15s; }
html.as-mini .as-sidebar { width: 64px; min-width: 64px; }
html.as-mini .as-step-name { display: none; }
html:not(.as-mini) .as-step-tip { display: none !important; }
.as-step { position: relative; gap: 12px; padding: 8px 10px; border-radius: 8px; color: #57606a;
  text-decoration: none; align-items: center; flex-wrap: nowrap; }
a.as-step:hover { background: #f6f8fa; }
.as-step-current, a.as-step-current:hover { background: var(--as-accent-tint); color: var(--as-accent-text);
  font-weight: 600; }
.as-step-later { color: #b0b7c0; cursor: default; }
.as-step .as-dot { position: absolute; top: 6px; left: 26px; border: 1.5px solid #fff; box-sizing: content-box; }
.as-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
.as-dot-todo { background: #fff; box-shadow: inset 0 0 0 1.5px #8c959f; }
.as-main { flex: 1; min-width: 0; padding: 14px 28px 28px; gap: 14px; }
.as-crumbs { gap: 10px; min-height: 36px; align-items: center; flex-wrap: nowrap; }
.as-crumb-link { color: var(--as-muted); text-decoration: none; }
.as-crumb-link:hover { color: var(--as-accent); }
.as-crumb-project { max-width: 24rem; }
.as-crumb-sep { color: #c4c9cf; }
.as-crumb-current { font-weight: 600; }
.as-content { gap: 14px; }
.as-page { padding: 14px 28px 28px; gap: 14px; }

.as-card { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 16px 18px;
  gap: 12px; box-shadow: none; }
.as-card-flush { padding: 0; gap: 0; overflow: hidden; }
.as-card-head { gap: 8px; align-items: center; flex-wrap: nowrap; }
.as-card-flush > .as-card-head { padding: 12px 14px; }
.as-card-title { font-size: 14px; font-weight: 600; }
.as-card-subtitle { font-size: 12px; color: var(--as-muted); }
.as-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-tile { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 16px; gap: 0; }
.as-tile-label { font-size: 12px; color: var(--as-muted); }
.as-tile-value { font-size: 22px; font-weight: 600; }
.as-tile-danger .as-tile-value { color: #a40e26; }
.as-pill { display: inline-block; padding: 1px 10px; border: 1px solid; border-radius: 999px; font-size: 12px;
  line-height: 18px; white-space: nowrap; text-transform: lowercase; }
.as-pill::first-letter { text-transform: uppercase; }
.as-tag { display: inline-block; padding: 1px 8px; border-radius: 6px; background: var(--as-hairline);
  color: #57606a; font-size: 12px; white-space: nowrap; }
.as-banner { width: 100%; padding: 8px 12px; gap: 8px; border: 1px solid; border-radius: 8px;
  align-items: flex-start; flex-wrap: nowrap; }
.as-banner .q-icon { font-size: 18px; }
.as-ok-line { gap: 8px; align-items: center; color: #116329; flex-wrap: nowrap; }
.as-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }

.as-table { display: grid; gap: 0; width: 100%; align-items: stretch; }
.as-th { padding: 9px 14px; font-size: 12px; font-weight: 500; color: var(--as-muted); }
.as-td { padding: 8px 14px; border-top: 1px solid var(--as-hairline); min-height: 40px; display: flex;
  align-items: center; flex-wrap: nowrap; gap: 8px; }
.as-td-failure { padding: 0 14px 8px; }
.as-failure { background: #fff5f5; border: 1px solid #ffd7d5; border-radius: 6px; padding: 7px 10px;
  font-family: var(--as-mono); font-size: 12px; color: #a40e26; white-space: pre-wrap;
  max-height: 7.5em; overflow: auto; }
.as-dup { color: #a40e26; font-weight: 600; }
.as-recent-row { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: inherit;
  text-decoration: none; border-top: 1px solid var(--as-hairline); width: 100%; box-sizing: border-box; }
.as-recent-row > .as-tag, .as-recent-row > .as-pill { flex: none; }
.as-recent-row:hover { background: #f6f8fa; }

.as-btn { text-transform: none; border-radius: 8px; font-weight: 500; min-height: 32px; padding: 0 14px; }
.as-btn-primary { background: #1f2328; color: #fff; }
.as-btn-secondary { background: #fff; color: var(--as-text); border: 1px solid var(--as-border); }
.as-btn-danger { background: #fff; color: #a40e26; border: 1px solid #ffd7d5; }
.as-btn-flat { background: transparent; color: var(--as-text); }
.as-chip { background: #fff; color: var(--as-text); border: 1px solid var(--as-border); border-radius: 6px;
  min-height: 26px; padding: 0 10px; font-weight: 400; text-transform: none; }
.as-chip:hover { background: var(--as-accent-tint); color: var(--as-accent-text); }

.as-field .q-field__control { border-radius: 8px; }
.as-field-mono input, .as-field-mono textarea { font-family: var(--as-mono); font-size: 12px; }
.as-readonly { border: 1px solid var(--as-border); border-radius: 8px; padding: 8px 10px; background: #fafbfc;
  min-height: 36px; word-break: break-all; }
.as-choice { display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-choice > div { margin: 0 !important; }
.as-choice .q-radio { width: 100%; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 12px; }
.as-choice .q-radio[aria-checked="true"] { border: 2px solid var(--as-accent); padding: 9px 11px; }
.as-choice-tile { border: 1px solid var(--as-border); border-radius: 10px; padding: 12px; background: #fff;
  cursor: pointer; gap: 2px; }
.as-choice-selected { border: 2px solid var(--as-accent); padding: 11px; }

.as-grid-2, .as-grid-3, .as-grid-form, .as-columns, .as-monitor { display: grid; gap: 14px; width: 100%;
  align-items: start; }
.as-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.as-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.as-grid-form { grid-template-columns: minmax(12rem, auto) minmax(0, 1fr); gap: 8px 14px; align-items: center; }
.as-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.as-columns-projects { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); }
.as-monitor { grid-template-columns: 250px minmax(0, 1fr); gap: 16px; }
@media (max-width: 900px) {
  .as-grid-2, .as-grid-3, .as-columns, .as-columns-projects, .as-monitor, .as-tiles { grid-template-columns: 1fr; }
}

.q-dialog .q-card { border-radius: 10px; box-shadow: 0 8px 24px rgba(31, 35, 40, .14); padding: 18px; gap: 12px; }
.as-dialog-title { font-size: 14px; font-weight: 600; }
.q-menu { border-radius: 8px; }
"""


def _variables() -> str:
    tokens = {"page": PAGE_BG, "border": CARD_BORDER, "text": TEXT, "muted": MUTED, "hairline": HAIRLINE,
              "accent": ACCENT, "accent-tint": ACCENT_TINT, "accent-text": ACCENT_TEXT, "topbar": TOPBAR,
              "topbar-control": TOPBAR_CONTROL, "topbar-border": TOPBAR_BORDER, "topbar-muted": TOPBAR_MUTED,
              "running": RUNNING_DOT, "font": FONT, "mono": MONO}
    return ":root { " + " ".join(f"--as-{name}: {value};" for name, value in tokens.items()) + " }\n"


def component_css() -> str:
    """Every rule the kit's classes need: tokens as CSS variables, the base rules, then generated colours."""
    pills = "".join(f".as-pill-{tone} {{ background: {bg}; color: {fg}; border-color: {border}; }}\n"
                    for tone, (bg, fg, border) in PILL_COLORS.items())
    dots = "".join(f".as-dot-{state} {{ background: {color}; }}\n" for state, color in DOT_COLORS.items())
    banners = "".join(f".as-banner-{kind} {{ background: {bg}; border-color: {border}; color: {fg}; }}\n"
                      for kind, (bg, border, fg) in BANNER_COLORS.items())
    return _variables() + BASE_CSS + pills + dots + banners


def apply_theme() -> None:
    """Colours, fonts and component CSS for the current page; call once per page before building it."""
    ui.colors(primary=ACCENT, secondary="#57606a", accent=ACCENT, positive="#1a7f37", negative="#a40e26",
              warning="#bf8700", info="#0550ae")
    ui.add_head_html(RESTORE_SIDEBAR)
    ui.add_css(component_css())

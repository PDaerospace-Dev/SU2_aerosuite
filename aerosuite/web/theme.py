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
.as-job-text { max-width: 14rem; }
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
.as-conditions { background: #fff; border: 1px solid var(--as-border); border-left: 4px solid var(--as-accent);
  border-radius: 10px; padding: 8px 16px; gap: 0; row-gap: 6px; }
.as-condition { padding-right: 18px; margin-right: 18px; border-right: 1px solid var(--as-hairline); }
.as-condition-label { font-size: 11px; color: var(--as-muted); }
.as-condition-value { font-size: 15px; font-weight: 600; white-space: nowrap; }
.as-conditions .as-pill { margin-left: 6px; }
.as-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-tile { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 16px; gap: 0; }
.as-tile-label { font-size: 12px; color: var(--as-muted); }
.as-tile-value { font-size: 22px; font-weight: 600; }
.as-tile-danger .as-tile-value { color: #a40e26; }
.as-pill { display: inline-block; padding: 1px 10px; border: 1px solid; border-radius: 999px; font-size: 12px;
  line-height: 18px; white-space: nowrap; text-transform: lowercase; }
.as-pill::first-letter { text-transform: uppercase; }
.as-pill-toggle { cursor: pointer; }
.as-pill-toggle:hover { filter: brightness(.95); text-decoration: underline; }
.as-pill-chevron { cursor: pointer; color: var(--as-muted); font-size: 18px; margin-left: -4px; }
.as-tag { display: inline-block; padding: 1px 8px; border-radius: 6px; background: var(--as-hairline);
  color: #57606a; font-size: 12px; white-space: nowrap; }
.as-banner { width: 100%; padding: 8px 12px; gap: 8px; border: 1px solid; border-radius: 8px;
  align-items: flex-start; flex-wrap: nowrap; }
.as-banner .q-icon { font-size: 18px; }
.as-warn-group { background: #fff8c5; border: 1px solid #eed888; border-radius: 8px; color: #7a5200; }
.as-warn-group .q-item { min-height: 36px; padding: 4px 12px; font-weight: 500; }
.as-warn-group .q-item__section--avatar { min-width: 28px; color: #bf8700; }
.as-warn-group .q-expansion-item__content { padding: 0 12px 8px 40px; }
.as-warn-line { padding: 4px 0; border-top: 1px solid #f1e3a3; width: 100%; }
/* The template editor: line numbers, no wrapping (line N on screen is line N in the file) */
.as-code { border: 1px solid var(--as-border); border-radius: 8px; overflow: hidden; font-size: 12px; }
.as-code .cm-editor { height: 100%; }
.as-code .cm-scroller { font-family: var(--as-mono); }
.as-code .cm-gutters { background: #f6f8fa; border-right: 1px solid var(--as-hairline); color: #8c959f; }
.as-code .cm-activeLine, .as-code .cm-activeLineGutter { background: var(--as-accent-tint); }

/* Setup: the chosen mesh / template (green), one gone from disk (amber), none yet (grey dashes) */
.as-selected, .as-selected-missing, .as-selected-empty { padding: 10px 12px; gap: 10px; border: 1px solid;
  border-radius: 8px; }
.as-selected { background: #f3fcf5; border-color: #aceebb; }
.as-selected-missing { background: #fffbe6; border-color: #eed888; }
.as-selected-empty { background: transparent; border-style: dashed; border-color: #d0d7de; }
.as-selected-icon { font-size: 20px; margin-top: 1px; color: #8c959f; }
.as-selected .as-selected-icon { color: #1a7f37; }
.as-selected-missing .as-selected-icon { color: #bf8700; }

/* A folded section inside a card (Setup's Advanced run settings) */
.as-expansion { border: 1px solid var(--as-hairline); border-radius: 8px; }
.as-expansion .q-item { min-height: 36px; padding: 4px 12px; font-size: 13px; color: var(--as-muted); }
.as-expansion .q-expansion-item__content { padding: 4px 12px 12px; }
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
.as-chip-on { background: var(--as-accent-tint); color: var(--as-accent-text); border-color: #c7d2fe; }
.as-section { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; }
.as-section > .q-expansion-item__container > .q-item { padding: 12px 18px; min-height: 50px; }
.as-section > .q-expansion-item__container > .q-expansion-item__content { padding: 0 18px 16px; }
.as-section-flush > .q-expansion-item__container > .q-expansion-item__content { padding: 0; }
.as-pick-group { border: 1px solid var(--as-hairline); border-radius: 8px; background: #fff; }
.as-pick-group .q-item { min-height: 40px; padding: 4px 12px; }
.as-pick-group .q-expansion-item__content { padding: 2px 12px 10px; }
.as-pick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; width: 100%; }
.as-link { cursor: pointer; text-decoration: underline; }
.as-design-chip-error { border-color: #ffd7d5; color: #a40e26; }
.as-table-scroll { overflow-x: auto; }
.as-sticky { position: sticky; left: 0; background: #fff; z-index: 1; }
.as-work { display: grid; grid-template-columns: 68px minmax(0, 1fr); gap: 12px; align-items: start;
  position: relative; }
.as-work-main { min-width: 0; width: 100%; }
.as-icon-strip { background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 6px;
  position: sticky; top: 12px; }
.as-strip-item { position: relative; width: 100%; padding: 8px 2px 6px; border-radius: 7px; cursor: pointer;
  color: var(--as-muted); }
.as-strip-item:hover { background: var(--as-hairline); }
.as-strip-on, .as-strip-on:hover { background: var(--as-accent-tint); color: var(--as-accent-text); }
.as-strip-icon { font-size: 20px; }
.as-strip-label { font-size: 10.5px; }
.as-strip-count { position: absolute; top: 3px; right: 5px; min-width: 16px; height: 16px; padding: 0 4px;
  border-radius: 8px; background: var(--as-accent); color: #fff; font-size: 10px; line-height: 16px;
  text-align: center; }
.as-panel { position: absolute; left: 80px; top: 0; width: 320px; max-width: calc(100% - 80px); z-index: 5;
  background: #fff; border: 1px solid var(--as-border); border-radius: 10px; padding: 14px 16px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .16); }
.as-design-chip { border: 1px solid var(--as-border); border-radius: 999px; padding: 3px 10px; background: #fff; }
.as-chip:hover { background: var(--as-accent-tint); color: var(--as-accent-text); }

.as-field .q-field__control { border-radius: 8px; }
.as-field-mono input, .as-field-mono textarea { font-family: var(--as-mono); font-size: 12px; }
.as-field-readonly .q-field__control { background: #f6f8fa; }
.as-strip-result { gap: 32px; }
.as-readonly { border: 1px solid var(--as-border); border-radius: 8px; padding: 8px 10px; background: #fafbfc;
  min-height: 36px; word-break: break-all; }
/* Aircraft / Config: the right-hand Preview | SU2 reference card stays in view while the form scrolls,
   16px below the 52px sticky top bar */
.as-side { position: sticky; top: 68px; max-height: calc(100vh - 84px); overflow-y: auto; padding-top: 6px; }
.as-tabs { border-bottom: 1px solid var(--as-hairline); color: var(--as-muted); }
.as-side .as-tabs { position: sticky; top: -6px; background: #fff; z-index: 1; }
.as-page-tabs { border-bottom-color: var(--as-border); }

/* The log panel: a dark console along the bottom of a project page, opened by the Log button */
.as-log-button { position: fixed; right: 16px; bottom: 16px; z-index: 1400; border-radius: 999px;
  background: #0f1b2d; color: #e6edf3; box-shadow: 0 4px 12px rgba(31, 35, 40, .25); padding: 0 14px; }
.as-log { position: fixed; left: 0; right: 0; bottom: 0; height: 42vh; min-height: 220px; z-index: 1500;
  background: #0d1117; color: #c9d1d9; border-top: 1px solid #2a3a52; gap: 0 !important;
  box-shadow: 0 -8px 24px rgba(0, 0, 0, .25); }
.as-log-head { height: 40px; padding: 0 8px 0 14px; gap: 10px; align-items: center; background: #0f1b2d;
  border-bottom: 1px solid #2a3a52; }
.as-log-title { font-weight: 600; color: #e6edf3; }
.as-log-select { min-width: 13rem; font-family: var(--as-mono); font-size: 12px; }
.as-log-state { font-size: 12px; color: #9fb0c8; }
.as-log-close { color: #9fb0c8; }
.as-log-body { flex: 1 1 auto; width: 100%; height: calc(100% - 40px); }
.as-log-open { padding-bottom: 44vh; }
.as-log-text { white-space: pre; font-family: var(--as-mono); font-size: 12px; line-height: 1.45;
  padding: 10px 14px 16px; }
.as-tabs .q-tab { min-height: 38px; padding: 0 12px; font-weight: 500; }
.as-tabs .q-tab--active { color: var(--as-text); }
.as-tabs .q-tab__indicator { background: var(--as-accent); height: 2px; }
.as-tab-panels, .as-tab-panels .q-tab-panel { padding: 0; background: transparent; }
.as-tab-panels .q-tab-panel { padding-top: 12px; display: flex; flex-direction: column; }

/* A compact two-way switch in a page's action bar (Config's Sweep | Single case) */
.as-toggle { border: 1px solid var(--as-border); border-radius: 8px; overflow: hidden; background: #fff; }
.as-toggle .q-btn { min-height: 30px; padding: 0 12px; font-weight: 500; }

.as-choice { display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; width: 100%; }
.as-choice > div { margin: 0 !important; }
.as-choice .q-radio { width: 100%; border: 1px solid var(--as-border); border-radius: 10px; padding: 10px 12px; }
.as-choice .q-radio[aria-checked="true"] { border: 2px solid var(--as-accent); padding: 9px 11px; }
.as-choice-tile { border: 1px solid var(--as-border); border-radius: 10px; padding: 12px; background: #fff;
  cursor: pointer; gap: 2px; }
.as-choice-selected { border: 2px solid var(--as-accent); padding: 11px; }

.as-strip { background: #f6f8fa; border-radius: 8px; padding: 10px 12px; gap: 28px; align-items: center;
  flex-wrap: wrap; width: 100%; }
.as-stat-label { font-size: 11px; color: var(--as-muted); }
.as-stat-value { font-weight: 600; }

.as-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
/* Calculators over any page: a panel along the right, below the top bar */
.as-calc-panel { position: fixed; top: 52px; right: 0; bottom: 0; width: min(560px, 100vw); z-index: 1600;
  background: var(--as-page); color: var(--as-text); border-left: 1px solid var(--as-border); gap: 0 !important;
  box-shadow: -8px 0 24px rgba(31, 35, 40, .14); }
.as-calc-panel-head { height: 48px; padding: 0 10px 0 16px; gap: 10px; align-items: center; background: #fff;
  border-bottom: 1px solid var(--as-border); }
.as-calc-panel-body { flex: 1 1 auto; overflow-y: auto; padding: 14px 16px 24px; }
.as-calc-compact { grid-template-columns: 1fr !important; gap: 12px !important; }
.as-calc-compact .as-calc-item { flex-direction: row; padding: 6px 14px; border-color: var(--as-border);
  background: #fff; }
.as-calc-compact .as-calc-item-on { box-shadow: inset 0 -2px 0 var(--as-accent); }
.as-calc-compact .as-grid-2, .as-calc-compact .as-grid-3, .as-calc-compact .as-grid-4 {
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.as-topbar-icon.as-topbar-labelled { width: auto; padding: 0 10px; font-weight: 500; }
.as-topbar-labelled .q-icon { margin-right: 6px; }
.as-calc { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; align-items: start; width: 100%; }
.as-calc-item { padding: 10px 12px; border-radius: 8px; border: 1px solid transparent; cursor: pointer; gap: 2px; }
.as-calc-item:hover { background: #fff; }
.as-calc-item-on { background: #fff; border-color: var(--as-border); box-shadow: inset 3px 0 0 var(--as-accent); }
.as-result { background: #f6f8fa; border-radius: 8px; padding: 8px 12px; gap: 0; }
.as-result-hi { background: var(--as-accent-tint); }
.as-result-hi .as-result-value { color: var(--as-accent-text); }
.as-result-value { font-size: 16px; font-weight: 600; }
.as-formula { background: #f6f8fa; border-radius: 8px; padding: 10px 12px; gap: 3px; }

.as-grid-2, .as-grid-3, .as-grid-4, .as-grid-form, .as-columns, .as-monitor { display: grid; gap: 14px; width: 100%;
  align-items: start; }
.as-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.as-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.as-grid-form { grid-template-columns: minmax(12rem, auto) minmax(0, 1fr); gap: 8px 14px; align-items: center; }
.as-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.as-columns-projects { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); }
.as-columns-profiles { grid-template-columns: minmax(0, 20rem) minmax(0, 1fr); }
.as-tabs { border-bottom: 1px solid var(--as-border); margin-top: -4px; }
.as-tab { padding: 8px 14px; color: var(--as-muted); border-bottom: 2px solid transparent; cursor: pointer;
  margin-bottom: -1px; font-weight: 500; }
.as-tab:hover { color: var(--as-text); }
.as-tab-on, .as-tab-on:hover { color: var(--as-accent-text); border-bottom-color: var(--as-accent); font-weight: 600; }
.as-recent-row-on { background: var(--as-accent-tint); box-shadow: inset 3px 0 0 var(--as-accent); }
.as-monitor { grid-template-columns: 250px minmax(0, 1fr); gap: 16px; }
@media (max-width: 900px) {
  .as-grid-2, .as-grid-3, .as-grid-4, .as-columns, .as-columns-projects, .as-columns-profiles, .as-monitor,
  .as-tiles { grid-template-columns: 1fr; }
  .as-side { position: static; max-height: none; }
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

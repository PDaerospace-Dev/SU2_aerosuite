"""
Shared style constants for AeroSuite Pro.

Centralizes palette, fonts, QSS, and icons so every page looks
consistent instead of each file hand-rolling its own colors and
pixel sizes. Import from here rather than inlining new values.

Palette philosophy: one accent color (blue), used sparingly — only for
selection state and the single primary action per page. Everything
else is neutral grey/white with hairline borders. No rainbow of
green/purple/navy buttons competing for attention.
"""

from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:
    _HAS_QTA = False

BASE_FONT_FAMILY = "Segoe UI"
MONO_FONT_FAMILY = "Consolas"

BASE_FONT_SIZE   = 10   # pt, applied app-wide via QApplication.setFont()
SECTION_FONT_PX  = 11
BODY_FONT_PX     = 12
HINT_FONT_PX     = 11
SMALL_FONT_PX    = 10
MONO_FONT_PX     = 10

# ── Palette ──────────────────────────────────────────────────────────────
COLOR_TEXT          = "#1f2328"   # primary text — near-black, not pure black
COLOR_TEXT_SECONDARY = "#57606a"
COLOR_MUTED          = "#8b949e"
COLOR_DISABLED       = "#b0b3b8"

COLOR_ACCENT        = "#0969da"   # the one accent — selection, focus, primary actions
COLOR_ACCENT_BG      = "#ddf0ff"   # light tint for selected/active chips
COLOR_ACCENT_HOVER   = "#0857b3"

COLOR_SURFACE_0      = "#f6f8fa"   # page / tree background
COLOR_SURFACE_1      = "#f1f3f5"   # section-label chip background
COLOR_SURFACE_2      = "#ffffff"   # cards, inputs, content pane

COLOR_BORDER        = "#d0d7de"   # hairline
COLOR_BORDER_STRONG  = "#afb8c1"

COLOR_SUCCESS_BG      = "#dafbe1"
COLOR_SUCCESS_TEXT    = "#1a7f37"
COLOR_WARNING_BG      = "#fff8e1"
COLOR_WARNING_BORDER  = "#ffca28"
COLOR_WARNING_TEXT    = "#5d4037"
COLOR_DANGER         = "#d1242f"

# Status glyph colors (workflow tree)
STATUS_COLOR_DONE    = "#1a7f37"
STATUS_COLOR_WARN    = "#9a6700"
STATUS_COLOR_TODO    = "#57606a"
STATUS_COLOR_ACTIVE  = COLOR_ACCENT
STATUS_COLOR_PENDING = "#8b949e"

# ── Composed styles ──────────────────────────────────────────────────────
SECTION_LABEL_STYLE = (
    f"font-weight: 500; font-size: {SECTION_FONT_PX}px; letter-spacing: 0.03em; "
    f"color: {COLOR_TEXT_SECONDARY}; background: {COLOR_SURFACE_1}; "
    f"padding: 6px 10px; border-radius: 6px; margin-top: 8px;"
)

HINT_LABEL_STYLE = f"color: {COLOR_MUTED}; font-size: {HINT_FONT_PX}px;"

WARNING_BOX_STYLE = (
    f"background:{COLOR_WARNING_BG}; border:1px solid {COLOR_WARNING_BORDER}; border-radius:6px; "
    f"padding:10px; color:{COLOR_WARNING_TEXT}; font-size:{HINT_FONT_PX}px;"
)

INFO_BOX_STYLE = (
    f"background:{COLOR_SURFACE_1}; border:1px solid {COLOR_BORDER}; border-radius:6px; "
    f"padding:10px; color:{COLOR_TEXT_SECONDARY}; font-size:{HINT_FONT_PX}px;"
)

TOGGLE_BUTTON_STYLE = (
    f"QPushButton {{ text-align: left; background: none; border: none; "
    f"color: {COLOR_ACCENT}; font-size: {HINT_FONT_PX}px; font-weight: 500; padding: 4px 2px; }}"
    f"QPushButton:hover {{ color: {COLOR_ACCENT_HOVER}; text-decoration: underline; }}"
)

# Primary action button — reserved for ONE call-to-action per page
# (Generate, Load Mesh, Write control file). Everything else stays
# the default ghost-button style from APP_QSS.
PRIMARY_BUTTON_STYLE = (
    f"QPushButton {{ background: {COLOR_ACCENT}; color: white; font-weight: 500; "
    f"border: none; border-radius: 6px; padding: 8px 16px; }}"
    f"QPushButton:hover {{ background: {COLOR_ACCENT_HOVER}; }}"
    f"QPushButton:pressed {{ background: #06478f; }}"
)

# App-wide QSS applied once in main() — normalizes font sizes and gives
# every ordinary widget a consistent flat, hairline-bordered look.
APP_QSS = f"""
QWidget {{
    font-family: "{BASE_FONT_FAMILY}";
    font-size: {BODY_FONT_PX}px;
    color: {COLOR_TEXT};
}}
QMainWindow, QDialog {{
    background: {COLOR_SURFACE_2};
}}
QPushButton {{
    background: {COLOR_SURFACE_2};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 18px;
    color: {COLOR_TEXT};
}}
QPushButton:hover {{
    background: {COLOR_SURFACE_1};
    border-color: {COLOR_BORDER_STRONG};
}}
QPushButton:pressed {{
    background: #e7e9ec;
}}
QPushButton:disabled {{
    color: {COLOR_DISABLED};
    background: {COLOR_SURFACE_1};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {COLOR_SURFACE_2};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: {COLOR_ACCENT_BG};
    selection-color: {COLOR_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background: {COLOR_SURFACE_1};
    color: {COLOR_MUTED};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QCheckBox {{
    font-size: {BODY_FONT_PX}px;
    spacing: 6px;
}}
QTreeWidget {{
    background: {COLOR_SURFACE_0};
    border: none;
    font-size: {BODY_FONT_PX}px;
    outline: none;
}}
QTreeWidget::item {{
    padding: 6px 4px;
    border-radius: 6px;
    color: {COLOR_TEXT_SECONDARY};
}}
QTreeWidget::item:selected {{
    background: {COLOR_ACCENT_BG};
    color: {COLOR_ACCENT};
}}
QTreeWidget::item:hover:!selected {{
    background: {COLOR_SURFACE_1};
}}
QTableWidget {{
    background: {COLOR_SURFACE_2};
    gridline-color: {COLOR_BORDER};
    border: 1px solid {COLOR_BORDER};
    font-size: {BODY_FONT_PX}px;
}}
QHeaderView::section {{
    background: {COLOR_SURFACE_1};
    color: {COLOR_TEXT_SECONDARY};
    padding: 6px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    font-weight: 500;
    font-size: {BODY_FONT_PX}px;
}}
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
}}
QTabBar::tab {{
    font-size: {BODY_FONT_PX}px;
    padding: 7px 18px;
    background: {COLOR_SURFACE_1};
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {COLOR_TEXT_SECONDARY};
}}
QTabBar::tab:selected {{
    background: {COLOR_SURFACE_2};
    color: {COLOR_ACCENT};
    font-weight: 500;
}}
QMenuBar {{
    background: {COLOR_SURFACE_2};
    border-bottom: 1px solid {COLOR_BORDER};
    font-size: {BODY_FONT_PX}px;
}}
QMenuBar::item:selected {{
    background: {COLOR_SURFACE_1};
    border-radius: 4px;
}}
QMenu {{
    background: {COLOR_SURFACE_2};
    border: 1px solid {COLOR_BORDER};
    font-size: {BODY_FONT_PX}px;
}}
QMenu::item:selected {{
    background: {COLOR_ACCENT_BG};
    color: {COLOR_ACCENT};
}}
QSplitter::handle {{
    background: {COLOR_BORDER};
}}
QStatusBar {{
    background: {COLOR_SURFACE_1};
    border-top: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
    font-size: {SMALL_FONT_PX}px;
}}
QToolTip {{
    font-size: {SMALL_FONT_PX}px;
    background: {COLOR_TEXT};
    color: white;
    border: none;
    padding: 4px 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLOR_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""


def section_label(text: str) -> QLabel:
    """Consistent quiet chip-style section-header label used across every page."""
    lbl = QLabel(text)
    lbl.setStyleSheet(SECTION_LABEL_STYLE)
    return lbl


def hint_label(html: str) -> QLabel:
    """Consistent small muted hint text used across every page."""
    lbl = QLabel(html)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(HINT_LABEL_STYLE)
    return lbl


def icon(name: str, color: str = COLOR_TEXT_SECONDARY) -> QIcon:
    """Return a qtawesome icon, or a blank QIcon if qtawesome isn't installed
    (keeps the app running with text-only buttons rather than crashing)."""
    if not _HAS_QTA:
        return QIcon()
    try:
        return qta.icon(name, color=color)
    except Exception:
        return QIcon()

"""
Shared style constants for AeroSuite Pro.

Centralizes font family/sizes and common widget styling so every page
looks consistent instead of each file hand-rolling its own pixel sizes.
Import from here rather than inlining new font-size values.
"""

from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt

BASE_FONT_FAMILY = "Segoe UI"
MONO_FONT_FAMILY = "Consolas"

BASE_FONT_SIZE   = 10   # pt, applied app-wide via QApplication.setFont()
SECTION_FONT_PX  = 12
BODY_FONT_PX     = 12
HINT_FONT_PX     = 11
SMALL_FONT_PX    = 10
MONO_FONT_PX     = 10

COLOR_TEXT        = "#2c3e50"
COLOR_HINT        = "#666666"
COLOR_MUTED       = "#8a8d93"
COLOR_ACCENT      = "#00a2ed"
COLOR_SECTION_BG  = "#eef1f4"
COLOR_BORDER      = "#c9ccd1"

SECTION_LABEL_STYLE = (
    f"font-weight: bold; font-size: {SECTION_FONT_PX}px; color: {COLOR_TEXT}; "
    f"background: {COLOR_SECTION_BG}; padding: 5px 8px; border-radius: 2px; margin-top: 6px;"
)

HINT_LABEL_STYLE = f"color: {COLOR_HINT}; font-size: {HINT_FONT_PX}px;"

WARNING_BOX_STYLE = (
    "background:#fff8e1; border:1px solid #ffca28; border-radius:4px; "
    f"padding:8px; color:#5d4037; font-size:{HINT_FONT_PX}px;"
)

INFO_BOX_STYLE = (
    "background:#fafafa; border:1px solid #e0e0e0; border-radius:3px; "
    f"padding:8px; color:#37474f; font-size:{HINT_FONT_PX}px;"
)

TOGGLE_BUTTON_STYLE = (
    f"QPushButton {{ text-align: left; background: none; border: none; "
    f"color: {COLOR_ACCENT}; font-size: {HINT_FONT_PX}px; font-weight: bold; padding: 4px 2px; }}"
    f"QPushButton:hover {{ color: #0077a8; text-decoration: underline; }}"
)

# App-wide QSS applied once in main() — normalizes font sizes for common
# widget classes so individual pages don't need to set them one by one.
APP_QSS = f"""
QWidget {{
    font-family: "{BASE_FONT_FAMILY}";
    font-size: {BODY_FONT_PX}px;
}}
QPushButton {{
    font-size: {BODY_FONT_PX}px;
    padding: 5px 12px;
    min-height: 18px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    font-size: {BODY_FONT_PX}px;
    padding: 3px 5px;
    min-height: 20px;
}}
QLabel {{
    font-size: {BODY_FONT_PX}px;
}}
QCheckBox {{
    font-size: {BODY_FONT_PX}px;
}}
QTreeWidget {{
    font-size: {BODY_FONT_PX}px;
}}
QTableWidget, QHeaderView::section {{
    font-size: {BODY_FONT_PX}px;
}}
QTabBar::tab {{
    font-size: {BODY_FONT_PX}px;
    padding: 6px 18px;
}}
QMenuBar, QMenu {{
    font-size: {BODY_FONT_PX}px;
}}
QToolTip {{
    font-size: {SMALL_FONT_PX}px;
}}
"""


def section_label(text: str) -> QLabel:
    """Consistent bold section-header label used across every page."""
    lbl = QLabel(text)
    lbl.setStyleSheet(SECTION_LABEL_STYLE)
    return lbl


def hint_label(html: str) -> QLabel:
    """Consistent small italic/muted hint text used across every page."""
    lbl = QLabel(html)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(HINT_LABEL_STYLE)
    return lbl

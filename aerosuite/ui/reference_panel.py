"""
Reusable collapsible "reference config" panel.

Shows a swappable reference .cfg (defaults to the bundled
config_template.cfg) with a find/highlight box. Collapsed by default —
most of the time you don't need it open, only when copying a marker
block or checking something against a known-good file.
"""

from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QFileDialog, QMessageBox, QTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QTextCharFormat

from ..utils.file_handlers import read_template_file
from .style import (
    section_label, hint_label, TOGGLE_BUTTON_STYLE, MONO_FONT_FAMILY, MONO_FONT_PX
)

BUNDLED_REFERENCE = Path(__file__).resolve().parent.parent / "resources" / "config_template.cfg"


class ReferencePanel(QWidget):
    """Collapsible, swappable reference .cfg viewer with find/highlight."""

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self.setup_ui()
        self._load_reference(str(BUNDLED_REFERENCE), silent=True)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle_btn = QPushButton("▸  Show Reference Config")
        self.toggle_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        row = QHBoxLayout()
        self.reference_path_label = QLabel(str(BUNDLED_REFERENCE.name))
        self.reference_path_label.setStyleSheet(f"color:#555; font-size:{MONO_FONT_PX}px;")
        load_ref_btn = QPushButton("Load Reference Config…")
        load_ref_btn.clicked.connect(self.browse_reference)
        row.addWidget(self.reference_path_label, 1)
        row.addWidget(load_ref_btn)
        body_layout.addLayout(row)

        search_row = QHBoxLayout()
        self.reference_search_edit = QLineEdit()
        self.reference_search_edit.setPlaceholderText("Find (e.g. MARKER_EULER)")
        self.reference_search_edit.returnPressed.connect(self._find_in_reference)
        find_btn = QPushButton("Find Next")
        find_btn.clicked.connect(self._find_in_reference)
        search_row.addWidget(self.reference_search_edit, 1)
        search_row.addWidget(find_btn)
        body_layout.addLayout(search_row)

        self.reference_text = QPlainTextEdit()
        self.reference_text.setReadOnly(True)
        self.reference_text.setFont(QFont(MONO_FONT_FAMILY, MONO_FONT_PX))
        self.reference_text.setStyleSheet("background:#fafafa; border:1px solid #ddd;")
        self.reference_text.setMinimumHeight(260)
        body_layout.addWidget(self.reference_text, 1)

        layout.addWidget(self.body)
        self.body.setVisible(False)

    def _toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.toggle_btn.setText(("▾  Hide" if self._expanded else "▸  Show") + " Reference Config")

    # ── Reference loading / search ──────────────────────────────────────────

    def browse_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Reference Config", "", "Config (*.cfg);;All Files (*)")
        if path:
            self._load_reference(path)

    def _load_reference(self, path: str, silent: bool = False):
        content = read_template_file(Path(path))
        if content is None:
            if not silent:
                QMessageBox.warning(self, "Error", f"Could not read reference file:\n{path}")
            return
        self.reference_text.setPlainText(content)
        self.reference_path_label.setText(Path(path).name)
        self.reference_path_label.setToolTip(path)
        if not silent:
            self.status_message.emit(f"Reference config loaded: {path}")

    def _find_in_reference(self):
        term = self.reference_search_edit.text().strip()
        if not term:
            return
        found = self.reference_text.find(term)
        if not found:
            cursor = self.reference_text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.reference_text.setTextCursor(cursor)
            found = self.reference_text.find(term)

        if found:
            # Persistent highlight so the match stays visibly marked even
            # when focus is back in the search box (Qt's own selection
            # paint is a muted grey when the text widget isn't focused).
            selection = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#ffeb3b"))
            fmt.setForeground(QColor("#000000"))
            selection.format = fmt
            selection.cursor = self.reference_text.textCursor()
            self.reference_text.setExtraSelections([selection])
            self.reference_text.setFocus()
        else:
            self.reference_text.setExtraSelections([])
            self.status_message.emit(f"'{term}' not found in reference config")

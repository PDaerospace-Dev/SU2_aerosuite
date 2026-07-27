"""
Directory Tab UI.

Working directory + output run-folder name, standalone as its own
workflow node, at the top of the Project tree. Mesh, Sweep, and Control File all
read from here instead of owning their own copies.
"""

from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QFrame
)
from PyQt5.QtCore import pyqtSignal

from .style import section_label, HINT_LABEL_STYLE


class DirectoryTab(QWidget):
    """Working directory + output run-folder name."""

    status_message = pyqtSignal(str)
    changed         = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    @staticmethod
    def _section(text: str) -> QLabel:
        return section_label(text)

    def setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(self._section("WORKING DIRECTORY"), 0, 0, 1, 3)

        self.output_edit = QLineEdit("")
        self.output_edit.setPlaceholderText("Base working directory for this project")
        browse_btn = QPushButton("Browse Dir")
        browse_btn.clicked.connect(self.browse_output_directory)

        self.folder_edit = QLineEdit("run_1")
        self.folder_edit.setToolTip("Sub-folder (inside the work dir) where generated files will go")

        layout.addWidget(QLabel("Work Dir:"),    1, 0); layout.addWidget(self.output_edit, 1, 1); layout.addWidget(browse_btn, 1, 2)
        layout.addWidget(QLabel("Folder Name:"), 2, 0); layout.addWidget(self.folder_edit, 2, 1)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep, 3, 0, 1, 3)

        hint = QLabel(
            "<i>This directory is used as the default location for the Mesh, Sweep, and "
            "Control File stages further down the workflow.</i>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_LABEL_STYLE)
        layout.addWidget(hint, 4, 0, 1, 3)

        self.output_edit.textChanged.connect(self.changed.emit)
        self.folder_edit.textChanged.connect(self.changed.emit)

        layout.setRowStretch(5, 1)

    def browse_output_directory(self):
        d = QFileDialog.getExistingDirectory(self, "Select Working Directory", self.output_edit.text())
        if d:
            self.output_edit.setText(d)
            self.status_message.emit(f"Working directory set: {d}")

    # ── Accessors ────────────────────────────────────────────────────────────

    def get_workdir(self) -> str:
        return self.output_edit.text().strip()

    def get_folder(self) -> str:
        return self.folder_edit.text().strip() or "run_1"

    def get_output_dir(self) -> Path:
        return Path(self.get_workdir()) / self.get_folder()

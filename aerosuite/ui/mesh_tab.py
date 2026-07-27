"""
Mesh Tab UI.

Mesh file load + marker extraction only. Working directory now lives
on the standalone Directory page; use set_directory_source() to link
to it for a sensible default browse location.
"""

from pathlib import Path
from typing import List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..core.su2_generator import SU2Generator
from .style import section_label, HINT_LABEL_STYLE, MONO_FONT_FAMILY, MONO_FONT_PX, PRIMARY_BUTTON_STYLE


class MeshTab(QWidget):
    """Mesh file + marker extraction."""

    status_message  = pyqtSignal(str)
    markers_loaded  = pyqtSignal(list)   # List[str] marker tags

    def __init__(self, parent=None):
        super().__init__(parent)
        self.markers: List[str] = []
        self._mesh_full_path: str = ""
        self._directory_source = None
        self.setup_ui()

    def set_directory_source(self, directory_tab):
        """Link to the Directory page for a sensible default browse location."""
        self._directory_source = directory_tab

    @staticmethod
    def _section(text: str) -> QLabel:
        return section_label(text)

    def setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(self._section("MESH FILE"), 0, 0, 1, 3)

        self.mesh_edit = QLineEdit("")
        self.mesh_edit.setPlaceholderText("e.g. mesh.su2, grid.cgns, mesh.msh …")
        self.mesh_edit.setToolTip(
            "Input mesh file for the simulation.\n"
            "Supported: .su2  .cgns  .msh  .med  .dat  .nas  .bdf  .stl  .vtk  .vtu"
        )
        load_mesh_btn = QPushButton("Load Mesh")
        load_mesh_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        load_mesh_btn.clicked.connect(self.load_mesh_and_extract_markers)

        layout.addWidget(QLabel("Mesh File:"), 1, 0); layout.addWidget(self.mesh_edit, 1, 1); layout.addWidget(load_mesh_btn, 1, 2)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep, 2, 0, 1, 3)

        layout.addWidget(self._section("MARKERS FOUND IN MESH"), 3, 0, 1, 3)

        hint = QLabel("<i>Auto-populated after Load Mesh (SU2 files only). Used as reference on the CFG page.</i>")
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_LABEL_STYLE)
        layout.addWidget(hint, 4, 0, 1, 3)

        self.found_markers_text = QTextEdit()
        self.found_markers_text.setReadOnly(True)
        self.found_markers_text.setFont(QFont(MONO_FONT_FAMILY, MONO_FONT_PX))
        self.found_markers_text.setStyleSheet("background:#f5f5f5; border:1px solid #ddd;")
        layout.addWidget(self.found_markers_text, 5, 0, 1, 3)

        layout.setRowStretch(5, 1)

    # ── Actions ──────────────────────────────────────────────────────────────

    def load_mesh_and_extract_markers(self):
        default_dir = ""
        if self._directory_source is not None and self._directory_source.get_workdir():
            default_dir = self._directory_source.get_workdir()

        path, _ = QFileDialog.getOpenFileName(
            self, "Open Mesh File", default_dir,
            "All Mesh Files (*.su2 *.cgns *.med *.msh *.dat *.nas *.bdf *.stl *.vtk *.vtu);;"
            "SU2 Mesh (*.su2);;CGNS (*.cgns);;Gmsh (*.msh *.med);;All Files (*)"
        )
        if not path:
            return

        self._mesh_full_path = path
        self.mesh_edit.setText(Path(path).name)

        try:
            if Path(path).suffix.lower() == '.su2':
                markers = SU2Generator.extract_mesh_markers(Path(path))
                self.markers = markers
                if markers:
                    self.found_markers_text.setPlainText("\n".join(markers))
                    self.status_message.emit(f"Loaded {len(markers)} markers from mesh")
                else:
                    self.found_markers_text.setPlainText("No markers found in .su2 file.")
                    self.status_message.emit("No markers found in mesh file")
                self.markers_loaded.emit(markers)
            else:
                self.markers = []
                fmt = Path(path).suffix.upper()
                self.found_markers_text.setPlainText(
                    f"Automatic marker extraction is only supported for .su2 files.\n"
                    f"{fmt} detected — enter marker names manually on the CFG page."
                )
                self.status_message.emit(f"Mesh loaded ({fmt}). Enter markers manually.")
                self.markers_loaded.emit([])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load mesh: {str(e)}")

    # ── Accessors used by other pages ───────────────────────────────────────

    def get_mesh_filename(self) -> str:
        return self.mesh_edit.text().strip()

    def get_mesh_full_path(self) -> str:
        return self._mesh_full_path

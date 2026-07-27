"""
CFG pages: Aircraft Aero and General.

These are two standalone pages (no longer wrapped in an internal tab
bar) — they appear as expandable child nodes under "CFG" in the
workflow tree, same pattern as Calculators' ISA / y+ children.

  - AircraftAeroPage: master template + freestream + markers/physics
    editor, with a live preview and a collapsible reference .cfg panel.
  - GeneralPage: load any template and live-edit its raw text directly,
    with the same collapsible reference panel at the side.
"""

from pathlib import Path
from typing import Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QPlainTextEdit, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QMessageBox, QFrame,
    QScrollArea, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..core.su2_generator import SU2Generator
from ..utils.file_handlers import read_template_file, write_config_file
from .reference_panel import ReferencePanel
from .collapsible import CollapsibleSection
from .style import section_label, hint_label, MONO_FONT_FAMILY, MONO_FONT_PX, PRIMARY_BUTTON_STYLE


class AircraftAeroPage(QWidget):
    """Master template + freestream + markers/physics editor with live preview."""

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mesh_source = None
        self.setup_ui()

    def set_mesh_source(self, mesh_tab):
        self._mesh_source = mesh_tab
        mesh_tab.markers_loaded.connect(self._on_markers_loaded)

    # ── UI ───────────────────────────────────────────────────────────────────

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_form_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([580, 540])
        outer.addWidget(splitter)

    def _build_form_panel(self) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(8, 8, 4, 8)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)

        # ── Master template ──────────────────────────────────────────────────
        layout.addWidget(section_label("MASTER TEMPLATE"))
        tpl_row = QHBoxLayout()
        self.template_edit = QLineEdit("")
        self.template_edit.setPlaceholderText(".cfg master template file")
        browse_template_btn = QPushButton("Select Template")
        browse_template_btn.clicked.connect(self.browse_template)
        tpl_row.addWidget(self.template_edit)
        tpl_row.addWidget(browse_template_btn)
        layout.addLayout(tpl_row)

        # ── Freestream ───────────────────────────────────────────────────────
        layout.addWidget(section_label("FREESTREAM"))
        fs_grid = QGridLayout(); fs_grid.setSpacing(6)

        self.mach_edit  = QLineEdit(""); self.mach_edit.setPlaceholderText("0.3")
        self.alpha_edit = QLineEdit(""); self.alpha_edit.setPlaceholderText("2.0")
        self.beta_edit  = QLineEdit(""); self.beta_edit.setPlaceholderText("0.0")
        self.temp_edit      = QLineEdit(""); self.temp_edit.setPlaceholderText("288.15")
        self.reynolds_edit  = QLineEdit(""); self.reynolds_edit.setPlaceholderText("1000000")

        fs_grid.addWidget(QLabel("Mach:"),        0, 0); fs_grid.addWidget(self.mach_edit,      0, 1)
        fs_grid.addWidget(QLabel("Alpha (deg):"), 1, 0); fs_grid.addWidget(self.alpha_edit,     1, 1)
        fs_grid.addWidget(QLabel("Beta (deg):"),  2, 0); fs_grid.addWidget(self.beta_edit,      2, 1)
        fs_grid.addWidget(QLabel("Temp (K):"),    3, 0); fs_grid.addWidget(self.temp_edit,      3, 1)
        fs_grid.addWidget(QLabel("Reynolds No:"), 4, 0); fs_grid.addWidget(self.reynolds_edit,  4, 1)
        fs_grid.setColumnStretch(1, 1)
        layout.addLayout(fs_grid)

        # ── Markers ──────────────────────────────────────────────────────────
        layout.addWidget(section_label("MARKERS"))
        layout.addWidget(hint_label("<i>Check a marker to include it. Uncheck to omit that MARKER_ line entirely.</i>"))

        marker_grid = QGridLayout(); marker_grid.setSpacing(6)

        self.use_heat_flux  = QCheckBox("MARKER_HEATFLUX");  self.use_heat_flux.setChecked(True)
        self.heat_flux_edit = QLineEdit(""); self.heat_flux_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        self.use_far_field  = QCheckBox("MARKER_FAR");       self.use_far_field.setChecked(True)
        self.far_field_edit = QLineEdit(""); self.far_field_edit.setPlaceholderText("( FarField )")

        self.use_plotting   = QCheckBox("MARKER_PLOTTING");  self.use_plotting.setChecked(True)
        self.plotting_edit  = QLineEdit(""); self.plotting_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        self.use_monitoring = QCheckBox("MARKER_MONITORING"); self.use_monitoring.setChecked(True)
        self.monitoring_edit = QLineEdit(""); self.monitoring_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        def _wire_marker(chk, edit):
            edit.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda s, e=edit: e.setEnabled(s == Qt.Checked))
            chk.stateChanged.connect(self._update_preview)
            edit.textChanged.connect(self._update_preview)

        _wire_marker(self.use_heat_flux,  self.heat_flux_edit)
        _wire_marker(self.use_far_field,  self.far_field_edit)
        _wire_marker(self.use_plotting,   self.plotting_edit)
        _wire_marker(self.use_monitoring, self.monitoring_edit)

        marker_grid.addWidget(self.use_heat_flux,   0, 0); marker_grid.addWidget(self.heat_flux_edit,  0, 1)
        marker_grid.addWidget(self.use_far_field,   1, 0); marker_grid.addWidget(self.far_field_edit,  1, 1)
        marker_grid.addWidget(self.use_plotting,    2, 0); marker_grid.addWidget(self.plotting_edit,   2, 1)
        marker_grid.addWidget(self.use_monitoring,  3, 0); marker_grid.addWidget(self.monitoring_edit, 3, 1)
        marker_grid.setColumnStretch(1, 1)
        layout.addLayout(marker_grid)

        self._found_markers_label = hint_label("Found in mesh (from Mesh page): —")
        self._found_markers_label.setStyleSheet(self._found_markers_label.styleSheet() + " color:#888;")
        layout.addWidget(self._found_markers_label)

        # ── Physical & reference properties ─────────────────────────────────
        layout.addWidget(section_label("PHYSICAL & REFERENCE PROPERTIES"))
        phys_grid = QGridLayout(); phys_grid.setSpacing(6)

        self.rey_len      = QLineEdit(""); self.rey_len.setPlaceholderText("1")
        self.ref_len       = QLineEdit(""); self.ref_len.setPlaceholderText("6")
        self.ref_area      = QLineEdit(""); self.ref_area.setPlaceholderText("16.213")
        self.ref_origin_x  = QLineEdit(""); self.ref_origin_x.setPlaceholderText("5.16")
        self.ref_origin_y  = QLineEdit(""); self.ref_origin_y.setPlaceholderText("0.00")
        self.ref_origin_z  = QLineEdit(""); self.ref_origin_z.setPlaceholderText("0.00")

        phys_grid.addWidget(QLabel("Ref Length:"),      0, 0); phys_grid.addWidget(self.ref_len,      0, 1)
        phys_grid.addWidget(QLabel("Ref Area:"),        1, 0); phys_grid.addWidget(self.ref_area,     1, 1)
        phys_grid.addWidget(QLabel("Origin X:"),        2, 0); phys_grid.addWidget(self.ref_origin_x, 2, 1)
        phys_grid.addWidget(QLabel("Origin Y:"),        3, 0); phys_grid.addWidget(self.ref_origin_y, 3, 1)
        phys_grid.addWidget(QLabel("Origin Z:"),        4, 0); phys_grid.addWidget(self.ref_origin_z, 4, 1)
        phys_grid.addWidget(QLabel("Reynolds Length:"), 5, 0); phys_grid.addWidget(self.rey_len,      5, 1)
        phys_grid.setColumnStretch(1, 1)
        layout.addLayout(phys_grid)

        # ── Numerics (collapsible — defaults tend to be fine as-is) ───────────
        self.numerics_section = CollapsibleSection("Advanced Numerics")
        numerics_section = self.numerics_section
        num_grid = QGridLayout(); num_grid.setSpacing(6)

        self.conv_dropdown       = QComboBox(); self.conv_dropdown.addItems(['ROE', 'JST', 'AUSM'])
        self.muscl_flow_dropdown = QComboBox(); self.muscl_flow_dropdown.addItems(['YES', 'NO']); self.muscl_flow_dropdown.setCurrentText('YES')
        self.turb_model_dropdown = QComboBox(); self.turb_model_dropdown.addItems(['SST', 'SA'])
        self.restart_dropdown    = QComboBox(); self.restart_dropdown.addItems(['NO', 'YES'])
        self.cfl_spinner  = QDoubleSpinBox(); self.cfl_spinner.setValue(1.0);    self.cfl_spinner.setRange(0, 1e6)
        self.iter_spinner = QSpinBox();        self.iter_spinner.setValue(1500); self.iter_spinner.setRange(1, 100000)

        num_grid.addWidget(QLabel("Convective:"),  0, 0); num_grid.addWidget(self.conv_dropdown,       0, 1)
        num_grid.addWidget(QLabel("MUSCL Flow:"),  1, 0); num_grid.addWidget(self.muscl_flow_dropdown, 1, 1)
        num_grid.addWidget(QLabel("Turbulence:"),  2, 0); num_grid.addWidget(self.turb_model_dropdown, 2, 1)
        num_grid.addWidget(QLabel("Restart Sol:"), 3, 0); num_grid.addWidget(self.restart_dropdown,    3, 1)
        num_grid.addWidget(QLabel("CFL:"),         4, 0); num_grid.addWidget(self.cfl_spinner,         4, 1)
        num_grid.addWidget(QLabel("Iterations:"),  5, 0); num_grid.addWidget(self.iter_spinner,        5, 1)
        num_grid.setColumnStretch(1, 1)
        numerics_section.addLayout(num_grid)
        layout.addWidget(numerics_section)

        for w in [self.mach_edit, self.alpha_edit, self.beta_edit, self.temp_edit, self.reynolds_edit,
                  self.rey_len, self.ref_len, self.ref_area, self.ref_origin_x,
                  self.ref_origin_y, self.ref_origin_z]:
            w.textChanged.connect(self._update_preview)
        for cb in [self.conv_dropdown, self.muscl_flow_dropdown, self.turb_model_dropdown, self.restart_dropdown]:
            cb.currentTextChanged.connect(self._update_preview)
        self.cfl_spinner.valueChanged.connect(self._update_preview)
        self.iter_spinner.valueChanged.connect(self._update_preview)
        self.template_edit.textChanged.connect(self._update_preview)

        # ── Custom placeholders (collapsible — most templates won't need this) ─
        self.placeholders_section = CollapsibleSection("Custom Placeholders")
        placeholders_section = self.placeholders_section
        placeholders_section.addWidget(hint_label(
            "<i>One <code>KEY= value</code> per line. Existing keys are replaced in place; "
            "new keys are appended.</i>"
        ))

        self.custom_placeholders_edit = QTextEdit()
        self.custom_placeholders_edit.setPlaceholderText("Example:\nMULTIGRID= NO\nLINEAR_SOLVER= FGMRES")
        self.custom_placeholders_edit.setFixedHeight(80)
        self.custom_placeholders_edit.setFont(QFont(MONO_FONT_FAMILY, MONO_FONT_PX))
        self.custom_placeholders_edit.textChanged.connect(self._update_preview)
        placeholders_section.addWidget(self.custom_placeholders_edit)
        layout.addWidget(placeholders_section)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        gen_btn = QPushButton("⚙  Generate Config File")
        gen_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        gen_btn.setToolTip("Write ONE .cfg file with freestream, markers, and physics substituted.")
        gen_btn.clicked.connect(self.generate_single_config)
        outer.addWidget(gen_btn)

        return container

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 8, 8, 8)
        layout.setSpacing(8)

        self.reference_panel = ReferencePanel()
        self.reference_panel.status_message.connect(self.status_message)
        layout.addWidget(self.reference_panel)

        layout.addWidget(section_label("LIVE PREVIEW (your template + current settings)"))
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont(MONO_FONT_FAMILY, MONO_FONT_PX))
        self.preview_text.setStyleSheet("background:#0e2a12; color:#c8e6c9; border:1px solid #ddd;")
        layout.addWidget(self.preview_text, 1)

        return container

    # ── Mesh linkage ─────────────────────────────────────────────────────────

    def _on_markers_loaded(self, markers):
        if markers:
            self._found_markers_label.setText("Found in mesh: " + ", ".join(markers))
        else:
            self._found_markers_label.setText("Found in mesh (from Mesh page): —")

    # ── Template browse ──────────────────────────────────────────────────────

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Master Template", "", "Config (*.cfg)")
        if path:
            self.template_edit.setText(path)
            self.status_message.emit(f"Template selected: {path}")

    # ── Parameter dict ───────────────────────────────────────────────────────

    def get_physics_params(self) -> Dict[str, str]:
        """Everything this page can substitute: freestream + markers + physics."""
        _RM = SU2Generator.REMOVE_LINE
        params = {
            "MACH_NUMBER":            self.mach_edit.text()  or "0.0",
            "AOA":                    self.alpha_edit.text() or "0.0",
            "SIDESLIP_ANGLE":         self.beta_edit.text()  or "0.0",
            "FREESTREAM_TEMPERATURE": self.temp_edit.text()  or "288.15",
            "REYNOLDS_NUMBER":        self.reynolds_edit.text() or "1000000",
            "KIND_TURB_MODEL":       self.turb_model_dropdown.currentText(),
            "RESTART_SOL":           self.restart_dropdown.currentText(),
            "REYNOLDS_LENGTH":       self.rey_len.text(),
            "REF_ORIGIN_MOMENT_X":   self.ref_origin_x.text(),
            "REF_ORIGIN_MOMENT_Y":   self.ref_origin_y.text(),
            "REF_ORIGIN_MOMENT_Z":   self.ref_origin_z.text(),
            "REF_LENGTH":            self.ref_len.text(),
            "REF_AREA":              self.ref_area.text(),
            "CFL_NUMBER":            f"{self.cfl_spinner.value():.1f}",
            "ITER":                  str(self.iter_spinner.value()),
            "CONV_NUM_METHOD_FLOW":  self.conv_dropdown.currentText(),
            "MUSCL_FLOW":            self.muscl_flow_dropdown.currentText(),
            "MARKER_HEATFLUX":       self.heat_flux_edit.text()  if self.use_heat_flux.isChecked()  else _RM,
            "MARKER_FAR":            self.far_field_edit.text()  if self.use_far_field.isChecked()  else _RM,
            "MARKER_PLOTTING":       self.plotting_edit.text()   if self.use_plotting.isChecked()   else _RM,
            "MARKER_MONITORING":     self.monitoring_edit.text() if self.use_monitoring.isChecked() else _RM,
        }
        if self._mesh_source is not None:
            mesh_name = self._mesh_source.get_mesh_filename()
            if mesh_name:
                params["MESH_FILENAME"] = mesh_name
        params.update(self.parse_custom_placeholders())
        return params

    def parse_custom_placeholders(self) -> Dict[str, str]:
        custom_params: Dict[str, str] = {}
        text = self.custom_placeholders_edit.toPlainText().strip()
        if not text:
            return custom_params
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                custom_params[key] = value.strip()
        return custom_params

    def get_template_path(self) -> Path:
        return Path(self.template_edit.text().strip())

    # ── Live preview ─────────────────────────────────────────────────────────

    def _update_preview(self, *_args):
        template_path_str = self.template_edit.text().strip()
        if not template_path_str or not Path(template_path_str).exists():
            self.preview_text.setPlainText(
                "(Select a master template above to see a live preview here.)"
            )
            return
        try:
            content = read_template_file(Path(template_path_str))
            if content is None:
                self.preview_text.setPlainText("(Could not read template file.)")
                return
            updated = SU2Generator.update_template_content(content, self.get_physics_params())
            self.preview_text.setPlainText(updated)
        except Exception as e:
            self.preview_text.setPlainText(f"(Preview error: {e})")

    # ── Single-file generation ──────────────────────────────────────────────

    def generate_single_config(self):
        template_path = self.get_template_path()
        if not template_path.exists():
            QMessageBox.warning(self, "No Template", "Select a master template .cfg first.")
            return

        default_name = f"{template_path.stem}_config.cfg"
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Config File", default_name, "Config (*.cfg)")
        if not save_path:
            return

        try:
            content = read_template_file(template_path)
            if content is None:
                raise ValueError("Failed to read template file")
            updated = SU2Generator.update_template_content(content, self.get_physics_params())
            if not write_config_file(Path(save_path), updated):
                raise ValueError("Failed to write config file")
            QMessageBox.information(self, "Success", f"Config file written:\n{save_path}")
            self.status_message.emit(f"Generated config: {save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to generate config:\n{str(e)}")

    def update_from_isa(self, temperature: str, reynolds: str):
        self.temp_edit.setText(temperature)
        self.reynolds_edit.setText(reynolds)


class GeneralPage(QWidget):
    """Load any template, edit its raw text directly, generate as-is.
    Reference config sits at the side for copy/paste reference."""

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_editor_panel())
        splitter.addWidget(self._build_reference_side())
        splitter.setSizes([620, 500])
        outer.addWidget(splitter)

    def _build_editor_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 4, 8)
        layout.setSpacing(8)

        layout.addWidget(section_label("LOAD TEMPLATE"))
        row = QHBoxLayout()
        self.template_edit = QLineEdit("")
        self.template_edit.setPlaceholderText(".cfg file to load and edit directly")
        browse_btn = QPushButton("Load Template")
        browse_btn.clicked.connect(self.browse_template)
        row.addWidget(self.template_edit)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        layout.addWidget(hint_label("<i>Edit the file content below directly, then Generate Config File to save it.</i>"))

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont(MONO_FONT_FAMILY, MONO_FONT_PX))
        self.editor.setStyleSheet("background:#fafafa; border:1px solid #ddd;")
        layout.addWidget(self.editor, 1)

        gen_btn = QPushButton("⚙  Generate Config File")
        gen_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        gen_btn.clicked.connect(self.generate_config)
        layout.addWidget(gen_btn)

        return container

    def _build_reference_side(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 8, 8, 8)
        layout.setSpacing(8)

        self.reference_panel = ReferencePanel()
        self.reference_panel.status_message.connect(self.status_message)
        layout.addWidget(self.reference_panel)
        layout.addStretch()

        return container

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Template", "", "Config (*.cfg);;All Files (*)")
        if not path:
            return
        content = read_template_file(Path(path))
        if content is None:
            QMessageBox.warning(self, "Error", f"Could not read file:\n{path}")
            return
        self.template_edit.setText(path)
        self.editor.setPlainText(content)
        self.status_message.emit(f"Template loaded for direct editing: {path}")

    def generate_config(self):
        if not self.editor.toPlainText().strip():
            QMessageBox.warning(self, "Nothing to Save", "Load a template and/or write config content first.")
            return

        default_name = Path(self.template_edit.text()).stem + "_edited.cfg" if self.template_edit.text().strip() else "config.cfg"
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Config File", default_name, "Config (*.cfg)")
        if not save_path:
            return

        try:
            if not write_config_file(Path(save_path), self.editor.toPlainText()):
                raise ValueError("Failed to write config file")
            QMessageBox.information(self, "Success", f"Config file written:\n{save_path}")
            self.status_message.emit(f"Generated config (General): {save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to generate config:\n{str(e)}")

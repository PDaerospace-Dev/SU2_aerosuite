"""
SU2 Configuration Generator Tab UI.

Provides the user interface for generating batch SU2 configuration files.
"""

import os
from pathlib import Path
from typing import List, Optional, Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QTabWidget, QFileDialog, QMessageBox,
    QDialog, QDialogButtonBox, QProgressDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QSizePolicy,
    QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QCursor

from ..core.su2_generator import SU2Generator, GenerationConfig
from ..utils.validators import validate_float_list
from ..utils.file_handlers import read_template_file, write_config_file, ensure_directory


# ── Preview Dialog ─────────────────────────────────────────────────────────────

class PreviewDialog(QDialog):
    """
    Dialog to preview CFG filenames before generation.
    Offers two actions:
      • Generate Control File  → writes run_control.txt, transfers to Batch Control tab
      • Generate CFG           → immediately writes .cfg files
    """

    ACTION_NONE         = 0
    ACTION_CTRL_FILE    = 1
    ACTION_GENERATE_CFG = 2

    def __init__(self, filenames: List[str], output_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview — Config Files")
        self.setGeometry(200, 150, 720, 520)
        self.action = self.ACTION_NONE

        layout = QVBoxLayout(self)

        # Header
        info = QLabel(
            f"<b>{len(filenames)} config files</b> will be created in:<br>"
            f"<code>{output_dir}</code>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # File list table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["#", "Filename"])
        self.table.setRowCount(len(filenames))
        for i, fname in enumerate(filenames):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(fname))
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.table.setColumnWidth(0, 40)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # Action buttons row
        hint = QLabel(
            "<i>Generate Control File</i> — writes run_control.txt and opens Batch Control tab.<br>"
            "<i>Generate CFG</i> — directly writes the .cfg files to disk."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 10px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setFixedWidth(90)

        ctrl_btn = QPushButton("📋  Generate Control File")
        ctrl_btn.setStyleSheet(
            "background:#6A1B9A; color:white; font-weight:bold; padding:8px 14px;"
        )
        ctrl_btn.setToolTip(
            "Write run_control.txt (no .cfg files yet) and go to Batch Control tab"
        )
        ctrl_btn.clicked.connect(self._choose_ctrl)

        gen_btn = QPushButton("⚙  Generate CFG Files")
        gen_btn.setStyleSheet(
            "background:#2E7D32; color:white; font-weight:bold; padding:8px 14px;"
        )
        gen_btn.setToolTip("Write the .cfg files to disk immediately")
        gen_btn.clicked.connect(self._choose_gen)

        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(ctrl_btn)
        btn_row.addWidget(gen_btn)
        layout.addLayout(btn_row)

    def _choose_ctrl(self):
        self.action = self.ACTION_CTRL_FILE
        self.accept()

    def _choose_gen(self):
        self.action = self.ACTION_GENERATE_CFG
        self.accept()


# ── Batch-Control Help Dialog ──────────────────────────────────────────────────

class BatchControlHelpDialog(QDialog):
    """Dialog explaining the Batch Control File and restart modes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Control File — Help")
        self.setMinimumWidth(580)
        self.setMinimumHeight(480)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Batch Control File")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1a237e;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(14)

        def section(heading, body_html):
            h = QLabel(f"<b>{heading}</b>")
            h.setStyleSheet("color: #37474f; font-size: 12px;")
            b = QLabel(body_html)
            b.setWordWrap(True)
            b.setTextFormat(Qt.RichText)
            b.setStyleSheet("color: #424242; padding-left: 8px;")
            content_layout.addWidget(h)
            content_layout.addWidget(b)

        section(
            "What is a Control File?",
            "A plain-text file that tells AeroSuite the <i>execution order</i> and "
            "<i>restart behaviour</i> for every case in the sweep."
        )
        section(
            "File Format",
            "Each line: <code>&lt;config.cfg&gt;, restart_option, [optional_restart_path]</code><br>"
            "restart_option: <b>none</b> | <b>previous</b> | <b>custom</b>"
        )

        ex_label = QLabel("<b>Example</b>")
        ex_label.setStyleSheet("color: #37474f; font-size: 12px;")
        content_layout.addWidget(ex_label)
        ex_box = QTextEdit()
        ex_box.setReadOnly(True)
        ex_box.setFont(QFont("Courier New", 10))
        ex_box.setFixedHeight(90)
        ex_box.setStyleSheet("background:#f5f5f5; border:1px solid #ddd; border-radius:4px; padding:6px;")
        ex_box.setPlainText(
            "ht_M0p3_A0_B0_sl.cfg,   none\n"
            "ht_M0p3_A5_B0_sl.cfg,   previous\n"
            "ht_M0p6_A0_B0_sl.cfg,   custom,   /data/restart_flow.dat"
        )
        content_layout.addWidget(ex_box)

        options = [
            ("none",     "#e8f5e9", "#2e7d32",
             "Start every case <b>from scratch</b>."),
            ("previous", "#e3f2fd", "#1565c0",
             "Use the <b>restart file from the immediately preceding case</b>."),
            ("custom",   "#fff3e0", "#e65100",
             "Provide an <b>explicit path</b> to a specific restart file."),
        ]
        for name, bg, fg, desc in options:
            row = QWidget()
            row.setStyleSheet(f"background-color:{bg}; border-radius:6px; border-left:4px solid {fg};")
            rl = QHBoxLayout(row); rl.setContentsMargins(10, 8, 10, 8)
            tag = QLabel(name)
            tag.setStyleSheet(f"font-family:'Courier New'; font-weight:bold; font-size:12px; color:{fg}; min-width:70px;")
            tag.setAlignment(Qt.AlignTop)
            dl = QLabel(desc); dl.setWordWrap(True); dl.setTextFormat(Qt.RichText)
            dl.setStyleSheet("color:#333; background:transparent; border:none;")
            rl.addWidget(tag); rl.addWidget(dl, 1)
            content_layout.addWidget(row)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)


# ── Main SU2Tab ────────────────────────────────────────────────────────────────

class SU2Tab(QWidget):
    """SU2 Configuration Generator tab widget."""

    status_message      = pyqtSignal(str)
    generation_complete = pyqtSignal(str, str)   # (cfg_dir, ctrl_file_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generator = SU2Generator()
        self.setup_ui()

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_section_header(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight:bold; color:#2c3e50; font-size:11px;"
            "background:#e8eaf6; padding:3px 6px; border-radius:3px;"
        )
        return lbl

    # ── top-level layout ─────────────────────────────────────────────────────

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        self.sub_tabs = QTabWidget()
        layout.addWidget(self.sub_tabs)

        self.create_setup_tab()          # tab 0 — Setup & Freestream (has summary)
        self.create_markers_physics_tab()# tab 1 — Markers & Physics  (has Preview button)
        self.create_batch_tab()          # tab 2 — Batch Control

        self.update_summary()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 0 — Setup & Freestream
    # ══════════════════════════════════════════════════════════════════════════

    def create_setup_tab(self):
        """Setup & Freestream tab: I/O, freestream values, Configuration Summary."""
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── I/O CONTROL ──────────────────────────────────────────────────────
        layout.addWidget(self._make_section_header("TEMPLATE & I/O CONTROL"), 0, 0, 1, 3)

        self.template_edit = QLineEdit("")
        self.template_edit.setPlaceholderText(".cfg master template file")
        browse_template_btn = QPushButton("Select Template")
        browse_template_btn.clicked.connect(self.browse_template)

        self.mesh_edit = QLineEdit("")
        self.mesh_edit.setPlaceholderText("e.g. mesh.su2, grid.cgns, mesh.msh …")
        self.mesh_edit.setToolTip(
            "Input mesh file for the simulation.\n"
            "Supported: .su2  .cgns  .msh  .med  .dat  .nas  .bdf  .stl  .vtk  .vtu\n"
            "You can also type the filename manually."
        )
        load_mesh_btn = QPushButton("Load Mesh")
        load_mesh_btn.clicked.connect(self.load_mesh_and_extract_markers)

        self.output_edit = QLineEdit("")
        self.output_edit.setToolTip("Base directory for generated files")
        browse_btn = QPushButton("Browse Dir")
        browse_btn.clicked.connect(self.browse_output_directory)

        self.folder_edit = QLineEdit("run_1")

        layout.addWidget(QLabel("Master Template:"), 1, 0); layout.addWidget(self.template_edit, 1, 1); layout.addWidget(browse_template_btn, 1, 2)
        layout.addWidget(QLabel("Mesh File:"),       2, 0); layout.addWidget(self.mesh_edit,     2, 1); layout.addWidget(load_mesh_btn,       2, 2)
        layout.addWidget(QLabel("Work Dir:"),        3, 0); layout.addWidget(self.output_edit,   3, 1); layout.addWidget(browse_btn,          3, 2)
        layout.addWidget(QLabel("Folder Name:"),     4, 0); layout.addWidget(self.folder_edit,   4, 1)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1, 5, 0, 1, 3)

        # ── FREESTREAM ────────────────────────────────────────────────────────
        layout.addWidget(self._make_section_header("FREESTREAM"), 6, 0, 1, 3)

        self.mach_edit = QLineEdit(""); self.mach_edit.setPlaceholderText("0.3 0.6 1.2")
        self.inc_mach = QCheckBox("Inc. Name"); self.inc_mach.setChecked(True)

        self.alpha_edit = QLineEdit(""); self.alpha_edit.setPlaceholderText("-10 0 10 25 45")
        self.inc_alpha = QCheckBox("Inc. Name"); self.inc_alpha.setChecked(True)

        self.beta_edit = QLineEdit(""); self.beta_edit.setPlaceholderText("-2 0 2")
        self.inc_beta = QCheckBox("Inc. Name"); self.inc_beta.setChecked(True)

        self.altitude_dropdown = QComboBox()
        self.altitude_dropdown.setEditable(True)
        self.altitude_dropdown.addItems(['sl', '10km', '20km', '30km', '40km', '50km'])
        self.inc_alt = QCheckBox("Inc. Name"); self.inc_alt.setChecked(True)

        self.base_edit = QLineEdit(""); self.base_edit.setPlaceholderText("e.g. HT")
        self.inc_base = QCheckBox("Inc. Name"); self.inc_base.setChecked(True)

        self.temp_edit     = QLineEdit(""); self.temp_edit.setPlaceholderText("270")
        self.reynolds_edit = QLineEdit(""); self.reynolds_edit.setPlaceholderText("100000")

        layout.addWidget(QLabel("Mach Numbers:"), 7,  0); layout.addWidget(self.mach_edit,          7,  1); layout.addWidget(self.inc_mach,  7,  2)
        layout.addWidget(QLabel("Alpha Values:"),  8,  0); layout.addWidget(self.alpha_edit,         8,  1); layout.addWidget(self.inc_alpha, 8,  2)
        layout.addWidget(QLabel("Beta Values:"),   9,  0); layout.addWidget(self.beta_edit,          9,  1); layout.addWidget(self.inc_beta,  9,  2)
        layout.addWidget(QLabel("Altitude:"),      10, 0); layout.addWidget(self.altitude_dropdown,  10, 1); layout.addWidget(self.inc_alt,   10, 2)
        layout.addWidget(QLabel("Config Name:"),   11, 0); layout.addWidget(self.base_edit,          11, 1); layout.addWidget(self.inc_base,  11, 2)
        layout.addWidget(QLabel("Temp (K):"),      12, 0); layout.addWidget(self.temp_edit,          12, 1)
        layout.addWidget(QLabel("Reynolds No:"),   13, 0); layout.addWidget(self.reynolds_edit,      13, 1)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2, 14, 0, 1, 3)

        # ── CONFIGURATION SUMMARY ─────────────────────────────────────────────
        layout.addWidget(self._make_section_header("CONFIGURATION SUMMARY"), 15, 0, 1, 3)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(QFont("Courier New", 10))
        self.summary_text.setMinimumHeight(120)
        self.summary_text.setMaximumHeight(180)
        layout.addWidget(self.summary_text, 16, 0, 1, 3)

        layout.setRowStretch(17, 1)

        # Connect signals
        for w in [self.template_edit, self.mach_edit, self.alpha_edit,
                  self.beta_edit, self.temp_edit, self.reynolds_edit,
                  self.folder_edit, self.base_edit]:
            w.textChanged.connect(self.update_summary)
        self.altitude_dropdown.currentTextChanged.connect(self.update_summary)
        for cb in [self.inc_base, self.inc_mach, self.inc_alpha, self.inc_beta, self.inc_alt]:
            cb.stateChanged.connect(self.update_summary)

        self.sub_tabs.addTab(tab, "Setup & Freestream")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Markers & Physics (merged)
    # ══════════════════════════════════════════════════════════════════════════

    def create_markers_physics_tab(self):
        """
        Merged Markers + Physics & Numerical tab.

        Layout
        ──────
        1.  MARKERS section  (4 markers with enable checkbox each)
        2.  PHYSICAL & REFERENCE PROPERTIES
        3.  NUMERICAL METHODS
        4.  CUSTOM PLACEHOLDERS  (with verification note)
        5.  MARKERS FOUND IN MESH  (read-only, at the bottom)
        6.  [Preview Files] button
        """
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(6)
        outer.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── 1. MARKERS ────────────────────────────────────────────────────────
        layout.addWidget(self._make_section_header("MARKERS"))

        marker_hint = QLabel(
            "<i>Check each marker to include it in generated config files. "
            "Uncheck to omit that MARKER_ line entirely.</i>"
        )
        marker_hint.setWordWrap(True)
        marker_hint.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(marker_hint)

        marker_grid = QGridLayout()
        marker_grid.setSpacing(4)

        # Heat Flux
        self.use_heat_flux  = QCheckBox("MARKER_HEATFLUX")
        self.use_heat_flux.setChecked(True)
        self.heat_flux_edit = QLineEdit("")
        self.heat_flux_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        # Far Field
        self.use_far_field  = QCheckBox("MARKER_FAR")
        self.use_far_field.setChecked(True)
        self.far_field_edit = QLineEdit("")
        self.far_field_edit.setPlaceholderText("( FarField )")

        # Plotting
        self.use_plotting   = QCheckBox("MARKER_PLOTTING")
        self.use_plotting.setChecked(True)
        self.plotting_edit  = QLineEdit("")
        self.plotting_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        # Monitoring
        self.use_monitoring = QCheckBox("MARKER_MONITORING")
        self.use_monitoring.setChecked(True)
        self.monitoring_edit = QLineEdit("")
        self.monitoring_edit.setPlaceholderText("( Fuselage, Wing, VT, HT )")

        def _wire_marker(chk, edit):
            edit.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda s, e=edit: e.setEnabled(s == Qt.Checked))

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

        sep_a = QFrame(); sep_a.setFrameShape(QFrame.HLine); sep_a.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep_a)

        # ── 2. PHYSICAL & REFERENCE ───────────────────────────────────────────
        layout.addWidget(self._make_section_header("PHYSICAL & REFERENCE PROPERTIES"))

        phys_grid = QGridLayout(); phys_grid.setSpacing(4)

        self.rey_len     = QLineEdit(""); self.rey_len.setPlaceholderText("1")
        self.ref_len     = QLineEdit(""); self.ref_len.setPlaceholderText("6")
        self.ref_area    = QLineEdit(""); self.ref_area.setPlaceholderText("16.213")
        self.ref_origin_x = QLineEdit(""); self.ref_origin_x.setPlaceholderText("5.16")
        self.ref_origin_y = QLineEdit(""); self.ref_origin_y.setPlaceholderText("0.00")
        self.ref_origin_z = QLineEdit(""); self.ref_origin_z.setPlaceholderText("0.00")

        phys_grid.addWidget(QLabel("Ref Length:"),     0, 0); phys_grid.addWidget(self.ref_len,      0, 1)
        phys_grid.addWidget(QLabel("Ref Area:"),       1, 0); phys_grid.addWidget(self.ref_area,     1, 1)
        phys_grid.addWidget(QLabel("Origin X:"),       2, 0); phys_grid.addWidget(self.ref_origin_x, 2, 1)
        phys_grid.addWidget(QLabel("Origin Y:"),       3, 0); phys_grid.addWidget(self.ref_origin_y, 3, 1)
        phys_grid.addWidget(QLabel("Origin Z:"),       4, 0); phys_grid.addWidget(self.ref_origin_z, 4, 1)
        phys_grid.addWidget(QLabel("Reynolds Length:"),5, 0); phys_grid.addWidget(self.rey_len,      5, 1)
        phys_grid.setColumnStretch(1, 1)
        layout.addLayout(phys_grid)

        sep_b = QFrame(); sep_b.setFrameShape(QFrame.HLine); sep_b.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep_b)

        # ── 3. NUMERICAL METHODS ──────────────────────────────────────────────
        layout.addWidget(self._make_section_header("NUMERICAL METHODS"))

        num_grid = QGridLayout(); num_grid.setSpacing(4)

        self.conv_dropdown = QComboBox(); self.conv_dropdown.addItems(['ROE', 'JST', 'AUSM'])
        self.muscl_flow_dropdown = QComboBox(); self.muscl_flow_dropdown.addItems(['YES', 'NO']); self.muscl_flow_dropdown.setCurrentText('YES')
        self.turb_model_dropdown = QComboBox(); self.turb_model_dropdown.addItems(['SST', 'SA'])
        self.restart_dropdown    = QComboBox(); self.restart_dropdown.addItems(['NO', 'YES'])
        self.cfl_spinner   = QDoubleSpinBox(); self.cfl_spinner.setValue(1.0);   self.cfl_spinner.setRange(0, 1e6)
        self.iter_spinner  = QSpinBox();        self.iter_spinner.setValue(1500); self.iter_spinner.setRange(1, 100000)

        num_grid.addWidget(QLabel("Convective:"),  0, 0); num_grid.addWidget(self.conv_dropdown,       0, 1)
        num_grid.addWidget(QLabel("MUSCL Flow:"),  1, 0); num_grid.addWidget(self.muscl_flow_dropdown, 1, 1)
        num_grid.addWidget(QLabel("Turbulence:"),  2, 0); num_grid.addWidget(self.turb_model_dropdown, 2, 1)
        num_grid.addWidget(QLabel("Restart Sol:"), 3, 0); num_grid.addWidget(self.restart_dropdown,    3, 1)
        num_grid.addWidget(QLabel("CFL:"),         4, 0); num_grid.addWidget(self.cfl_spinner,         4, 1)
        num_grid.addWidget(QLabel("Iterations:"),  5, 0); num_grid.addWidget(self.iter_spinner,        5, 1)
        num_grid.setColumnStretch(1, 1)
        layout.addLayout(num_grid)

        sep_c = QFrame(); sep_c.setFrameShape(QFrame.HLine); sep_c.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep_c)

        # ── 4. CUSTOM PLACEHOLDERS ────────────────────────────────────────────
        layout.addWidget(self._make_section_header("CUSTOM PLACEHOLDERS"))

        cp_hint = QLabel(
            "<i>One <code>KEY= value</code> per line. Each key must exist as "
            "<code>KEY=</code> in your template — the generator replaces the "
            "whole line.  Values are written verbatim into every generated .cfg file.</i>"
        )
        cp_hint.setWordWrap(True)
        cp_hint.setTextFormat(Qt.RichText)
        cp_hint.setStyleSheet("color:#555; font-size:10px;")
        layout.addWidget(cp_hint)

        self.custom_placeholders_edit = QTextEdit()
        self.custom_placeholders_edit.setPlaceholderText(
            "Example:\nMULTIGRID= NO\nLINEAR_SOLVER= FGMRES\nTIME_STEP= 0.001"
        )
        self.custom_placeholders_edit.setFixedHeight(100)
        self.custom_placeholders_edit.setFont(QFont("Courier New", 10))
        layout.addWidget(self.custom_placeholders_edit)

        sep_d = QFrame(); sep_d.setFrameShape(QFrame.HLine); sep_d.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep_d)

        # ── 5. MARKERS FOUND IN MESH ──────────────────────────────────────────
        layout.addWidget(self._make_section_header("MARKERS FOUND IN MESH"))

        mesh_hint = QLabel(
            "<i>Auto-populated when you click <b>Load Mesh</b> in the Setup tab "
            "(SU2 files only). Click a marker name to copy it.</i>"
        )
        mesh_hint.setWordWrap(True)
        mesh_hint.setTextFormat(Qt.RichText)
        mesh_hint.setStyleSheet("color:#555; font-size:10px;")
        layout.addWidget(mesh_hint)

        self.found_markers_text = QTextEdit()
        self.found_markers_text.setReadOnly(True)
        self.found_markers_text.setFixedHeight(90)
        self.found_markers_text.setStyleSheet("background:#f0f0f0; border:1px solid #ddd;")
        layout.addWidget(self.found_markers_text)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ── 6. Action buttons: Preview Files | Generate CFG Files ────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        preview_btn = QPushButton("🔍  Preview Files")
        preview_btn.setStyleSheet(
            "background:#1565C0; color:white; font-weight:bold; padding:9px 22px;"
        )
        preview_btn.setToolTip(
            "Preview all cfg filenames — choose Generate Control File or Generate CFG"
        )
        preview_btn.clicked.connect(self.preview_files)

        gen_cfg_btn = QPushButton("⚙  Generate CFG Files")
        gen_cfg_btn.setStyleSheet(
            "background:#2E7D32; color:white; font-weight:bold; padding:9px 22px;"
        )
        gen_cfg_btn.setToolTip("Directly generate all .cfg files without preview")
        gen_cfg_btn.clicked.connect(self._direct_generate_cfg)

        btn_row.addWidget(preview_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(gen_cfg_btn)
        outer.addLayout(btn_row)

        self.sub_tabs.addTab(tab, "Markers & Physics")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Batch Control
    # ══════════════════════════════════════════════════════════════════════════

    def create_batch_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Batch Control File checkbox ───────────────────────────────────────
        layout.addWidget(self._make_section_header("BATCH CONTROL FILE"))

        self.batch_checkbox = QCheckBox("Generate Batch Control File")
        self.batch_checkbox.setChecked(True)

        batch_help_btn = QPushButton("?")
        batch_help_btn.setFixedSize(22, 22)
        batch_help_btn.setCursor(QCursor(Qt.WhatsThisCursor))
        batch_help_btn.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; font-weight:bold;"
            " border-radius:11px; font-size:13px; border:none; }"
            "QPushButton:hover { background:#1565C0; }"
        )
        batch_help_btn.clicked.connect(self._show_batch_help)

        batch_row = QWidget()
        brl = QHBoxLayout(batch_row); brl.setContentsMargins(0, 0, 0, 0); brl.setSpacing(6)
        brl.addWidget(self.batch_checkbox); brl.addWidget(batch_help_btn); brl.addStretch()
        layout.addWidget(batch_row)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine); sep0.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep0)

        # ── Scan existing .cfg folder (collapsible) ───────────────────────────
        self.standalone_toggle_btn = QPushButton("▶  Scan Existing .cfg Folder into Table")
        self.standalone_toggle_btn.setCheckable(True)
        self.standalone_toggle_btn.setChecked(False)
        self.standalone_toggle_btn.setStyleSheet(
            "QPushButton { text-align:left; padding:5px 8px; background:#e8eaf6;"
            " color:#2c3e50; font-weight:bold; font-size:11px;"
            " border:1px solid #c5cae9; border-radius:3px; }"
            "QPushButton:checked { background:#c5cae9; }"
        )
        self.standalone_toggle_btn.toggled.connect(self._toggle_standalone_panel)
        layout.addWidget(self.standalone_toggle_btn)

        self.standalone_panel = QWidget()
        self.standalone_panel.setVisible(False)
        pl = QGridLayout(self.standalone_panel); pl.setContentsMargins(0, 4, 0, 4); pl.setSpacing(4)
        scan_info = QLabel("Scan a folder for .cfg files and load them into the table below.")
        scan_info.setWordWrap(True); scan_info.setStyleSheet("color:#555; font-size:11px;")
        pl.addWidget(scan_info, 0, 0, 1, 4)
        self.standalone_dir_edit = QLineEdit(); self.standalone_dir_edit.setPlaceholderText("Folder containing .cfg files")
        standalone_browse_btn = QPushButton("Browse"); standalone_browse_btn.clicked.connect(self._browse_standalone_dir)
        scan_btn = QPushButton("Scan → Load Table")
        scan_btn.setStyleSheet("background:#6A1B9A; color:white; font-weight:bold; padding:5px 14px;")
        scan_btn.clicked.connect(self._scan_folder_into_table)
        pl.addWidget(QLabel("Cfg Folder:"), 1, 0); pl.addWidget(self.standalone_dir_edit, 1, 1)
        pl.addWidget(standalone_browse_btn, 1, 2);  pl.addWidget(scan_btn, 1, 3)
        layout.addWidget(self.standalone_panel)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1)

        # ── Per-file table ────────────────────────────────────────────────────
        table_hdr = QHBoxLayout()
        table_hdr.addWidget(self._make_section_header("PER-FILE RESTART CONFIGURATION"))
        table_hdr.addStretch()

        apply_all_combo = QComboBox(); apply_all_combo.addItems(['none', 'previous', 'custom'])
        apply_all_btn   = QPushButton("Apply to All")
        apply_all_btn.setStyleSheet("background:#1976D2; color:white; font-weight:bold; padding:3px 10px;")
        apply_all_btn.clicked.connect(lambda: self._apply_restart_to_all(apply_all_combo.currentText()))
        self._apply_all_combo = apply_all_combo

        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setStyleSheet("background:#37474F; color:white; font-weight:bold; padding:3px 10px;")
        refresh_btn.clicked.connect(self._refresh_table)

        table_hdr.addWidget(QLabel("Apply to all:"))
        table_hdr.addWidget(apply_all_combo)
        table_hdr.addWidget(apply_all_btn)
        table_hdr.addSpacing(8)
        table_hdr.addWidget(refresh_btn)
        layout.addLayout(table_hdr)

        hint = QLabel("Populated automatically after Preview → Generate Control File, or Scan → Load Table.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#777; font-size:10px;")
        layout.addWidget(hint)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["Config File", "Restart Option", "Custom Path"])
        hdr = self.preview_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.preview_table.setColumnWidth(0, 320); self.preview_table.setColumnWidth(1, 120)
        self.preview_table.verticalHeader().setDefaultSectionSize(26)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setMinimumHeight(200)
        layout.addWidget(self.preview_table, 1)

        write_ctrl_btn = QPushButton("💾  Write run_control.txt from Table")
        write_ctrl_btn.setStyleSheet("background:#2E7D32; color:white; font-weight:bold; padding:7px 16px;")
        write_ctrl_btn.setToolTip("Write run_control.txt using the restart options in the table")
        write_ctrl_btn.clicked.connect(self._write_control_from_table)
        layout.addWidget(write_ctrl_btn)

        self._batch_cfg_dir: Optional[str]  = None
        self._last_cfg_files: List[str]     = []

        self.sub_tabs.addTab(tab, "Batch Control")

    # ══════════════════════════════════════════════════════════════════════════
    # File-browse helpers
    # ══════════════════════════════════════════════════════════════════════════

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Master Template", "", "Config (*.cfg)")
        if path:
            self.template_edit.setText(path)

    def browse_output_directory(self):
        d = QFileDialog.getExistingDirectory(self, "Select Base Directory", self.output_edit.text())
        if d:
            self.output_edit.setText(d)

    def load_mesh_and_extract_markers(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Mesh File", "",
            "All Mesh Files (*.su2 *.cgns *.med *.msh *.dat *.nas *.bdf *.stl *.vtk *.vtu);;"
            "SU2 Mesh (*.su2);;CGNS (*.cgns);;Gmsh (*.msh *.med);;All Files (*)"
        )
        if not path:
            return
        self.mesh_edit.setText(Path(path).name)
        try:
            if Path(path).suffix.lower() == '.su2':
                markers = self.generator.extract_mesh_markers(Path(path))
                if markers:
                    self.found_markers_text.setPlainText("\n".join(markers))
                    tag_str = f"( {', '.join(markers)} )"
                    self.heat_flux_edit.setText(tag_str)
                    self.monitoring_edit.setText(tag_str)
                    self.plotting_edit.setText(tag_str)
                    self.status_message.emit(f"Loaded {len(markers)} markers from mesh")
                else:
                    self.found_markers_text.setPlainText("No markers found in .su2 file.")
                    self.status_message.emit("No markers found in mesh file")
            else:
                fmt = Path(path).suffix.upper()
                self.found_markers_text.setPlainText(
                    f"Automatic marker extraction is only supported for .su2 files.\n"
                    f"{fmt} detected — enter marker names manually above."
                )
                self.status_message.emit(f"Mesh loaded ({fmt}). Enter markers manually.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load mesh: {str(e)}")

    # ══════════════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════════════

    def update_summary(self):
        try:
            config = self.get_generation_config()
            total = config.get_total_cases()
            m = config.mach_values[0]  if config.mach_values  else 0.0
            a = config.alpha_values[0] if config.alpha_values else 0.0
            b = config.beta_values[0]  if config.beta_values  else 0.0
            preview = self.generator.generate_filename(
                m, a, b, config.altitude, config.base_name,
                config.include_mach, config.include_alpha, config.include_beta,
                config.include_altitude, config.include_base
            )
            self.summary_text.setPlainText(
                f"Total Cases : {total}\n"
                f"Mach        : {len(config.mach_values)} values\n"
                f"Alpha       : {len(config.alpha_values)} values\n"
                f"Beta        : {len(config.beta_values)} values\n"
                f"Template    : {Path(self.template_edit.text()).name}\n"
                f"Output      : {config.output_dir}\n"
                f"Name Preview: {preview}"
            )
        except (ValueError, IndexError) as e:
            self.summary_text.setPlainText(f"Incomplete data: {str(e)}")

    def get_generation_config(self) -> GenerationConfig:
        mach_values  = [float(x) for x in self.mach_edit.text().split()]
        alpha_values = [float(x) for x in self.alpha_edit.text().split()]
        beta_values  = [float(x) for x in self.beta_edit.text().split()]
        if not mach_values or not alpha_values or not beta_values:
            raise ValueError("Mach, Alpha, and Beta must have at least one value")
        output_dir    = Path(self.output_edit.text()) / self.folder_edit.text()
        template_path = Path(self.template_edit.text())
        return GenerationConfig(
            mach_values=mach_values, alpha_values=alpha_values, beta_values=beta_values,
            include_mach=self.inc_mach.isChecked(), include_alpha=self.inc_alpha.isChecked(),
            include_beta=self.inc_beta.isChecked(), include_altitude=self.inc_alt.isChecked(),
            include_base=self.inc_base.isChecked(), altitude=self.altitude_dropdown.currentText(),
            base_name=self.base_edit.text(), output_dir=output_dir, template_path=template_path
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Preview → two-action dialog
    # ══════════════════════════════════════════════════════════════════════════

    def preview_files(self):
        """Open the Preview dialog; user picks Generate Control File or Generate CFG."""
        try:
            config = self.get_generation_config()
            is_valid, error_msg = self.generator.validate_config(config)
            if not is_valid:
                QMessageBox.critical(self, "Validation Error", error_msg)
                return

            filenames = self.generator.generate_all_filenames(config)
            dlg = PreviewDialog(filenames, config.output_dir, self)
            if dlg.exec_() != QDialog.Accepted:
                return

            if dlg.action == PreviewDialog.ACTION_CTRL_FILE:
                self._generate_control_file_only(config, filenames)
            elif dlg.action == PreviewDialog.ACTION_GENERATE_CFG:
                self.perform_generation(config, filenames)

        except Exception as e:
            QMessageBox.critical(self, "Preview Error", f"Failed to generate preview:\n{str(e)}")

    def _direct_generate_cfg(self):
        """Generate CFG files directly without the preview dialog."""
        try:
            config = self.get_generation_config()
            is_valid, error_msg = self.generator.validate_config(config)
            if not is_valid:
                QMessageBox.critical(self, "Validation Error", error_msg)
                return
            filenames = self.generator.generate_all_filenames(config)
            self.perform_generation(config, filenames)
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to generate files:\n{str(e)}")

    def _generate_control_file_only(self, config: GenerationConfig, filenames: List[str]):
        """
        Write run_control.txt (no .cfg files), populate Batch Control table,
        and switch to the Batch Control tab.
        """
        try:
            ensure_directory(config.output_dir)
            ctrl_path = config.output_dir / "run_control.txt"
            lines = [f"{fname}, none\n" for fname in filenames]
            with open(ctrl_path, "w") as fh:
                fh.writelines(lines)

            # Populate Batch Control table
            self._batch_cfg_dir    = str(config.output_dir)
            self._last_cfg_files   = list(filenames)
            self._populate_preview_table(list(filenames), "none")

            # Switch to Batch Control tab (index 2)
            self.sub_tabs.setCurrentIndex(2)

            self.status_message.emit(
                f"run_control.txt written ({len(filenames)} entries) — review in Batch Control tab"
            )
            QMessageBox.information(
                self, "Control File Written",
                f"run_control.txt written with {len(filenames)} entries.\n"
                f"Path: {ctrl_path}\n\n"
                "The Batch Control tab is now populated.\n"
                "Adjust per-file restart options, then click "
                "\"Write run_control.txt from Table\" to finalize."
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to write control file:\n{str(e)}")

    # ══════════════════════════════════════════════════════════════════════════
    # Actual CFG generation
    # ══════════════════════════════════════════════════════════════════════════

    def perform_generation(self, config: GenerationConfig, filenames: List[str]):
        """Write .cfg files to disk."""
        try:
            template_content = read_template_file(config.template_path)
            if template_content is None:
                raise ValueError("Failed to read template file")

            ensure_directory(config.output_dir)

            progress = QProgressDialog(
                "Generating configuration files...", "Cancel", 0, len(filenames), self
            )
            progress.setWindowModality(Qt.WindowModal)

            files_created = []
            for i, (m, a, b) in enumerate(
                (m, a, b)
                for m in config.mach_values
                for a in config.alpha_values
                for b in config.beta_values
            ):
                if progress.wasCanceled():
                    break

                fname = filenames[i]

                # Build parameter dict — only include markers that are enabled
                parameters = {
                    "KIND_TURB_MODEL":          self.turb_model_dropdown.currentText(),
                    "RESTART_SOL":              self.restart_dropdown.currentText(),
                    "MACH_NUMBER":              f"{m:.1f}",
                    "AOA":                      f"{a:.1f}",
                    "SIDESLIP_ANGLE":           f"{b:.1f}",
                    "FREESTREAM_TEMPERATURE":   f"{float(self.temp_edit.text()):.2f}",
                    "REYNOLDS_NUMBER":          f"{float(self.reynolds_edit.text()):.0f}",
                    "REYNOLDS_LENGTH":          self.rey_len.text(),
                    "REF_ORIGIN_MOMENT_X":      self.ref_origin_x.text(),
                    "REF_ORIGIN_MOMENT_Y":      self.ref_origin_y.text(),
                    "REF_ORIGIN_MOMENT_Z":      self.ref_origin_z.text(),
                    "REF_LENGTH":               self.ref_len.text(),
                    "REF_AREA":                 self.ref_area.text(),
                    "CFL_NUMBER":               f"{self.cfl_spinner.value():.1f}",
                    "ITER":                     str(self.iter_spinner.value()),
                    "CONV_NUM_METHOD_FLOW":     self.conv_dropdown.currentText(),
                    "MUSCL_FLOW":               self.muscl_flow_dropdown.currentText(),
                    "MESH_FILENAME":            self.mesh_edit.text(),
                    "BREAKDOWN_FILENAME":       f"{Path(fname).stem}_FB.dat",
                }

                # Markers — checked: write value; unchecked: remove line from cfg
                _RM = SU2Generator.REMOVE_LINE
                parameters["MARKER_HEATFLUX"]  = self.heat_flux_edit.text()  if self.use_heat_flux.isChecked()  else _RM
                parameters["MARKER_FAR"]        = self.far_field_edit.text()  if self.use_far_field.isChecked()  else _RM
                parameters["MARKER_PLOTTING"]   = self.plotting_edit.text()   if self.use_plotting.isChecked()   else _RM
                parameters["MARKER_MONITORING"] = self.monitoring_edit.text() if self.use_monitoring.isChecked() else _RM

                # Custom placeholders — if key exists in template: replaced in-place;
                # if key is NEW (e.g. MARKER_ISOTHERMAL): appended at end of cfg.
                custom_params = self.parse_custom_placeholders()
                parameters.update(custom_params)

                content = self.generator.update_template_content(template_content, parameters)

                output_path = config.output_dir / fname
                write_config_file(output_path, content)
                files_created.append(fname)
                progress.setValue(i + 1)

            progress.close()

            if self.batch_checkbox.isChecked():
                self._batch_cfg_dir  = str(config.output_dir)
                self._last_cfg_files = files_created
                self._populate_preview_table(files_created, "none")
                self.sub_tabs.setCurrentIndex(2)  # switch to Batch Control

            QMessageBox.information(
                self, "Success",
                f"Successfully generated {len(files_created)} configuration files.\n"
                f"Output: {config.output_dir}\n\n"
                "Batch Control tab is now populated — adjust restart options then click\n"
                "\"Write run_control.txt from Table\"."
            )
            self.status_message.emit(f"Generated {len(files_created)} files")

        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"File generation failed:\n{str(e)}")

    # ══════════════════════════════════════════════════════════════════════════
    # Batch Control helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _show_batch_help(self):
        BatchControlHelpDialog(self).exec_()

    def _toggle_standalone_panel(self, checked: bool):
        self.standalone_panel.setVisible(checked)
        self.standalone_toggle_btn.setText(
            ("▼" if checked else "▶") + "  Scan Existing .cfg Folder into Table"
        )

    def _browse_standalone_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with .cfg Files")
        if folder:
            self.standalone_dir_edit.setText(folder)

    def _refresh_table(self):
        if not self._batch_cfg_dir or not os.path.isdir(self._batch_cfg_dir):
            scan_folder = self.standalone_dir_edit.text().strip()
            if scan_folder and os.path.isdir(scan_folder):
                self._batch_cfg_dir = scan_folder
            else:
                QMessageBox.information(
                    self, "Nothing to Refresh",
                    "No cfg directory is set yet.\nGenerate config files or scan a folder first."
                )
                return
        cfg_files = sorted(f for f in os.listdir(self._batch_cfg_dir) if f.endswith(".cfg"))
        if not cfg_files:
            QMessageBox.warning(self, "No .cfg Files", f"No .cfg files found in:\n{self._batch_cfg_dir}")
            return
        self._last_cfg_files = cfg_files
        restart_data = self._read_restart_options_from_cfgs(self._batch_cfg_dir, cfg_files)
        self._populate_preview_table_with_data(cfg_files, restart_data)
        self.status_message.emit(f"Table refreshed: {len(cfg_files)} cfg files")

    def _read_restart_options_from_cfgs(self, folder: str, cfg_files: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for fname in cfg_files:
            path   = os.path.join(folder, fname)
            option = "none"
            try:
                with open(path, "r") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped.upper().startswith("RESTART_SOL"):
                            value  = stripped.split("=", 1)[-1].strip().upper()
                            option = "previous" if value == "YES" else "none"
                            break
            except Exception:
                pass
            result[fname] = option
        return result

    def _scan_folder_into_table(self):
        folder = self.standalone_dir_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Missing Folder", "Please select the folder containing .cfg files.")
            return
        cfg_files = sorted(f for f in os.listdir(folder) if f.endswith(".cfg"))
        if not cfg_files:
            QMessageBox.warning(self, "No .cfg Files", f"No .cfg files found in:\n{folder}")
            return
        self._batch_cfg_dir  = folder
        self._last_cfg_files = cfg_files
        restart_data = self._read_restart_options_from_cfgs(folder, cfg_files)
        self._populate_preview_table_with_data(cfg_files, restart_data)
        self.status_message.emit(f"Scanned {len(cfg_files)} cfg files from {folder}")

    def _populate_preview_table_with_data(self, cfg_files, restart_data, default_custom=""):
        self.preview_table.setRowCount(0)
        self.preview_table.setRowCount(len(cfg_files))
        for row, fname in enumerate(cfg_files):
            item = QTableWidgetItem(fname)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.preview_table.setItem(row, 0, item)

            option = restart_data.get(fname, "none")
            combo  = QComboBox()
            combo.addItems(['none', 'previous', 'custom'])
            combo.setCurrentText(option)
            combo.currentTextChanged.connect(lambda opt, r=row: self._on_row_restart_changed(r, opt))
            self.preview_table.setCellWidget(row, 1, combo)

            path_edit = QLineEdit()
            path_edit.setPlaceholderText("Custom restart file path")
            path_edit.setText(default_custom)
            path_edit.setEnabled(option == "custom")
            path_edit.setStyleSheet("background:#fafafa;")
            self.preview_table.setCellWidget(row, 2, path_edit)
        self.preview_table.resizeRowsToContents()

    def _populate_preview_table(self, cfg_files, default_option="none", default_custom=""):
        self._populate_preview_table_with_data(
            cfg_files,
            {fname: default_option for fname in cfg_files},
            default_custom
        )

    def _on_row_restart_changed(self, row, option):
        path_edit = self.preview_table.cellWidget(row, 2)
        if path_edit:
            path_edit.setEnabled(option == "custom")
        if self._batch_cfg_dir:
            cfg_item = self.preview_table.item(row, 0)
            if cfg_item:
                self._patch_restart_sol(
                    os.path.join(self._batch_cfg_dir, cfg_item.text()),
                    option in ("previous", "custom")
                )

    def _patch_restart_sol(self, cfg_path, needs_restart):
        if not os.path.isfile(cfg_path):
            return
        try:
            with open(cfg_path, "r") as fh:
                lines = fh.readlines()
            new_value = "YES" if needs_restart else "NO"
            found, new_lines = False, []
            for line in lines:
                if line.strip().upper().startswith("RESTART_SOL"):
                    new_lines.append(f"RESTART_SOL= {new_value}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"RESTART_SOL= {new_value}\n")
            with open(cfg_path, "w") as fh:
                fh.writelines(new_lines)
            self.status_message.emit(f"RESTART_SOL={new_value} → {Path(cfg_path).name}")
        except Exception as exc:
            print(f"[AeroSuite] Could not patch {cfg_path}: {exc}")

    def _apply_restart_to_all(self, option):
        for row in range(self.preview_table.rowCount()):
            combo = self.preview_table.cellWidget(row, 1)
            if combo:
                combo.setCurrentText(option)

    def _write_control_from_table(self):
        n = self.preview_table.rowCount()
        if n == 0:
            QMessageBox.warning(self, "Empty Table",
                                "The table is empty.\nGenerate config files or scan a folder first.")
            return
        if not self._batch_cfg_dir or not os.path.isdir(self._batch_cfg_dir):
            QMessageBox.warning(self, "No Output Dir",
                                "Cannot determine output directory. Generate or scan a folder first.")
            return

        lines, restart_yes, restart_no = [], [], []
        for row in range(n):
            cfg_item  = self.preview_table.item(row, 0)
            combo     = self.preview_table.cellWidget(row, 1)
            path_edit = self.preview_table.cellWidget(row, 2)
            if not cfg_item or not combo:
                continue
            fname  = cfg_item.text()
            option = combo.currentText()
            custom = path_edit.text().strip() if path_edit else ""

            if option == "custom":
                if not custom:
                    QMessageBox.warning(self, "Missing Custom Path",
                                        f"Row {row+1} ({fname}) has 'custom' but no path.")
                    return
                lines.append(f"{fname}, {option}, {custom}\n")
            else:
                lines.append(f"{fname}, {option}\n")

            needs_restart = option in ("previous", "custom")
            self._patch_restart_sol(os.path.join(self._batch_cfg_dir, fname), needs_restart)
            (restart_yes if needs_restart else restart_no).append(fname)

        ctrl_path = os.path.join(self._batch_cfg_dir, "run_control.txt")
        try:
            with open(ctrl_path, "w") as fh:
                fh.writelines(lines)
        except Exception as exc:
            QMessageBox.critical(self, "Write Failed", str(exc))
            return

        QMessageBox.information(
            self, "Control File Written",
            f"run_control.txt written with {n} entries:\n{ctrl_path}\n\n"
            f"RESTART_SOL= YES: {len(restart_yes)} file(s)\n"
            f"RESTART_SOL= NO:  {len(restart_no)} file(s)"
        )
        self.status_message.emit(f"run_control.txt written: {n} cases → {ctrl_path}")
        self.generation_complete.emit(self._batch_cfg_dir, ctrl_path)

    # ══════════════════════════════════════════════════════════════════════════
    # Custom placeholder parser
    # ══════════════════════════════════════════════════════════════════════════

    def parse_custom_placeholders(self) -> Dict[str, str]:
        """
        Parse KEY= value lines from the custom placeholders box.
        Each key is substituted verbatim into the template — the generator
        uses regex to replace lines starting with KEY= , so the key MUST
        appear as a top-level assignment in the template file.
        """
        custom_params: Dict[str, str] = {}
        text = self.custom_placeholders_edit.toPlainText().strip()
        if not text:
            return custom_params
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                parts = line.split("=", 1)
                key, value = parts[0].strip(), parts[1].strip()
                if key:
                    custom_params[key] = value
        return custom_params

    # ══════════════════════════════════════════════════════════════════════════
    # Cross-tab wiring (called by main window)
    # ══════════════════════════════════════════════════════════════════════════

    def update_from_isa(self, altitude: str, temperature: str, reynolds: str):
        self.altitude_dropdown.setCurrentText(altitude)
        self.temp_edit.setText(temperature)
        self.reynolds_edit.setText(reynolds)
        self.update_summary()

    def set_cfg_paths(self, cfg_dir: str, ctrl_file: str):
        """Called by SweepTab to pre-fill paths (if needed)."""
        pass  # Sweep tab receives these via generation_complete signal

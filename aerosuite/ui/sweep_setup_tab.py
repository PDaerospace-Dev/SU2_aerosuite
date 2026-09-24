"""
Sweep Tab UI (freestream setup).

Self-contained: loads its own base .cfg file at the top and substitutes
per-case freestream values (Mach/Alpha/Beta/Temp/Reynolds) into it for
every case in the sweep — it does not depend on the CFG page at all.
Working directory / output folder still comes from the Directory page.
"""

import os
from pathlib import Path
from typing import List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QCheckBox, QComboBox, QFileDialog, QMessageBox,
    QFrame, QProgressDialog
)
from PyQt5.QtCore import Qt, pyqtSignal

from ..core.su2_generator import SU2Generator, GenerationConfig
from ..engine.naming import format_value
from ..utils.file_handlers import read_template_file, write_config_file, ensure_directory
from .style import section_label, PRIMARY_BUTTON_STYLE


class SweepSetupTab(QWidget):
    """Load a base .cfg + freestream range setup + full-sweep generation."""

    status_message      = pyqtSignal(str)
    configs_generated    = pyqtSignal(str)         # cfg_dir
    generation_complete  = pyqtSignal(str, str)     # cfg_dir, ctrl_file

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory_source = None
        self.setup_ui()

    def set_directory_source(self, directory_tab):
        """Link to the Directory page so this page never needs its own working-dir field."""
        self._directory_source = directory_tab

    @staticmethod
    def _section(text: str) -> QLabel:
        return section_label(text)

    def setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(self._section("BASE CFG FILE"), 0, 0, 1, 3)

        self.base_cfg_edit = QLineEdit("")
        self.base_cfg_edit.setPlaceholderText(".cfg file to use as the base for every case in this sweep")
        browse_cfg_btn = QPushButton("Load CFG File")
        browse_cfg_btn.clicked.connect(self.browse_base_cfg)
        layout.addWidget(QLabel("Cfg File:"), 1, 0); layout.addWidget(self.base_cfg_edit, 1, 1); layout.addWidget(browse_cfg_btn, 1, 2)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine); sep0.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep0, 2, 0, 1, 3)

        layout.addWidget(self._section("FREESTREAM SWEEP"), 3, 0, 1, 3)

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

        layout.addWidget(QLabel("Mach Numbers:"), 4,  0); layout.addWidget(self.mach_edit,          4,  1); layout.addWidget(self.inc_mach,  4,  2)
        layout.addWidget(QLabel("Alpha Values:"),  5,  0); layout.addWidget(self.alpha_edit,         5,  1); layout.addWidget(self.inc_alpha, 5,  2)
        layout.addWidget(QLabel("Beta Values:"),   6,  0); layout.addWidget(self.beta_edit,          6,  1); layout.addWidget(self.inc_beta,  6,  2)
        layout.addWidget(QLabel("Altitude:"),      7, 0);  layout.addWidget(self.altitude_dropdown,  7, 1);  layout.addWidget(self.inc_alt,   7, 2)
        layout.addWidget(QLabel("Config Name:"),   8, 0);  layout.addWidget(self.base_edit,          8, 1);  layout.addWidget(self.inc_base,  8, 2)
        layout.addWidget(QLabel("Temp (K):"),      9, 0);  layout.addWidget(self.temp_edit,          9, 1)
        layout.addWidget(QLabel("Reynolds No:"),   10, 0); layout.addWidget(self.reynolds_edit,      10, 1)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep, 11, 0, 1, 3)

        layout.addWidget(self._section("CONFIGURATION SUMMARY"), 12, 0, 1, 3)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(110)
        self.summary_text.setMaximumHeight(160)
        layout.addWidget(self.summary_text, 13, 0, 1, 3)

        for w in [self.mach_edit, self.alpha_edit, self.beta_edit, self.temp_edit,
                  self.reynolds_edit, self.base_edit]:
            w.textChanged.connect(self.update_summary)
        self.altitude_dropdown.currentTextChanged.connect(self.update_summary)
        for cb in [self.inc_base, self.inc_mach, self.inc_alpha, self.inc_beta, self.inc_alt]:
            cb.stateChanged.connect(self.update_summary)

        gen_btn = QPushButton("⚙  Generate Sweep Configs")
        gen_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        gen_btn.setToolTip("Generate all .cfg files for the full Mach × Alpha × Beta sweep")
        gen_btn.clicked.connect(self.generate_sweep_configs)
        layout.addWidget(gen_btn, 14, 0, 1, 3)

        layout.setRowStretch(15, 1)
        self.update_summary()

    # ── Base cfg ─────────────────────────────────────────────────────────────

    def browse_base_cfg(self):
        default_dir = ""
        if self._directory_source is not None and self._directory_source.get_workdir():
            default_dir = self._directory_source.get_workdir()
        path, _ = QFileDialog.getOpenFileName(self, "Load Base CFG File", default_dir, "Config (*.cfg);;All Files (*)")
        if path:
            self.base_cfg_edit.setText(path)
            self.status_message.emit(f"Base cfg loaded: {path}")

    # ── Summary ──────────────────────────────────────────────────────────────

    def update_summary(self):
        try:
            mach_values  = [float(x) for x in self.mach_edit.text().split()]
            alpha_values = [float(x) for x in self.alpha_edit.text().split()]
            beta_values  = [float(x) for x in self.beta_edit.text().split()]
            total = max(len(mach_values), 1) * max(len(alpha_values), 1) * max(len(beta_values), 1)
            out_dir = self._directory_source.get_output_dir() if self._directory_source else "(set on Directory page)"
            self.summary_text.setPlainText(
                f"Cases: {total}\n"
                f"Mach:  {mach_values or '—'}\n"
                f"Alpha: {alpha_values or '—'}\n"
                f"Beta:  {beta_values or '—'}\n"
                f"Altitude: {self.altitude_dropdown.currentText()}\n"
                f"Output dir: {out_dir}"
            )
        except Exception:
            self.summary_text.setPlainText("(enter valid numeric ranges, space-separated)")

    # ── Generation ───────────────────────────────────────────────────────────

    def _parse_ranges(self):
        try:
            mach_values = [float(x) for x in self.mach_edit.text().split()]
        except ValueError:
            raise ValueError("Mach: invalid number format")
        try:
            alpha_values = [float(x) for x in self.alpha_edit.text().split()]
        except ValueError:
            raise ValueError("Alpha: invalid number format")
        try:
            beta_values = [float(x) for x in self.beta_edit.text().split()]
        except ValueError:
            raise ValueError("Beta: invalid number format")
        return mach_values or [0.0], alpha_values or [0.0], beta_values or [0.0]

    def generate_sweep_configs(self):
        if self._directory_source is None:
            QMessageBox.warning(self, "Not Linked", "Sweep page is not linked to the Directory page.")
            return

        base_cfg_str = self.base_cfg_edit.text().strip()
        if not base_cfg_str or not Path(base_cfg_str).exists():
            QMessageBox.warning(self, "No Base CFG", "Load a base .cfg file at the top of this page first.")
            return
        base_cfg_path = Path(base_cfg_str)

        workdir = self._directory_source.get_workdir()
        if not workdir:
            QMessageBox.warning(self, "No Working Directory", "Set the working directory on the Directory page first.")
            return

        try:
            mach_values, alpha_values, beta_values = self._parse_ranges()
        except ValueError as e:
            QMessageBox.critical(self, "Invalid Range", str(e))
            return

        config = GenerationConfig(
            mach_values=mach_values, alpha_values=alpha_values, beta_values=beta_values,
            include_mach=self.inc_mach.isChecked(), include_alpha=self.inc_alpha.isChecked(),
            include_beta=self.inc_beta.isChecked(), include_altitude=self.inc_alt.isChecked(),
            include_base=self.inc_base.isChecked(),
            altitude=self.altitude_dropdown.currentText(), base_name=self.base_edit.text(),
            output_dir=self._directory_source.get_output_dir(), template_path=base_cfg_path,
        )

        is_valid, error_msg = SU2Generator.validate_config(config)
        if not is_valid:
            QMessageBox.critical(self, "Validation Error", error_msg)
            return

        filenames = SU2Generator.generate_all_filenames(config)

        try:
            template_content = read_template_file(config.template_path)
            if template_content is None:
                raise ValueError("Failed to read base cfg file")
            ensure_directory(config.output_dir)

            progress = QProgressDialog("Generating configuration files...", "Cancel", 0, len(filenames), self)
            progress.setWindowModality(Qt.WindowModal)

            files_created: List[str] = []

            for i, (m, a, b) in enumerate(
                (m, a, b) for m in config.mach_values for a in config.alpha_values for b in config.beta_values
            ):
                if progress.wasCanceled():
                    break
                fname = filenames[i]
                parameters = {
                    "MACH_NUMBER":            format_value(m),
                    "AOA":                    format_value(a),
                    "SIDESLIP_ANGLE":         format_value(b),
                    "FREESTREAM_TEMPERATURE": f"{float(self.temp_edit.text()):.2f}" if self.temp_edit.text().strip() else "288.15",
                    "REYNOLDS_NUMBER":        f"{float(self.reynolds_edit.text()):.0f}" if self.reynolds_edit.text().strip() else "1000000",
                    "BREAKDOWN_FILENAME":     f"{Path(fname).stem}_FB.dat",
                }
                content = SU2Generator.update_template_content(template_content, parameters)
                write_config_file(config.output_dir / fname, content)
                files_created.append(fname)
                progress.setValue(i + 1)

            progress.close()

            QMessageBox.information(
                self, "Success",
                f"Generated {len(files_created)} configuration files.\nOutput: {config.output_dir}\n\n"
                "Head to the Control File page to write run_control.txt when you're ready."
            )
            self.status_message.emit(f"Generated {len(files_created)} sweep configs in {config.output_dir}")
            self.configs_generated.emit(str(config.output_dir))

        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"File generation failed:\n{str(e)}")

    # ── Cross-tab wiring ─────────────────────────────────────────────────────

    def update_from_isa(self, altitude: str, temperature: str, reynolds: str):
        self.altitude_dropdown.setCurrentText(altitude)
        self.temp_edit.setText(temperature)
        self.reynolds_edit.setText(reynolds)
        self.update_summary()

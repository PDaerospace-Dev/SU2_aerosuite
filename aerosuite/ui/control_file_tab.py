"""
Control File Tab UI.

Scans a folder of .cfg files (defaulting to the working directory set on
the Mesh page) into a per-file restart-configuration table, and writes
run_control.txt from that table.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QMessageBox, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt, pyqtSignal

from .style import section_label, hint_label, INFO_BOX_STYLE, TOGGLE_BUTTON_STYLE, HINT_LABEL_STYLE, PRIMARY_BUTTON_STYLE


class ControlFileTab(QWidget):
    """Scan .cfg folder -> per-file restart table -> write run_control.txt."""

    status_message      = pyqtSignal(str)
    generation_complete  = pyqtSignal(str, str)   # cfg_dir, ctrl_file

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory_source = None
        self._batch_cfg_dir: Optional[str] = None
        self._last_cfg_files: List[str] = []
        self._info_expanded = False
        self.setup_ui()

    def set_directory_source(self, directory_tab):
        self._directory_source = directory_tab

    @staticmethod
    def _section(text: str) -> QLabel:
        return section_label(text)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(self._section("SCAN FOLDER"))

        scan_row = QGridLayout(); scan_row.setSpacing(4)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Folder containing .cfg files (defaults to Mesh page's working directory)")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_dir)
        use_workdir_btn = QPushButton("Use Working Directory")
        use_workdir_btn.setToolTip("Fill in the working directory set on the Mesh page")
        use_workdir_btn.clicked.connect(self._use_workdir)
        scan_btn = QPushButton("🔍  Scan → Load Table")
        scan_btn.clicked.connect(self._scan_folder_into_table)

        scan_row.addWidget(QLabel("Cfg Folder:"), 0, 0)
        scan_row.addWidget(self.dir_edit, 0, 1)
        scan_row.addWidget(browse_btn, 0, 2)
        scan_row.addWidget(use_workdir_btn, 1, 1)
        scan_row.addWidget(scan_btn, 1, 2)
        layout.addLayout(scan_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        self.info_toggle_btn = QPushButton("▸  What is a control file?")
        self.info_toggle_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        self.info_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.info_toggle_btn.clicked.connect(self._toggle_info)
        layout.addWidget(self.info_toggle_btn)

        self.info_body = QWidget()
        info_layout = QVBoxLayout(self.info_body)
        info_layout.setContentsMargins(0, 4, 0, 0)
        explain = QLabel(
            "A plain-text file that tells AeroSuite the <b>execution order</b> and "
            "<b>restart behaviour</b> for every case in the sweep.<br><br>"
            "<b>Format:</b> one line per case — "
            "<code>&lt;config.cfg&gt;, restart_option, [optional_restart_path]</code><br>"
            "<b>restart_option:</b> <code>none</code> (start fresh) | <code>previous</code> "
            "(RESTART_SOL= YES, uses that case's own restart file) | <code>custom</code> "
            "(RESTART_SOL= YES, uses the path you specify)<br><br>"
            "<b>Example:</b><br>"
            "<code>ht_M0p3_A0_B0_sl.cfg,   none<br>"
            "ht_M0p3_A5_B0_sl.cfg,   previous<br>"
            "ht_M0p6_A0_B0_sl.cfg,   custom,   /data/restart_flow.dat</code>"
        )
        explain.setWordWrap(True)
        explain.setTextFormat(Qt.RichText)
        explain.setStyleSheet(INFO_BOX_STYLE)
        info_layout.addWidget(explain)
        layout.addWidget(self.info_body)
        self.info_body.setVisible(False)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        table_hdr = QHBoxLayout()
        table_hdr.addWidget(self._section("PER-FILE RESTART CONFIGURATION"))
        table_hdr.addStretch()

        self._apply_all_combo = QComboBox(); self._apply_all_combo.addItems(['none', 'previous', 'custom'])
        apply_all_btn = QPushButton("Apply to All")
        apply_all_btn.clicked.connect(lambda: self._apply_restart_to_all(self._apply_all_combo.currentText()))

        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.clicked.connect(self._refresh_table)

        table_hdr.addWidget(QLabel("Apply to all:"))
        table_hdr.addWidget(self._apply_all_combo)
        table_hdr.addWidget(apply_all_btn)
        table_hdr.addSpacing(8)
        table_hdr.addWidget(refresh_btn)
        layout.addLayout(table_hdr)

        hint = QLabel("Populated after Scan → Load Table, or automatically after generating a sweep.")
        hint.setWordWrap(True); hint.setStyleSheet(HINT_LABEL_STYLE)
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
        self.preview_table.setMinimumHeight(220)
        layout.addWidget(self.preview_table, 1)

        write_ctrl_btn = QPushButton("💾  Write run_control.txt from Table")
        write_ctrl_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        write_ctrl_btn.setToolTip("Write run_control.txt using the restart options in the table")
        write_ctrl_btn.clicked.connect(self._write_control_from_table)
        layout.addWidget(write_ctrl_btn)

    def _toggle_info(self):
        self._info_expanded = not self._info_expanded
        self.info_body.setVisible(self._info_expanded)
        self.info_toggle_btn.setText(("▾  " if self._info_expanded else "▸  ") + "What is a control file?")

    # ── Directory helpers ────────────────────────────────────────────────────

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Cfg Folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _use_workdir(self):
        if self._directory_source is not None and self._directory_source.get_workdir():
            self.dir_edit.setText(str(self._directory_source.get_output_dir()))
        else:
            QMessageBox.information(self, "No Working Directory", "Set the working directory on the Mesh page first.")

    def prefill_dir(self, path: str):
        """Called by main window after a sweep is generated elsewhere."""
        self.dir_edit.setText(path)

    # ── Scan / table population ─────────────────────────────────────────────

    def _read_restart_options_from_cfgs(self, folder: str, cfg_files: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for fname in cfg_files:
            path = os.path.join(folder, fname)
            option = "none"
            try:
                with open(path, "r") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped.upper().startswith("RESTART_SOL"):
                            value = stripped.split("=", 1)[-1].strip().upper()
                            option = "previous" if value == "YES" else "none"
                            break
            except Exception:
                pass
            result[fname] = option
        return result

    def _scan_folder_into_table(self):
        folder = self.dir_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Missing Folder", "Please select the folder containing .cfg files.")
            return
        cfg_files = sorted(f for f in os.listdir(folder) if f.endswith(".cfg"))
        if not cfg_files:
            QMessageBox.warning(self, "No .cfg Files", f"No .cfg files found in:\n{folder}")
            return
        self._batch_cfg_dir = folder
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
            combo = QComboBox()
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
        self._populate_preview_table_with_data(cfg_files, {f: default_option for f in cfg_files}, default_custom)

    def _refresh_table(self):
        if self._batch_cfg_dir and os.path.isdir(self._batch_cfg_dir):
            cfg_files = sorted(f for f in os.listdir(self._batch_cfg_dir) if f.endswith(".cfg"))
            restart_data = self._read_restart_options_from_cfgs(self._batch_cfg_dir, cfg_files)
            self._populate_preview_table_with_data(cfg_files, restart_data)
            self.status_message.emit(f"Table refreshed: {len(cfg_files)} cfg files")

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
            QMessageBox.warning(self, "Empty Table", "The table is empty.\nScan a folder first.")
            return
        if not self._batch_cfg_dir or not os.path.isdir(self._batch_cfg_dir):
            QMessageBox.warning(self, "No Output Dir", "Cannot determine output directory. Scan a folder first.")
            return

        lines, restart_yes, restart_no = [], [], []
        for row in range(n):
            cfg_item = self.preview_table.item(row, 0)
            combo = self.preview_table.cellWidget(row, 1)
            path_edit = self.preview_table.cellWidget(row, 2)
            if not cfg_item or not combo:
                continue
            fname = cfg_item.text()
            option = combo.currentText()
            custom = path_edit.text().strip() if path_edit else ""

            if option == "custom":
                if not custom:
                    QMessageBox.warning(self, "Missing Custom Path", f"Row {row+1} ({fname}) has 'custom' but no path.")
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

"""
Sweep Runner Tab UI.

Launches the sweep script (aoa_sweep_v8.py or compatible) from inside
the config directory, exactly as it was used from the terminal.

GUI responsibilities
--------------------
- Input fields: sweep script, config dir, control file, partitions
- Execution plan table populated by "Load Plan"
- Run / Stop buttons
- Live status table shown immediately when Run is pressed
- Status column: In Queue → Running… → SUCCESS / FAILED / STOPPED
- Status bar updates via status_message signal
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QSettings, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.sweep_runner import SweepRunner, parse_control_file


# ── Status display helpers ────────────────────────────────────────────────────

_STATUS_DISPLAY = {
    "QUEUED":   ("⏳  In Queue",   QColor("#f5f5f5"),  QColor("#757575")),
    "RUNNING":  ("🔄  Running…",   QColor("#e3f2fd"),  QColor("#1565c0")),
    "SUCCESS":  ("✓   SUCCESS",    QColor("#e8f5e9"),  QColor("#2e7d32")),
    "FAILED":   ("✗   FAILED",     QColor("#ffebee"),  QColor("#c62828")),
    "STOPPED":  ("⊘   Stopped",    QColor("#fff3e0"),  QColor("#e65100")),
    "NOT RUN":  ("–   Not Run",    QColor("#fafafa"),  QColor("#9e9e9e")),
}


def _status_item(status: str, text_override: str = "") -> QTableWidgetItem:
    display, bg, fg = _STATUS_DISPLAY.get(status, _STATUS_DISPLAY["NOT RUN"])
    item = QTableWidgetItem(text_override or display)
    item.setBackground(bg)
    item.setForeground(fg)
    return item


# ── Background worker ─────────────────────────────────────────────────────────

class _SweepWorker(QThread):
    """Runs SweepRunner.run() in a background thread."""

    finished     = pyqtSignal(list)   # List[Dict] results
    errored      = pyqtSignal(str)    # error message string
    case_status  = pyqtSignal(str, str)  # (cfg_file, status)

    def __init__(self, runner: SweepRunner, parent=None):
        super().__init__(parent)
        self.runner = runner

    def run(self):
        # Wire the runner callback to emit our Qt signal (thread-safe)
        self.runner.case_status_cb = lambda cfg, st: self.case_status.emit(cfg, st)
        try:
            results = self.runner.run()
            self.finished.emit(results)
        except Exception as exc:
            self.errored.emit(str(exc))


# ── Tab widget ────────────────────────────────────────────────────────────────

class SweepTab(QWidget):
    """Sweep Runner tab."""

    status_message = pyqtSignal(str)
    _SETTINGS_KEY  = "sweep_runner/script_path"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker:       Optional[_SweepWorker] = None
        self._case_row_map: Dict[str, int]         = {}   # cfg_file → summary row
        self._settings = QSettings("AeroSuite", "AeroSuitePro")
        self._build_ui()
        saved = self._settings.value(self._SETTINGS_KEY, "")
        if saved and os.path.isfile(saved):
            self.script_edit.setText(saved)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── 1. Inputs ─────────────────────────────────────────────────────
        root.addWidget(_section_header("INPUTS"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(0, 100)
        grid.setColumnStretch(1, 1)

        # Sweep script
        self.script_edit = QLineEdit()
        self.script_edit.setPlaceholderText("Path to aoa_sweep_v8.py")
        self.script_edit.editingFinished.connect(
            lambda: self._settings.setValue(self._SETTINGS_KEY, self.script_edit.text().strip())
        )
        btn_script = _browse_btn()
        btn_script.clicked.connect(self._browse_script)
        grid.addWidget(QLabel("Sweep Script:"), 0, 0)
        grid.addWidget(self.script_edit,        0, 1)
        grid.addWidget(btn_script,              0, 2)

        # Config directory
        self.cfg_dir_edit = QLineEdit()
        self.cfg_dir_edit.setPlaceholderText("Directory containing .cfg files and control file")
        btn_cfg = _browse_btn()
        btn_cfg.clicked.connect(self._browse_cfg_dir)
        grid.addWidget(QLabel("Config Dir:"),   1, 0)
        grid.addWidget(self.cfg_dir_edit,       1, 1)
        grid.addWidget(btn_cfg,                 1, 2)

        # Control file
        self.ctrl_edit = QLineEdit()
        self.ctrl_edit.setPlaceholderText("run_control.txt")
        btn_ctrl = _browse_btn()
        btn_ctrl.clicked.connect(self._browse_ctrl)
        grid.addWidget(QLabel("Control File:"), 2, 0)
        grid.addWidget(self.ctrl_edit,          2, 1)
        grid.addWidget(btn_ctrl,                2, 2)

        # MPI partitions
        self.partitions_spin = QSpinBox()
        self.partitions_spin.setRange(1, 512)
        self.partitions_spin.setValue(64)
        self.partitions_spin.setToolTip("MPI partitions — 1 = serial run")
        grid.addWidget(QLabel("Partitions:"),   3, 0)
        grid.addWidget(self.partitions_spin,    3, 1)

        # Mesh file copy
        self.mesh_edit = QLineEdit()
        self.mesh_edit.setPlaceholderText("Optional: select mesh file to copy into Config Dir")
        btn_mesh_browse = _browse_btn()
        btn_mesh_browse.clicked.connect(self._browse_mesh)
        self.btn_copy_mesh = QPushButton("Copy Mesh")
        self.btn_copy_mesh.setFixedWidth(90)
        self.btn_copy_mesh.setToolTip("Copy selected mesh file into the Config Dir")
        self.btn_copy_mesh.clicked.connect(self._copy_mesh)
        grid.addWidget(QLabel("Mesh File:"),    4, 0)
        grid.addWidget(self.mesh_edit,          4, 1)
        mesh_btn_row = QHBoxLayout()
        mesh_btn_row.setSpacing(4)
        mesh_btn_row.addWidget(btn_mesh_browse)
        mesh_btn_row.addWidget(self.btn_copy_mesh)
        grid.addLayout(mesh_btn_row,            4, 2)

        root.addLayout(grid)
        root.addWidget(_hline())

        # ── 2. Execution plan table ────────────────────────────────────────
        root.addWidget(_section_header("EXECUTION PLAN"))

        self.plan_table = QTableWidget()
        self.plan_table.setColumnCount(3)
        self.plan_table.setHorizontalHeaderLabels(
            ["Config File", "Restart Option", "Custom Path"]
        )
        hdr = self.plan_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.plan_table.setColumnWidth(0, 320)
        self.plan_table.setColumnWidth(1, 110)
        self.plan_table.verticalHeader().setDefaultSectionSize(24)
        self.plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setMaximumHeight(160)
        root.addWidget(self.plan_table)

        # ── 3. Action buttons ──────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self.btn_load = QPushButton("Load Plan")
        self.btn_load.setStyleSheet(_btn_style("#1976D2"))
        self.btn_load.clicked.connect(self.load_plan)

        self.btn_run = QPushButton("▶  Run Sweep")
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet(_btn_style("#2E7D32"))
        self.btn_run.clicked.connect(self.run_sweep)

        self.btn_stop = QPushButton("⏹  Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(_btn_style("#B71C1C"))
        self.btn_stop.setToolTip(
            "Kill the SU2 process immediately.\n"
            "Note: closing AeroSuite does NOT stop the simulation — use this button."
        )
        self.btn_stop.clicked.connect(self._stop_sweep)

        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── 4. Live execution status table ─────────────────────────────────
        # Shown immediately when Run is pressed; Status column updates live.
        self.summary_header = _section_header("EXECUTION STATUS")
        self.summary_header.setVisible(False)
        root.addWidget(self.summary_header)

        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(4)
        self.summary_table.setHorizontalHeaderLabels(
            ["Config File", "Status", "Iterations", "Restart Option"]
        )
        shdr = self.summary_table.horizontalHeader()
        shdr.setSectionResizeMode(QHeaderView.Interactive)
        shdr.setStretchLastSection(True)
        self.summary_table.setColumnWidth(0, 280)
        self.summary_table.setColumnWidth(1, 120)
        self.summary_table.setColumnWidth(2, 80)
        self.summary_table.verticalHeader().setDefaultSectionSize(24)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setVisible(False)
        root.addWidget(self.summary_table)

        # Log file path label
        self.log_label = QLabel()
        self.log_label.setStyleSheet(
            "font-size: 11px; color: #37474f; padding: 4px 2px;"
        )
        self.log_label.setWordWrap(True)
        self.log_label.setVisible(False)
        root.addWidget(self.log_label)

        root.addStretch()

    # ── Browse helpers ────────────────────────────────────────────────────────

    def _browse_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Sweep Script", "",
            "Python Scripts (*.py);;All Files (*)"
        )
        if path:
            self.script_edit.setText(path)
            self._settings.setValue(self._SETTINGS_KEY, path)

    def _browse_cfg_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Config Directory")
        if not folder:
            return
        self.cfg_dir_edit.setText(folder)
        for name in sorted(os.listdir(folder)):
            low = name.lower()
            if "control" in low and name.endswith((".txt", ".dat", ".csv")):
                self.ctrl_edit.setText(os.path.join(folder, name))
                self.status_message.emit(f"Auto-detected control file: {name}")
                break

    def _browse_ctrl(self):
        start = self.cfg_dir_edit.text().strip() or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Control File", start,
            "Text/Data Files (*.txt *.dat *.csv);;All Files (*)"
        )
        if path:
            self.ctrl_edit.setText(path)

    def _browse_mesh(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Mesh File", "",
            "Mesh Files (*.su2 *.cgns *.msh *.med);;All Files (*)"
        )
        if path:
            self.mesh_edit.setText(path)

    def _copy_mesh(self):
        src     = self.mesh_edit.text().strip()
        cfg_dir = self.cfg_dir_edit.text().strip()

        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "No Mesh Selected",
                                "Please browse and select a mesh file first.")
            return
        if not cfg_dir or not os.path.isdir(cfg_dir):
            QMessageBox.warning(self, "No Config Dir",
                                "Please select the Config Dir before copying the mesh.")
            return

        dest = os.path.join(cfg_dir, Path(src).name)
        if os.path.exists(dest):
            reply = QMessageBox.question(
                self, "File Exists",
                f"{Path(src).name} already exists in Config Dir.\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        try:
            shutil.copy2(src, dest)
            self.status_message.emit(f"Mesh copied → {Path(dest).name}")
            QMessageBox.information(self, "Mesh Copied", f"Copied to:\n  {dest}")
        except Exception as exc:
            QMessageBox.critical(self, "Copy Failed", str(exc))

    # ── Plan loading ──────────────────────────────────────────────────────────

    def load_plan(self):
        ctrl = self.ctrl_edit.text().strip()
        if not ctrl or not os.path.isfile(ctrl):
            QMessageBox.warning(self, "Missing Control File",
                                "Please select a valid control file first.")
            return

        try:
            run_list, warnings = parse_control_file(ctrl)
        except Exception as exc:
            QMessageBox.critical(self, "Parse Error", str(exc))
            return

        if warnings:
            QMessageBox.warning(self, "Control File Warnings", "\n".join(warnings))

        self.plan_table.setRowCount(len(run_list))
        for row, item in enumerate(run_list):
            self.plan_table.setItem(row, 0, QTableWidgetItem(item["cfg_file"]))
            self.plan_table.setItem(row, 1, QTableWidgetItem(item["restart_option"]))
            self.plan_table.setItem(row, 2, QTableWidgetItem(item["restart_path"] or ""))

        if run_list:
            self.btn_run.setEnabled(True)
            self.status_message.emit(
                f"Plan loaded: {len(run_list)} case(s) from {Path(ctrl).name}"
            )
        else:
            self.btn_run.setEnabled(False)
            QMessageBox.warning(self, "Empty Plan",
                                "No valid cases found in the control file.")

    # ── Sweep execution ───────────────────────────────────────────────────────

    def run_sweep(self):
        script  = self.script_edit.text().strip()
        cfg_dir = self.cfg_dir_edit.text().strip()
        ctrl    = self.ctrl_edit.text().strip()
        n       = self.plan_table.rowCount()

        if not script or not os.path.isfile(script):
            QMessageBox.warning(self, "Missing Script",
                                "Please select the sweep script (e.g. aoa_sweep_v8.py).")
            return
        if not cfg_dir or not os.path.isdir(cfg_dir):
            QMessageBox.warning(self, "Missing Config Directory",
                                "Please select the directory containing the .cfg files.")
            return
        if not ctrl or not os.path.isfile(ctrl):
            QMessageBox.warning(self, "Missing Control File",
                                "Please select the batch control file.")
            return
        if n == 0:
            QMessageBox.warning(self, "No Plan Loaded",
                                "Click 'Load Plan' first to preview the execution plan.")
            return

        reply = QMessageBox.question(
            self, "Confirm Sweep",
            f"Run {n} case(s) from:\n  {cfg_dir}\n\n"
            f"• SU2 output goes to a timestamped log file — tail it for live output.\n"
            f"• Closing AeroSuite will NOT stop the simulation.\n"
            f"• Use the Stop button to kill SU2 if needed.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        # ── Pre-populate status table immediately ──────────────────────────
        self._case_row_map = {}
        self.summary_table.setRowCount(n)

        for row in range(n):
            cfg_file = self.plan_table.item(row, 0).text() if self.plan_table.item(row, 0) else ""
            restart  = self.plan_table.item(row, 1).text() if self.plan_table.item(row, 1) else ""
            self._case_row_map[cfg_file] = row
            self.summary_table.setItem(row, 0, QTableWidgetItem(cfg_file))
            self.summary_table.setItem(row, 1, _status_item("QUEUED"))
            self.summary_table.setItem(row, 2, QTableWidgetItem("—"))
            self.summary_table.setItem(row, 3, QTableWidgetItem(restart))

        self.summary_header.setVisible(True)
        self.summary_table.setVisible(True)
        self.log_label.setVisible(False)
        self.log_label.setText("")

        # Lock Run/Load, enable Stop
        self.btn_run.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.status_message.emit(f"Sweep started — {n} case(s) queued…")

        runner = SweepRunner(
            script_path  = script,
            cfg_dir      = cfg_dir,
            control_file = ctrl,
            partitions   = self.partitions_spin.value(),
            progress_cb  = self._on_progress,
        )

        self._worker = _SweepWorker(runner)
        self._worker.case_status.connect(self._on_case_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.errored.connect(self._on_error)
        self._worker.start()

    # ── Stop ──────────────────────────────────────────────────────────────────

    def _stop_sweep(self):
        if self._worker and self._worker.runner:
            reply = QMessageBox.question(
                self, "Stop Sweep",
                "Kill the running SU2 simulation?\n\nThis will send SIGKILL to the entire "
                "mpirun/SU2 process group. Any in-progress case will be terminated immediately.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
            self._worker.runner.stop()
            self.btn_stop.setEnabled(False)
            self.status_message.emit("Stop signal sent — waiting for process to exit…")

    # ── Worker callbacks ──────────────────────────────────────────────────────

    def _on_progress(self, done: int, total: int):
        self.status_message.emit(f"Sweep running: {done}/{total} cases started")

    def _on_case_status(self, cfg_file: str, status: str):
        """Update a single row in the live status table."""
        row = self._case_row_map.get(cfg_file)
        if row is not None:
            self.summary_table.setItem(row, 1, _status_item(status))

    def _on_finished(self, results: List[Dict]):
        self._unlock_ui()
        log_path = getattr(self._worker.runner, "log_path", None)
        self._populate_final_status(results, log_path)
        n_ok     = sum(1 for r in results if r["status"] == "SUCCESS")
        n_fail   = sum(1 for r in results if r["status"] == "FAILED")
        n_stop   = sum(1 for r in results if r["status"] == "STOPPED")
        if n_stop:
            self.status_message.emit(
                f"Sweep stopped — {n_ok} done, {n_fail} failed, {n_stop} not run"
            )
        else:
            self.status_message.emit(
                f"Sweep finished — {n_ok} succeeded, {n_fail} failed"
            )
        log_note = f"\n\nLog: {log_path}" if log_path else ""
        if n_fail:
            QMessageBox.warning(
                self, "Sweep Finished",
                f"{n_ok} case(s) succeeded, {n_fail} case(s) failed.\n"
                f"Check error.log inside each failed case folder.{log_note}"
            )
        elif n_stop:
            QMessageBox.information(
                self, "Sweep Stopped",
                f"Stopped by user. {n_ok} case(s) completed before stop.{log_note}"
            )
        else:
            QMessageBox.information(
                self, "Sweep Finished",
                f"All {n_ok} case(s) completed successfully.{log_note}"
            )

    def _on_error(self, message: str):
        self._unlock_ui()
        self.status_message.emit("Sweep failed — see error dialog")
        QMessageBox.critical(self, "Sweep Error", message)

    def set_cfg_paths(self, cfg_dir: str, ctrl_file: str):
        """Slot called by SU2 tab after generation."""
        self.cfg_dir_edit.setText(cfg_dir)
        self.ctrl_edit.setText(ctrl_file)
        if os.path.isfile(ctrl_file):
            self.load_plan()

    def _unlock_ui(self):
        self.btn_run.setEnabled(self.plan_table.rowCount() > 0)
        self.btn_load.setEnabled(True)
        self.btn_stop.setEnabled(False)

    # ── Final status population ───────────────────────────────────────────────

    def _populate_final_status(self, results: List[Dict], log_path: Optional[str] = None):
        """Update all rows with final status after the sweep completes."""
        for r in results:
            row = self._case_row_map.get(r["cfg_file"])
            if row is None:
                continue
            status = r["status"]
            self.summary_table.setItem(row, 1, _status_item(status))
            self.summary_table.setItem(row, 2, QTableWidgetItem(r["iterations"]))
            # Restart option already set; update in case it wasn't
            self.summary_table.setItem(row, 3, QTableWidgetItem(r["restart_option"]))

        if log_path:
            self.log_label.setText(f"📄  Log: {log_path}")
            self.log_label.setVisible(True)


# ── Small UI helpers ──────────────────────────────────────────────────────────

def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-weight: bold; font-size: 11px; color: #2c3e50;"
        "background: #e8eaf6; padding: 3px 6px; border-radius: 3px;"
    )
    return lbl


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def _browse_btn() -> QPushButton:
    btn = QPushButton("Browse")
    btn.setFixedWidth(70)
    return btn


def _btn_style(color: str) -> str:
    return (
        f"background: {color}; color: white; font-weight: bold;"
        "padding: 7px 18px; border-radius: 4px;"
    )

"""
AeroSuite Pro - Main Application

IDE-style main window: menu/toolbar header, a workflow tree with
per-stage status icons on the left, a central content pane, and a
console/log panel at the bottom.

Tree structure:
  Calculators (utility tools, no status tracking)
    - ISA Calculator
    - y+ Calculator
  Project (top-to-bottom CFD workflow)
    - Directory
    - Geometry (disabled placeholder)
    - Mesh
    - CFG (group node)
        - Aircraft Aero
        - General
    - Sweep
    - Control File
    - Run
    - Monitor
    - Results
"""

import sys
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QApplication, QAction, QMessageBox, QFileDialog, QTreeWidget,
    QTreeWidgetItem, QStackedWidget, QSplitter, QStyle, QSizePolicy,
    QToolBar, QTextEdit, QFrame
)
from PyQt5.QtCore import Qt, QSettings, QSize
from PyQt5.QtGui import QFont, QColor, QBrush, QIcon

from aerosuite import (
    WINDOW_TITLE, DEFAULT_GEOMETRY, SETTINGS_ORG, SETTINGS_APP,
    MAX_RECENT_FILES, __version__
)
from aerosuite.ui import (
    ISATab, DirectoryTab, MeshTab, AircraftAeroPage, GeneralPage,
    SweepSetupTab, ControlFileTab, MonitorTab, AeroSummaryTab, SweepTab
)
from aerosuite.ui.style import APP_QSS, BASE_FONT_FAMILY, BASE_FONT_SIZE
from aerosuite.core.isa_calculator import ISACalculator
from aerosuite.utils.file_handlers import read_json_file, write_json_file


STATUS_DONE    = "\u2713"
STATUS_WARN    = "\u26A0"
STATUS_TODO    = "\u2717"
STATUS_ACTIVE  = "\u25B6"
STATUS_PENDING = "\u25CB"

# NOTE: STATUS_TODO deliberately uses a darker grey than the disabled
# Geometry node (#b0b3b8) so "not started yet" never looks like "disabled".
STATUS_COLOR = {
    STATUS_DONE:    QColor("#2e7d32"),
    STATUS_WARN:    QColor("#e6a400"),
    STATUS_TODO:    QColor("#5c6570"),
    STATUS_ACTIVE:  QColor("#00a2ed"),
    STATUS_PENDING: QColor("#8a8d93"),
}

DISABLED_COLOR = QColor("#b0b3b8")


class GeometryPlaceholderPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("Geometry")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #b0b3b8;")
        subtitle = QLabel("Coming soon - geometry tools are not yet part of AeroSuite Pro.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #999; margin-top: 6px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)


class AeroSuiteMainWindow(QMainWindow):
    NODE_CALC_ISA     = "calc_isa"
    NODE_CALC_YPLUS   = "calc_yplus"
    NODE_DIRECTORY    = "directory"
    NODE_GEOMETRY     = "geometry"
    NODE_MESH         = "mesh"
    NODE_CFG_AIRCRAFT = "cfg_aircraft"
    NODE_CFG_GENERAL  = "cfg_general"
    NODE_SWEEP        = "sweep"
    NODE_CONTROL      = "control"
    NODE_RUN          = "run"
    NODE_MONITOR      = "monitor"
    NODE_RESULTS      = "results"

    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.recent_files = []
        self.project_name = "Untitled Project"
        self._sweep_ran = False
        self._results_ran = False

        self.setWindowTitle(WINDOW_TITLE)
        self.restore_geometry()

        self.create_menu()
        self.create_ui()
        self.create_toolbar()
        self.load_recent_files()
        self.restore_last_session()
        self.refresh_workflow_status()

    def restore_geometry(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(*DEFAULT_GEOMETRY)

    # -- Menu --------------------------------------------------------------

    def create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu('&File')

        self.recent_menu = file_menu.addMenu('Recent Templates')
        self.update_recent_menu()

        file_menu.addSeparator()
        exit_action = QAction('E&xit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        profile_menu = menubar.addMenu('&Profiles')

        save_action = QAction('Save SU2 Profile...', self)
        save_action.setToolTip("Save the current SU2 configuration to a JSON file")
        save_action.setShortcut('Ctrl+S')
        save_action.triggered.connect(self.save_profile)

        load_action = QAction('Load SU2 Profile...', self)
        load_action.setToolTip("Load previously saved SU2 configuration")
        load_action.setShortcut('Ctrl+O')
        load_action.triggered.connect(self.load_profile)

        profile_menu.addAction(save_action)
        profile_menu.addAction(load_action)

        view_menu = menubar.addMenu('&View')
        self.toggle_console_action = QAction('Console / Log', self, checkable=True, checked=True)
        self.toggle_console_action.triggered.connect(self.toggle_console)
        view_menu.addAction(self.toggle_console_action)

        help_menu = menubar.addMenu('&Help')

        formula_action = QAction('ISA Formulas', self)
        formula_action.triggered.connect(self.show_formulas)
        help_menu.addAction(formula_action)

        constants_action = QAction('Physical Constants', self)
        constants_action.triggered.connect(self.show_constants)
        help_menu.addAction(constants_action)

        help_menu.addSeparator()

        about_action = QAction('About AeroSuite', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # -- Toolbar -------------------------------------------------------------

    def create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            "QToolBar { background: #eef1f4; border-bottom: 1px solid #c9ccd1; spacing: 4px; padding: 4px; }"
        )
        self.addToolBar(toolbar)

        style = self.style()

        new_action = QAction(style.standardIcon(QStyle.SP_FileIcon), "New Project", self)
        new_action.triggered.connect(self.new_project)
        toolbar.addAction(new_action)

        save_action = QAction(style.standardIcon(QStyle.SP_DialogSaveButton), "Save Profile", self)
        save_action.triggered.connect(self.save_profile)
        toolbar.addAction(save_action)

        load_action = QAction(style.standardIcon(QStyle.SP_DialogOpenButton), "Load Profile", self)
        load_action.triggered.connect(self.load_profile)
        toolbar.addAction(load_action)

        toolbar.addSeparator()

        cfg_gen_action = QAction(style.standardIcon(QStyle.SP_FileDialogDetailedView), "Go to CFG", self)
        cfg_gen_action.setToolTip("Go to the CFG > Aircraft Aero page")
        cfg_gen_action.triggered.connect(self.toolbar_generate_single_config)
        toolbar.addAction(cfg_gen_action)

        sweep_gen_action = QAction(style.standardIcon(QStyle.SP_FileDialogNewFolder), "Go to Sweep", self)
        sweep_gen_action.setToolTip("Go to the Sweep page")
        sweep_gen_action.triggered.connect(self.toolbar_generate_sweep)
        toolbar.addAction(sweep_gen_action)

        run_action = QAction(style.standardIcon(QStyle.SP_MediaPlay), "Run Sweep", self)
        run_action.triggered.connect(self.toolbar_run_sweep)
        toolbar.addAction(run_action)

        stop_action = QAction(style.standardIcon(QStyle.SP_MediaStop), "Stop Sweep", self)
        stop_action.triggered.connect(self.toolbar_stop_sweep)
        toolbar.addAction(stop_action)

        toolbar.addSeparator()

        refresh_action = QAction(style.standardIcon(QStyle.SP_BrowserReload), "Refresh Status", self)
        refresh_action.triggered.connect(self.refresh_workflow_status)
        toolbar.addAction(refresh_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self.project_name_label = QLabel(self.project_name)
        self.project_name_label.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #2c3e50; padding-right: 10px;"
        )
        toolbar.addWidget(self.project_name_label)

    # -- Central layout --------------------------------------------------------

    def create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.geometry_page     = GeometryPlaceholderPage()
        self.isa_tab           = ISATab()
        self.directory_tab     = DirectoryTab()
        self.mesh_tab          = MeshTab()
        self.cfg_aircraft_tab  = AircraftAeroPage()
        self.cfg_general_tab   = GeneralPage()
        self.sweep_setup_tab   = SweepSetupTab()
        self.control_file_tab  = ControlFileTab()
        self.sweep_tab         = SweepTab()
        self.monitor_tab       = MonitorTab()
        self.aerosummary_tab   = AeroSummaryTab()

        self.mesh_tab.set_directory_source(self.directory_tab)
        self.cfg_aircraft_tab.set_mesh_source(self.mesh_tab)
        self.sweep_setup_tab.set_directory_source(self.directory_tab)
        self.control_file_tab.set_directory_source(self.directory_tab)

        self.content_stack = QStackedWidget()
        for w in (self.geometry_page, self.isa_tab, self.directory_tab, self.mesh_tab,
                  self.cfg_aircraft_tab, self.cfg_general_tab, self.sweep_setup_tab,
                  self.control_file_tab, self.sweep_tab, self.monitor_tab, self.aerosummary_tab):
            self.content_stack.addWidget(w)

        self.workflow_tree = QTreeWidget()
        self.workflow_tree.setHeaderHidden(True)
        self.workflow_tree.setMinimumWidth(220)
        self.workflow_tree.setMaximumWidth(340)
        self.workflow_tree.setStyleSheet(
            "QTreeWidget { background: #f2f4f7; border: none; border-right: 1px solid #c9ccd1; font-size: 13px; }"
            "QTreeWidget::item { padding: 6px 2px; }"
            "QTreeWidget::item:selected { background: #00a2ed; color: white; }"
        )
        self._build_workflow_tree()
        self.workflow_tree.currentItemChanged.connect(self.handle_tree_navigation)
        # currentItemChanged doesn't fire for the selection made inside
        # _build_workflow_tree (signal wasn't connected yet), so sync the
        # content pane to that initial selection explicitly.
        self.content_stack.setCurrentWidget(self.directory_tab)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self.workflow_tree)
        top_splitter.addWidget(self.content_stack)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([260, 980])

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 10))
        self.console.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; border: 1px solid #c9ccd1; }"
        )
        self._console_container = self._panel("Console / Log", self.console)
        self._console_container.setMaximumHeight(190)

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self._console_container)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([700, 160])

        root_layout.addWidget(main_splitter)

        self.isa_tab.transfer_requested.connect(self.handle_isa_transfer)
        self.directory_tab.status_message.connect(self.log_message)
        self.directory_tab.changed.connect(self.refresh_workflow_status)
        self.mesh_tab.status_message.connect(self.log_message)
        self.mesh_tab.markers_loaded.connect(lambda m: self.refresh_workflow_status())
        self.cfg_aircraft_tab.status_message.connect(self.log_message)
        self.cfg_general_tab.status_message.connect(self.log_message)
        self.sweep_setup_tab.status_message.connect(self.log_message)
        self.sweep_setup_tab.configs_generated.connect(self.handle_configs_generated)
        self.sweep_setup_tab.generation_complete.connect(self.handle_generation_complete)
        self.control_file_tab.status_message.connect(self.log_message)
        self.control_file_tab.generation_complete.connect(self.handle_generation_complete)
        self.sweep_tab.status_message.connect(self.log_message)
        self.monitor_tab.status_message.connect(self.log_message)
        self.aerosummary_tab.status_message.connect(self.log_message)

        self.statusBar().showMessage("Ready")
        self.log_message("AeroSuite Pro ready.")

    @staticmethod
    def _panel(title: str, inner_widget: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel(title)
        header.setStyleSheet(
            "background: #dfe3e8; color: #2c3e50; font-weight: bold; font-size: 12px; "
            "padding: 4px 8px; border: 1px solid #c9ccd1; border-bottom: none;"
        )
        layout.addWidget(header)
        layout.addWidget(inner_widget)
        return container

    def toggle_console(self, checked: bool):
        self._console_container.setVisible(checked)

    # -- Workflow tree --------------------------------------------------------

    def _build_workflow_tree(self):
        self._tree_targets = {}
        self._nodes = {}

        def add_child(parent, key, label, widget, sub_index=None):
            item = QTreeWidgetItem(parent, [" " + label])
            self._tree_targets[id(item)] = (widget, sub_index)
            self._nodes[key] = item
            return item

        # ── Calculators (peer of Project, utility tools — no status tracking) ──
        calc_node = QTreeWidgetItem(self.workflow_tree, [" Calculators"])
        add_child(calc_node, self.NODE_CALC_ISA,   "ISA Calculator", self.isa_tab, 0)
        add_child(calc_node, self.NODE_CALC_YPLUS, "y+ Calculator",  self.isa_tab, 1)

        # ── Project (top-to-bottom CFD workflow) ────────────────────────────────
        project_node = QTreeWidgetItem(self.workflow_tree, ["SU2 Project"])

        add_child(project_node, self.NODE_DIRECTORY, "Directory", self.directory_tab)

        geo_item = QTreeWidgetItem(project_node, [" Geometry"])
        geo_item.setDisabled(True)
        geo_item.setToolTip(0, "Coming soon")
        geo_item.setForeground(0, QBrush(DISABLED_COLOR))
        self._tree_targets[id(geo_item)] = (self.geometry_page, None)
        self._nodes[self.NODE_GEOMETRY] = geo_item

        add_child(project_node, self.NODE_MESH, "Mesh", self.mesh_tab)

        cfg_node = QTreeWidgetItem(project_node, [" CFG"])
        add_child(cfg_node, self.NODE_CFG_AIRCRAFT, "Aircraft Aero", self.cfg_aircraft_tab)
        add_child(cfg_node, self.NODE_CFG_GENERAL,  "General",       self.cfg_general_tab)

        add_child(project_node, self.NODE_SWEEP,   "Sweep",        self.sweep_setup_tab)
        add_child(project_node, self.NODE_CONTROL, "Control File", self.control_file_tab)
        add_child(project_node, self.NODE_RUN,     "Run",          self.sweep_tab)
        add_child(project_node, self.NODE_MONITOR, "Monitor",      self.monitor_tab)
        add_child(project_node, self.NODE_RESULTS, "Results",      self.aerosummary_tab)

        self.workflow_tree.expandAll()
        self.workflow_tree.setCurrentItem(self._nodes[self.NODE_DIRECTORY])

    def _set_node_status(self, key: str, status: str, tooltip: str = ""):
        item = self._nodes.get(key)
        if item is None:
            return
        label = item.text(0).strip()
        for glyph in (STATUS_DONE, STATUS_WARN, STATUS_TODO, STATUS_ACTIVE, STATUS_PENDING):
            if label.startswith(glyph):
                label = label[len(glyph):].strip()
                break
        item.setText(0, f"{status} {label}")
        item.setForeground(0, QBrush(STATUS_COLOR.get(status, QColor("#333"))))
        if tooltip:
            item.setToolTip(0, tooltip)

    def refresh_workflow_status(self):
        workdir_set = bool(self.directory_tab.get_workdir())
        self._set_node_status(
            self.NODE_DIRECTORY,
            STATUS_DONE if workdir_set else STATUS_TODO,
            "Working directory: " + (self.directory_tab.get_workdir() or "not set")
        )

        mesh_set = bool(self.mesh_tab.get_mesh_filename())
        mesh_exists = bool(self.mesh_tab.get_mesh_full_path()) and Path(self.mesh_tab.get_mesh_full_path()).exists()
        self._set_node_status(
            self.NODE_MESH,
            STATUS_DONE if mesh_exists else (STATUS_WARN if mesh_set else STATUS_TODO),
            "Mesh file: " + (self.mesh_tab.get_mesh_filename() or "not set")
        )

        template_set = bool(self.cfg_aircraft_tab.template_edit.text().strip())
        self._set_node_status(
            self.NODE_CFG_AIRCRAFT,
            STATUS_DONE if template_set else STATUS_TODO,
            f"Turbulence model: {self.cfg_aircraft_tab.turb_model_dropdown.currentText()}"
        )
        general_set = bool(self.cfg_general_tab.editor.toPlainText().strip())
        self._set_node_status(self.NODE_CFG_GENERAL, STATUS_DONE if general_set else STATUS_TODO)

        sweep = self.sweep_setup_tab
        base_cfg_set = bool(sweep.base_cfg_edit.text().strip())
        param_set = any(
            len(getattr(sweep, f).text().strip()) > 0
            for f in ("mach_edit", "alpha_edit", "beta_edit")
        )
        self._set_node_status(
            self.NODE_SWEEP,
            STATUS_DONE if (base_cfg_set and param_set) else (STATUS_WARN if (base_cfg_set or param_set) else STATUS_TODO)
        )

        ctrl_ready = bool(self.control_file_tab._batch_cfg_dir)
        self._set_node_status(self.NODE_CONTROL, STATUS_DONE if ctrl_ready else STATUS_TODO)

        if self._sweep_ran:
            self._set_node_status(self.NODE_RUN, STATUS_DONE)
        elif ctrl_ready:
            self._set_node_status(self.NODE_RUN, STATUS_ACTIVE, "Ready to run")
        else:
            self._set_node_status(self.NODE_RUN, STATUS_TODO)

        self._set_node_status(self.NODE_MONITOR, STATUS_DONE if self._sweep_ran else STATUS_PENDING)
        self._set_node_status(self.NODE_RESULTS, STATUS_DONE if self._results_ran else STATUS_PENDING)

    # -- Navigation ------------------------------------------------------------

    def handle_tree_navigation(self, current, previous):
        if current is None:
            return
        target = self._tree_targets.get(id(current))
        if target is None:
            # Group node (Calculators, Project, CFG) — just expand it.
            current.setExpanded(True)
            return
        widget, sub_index = target
        self.content_stack.setCurrentWidget(widget)
        if sub_index is not None:
            sub_widget = getattr(widget, "sub_tabs", None) or getattr(widget, "tabs", None)
            if sub_widget is not None:
                sub_widget.setCurrentIndex(sub_index)
        self.refresh_workflow_status()

    def navigate_to(self, widget, sub_index=None):
        self.content_stack.setCurrentWidget(widget)
        if sub_index is not None:
            sub_widget = getattr(widget, "sub_tabs", None) or getattr(widget, "tabs", None)
            if sub_widget is not None:
                sub_widget.setCurrentIndex(sub_index)

        for item_id, (w, s) in self._tree_targets.items():
            if w is widget and s == sub_index:
                item = self._find_tree_item_by_id(item_id)
                if item is not None:
                    self.workflow_tree.blockSignals(True)
                    self.workflow_tree.setCurrentItem(item)
                    self.workflow_tree.blockSignals(False)
                break
        self.refresh_workflow_status()

    def _find_tree_item_by_id(self, target_id):
        def walk(item):
            if id(item) == target_id:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        root_item = self.workflow_tree.invisibleRootItem()
        for i in range(root_item.childCount()):
            found = walk(root_item.child(i))
            if found is not None:
                return found
        return None

    # -- Console -----------------------------------------------------------

    def log_message(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.append(f"[{timestamp}] {message}")
        self.statusBar().showMessage(message, 5000)

    # -- Toolbar actions -----------------------------------------------------

    def new_project(self):
        reply = QMessageBox.question(
            self, "New Project", "Start a new project? Unsaved settings will be lost.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.project_name = "Untitled Project"
            self.project_name_label.setText(self.project_name)
            self._sweep_ran = False
            self._results_ran = False
            self.navigate_to(self.directory_tab)
            self.log_message("Started new project.")

    def toolbar_generate_single_config(self):
        self.navigate_to(self.cfg_aircraft_tab)

    def toolbar_generate_sweep(self):
        self.navigate_to(self.sweep_setup_tab)

    def toolbar_run_sweep(self):
        self.navigate_to(self.sweep_tab)
        if hasattr(self.sweep_tab, "run_sweep"):
            self.sweep_tab.run_sweep()
            self._sweep_ran = True
            self.refresh_workflow_status()

    def toolbar_stop_sweep(self):
        if hasattr(self.sweep_tab, "_stop_sweep"):
            self.sweep_tab._stop_sweep()
            self.log_message("Sweep stop requested.")

    # -- Cross-page workflow handlers ------------------------------------------

    def handle_isa_transfer(self, altitude: str, temperature: str, reynolds: str):
        """ISA/y+ 'Update SU2 Parameters' -> just push values into Sweep and CFG.
        Does NOT navigate anywhere."""
        self.sweep_setup_tab.update_from_isa(altitude, temperature, reynolds)
        self.cfg_aircraft_tab.update_from_isa(temperature, reynolds)
        self.log_message(f"Transferred to Sweep & CFG: Altitude={altitude}, Temp={temperature}K, Re={reynolds}")
        self.refresh_workflow_status()

    def handle_configs_generated(self, cfg_dir: str):
        """Sweep configs generated -> prefill Control File dir, but stay on Sweep page."""
        self.control_file_tab.prefill_dir(cfg_dir)
        self.log_message(f"Configs ready in {cfg_dir} — open Control File when ready to build run_control.txt.")
        self.refresh_workflow_status()

    def handle_generation_complete(self, cfg_dir: str, ctrl_file: str):
        """Control file ready -> Run page."""
        self.sweep_tab.set_cfg_paths(cfg_dir, ctrl_file)
        self.navigate_to(self.sweep_tab)
        self.log_message(f"Control file ready - Run page loaded: {ctrl_file}")
        self.refresh_workflow_status()

    def update_status(self, message: str):
        self.log_message(message)

    # -- Recent files management ---------------------------------------------

    def load_recent_files(self):
        recent = self.settings.value("recent_files", [])
        if isinstance(recent, str):
            recent = [recent]
        self.recent_files = [f for f in recent if Path(f).exists()][:MAX_RECENT_FILES]

    def add_recent_file(self, filepath: str):
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:MAX_RECENT_FILES]
        self.settings.setValue("recent_files", self.recent_files)
        self.update_recent_menu()

    def update_recent_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            action = QAction("No recent files", self)
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return

        for filepath in self.recent_files:
            action = QAction(Path(filepath).name, self)
            action.setToolTip(filepath)
            action.triggered.connect(
                lambda checked, f=filepath: self.load_recent_template(f)
            )
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def load_recent_template(self, filepath: str):
        if Path(filepath).exists():
            self.cfg_aircraft_tab.template_edit.setText(filepath)
            self.add_recent_file(filepath)
            self.navigate_to(self.cfg_aircraft_tab)
            self.log_message(f"Loaded template: {filepath}")
        else:
            QMessageBox.warning(
                self, "File Not Found",
                f"The file no longer exists:\n{filepath}"
            )
            self.recent_files.remove(filepath)
            self.update_recent_menu()

    def clear_recent_files(self):
        self.recent_files = []
        self.settings.setValue("recent_files", [])
        self.update_recent_menu()

    # -- Session management ---------------------------------------------------

    def restore_last_session(self):
        if self.settings.value("restore_session", True, type=bool):
            output_dir = self.settings.value("last_output_dir", "")
            folder = self.settings.value("last_folder", "run_1")
            if output_dir:
                self.directory_tab.output_edit.setText(output_dir)
            if folder:
                self.directory_tab.folder_edit.setText(folder)

    def save_session(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("last_output_dir", self.directory_tab.output_edit.text())
        self.settings.setValue("last_folder", self.directory_tab.folder_edit.text())

    # -- Profile management ----------------------------------------------------

    def save_profile(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "", "JSON Files (*.json)"
        )

        if not filename:
            return

        try:
            cfg = self.cfg_aircraft_tab
            sweep = self.sweep_setup_tab
            data = {
                "version": __version__,
                "saved_at": datetime.now().isoformat(),
                "template": cfg.template_edit.text(),
                "mesh": self.mesh_tab.mesh_edit.text(),
                "output_dir": self.directory_tab.output_edit.text(),
                "folder": self.directory_tab.folder_edit.text(),
                "base_cfg": sweep.base_cfg_edit.text(),
                "mach": sweep.mach_edit.text(),
                "alpha": sweep.alpha_edit.text(),
                "beta": sweep.beta_edit.text(),
                "altitude": sweep.altitude_dropdown.currentText(),
                "base_name": sweep.base_edit.text(),
                "temperature": sweep.temp_edit.text(),
                "reynolds": sweep.reynolds_edit.text(),
                "include_base": sweep.inc_base.isChecked(),
                "include_mach": sweep.inc_mach.isChecked(),
                "include_alpha": sweep.inc_alpha.isChecked(),
                "include_beta": sweep.inc_beta.isChecked(),
                "include_altitude": sweep.inc_alt.isChecked(),
            }

            if write_json_file(Path(filename), data):
                QMessageBox.information(self, "Success", "Profile saved successfully")
                self.project_name = Path(filename).stem
                self.project_name_label.setText(self.project_name)
                self.log_message(f"Profile saved: {filename}")
            else:
                QMessageBox.warning(self, "Error", "Failed to save profile")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save profile:\n{str(e)}")

    def load_profile(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON Files (*.json)"
        )

        if not filename:
            return

        try:
            data = read_json_file(Path(filename))
            if data is None:
                QMessageBox.warning(self, "Error", "Failed to load profile")
                return

            cfg = self.cfg_aircraft_tab
            sweep = self.sweep_setup_tab

            cfg.template_edit.setText(data.get("template", ""))
            self.mesh_tab.mesh_edit.setText(data.get("mesh", ""))
            self.directory_tab.output_edit.setText(data.get("output_dir", ""))
            self.directory_tab.folder_edit.setText(data.get("folder", "run_1"))
            sweep.base_cfg_edit.setText(data.get("base_cfg", ""))
            sweep.mach_edit.setText(data.get("mach", ""))
            sweep.alpha_edit.setText(data.get("alpha", ""))
            sweep.beta_edit.setText(data.get("beta", ""))
            sweep.altitude_dropdown.setCurrentText(data.get("altitude", "sl"))
            sweep.base_edit.setText(data.get("base_name", ""))
            sweep.temp_edit.setText(data.get("temperature", ""))
            sweep.reynolds_edit.setText(data.get("reynolds", ""))
            sweep.inc_base.setChecked(data.get("include_base", True))
            sweep.inc_mach.setChecked(data.get("include_mach", True))
            sweep.inc_alpha.setChecked(data.get("include_alpha", True))
            sweep.inc_beta.setChecked(data.get("include_beta", True))
            sweep.inc_alt.setChecked(data.get("include_altitude", True))

            QMessageBox.information(self, "Success", "Profile loaded successfully")
            self.project_name = Path(filename).stem
            self.project_name_label.setText(self.project_name)
            self.navigate_to(self.cfg_aircraft_tab)
            self.log_message(f"Profile loaded: {filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profile:\n{str(e)}")

    # -- Help dialogs ------------------------------------------------------

    def show_formulas(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("ISA Formulas")
        msg.setTextFormat(Qt.RichText)
        msg.setText(ISACalculator.get_formulas())
        msg.exec_()

    def show_constants(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Physical Constants")
        msg.setTextFormat(Qt.RichText)
        msg.setText(ISACalculator.get_constants())
        msg.exec_()

    def show_about(self):
        about_text = (
            "<h2>AeroSuite Pro</h2>"
            f"<p>Version {__version__}</p>"
            "<p>A desktop toolkit for SU2 CFD preprocessing and aerodynamic calculations.</p>"
            "<h3>Workflow</h3>"
            "<p>Calculators &middot; Directory &rarr; Geometry &rarr; Mesh &rarr; "
            "CFG (Aircraft Aero / General) &rarr; Sweep &rarr; "
            "Control File &rarr; Run &rarr; Monitor &rarr; Results</p>"
            "<p><i>Built with PyQt5 and Python 3</i></p>"
        )

        QMessageBox.about(self, "About AeroSuite Pro", about_text)

    def closeEvent(self, event):
        self.save_session()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)
    app.setFont(QFont(BASE_FONT_FAMILY, BASE_FONT_SIZE))
    app.setStyleSheet(APP_QSS)

    window = AeroSuiteMainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

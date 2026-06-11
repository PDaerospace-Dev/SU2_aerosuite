"""
AeroSuite Pro - Main Application

Main window and application entry point for AeroSuite Pro.
"""

import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QTabWidget,
    QApplication, QAction, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QFont

from aerosuite import (
    WINDOW_TITLE, DEFAULT_GEOMETRY, SETTINGS_ORG, SETTINGS_APP,
    MAX_RECENT_FILES, __version__
)
from aerosuite.ui import ISATab, SU2Tab, MonitorTab, AeroSummaryTab, SweepTab
from aerosuite.core.isa_calculator import ISACalculator
from aerosuite.utils.file_handlers import read_json_file, write_json_file


class AeroSuiteMainWindow(QMainWindow):
    """Main application window for AeroSuite Pro."""
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.recent_files = []
        
        self.setWindowTitle(WINDOW_TITLE)
        self.restore_geometry()
        
        self.create_menu()
        self.create_ui()
        self.load_recent_files()
        self.restore_last_session()
    
    def restore_geometry(self):
        """Restore window geometry from settings."""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(*DEFAULT_GEOMETRY)
    
    def create_menu(self):
        """Create application menu bar."""
        menubar = self.menuBar()
        
        # File Menu
        file_menu = menubar.addMenu('&File')
        
        # Recent files submenu
        self.recent_menu = file_menu.addMenu('Recent Templates')
        self.update_recent_menu()
        
        file_menu.addSeparator()
        exit_action = QAction('E&xit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Profile Menu
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
        
        # Help Menu
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
    
    def create_ui(self):
        """Create the main user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(5)
        
        # Title
        title_label = QLabel("AeroSuite Pro - SU2 & Aero Toolkit")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; margin-bottom: 10px; "
            "color: #00a2ed;"
        )
        main_layout.addWidget(title_label)
        
        # Main tab widget (vertical tabs)
        self.main_tabs = QTabWidget()
        self.main_tabs.setTabPosition(QTabWidget.West)
        main_layout.addWidget(self.main_tabs)
        
        # Create tabs
        self.isa_tab         = ISATab()
        self.su2_tab         = SU2Tab()
        self.sweep_tab       = SweepTab()
        self.monitor_tab     = MonitorTab()
        self.aerosummary_tab = AeroSummaryTab()

        # Add tabs
        self.main_tabs.addTab(self.isa_tab,         "ISA & Y+ Calculator")
        self.main_tabs.addTab(self.su2_tab,         "SU2 Config Generator")
        self.main_tabs.addTab(self.sweep_tab,       "Sweep Runner")
        self.main_tabs.addTab(self.monitor_tab,     "Convergence Monitor")
        self.main_tabs.addTab(self.aerosummary_tab, "Results Analysis")

        # Connect signals
        self.isa_tab.transfer_requested.connect(self.handle_isa_transfer)
        self.su2_tab.status_message.connect(self.update_status)
        self.sweep_tab.status_message.connect(self.update_status)
        self.monitor_tab.status_message.connect(self.update_status)
        self.aerosummary_tab.status_message.connect(self.update_status)

        # Cross-tab workflow
        self.su2_tab.generation_complete.connect(self.handle_generation_complete)

        # Status bar
        self.statusBar().showMessage("Ready")
    
    def handle_isa_transfer(self, altitude: str, temperature: str, reynolds: str):
        """Handle transfer from ISA tab to SU2 tab."""
        self.su2_tab.update_from_isa(altitude, temperature, reynolds)
        self.main_tabs.setCurrentIndex(1)  # Switch to SU2 tab
        self.statusBar().showMessage(
            f"Transferred: Altitude={altitude}, Temp={temperature}K, Re={reynolds}",
            5000
        )

    def handle_generation_complete(self, cfg_dir: str, ctrl_file: str):
        """Auto-fill Sweep Runner after config generation and switch to it."""
        self.sweep_tab.set_cfg_paths(cfg_dir, ctrl_file)
        self.main_tabs.setCurrentWidget(self.sweep_tab)
        self.statusBar().showMessage(
            f"Config generated — Sweep Runner ready: {ctrl_file}", 6000
        )

    def update_status(self, message: str):
        """Update status bar message."""
        self.statusBar().showMessage(message, 5000)
    
    # Recent files management
    def load_recent_files(self):
        """Load recent files from settings."""
        recent = self.settings.value("recent_files", [])
        if isinstance(recent, str):
            recent = [recent]
        self.recent_files = [f for f in recent if Path(f).exists()][:MAX_RECENT_FILES]
    
    def add_recent_file(self, filepath: str):
        """Add file to recent files list."""
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:MAX_RECENT_FILES]
        self.settings.setValue("recent_files", self.recent_files)
        self.update_recent_menu()
    
    def update_recent_menu(self):
        """Update the recent files menu."""
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
        """Load a template from recent files."""
        if Path(filepath).exists():
            self.su2_tab.template_edit.setText(filepath)
            self.add_recent_file(filepath)
            self.main_tabs.setCurrentIndex(1)  # Switch to SU2 tab
        else:
            QMessageBox.warning(
                self, "File Not Found",
                f"The file no longer exists:\n{filepath}"
            )
            self.recent_files.remove(filepath)
            self.update_recent_menu()
    
    def clear_recent_files(self):
        """Clear the recent files list."""
        self.recent_files = []
        self.settings.setValue("recent_files", [])
        self.update_recent_menu()
    
    # Session management
    def restore_last_session(self):
        """Restore the last session settings."""
        if self.settings.value("restore_session", True, type=bool):
            output_dir = self.settings.value("last_output_dir", "")
            folder = self.settings.value("last_folder", "run_1")
            if output_dir:
                self.su2_tab.output_edit.setText(output_dir)
            if folder:
                self.su2_tab.folder_edit.setText(folder)
    
    def save_session(self):
        """Save current session settings."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("last_output_dir", self.su2_tab.output_edit.text())
        self.settings.setValue("last_folder", self.su2_tab.folder_edit.text())
    
    # Profile management
    def save_profile(self):
        """Save current SU2 configuration as a profile."""
        from datetime import datetime
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "", "JSON Files (*.json)"
        )
        
        if not filename:
            return
        
        try:
            data = {
                "version": __version__,
                "saved_at": datetime.now().isoformat(),
                "template": self.su2_tab.template_edit.text(),
                "mesh": self.su2_tab.mesh_edit.text(),
                "output_dir": self.su2_tab.output_edit.text(),
                "folder": self.su2_tab.folder_edit.text(),
                "mach": self.su2_tab.mach_edit.text(),
                "alpha": self.su2_tab.alpha_edit.text(),
                "beta": self.su2_tab.beta_edit.text(),
                "altitude": self.su2_tab.altitude_dropdown.currentText(),
                "base_name": self.su2_tab.base_edit.text(),
                "temperature": self.su2_tab.temp_edit.text(),
                "reynolds": self.su2_tab.reynolds_edit.text(),
                "include_base": self.su2_tab.inc_base.isChecked(),
                "include_mach": self.su2_tab.inc_mach.isChecked(),
                "include_alpha": self.su2_tab.inc_alpha.isChecked(),
                "include_beta": self.su2_tab.inc_beta.isChecked(),
                "include_altitude": self.su2_tab.inc_alt.isChecked(),
            }
            
            if write_json_file(Path(filename), data):
                QMessageBox.information(self, "Success", "Profile saved successfully")
            else:
                QMessageBox.warning(self, "Error", "Failed to save profile")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save profile:\n{str(e)}")
    
    def load_profile(self):
        """Load a saved SU2 profile."""
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
            
            # Restore settings
            self.su2_tab.template_edit.setText(data.get("template", ""))
            self.su2_tab.mesh_edit.setText(data.get("mesh", ""))
            self.su2_tab.output_edit.setText(data.get("output_dir", ""))
            self.su2_tab.folder_edit.setText(data.get("folder", "run_1"))
            self.su2_tab.mach_edit.setText(data.get("mach", ""))
            self.su2_tab.alpha_edit.setText(data.get("alpha", ""))
            self.su2_tab.beta_edit.setText(data.get("beta", ""))
            self.su2_tab.altitude_dropdown.setCurrentText(data.get("altitude", "sl"))
            self.su2_tab.base_edit.setText(data.get("base_name", ""))
            self.su2_tab.temp_edit.setText(data.get("temperature", ""))
            self.su2_tab.reynolds_edit.setText(data.get("reynolds", ""))
            self.su2_tab.inc_base.setChecked(data.get("include_base", True))
            self.su2_tab.inc_mach.setChecked(data.get("include_mach", True))
            self.su2_tab.inc_alpha.setChecked(data.get("include_alpha", True))
            self.su2_tab.inc_beta.setChecked(data.get("include_beta", True))
            self.su2_tab.inc_alt.setChecked(data.get("include_altitude", True))
            
            QMessageBox.information(self, "Success", "Profile loaded successfully")
            self.main_tabs.setCurrentIndex(1)  # Switch to SU2 tab
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profile:\n{str(e)}")
    
    # Help dialogs
    def show_formulas(self):
        """Show ISA formulas dialog."""
        msg = QMessageBox(self)
        msg.setWindowTitle("ISA Formulas")
        msg.setTextFormat(Qt.RichText)
        msg.setText(ISACalculator.get_formulas())
        msg.exec_()
    
    def show_constants(self):
        """Show physical constants dialog."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Physical Constants")
        msg.setTextFormat(Qt.RichText)
        msg.setText(ISACalculator.get_constants())
        msg.exec_()
    
    def show_about(self):
        """Show about dialog."""
        about_text = (
            "<h2>AeroSuite Pro</h2>"
            f"<p>Version 10.1</p>"
            "<p>A desktop toolkit for SU2 CFD preprocessing and aerodynamic calculations.</p>"
            "<h3>Tabs</h3>"
            "<ul>"
            "<li><b>ISA & Y+ Calculator</b> — atmospheric properties, Re number, Y+ value"
            "Transfer to SU2 Generator</li>"
            "<li><b>SU2 Config Generator</b> — batch .cfg creation from a master cfg template "
            "across Mach / alpha / beta sweeps; auto-generates run_control.txt; "
            "standalone control file generator for existing cfg folders</li>"
            "<li><b>Sweep Runner</b> — launches the sweep script exactly as from the terminal; "
            "summary table</li>"
            "<li><b>Convergence Monitor</b> — real-time residual plotting from SU2 history files</li>"
            "<li><b>Results Analysis</b> — consolidates batch history files into a summary CSV "
            "and CL/CD plots</li>"
            "</ul>"
            "<h3>Workflow</h3>"
            "<p>ISA & Y+ value → SU2 Generator → <i>(auto-switches)</i> → Sweep Runner → "
            "Monitor → Results Analysis</p>"
            "<p><i>Built with PyQt5 and Python 3</i></p>"
        )

        QMessageBox.about(self, "About AeroSuite Pro", about_text)
    
    def closeEvent(self, event):
        """Handle window close event."""
        self.save_session()
        event.accept()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)
    
    window = AeroSuiteMainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

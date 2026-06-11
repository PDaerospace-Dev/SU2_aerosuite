"""
AeroSummary Tab UI.

Provides the user interface for SU2 results consolidation and analysis.
"""

import os
from typing import List, Optional
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QSpinBox, QCheckBox, QTextEdit,
    QListWidget, QAbstractItemView, QFrame, QProgressBar,
    QMessageBox, QShortcut, QComboBox
)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings

from ..core.aerosummary import AeroSummary


# Constants
DEFAULT_AVG_ITERATIONS = 200
DEFAULT_PLOT_DIR = 'plots'


class ProcessingThread(QThread):
    """Worker thread for data processing to prevent GUI freezing."""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(list)  # List of plot files
    error_signal = pyqtSignal(str)
    
    def __init__(self, root_dir, output_file, columns, num_avg, should_plot, plot_dir, skip_list, append_mode=False):
        super().__init__()
        self.root_dir = root_dir
        self.output_file = output_file
        self.columns = columns
        self.num_avg = num_avg
        self.should_plot = should_plot
        self.plot_dir = plot_dir
        self.skip_list = skip_list
        self.append_mode = append_mode
    
    def run(self):
        """Execute the processing in a separate thread."""
        try:
            # Consolidate results
            summary_df, warnings = AeroSummary.consolidate_results(
                self.root_dir,
                self.columns,
                self.num_avg,
                self.skip_list,
                self.log_signal.emit,
                self.progress_signal.emit
            )
            
            if summary_df is None:
                self.error_signal.emit("No data was consolidated")
                return
            
            # Save summary file
            if AeroSummary.save_summary(summary_df, self.output_file, append=self.append_mode):
                mode_label = "appended to" if self.append_mode else "saved to"
                self.log_signal.emit(f"\n✓ Summary {mode_label}: {self.output_file}")
            else:
                self.log_signal.emit(f"\n✗ Failed to save summary file")
            
            # Generate plots if requested
            plot_files = []
            if self.should_plot:
                self.log_signal.emit("\nGenerating plots...")
                plot_files = AeroSummary.generate_plots(
                    summary_df,
                    self.columns,
                    self.plot_dir,
                    self.progress_signal.emit
                )
            
            self.finished_signal.emit(plot_files)
            
        except Exception as e:
            self.error_signal.emit(f"Processing error: {str(e)}")


class AeroSummaryTab(QWidget):
    """AeroSummary tab widget for results consolidation."""
    
    # Signal for status updates
    status_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.plot_list = []
        self.current_plot_idx = 0
        self.processing_thread = None
        self.settings = QSettings("AeroSuite", "AeroSuitePro")
        self.setup_ui()
        self.load_last_directory()
    
    def setup_ui(self):
        """Setup the user interface."""
        main_layout = QHBoxLayout(self)
        
        # Left Panel: Settings
        left_panel = QVBoxLayout()
        
        # Directory selection
        left_panel.addWidget(QLabel("<b>1. Root Directory:</b>"))
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText("Select directory containing case folders...")
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.btn_browse)
        left_panel.addLayout(dir_layout)
        
        # Lists layout (columns and skip cases)
        lists_layout = QHBoxLayout()
        
        # Column selection
        col_vbox = QVBoxLayout()
        col_vbox.addWidget(QLabel("<b>2. Columns to Extract:</b>"))
        
        col_btn_layout = QHBoxLayout()
        self.btn_select_all_cols = QPushButton("Select All")
        self.btn_select_none_cols = QPushButton("None")
        self.btn_select_all_cols.clicked.connect(
            lambda: self.select_all_items(self.col_list_widget)
        )
        self.btn_select_none_cols.clicked.connect(
            lambda: self.select_none_items(self.col_list_widget)
        )
        col_btn_layout.addWidget(self.btn_select_all_cols)
        col_btn_layout.addWidget(self.btn_select_none_cols)
        col_vbox.addLayout(col_btn_layout)
        
        self.col_list_widget = QListWidget()
        self.col_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        col_vbox.addWidget(self.col_list_widget)
        lists_layout.addLayout(col_vbox)
        
        # Skip cases selection
        skip_vbox = QVBoxLayout()
        skip_vbox.addWidget(QLabel("<b>3. Cases to SKIP:</b>"))
        
        skip_btn_layout = QHBoxLayout()
        self.btn_select_all_skip = QPushButton("Select All")
        self.btn_select_none_skip = QPushButton("None")
        self.btn_select_all_skip.clicked.connect(
            lambda: self.select_all_items(self.skip_list_widget)
        )
        self.btn_select_none_skip.clicked.connect(
            lambda: self.select_none_items(self.skip_list_widget)
        )
        skip_btn_layout.addWidget(self.btn_select_all_skip)
        skip_btn_layout.addWidget(self.btn_select_none_skip)
        skip_vbox.addLayout(skip_btn_layout)
        
        self.skip_list_widget = QListWidget()
        self.skip_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        skip_vbox.addWidget(self.skip_list_widget)
        lists_layout.addLayout(skip_vbox)
        
        left_panel.addLayout(lists_layout)
        
        # Output file path
        left_panel.addWidget(QLabel("<b>4. Output File:</b>"))
        out_layout = QHBoxLayout()
        self.out_input = QLineEdit("summary.dat")
        self.out_input.setToolTip("Full path for the output summary .dat file")
        self.btn_browse_out = QPushButton("Save As…")
        self.btn_browse_out.setToolTip("Choose where to save the summary file")
        self.btn_browse_out.clicked.connect(self.browse_output_file)
        out_layout.addWidget(self.out_input)
        out_layout.addWidget(self.btn_browse_out)
        left_panel.addLayout(out_layout)

        # Write mode: Append or Overwrite
        write_mode_layout = QHBoxLayout()
        write_mode_layout.addWidget(QLabel("Write Mode:"))
        self.write_mode_combo = QComboBox()
        self.write_mode_combo.addItems(["Overwrite", "Append"])
        self.write_mode_combo.setToolTip(
            "Overwrite: replace the existing summary file with new results.\n"
            "Append: add new rows to an existing summary file (duplicates removed)."
        )
        write_mode_layout.addWidget(self.write_mode_combo)
        write_mode_layout.addStretch()
        left_panel.addLayout(write_mode_layout)

        # Options row (avg iterations only now — output file moved above)
        opt_layout = QHBoxLayout()
        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 5000)
        self.avg_spin.setValue(DEFAULT_AVG_ITERATIONS)
        self.avg_spin.setToolTip("Number of last iterations to average")
        opt_layout.addWidget(QLabel("Avg Last N:"))
        opt_layout.addWidget(self.avg_spin)
        opt_layout.addStretch()
        left_panel.addLayout(opt_layout)
        
        # Plot checkbox
        self.plot_check = QCheckBox("Generate & Show Plots")
        self.plot_check.setChecked(True)
        left_panel.addWidget(self.plot_check)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        left_panel.addWidget(self.progress_bar)
        
        # Log output
        left_panel.addWidget(QLabel("<b>Processing Log:</b>"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        self.log_output.setStyleSheet("background-color: #f5f5f5; font-family: monospace;")
        left_panel.addWidget(self.log_output)
        
        # Run buttons
        button_layout = QHBoxLayout()
        
        self.btn_run = QPushButton("PROCESS DATA")
        self.btn_run.setStyleSheet(
            "background-color: #2E7D32; color: white; "
            "font-weight: bold; height: 40px; font-size: 14px;"
        )
        self.btn_run.clicked.connect(self.run_process)
        button_layout.addWidget(self.btn_run)
        
        self.btn_plots_only = QPushButton("GENERATE PLOTS ONLY")
        self.btn_plots_only.setStyleSheet(
            "background-color: #1976D2; color: white; "
            "font-weight: bold; height: 40px; font-size: 14px;"
        )
        self.btn_plots_only.setToolTip("Generate plots from existing summary file")
        self.btn_plots_only.clicked.connect(self.generate_plots_only)
        button_layout.addWidget(self.btn_plots_only)
        
        left_panel.addLayout(button_layout)
        
        main_layout.addLayout(left_panel, 2)
        
        # Right Panel: Plot Viewer
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("<b>Plot Preview:</b>"))
        
        # Plot display
        self.image_label = QLabel("Run processing to view plots")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("background-color: white;")
        right_panel.addWidget(self.image_label)
        
        # Plot counter
        self.plot_counter_label = QLabel("")
        self.plot_counter_label.setAlignment(Qt.AlignCenter)
        self.plot_counter_label.setStyleSheet("font-weight: bold; color: #666;")
        right_panel.addWidget(self.plot_counter_label)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◄ Previous")
        self.btn_next = QPushButton("Next ►")
        self.btn_prev.clicked.connect(self.prev_plot)
        self.btn_next.clicked.connect(self.next_plot)
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.btn_next)
        right_panel.addLayout(nav_layout)
        
        # Export plots button
        self.btn_export_plots = QPushButton("Export All Plots to PDF")
        self.btn_export_plots.clicked.connect(self.export_all_plots)
        self.btn_export_plots.setEnabled(False)
        self.btn_export_plots.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        right_panel.addWidget(self.btn_export_plots)
        
        main_layout.addLayout(right_panel, 3)
        
        # Setup keyboard shortcuts
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_plot)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_plot)
    
    def browse_output_file(self):
        """Browse for the output summary file save location."""
        current = self.out_input.text()
        start_dir = str(Path(current).parent) if current else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Summary File As", 
            current or "summary.dat",
            "Data Files (*.dat *.csv *.txt);;All Files (*)"
        )
        if path:
            self.out_input.setText(path)

    def browse_directory(self):
        """Browse for root directory."""
        last_dir = self.settings.value("aerosummary/last_directory", "")
        directory = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", last_dir
        )
        if directory:
            self.dir_input.setText(directory)
            self.settings.setValue("aerosummary/last_directory", directory)
            self.refresh_lists(directory)
    
    def load_last_directory(self):
        """Load the last used directory."""
        last_dir = self.settings.value("aerosummary/last_directory", "")
        if last_dir and os.path.exists(last_dir):
            self.dir_input.setText(last_dir)
            self.refresh_lists(last_dir)
    
    def refresh_lists(self, root: str):
        """Refresh column and case lists based on directory."""
        self.skip_list_widget.clear()
        self.col_list_widget.clear()
        self.log("Scanning directory...")
        
        # Auto-generate output filename based on Mach numbers, preserving any existing directory
        suggested_filename = AeroSummary.generate_output_filename(root)
        existing = self.out_input.text()
        existing_dir = str(Path(existing).parent) if existing and Path(existing).parent != Path(".") else ""
        if existing_dir:
            self.out_input.setText(str(Path(existing_dir) / suggested_filename))
        else:
            self.out_input.setText(suggested_filename)
        
        # Get available columns
        columns = AeroSummary.get_available_columns(root)
        if columns:
            self.col_list_widget.addItems(columns)
            
            # Auto-select common columns
            common_cols = ['CD', 'CL', 'CMy', 'CL/CD', 'CFx', 'CFy', 'CFz']
            for i in range(self.col_list_widget.count()):
                item = self.col_list_widget.item(i)
                if item.text() in common_cols:
                    item.setSelected(True)
        
        # Get case directories
        case_dirs = AeroSummary.get_case_directories(root)
        self.skip_list_widget.addItems(case_dirs)
        
        self.log(f"Found {len(case_dirs)} case folders")
        if columns:
            self.log(f"Found {len(columns)} columns in history files")
        self.log(f"Suggested output: {suggested_filename}")
    
    def select_all_items(self, list_widget: QListWidget):
        """Select all items in a list widget."""
        for i in range(list_widget.count()):
            list_widget.item(i).setSelected(True)
    
    def select_none_items(self, list_widget: QListWidget):
        """Deselect all items in a list widget."""
        list_widget.clearSelection()
    
    def log(self, message: str):
        """Add message to log output."""
        self.log_output.append(message)
    
    def run_process(self):
        """Start the data processing."""
        root = self.dir_input.text()
        cols = [item.text() for item in self.col_list_widget.selectedItems()]
        skip = [item.text() for item in self.skip_list_widget.selectedItems()]
        
        # Validation
        if not root:
            QMessageBox.warning(self, "Input Error", "Please select a root directory.")
            return
        
        if not os.path.exists(root):
            QMessageBox.warning(self, "Input Error", "Selected directory does not exist.")
            return
        
        if not cols:
            QMessageBox.warning(self, "Input Error", "Please select at least one column to extract.")
            return
        
        # Clear previous results
        self.log_output.clear()
        self.plot_list = []
        self.current_plot_idx = 0
        self.update_plot_counter()
        
        # Setup UI for processing
        self.btn_run.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Create and start worker thread
        append_mode = self.write_mode_combo.currentText() == "Append"
        self.processing_thread = ProcessingThread(
            root, self.out_input.text(), cols,
            self.avg_spin.value(), self.plot_check.isChecked(),
            DEFAULT_PLOT_DIR, skip, append_mode=append_mode
        )
        
        self.processing_thread.log_signal.connect(self.log)
        self.processing_thread.progress_signal.connect(self.progress_bar.setValue)
        self.processing_thread.finished_signal.connect(self.on_processing_finished)
        self.processing_thread.error_signal.connect(self.on_processing_error)
        
        self.processing_thread.start()
    
    def on_processing_finished(self, plot_files: List[str]):
        """Handle completion of processing."""
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if plot_files:
            self.plot_list = plot_files
            self.current_plot_idx = 0
            self.btn_prev.setEnabled(True)
            self.btn_next.setEnabled(True)
            self.btn_export_plots.setEnabled(True)
            self.display_plot()
            self.log(f"\n✓ Generated {len(plot_files)} plots")
        else:
            self.log("\nProcessing complete (no plots generated)")
        
        QMessageBox.information(self, "Success", "Processing completed successfully!")
        self.status_message.emit("AeroSummary processing complete")
    
    def on_processing_error(self, error_msg: str):
        """Handle processing error."""
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log(f"\n✗ {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self.status_message.emit(f"AeroSummary error: {error_msg}")
    
    def display_plot(self):
        """Display the current plot."""
        if not self.plot_list:
            self.image_label.setText("No plots available")
            self.update_plot_counter()
            return
        
        try:
            plot_path = self.plot_list[self.current_plot_idx]
            if not os.path.exists(plot_path):
                self.image_label.setText(f"Plot file not found:\n{plot_path}")
                return
            
            pixmap = QPixmap(plot_path)
            if pixmap.isNull():
                self.image_label.setText(f"Failed to load plot:\n{plot_path}")
                return
            
            # Scale image to fit label while keeping aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.image_label.width(),
                self.image_label.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.update_plot_counter()
            
        except Exception as e:
            self.image_label.setText(f"Error displaying plot:\n{str(e)}")
    
    def update_plot_counter(self):
        """Update the plot counter label."""
        if self.plot_list:
            self.plot_counter_label.setText(
                f"Plot {self.current_plot_idx + 1} of {len(self.plot_list)}"
            )
        else:
            self.plot_counter_label.setText("")
    
    def next_plot(self):
        """Show next plot."""
        if self.plot_list:
            self.current_plot_idx = (self.current_plot_idx + 1) % len(self.plot_list)
            self.display_plot()
    
    def prev_plot(self):
        """Show previous plot."""
        if self.plot_list:
            self.current_plot_idx = (self.current_plot_idx - 1) % len(self.plot_list)
            self.display_plot()
    
    def export_all_plots(self):
        """Export all plots to a single PDF file."""
        if not self.plot_list:
            return
        
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Export Plots to PDF", "aerosummary_plots.pdf", "PDF Files (*.pdf)"
        )
        
        if not output_path:
            return
        
        try:
            with PdfPages(output_path) as pdf:
                for plot_file in self.plot_list:
                    img = plt.imread(plot_file)
                    fig = plt.figure(figsize=(11, 8.5))
                    plt.imshow(img)
                    plt.axis('off')
                    pdf.savefig(fig, bbox_inches='tight')
                    plt.close(fig)
            
            QMessageBox.information(self, "Success", f"Plots exported to:\n{output_path}")
            self.log(f"✓ Exported {len(self.plot_list)} plots to PDF")
            self.status_message.emit(f"Exported {len(self.plot_list)} plots to PDF")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export plots:\n{str(e)}")
    
    def resizeEvent(self, event):
        """Handle window resize to refresh plot display."""
        super().resizeEvent(event)
        if self.plot_list:
            self.display_plot()
    
    def generate_plots_only(self):
        """Generate plots from existing summary file without reprocessing data."""
        # Check if summary file exists
        summary_file = self.out_input.text()
        
        if not os.path.exists(summary_file):
            QMessageBox.warning(
                self, 
                "File Not Found",
                f"Summary file not found: {summary_file}\n\n"
                "Please run 'PROCESS DATA' first or select an existing summary file."
            )
            return
        
        # Get selected columns
        cols = [item.text() for item in self.col_list_widget.selectedItems()]
        
        if not cols:
            QMessageBox.warning(
                self, "Input Error", 
                "Please select at least one column to plot."
            )
            return
        
        # Clear previous plots
        self.plot_list = []
        self.current_plot_idx = 0
        self.update_plot_counter()
        
        # Setup UI
        self.btn_run.setEnabled(False)
        self.btn_plots_only.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_output.clear()
        self.log(f"Generating plots from: {summary_file}")
        
        try:
            # Generate plots directly
            plot_files = AeroSummary.generate_plots_from_file(
                summary_file,
                cols,
                DEFAULT_PLOT_DIR,
                self.progress_bar.setValue
            )
            
            if plot_files:
                self.plot_list = plot_files
                self.current_plot_idx = 0
                self.btn_prev.setEnabled(True)
                self.btn_next.setEnabled(True)
                self.btn_export_plots.setEnabled(True)
                self.display_plot()
                self.log(f"\n✓ Generated {len(plot_files)} plots")
                QMessageBox.information(
                    self, "Success", 
                    f"Generated {len(plot_files)} plots successfully!"
                )
            else:
                self.log("\n✗ No plots generated")
                QMessageBox.warning(
                    self, "No Plots", 
                    "No plots were generated. Check the log for details."
                )
            
        except Exception as e:
            self.log(f"\n✗ Error: {str(e)}")
            QMessageBox.critical(
                self, "Error", 
                f"Failed to generate plots:\n{str(e)}"
            )
        finally:
            self.btn_run.setEnabled(True)
            self.btn_plots_only.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.status_message.emit("Plots generation complete")

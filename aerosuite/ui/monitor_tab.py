"""
SU2 Convergence Monitor Tab UI.

Provides real-time monitoring of SU2 convergence from history files.
"""

import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QCheckBox, QFileDialog, QGroupBox, QFrame, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from ..core.monitor import SU2Monitor


class MatplotlibWidget(QWidget):
    """Widget containing matplotlib figure with canvas and toolbar."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # Configure matplotlib
        matplotlib.rcParams['lines.linewidth'] = 2
        matplotlib.rcParams['figure.edgecolor'] = 'blue'
        matplotlib.rcParams['figure.frameon'] = True
        matplotlib.rcParams["figure.subplot.left"] = 0.10
        matplotlib.rcParams["figure.subplot.right"] = 0.6
        matplotlib.rcParams["figure.subplot.top"] = 0.9
        matplotlib.rcParams["figure.subplot.bottom"] = 0.1
        matplotlib.rcParams["figure.subplot.wspace"] = 0.1
        matplotlib.rcParams["figure.subplot.hspace"] = 0.1
        
        # Create layout
        layout = QGridLayout(self)
        
        groupbox = QGroupBox("Convergence")
        layout.addWidget(groupbox)
        
        mpl_layout = QVBoxLayout()
        groupbox.setLayout(mpl_layout)
        mpl_layout.addWidget(self.toolbar)
        mpl_layout.addWidget(self.canvas)
    
    def plot(self, filename: str, selected_columns, normalize: bool):
        """Plot residuals from history file."""
        if not filename:
            return
        
        iterations, data_lists, column_names = SU2Monitor.get_plot_data(
            filename, selected_columns, normalize
        )
        
        if not data_lists:
            return
        
        self.figure.clf()
        ax = self.figure.add_subplot(111)
        
        ax.set_xlabel('iterations')
        ax.set_ylabel('residuals')
        
        # Plot each selected column
        plot_list = []
        for data, name in zip(data_lists, column_names):
            p, = ax.plot(iterations, data, label=name)
            plot_list.append(p)
        
        # Add legend
        ax.legend(
            bbox_to_anchor=(1.01, 1),
            loc='upper left',
            prop={'size': 6, 'weight': 'bold'},
            borderaxespad=None
        )
        
        self.figure.tight_layout()
        self.canvas.draw_idle()


class MonitorTab(QWidget):
    """SU2 Convergence Monitor tab widget."""
    
    # Signal for status updates
    status_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitor = SU2Monitor()
        self.filename = ""
        self.normalize = False
        self.checkboxes = []
        
        self.setup_ui()
        
        # Setup timer for auto-refresh
        self.timer = QTimer()
        self.timer.setInterval(500)  # 500ms refresh
        self.timer.timeout.connect(self.plot_data)
        self.timer.start()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        
        # Create matplotlib widget
        self.figure_widget = MatplotlibWidget()
        
        # Create control panel
        self.btn_layout = QVBoxLayout()
        
        # File selection
        self.btn_openfile = QPushButton("Select File")
        self.btn_openfile.clicked.connect(self.select_file)
        self.btn_openfile.setToolTip('Click to select the file containing the residual data')
        
        self.show_filename = QLabel("No file selected")
        self.show_filename.setWordWrap(True)
        
        # Start/Stop button
        self.btn_plot_data = QPushButton('Stop')
        self.btn_plot_data.setToolTip('Click to stop real time data gathering')
        self.btn_plot_data.clicked.connect(self.timer_start_stop)
        
        # Normalize checkbox
        self.btn_normalize = QCheckBox('Normalize')
        self.btn_normalize.setToolTip('Normalize all residuals with the value at iteration 1')
        self.btn_normalize.stateChanged.connect(self.update_normalize)
        
        # Add controls to layout
        self.btn_layout.addWidget(self.btn_openfile)
        self.btn_layout.addWidget(self.show_filename)
        self.btn_layout.addWidget(self.btn_plot_data)
        self.btn_layout.addWidget(self.btn_normalize)
        self.btn_layout.addStretch()
        
        # Create left side frame with controls
        left_frame = QFrame()
        left_frame.setLayout(self.btn_layout)
        
        # Combine controls and plot in splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_frame)
        splitter.addWidget(self.figure_widget)
        splitter.setSizes([75, 700])
        
        layout.addWidget(splitter)
    
    def select_file(self):
        """Open file dialog to select history file."""
        fname, _ = QFileDialog.getOpenFileName(
            self, 'Open file', 'history.csv',
            filter='csv files (*.csv)\ndat files (*.dat)\nall files (*)'
        )
        
        if not fname:
            return
        
        self.filename = fname
        
        # Clear old checkboxes
        self.clear_checkboxes()
        
        # Update file display
        fn = os.path.basename(self.filename)
        fb = os.path.basename(os.path.dirname(self.filename))
        self.show_filename.setText(os.path.join(fb, fn))
        self.show_filename.setToolTip(self.filename)
        
        # Create new checkboxes for columns
        self.update_checkboxes()
        
        self.status_message.emit(f"Loaded file: {fn}")
    
    def clear_checkboxes(self):
        """Remove all existing checkboxes."""
        for checkbox in self.checkboxes:
            self.btn_layout.removeWidget(checkbox)
            checkbox.setParent(None)
            checkbox.deleteLater()
        self.checkboxes = []
        self.btn_layout.update()
    
    def update_checkboxes(self):
        """Create checkboxes for each column in the file."""
        if not self.filename:
            return
        
        column_names = self.monitor.get_column_names(self.filename)
        
        self.checkboxes = []
        for name in column_names:
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)  # All checked by default
            checkbox.toggled.connect(self.plot_data)
            self.checkboxes.append(checkbox)
        
        # Add checkboxes to layout
        for checkbox in self.checkboxes:
            self.btn_layout.addWidget(checkbox)
        
        self.btn_layout.addStretch()
        self.btn_layout.update()
    
    def update_normalize(self, state):
        """Update normalization setting."""
        self.normalize = (state == Qt.Checked)
    
    def timer_start_stop(self):
        """Toggle the auto-refresh timer."""
        if self.timer.isActive():
            self.timer.stop()
            self.btn_plot_data.setText('Start')
            self.btn_plot_data.setToolTip('Click to start real time data gathering')
        else:
            self.timer.start()
            self.btn_plot_data.setText('Stop')
            self.btn_plot_data.setToolTip('Click to stop real time data gathering')
        self.btn_plot_data.update()
        self.btn_layout.update()
    
    def plot_data(self):
        """Plot the current data."""
        if not self.filename:
            return
        
        checklist = [cb.isChecked() for cb in self.checkboxes]
        self.figure_widget.plot(self.filename, checklist, self.normalize)

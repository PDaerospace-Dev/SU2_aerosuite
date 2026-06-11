"""
ISA Calculator + y+ First Cell Height Calculator Tab UI.

Two horizontal sub-tabs inside ISATab:
  0 — ISA Calculator  (atmospheric properties)
  1 — y+ Calculator   (first cell height)

Styled to match the Sweep Runner tab (section headers, hline dividers,
_btn_style buttons, clean grid inputs, alternating result rows).
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..core.isa_calculator import ISACalculator
from ..core.yplus_calculator import calculate as yplus_calculate


# ── Shared style helpers (same pattern as sweep_tab.py) ──────────────────────

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


def _btn_style(color: str) -> str:
    return (
        f"background: {color}; color: white; font-weight: bold;"
        "padding: 7px 18px; border-radius: 4px;"
    )


def _fmt(v: float, p: int = 4) -> str:
    if abs(v) >= 1e4 or (abs(v) < 1e-3 and v != 0):
        return f"{v:.4e}"
    return f"{v:.{p}f}"


# ── Result row builder ────────────────────────────────────────────────────────

def _result_row(grid: QGridLayout, row: int, label: str,
                unit: str, bg: str, val_color: str) -> QLabel:
    """Add a label / value / unit row to grid; return the value QLabel."""
    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: #546e7a; background: {bg}; padding: 4px 6px;")
    val = QLabel("—")
    val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    val.setStyleSheet(
        f"font-weight: bold; font-size: 12px; color: {val_color}; "
        f"background: {bg}; padding: 4px 6px;"
    )
    unt = QLabel(unit)
    unt.setStyleSheet(
        f"font-style: italic; color: #78909c; background: {bg}; padding: 4px 6px;"
    )
    grid.addWidget(lbl, row, 0)
    grid.addWidget(val, row, 1)
    grid.addWidget(unt, row, 2)
    return val


# ── ISA sub-widget ────────────────────────────────────────────────────────────

class _ISAWidget(QWidget):
    transfer_su2_requested   = pyqtSignal(str, str, str)
    transfer_yplus_requested = pyqtSignal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.calculator = ISACalculator()
        self._results   = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Inputs ────────────────────────────────────────────────────────────
        root.addWidget(_section_header("INPUT PARAMETERS"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(0, 130)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("Altitude (km):"),    0, 0)
        self.alt_input = QLineEdit("0")
        self.alt_input.setToolTip("Altitude in kilometers (0–100)")
        self.alt_input.returnPressed.connect(self.calculate)
        grid.addWidget(self.alt_input,              0, 1)

        grid.addWidget(QLabel("Target Mach:"),      1, 0)
        self.mach_input = QLineEdit("1.0")
        self.mach_input.setToolTip("Mach number for calculations")
        self.mach_input.returnPressed.connect(self.calculate)
        grid.addWidget(self.mach_input,             1, 1)

        grid.addWidget(QLabel("Char. Length (m):"), 2, 0)
        self.len_input = QLineEdit("1.0")
        self.len_input.setToolTip("Characteristic length in metres")
        self.len_input.returnPressed.connect(self.calculate)
        grid.addWidget(self.len_input,              2, 1)

        root.addLayout(grid)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.calc_btn = QPushButton("Calculate ISA Properties")
        self.calc_btn.setStyleSheet(_btn_style("#2E7D32"))
        self.calc_btn.clicked.connect(self.calculate)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(_btn_style("#c62828"))
        self.clear_btn.clicked.connect(self.clear_fields)

        btn_row.addWidget(self.calc_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addWidget(_hline())

        # ── Results grid ──────────────────────────────────────────────────────
        root.addWidget(_section_header("ATMOSPHERIC PROPERTIES"))

        atm_grid = QGridLayout()
        atm_grid.setSpacing(0)
        atm_grid.setColumnStretch(1, 1)
        rows_atm = [
            ("Ambient Temp",      "K",         "#f1f8e9", "#2e7d32"),
            ("Static Pressure",   "Pa",        "#e8f5e9", "#1b5e20"),
            ("Air Density",       "kg/m³",     "#f1f8e9", "#2e7d32"),
        ]
        self.temp_val  = _result_row(atm_grid, 0, *rows_atm[0])
        self.press_val = _result_row(atm_grid, 1, *rows_atm[1])
        self.rho_val   = _result_row(atm_grid, 2, *rows_atm[2])
        root.addLayout(atm_grid)

        root.addWidget(_section_header("VISCOSITY PROPERTIES"))

        vis_grid = QGridLayout()
        vis_grid.setSpacing(0)
        vis_grid.setColumnStretch(1, 1)
        self.mu_val = _result_row(vis_grid, 0, "Dynamic Visc μ",  "kg/(m·s)", "#e3f2fd", "#1565c0")
        self.nu_val = _result_row(vis_grid, 1, "Kinematic Visc ν","m²/s",     "#e8eaf6", "#283593")
        root.addLayout(vis_grid)

        root.addWidget(_section_header("FLOW PARAMETERS"))

        flow_grid = QGridLayout()
        flow_grid.setSpacing(0)
        flow_grid.setColumnStretch(1, 1)
        self.sos_val = _result_row(flow_grid, 0, "Speed of Sound",  "m/s", "#fff3e0", "#e65100")
        self.tas_val = _result_row(flow_grid, 1, "Velocity",   "m/s", "#fbe9e7", "#bf360c")
        self.q_val   = _result_row(flow_grid, 2, "Dyn. Pressure (Q)", "Pa",  "#fff3e0", "#e65100")
        self.re_val  = _result_row(flow_grid, 3, "Reynolds Number", "—",   "#fce4ec", "#880e4f")
        root.addLayout(flow_grid)

        root.addWidget(_hline())

        # ── Transfer buttons ──────────────────────────────────────────────────
        root.addWidget(_section_header("TRANSFER"))

        xfer_row = QHBoxLayout()
        su2_btn = QPushButton("→  Update SU2 Parameters")
        su2_btn.setStyleSheet(_btn_style("#1565c0"))
        su2_btn.setToolTip("Transfer altitude, temperature and Reynolds number to SU2 Generator tab")
        su2_btn.clicked.connect(self._transfer_su2)

        yplus_btn = QPushButton("→  Calculate y+")
        yplus_btn.setStyleSheet(_btn_style("#6a1b9a"))
        yplus_btn.setToolTip("Send ISA flow conditions to the y+ Calculator tab")
        yplus_btn.clicked.connect(self._transfer_yplus)

        xfer_row.addWidget(su2_btn)
        xfer_row.addWidget(yplus_btn)
        xfer_row.addStretch()
        root.addLayout(xfer_row)

        root.addStretch()

    # ── slots ─────────────────────────────────────────────────────────────────

    def calculate(self):
        try:
            h = float(self.alt_input.text())
            m = float(self.mach_input.text())
            L = float(self.len_input.text())
            if not 0 <= h <= 100:
                QMessageBox.warning(self, "Input Error", "Altitude must be 0–100 km")
                return
            r = self.calculator.calculate(h, m, L)
            self._results = r
            self.temp_val.setText(f"{r['temperature']:.2f}")
            self.press_val.setText(f"{r['pressure']:.2f}")
            self.rho_val.setText(f"{r['density']:.5e}")
            self.mu_val.setText(f"{r['dynamic_viscosity']:.5e}")
            self.nu_val.setText(f"{r['kinematic_viscosity']:.5e}")
            self.sos_val.setText(f"{r['speed_of_sound']:.2f}")
            self.tas_val.setText(f"{r['true_airspeed']:.2f}")
            self.q_val.setText(f"{r['dynamic_pressure']:.2f}")
            self.re_val.setText(f"{r['reynolds_number']:.4e}")
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numbers")
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Error: {e}")

    def clear_fields(self):
        self.alt_input.setText("0")
        self.mach_input.setText("1.0")
        self.len_input.setText("1.0")
        self._results = {}
        for lbl in (self.temp_val, self.press_val, self.rho_val,
                    self.mu_val, self.nu_val, self.sos_val,
                    self.tas_val, self.q_val, self.re_val):
            lbl.setText("—")

    def _transfer_su2(self):
        try:
            if self.temp_val.text() == "—":
                QMessageBox.warning(self, "No Data",
                                    "Please calculate ISA properties first.")
                return
            altitude = self.alt_input.text().strip()
            alt_str  = f"{altitude}km" if not altitude.endswith("km") else altitude
            temp_val = "".join(c for c in self.temp_val.text() if c.isdigit() or c == ".")
            self.transfer_su2_requested.emit(alt_str, temp_val, self.re_val.text())
        except Exception as e:
            QMessageBox.critical(self, "Transfer Error", f"Failed to transfer:\n{e}")

    def _transfer_yplus(self):
        if not self._results:
            self.calculate()
        if not self._results:
            return
        r = self._results
        try:
            L = float(self.len_input.text())
        except ValueError:
            L = 1.0
        self.transfer_yplus_requested.emit(
            r["true_airspeed"],
            r["density"],
            r["dynamic_viscosity"],
            L,
        )


# ── y+ sub-widget ─────────────────────────────────────────────────────────────

class _YPlusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._domain = "External"
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Inputs ────────────────────────────────────────────────────────────
        root.addWidget(_section_header("INPUT PARAMETERS"))

        hint = QLabel("Values auto-filled from ISA Calculator via  →  Calculate y+")
        hint.setStyleSheet(
            "color: #6a1b9a; font-style: italic; font-size: 9px; padding: 0px 2px;"
        )
        root.addWidget(hint)

        inp_grid = QGridLayout()
        inp_grid.setHorizontalSpacing(6)
        inp_grid.setVerticalSpacing(4)
        inp_grid.setColumnMinimumWidth(0, 150)
        inp_grid.setColumnStretch(1, 1)

        fields = [
            ("Flow Velocity",     "m/s",      "1.0",     "vel_input"),
            ("Fluid Density",     "kg/m³",    "1.225",   "rho_input"),
            ("Dynamic Viscosity", "kg/(m·s)", "1.81e-5", "mu_input"),
            ("Char. Length",      "m",        "1.0",     "len_input"),
            ("Target y+",         "—",        "1.0",     "yp_input"),
        ]
        for i, (label, unit, default, attr) in enumerate(fields):
            inp_grid.addWidget(QLabel(f"{label}:"), i, 0)
            edit = QLineEdit(default)
            edit.returnPressed.connect(self.calculate)
            inp_grid.addWidget(edit, i, 1)
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet("color: #546e7a; font-style: italic;")
            inp_grid.addWidget(unit_lbl, i, 2)
            setattr(self, attr, edit)

        root.addLayout(inp_grid)

        # ── Domain toggle ─────────────────────────────────────────────────────
        root.addWidget(_hline())
        root.addWidget(_section_header("FLOW DOMAIN"))

        dom_row = QHBoxLayout()
        self.ext_btn = QPushButton("  External  ")
        self.int_btn = QPushButton("  Internal  ")
        for btn in (self.ext_btn, self.int_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
        self.ext_btn.setChecked(True)
        self._style_domain_btns()
        self.ext_btn.clicked.connect(lambda: self._set_domain("External"))
        self.int_btn.clicked.connect(lambda: self._set_domain("Internal"))
        dom_row.addWidget(self.ext_btn)
        dom_row.addWidget(self.int_btn)
        dom_row.addStretch()
        root.addLayout(dom_row)

        # ── Calculate button ──────────────────────────────────────────────────
        calc_btn = QPushButton("  CALCULATE y+")
        calc_btn.setStyleSheet(_btn_style("#6a1b9a"))
        calc_btn.clicked.connect(self.calculate)
        root.addWidget(calc_btn)

        root.addWidget(_hline())

        # ── Results ───────────────────────────────────────────────────────────
        root.addWidget(_section_header("RESULTS"))

        res_grid = QGridLayout()
        res_grid.setSpacing(0)
        res_grid.setColumnStretch(1, 1)

        result_defs = [
            ("Flow Regime",          "regime",   "—",   "#edfff4", "#2e7d32"),
            ("Reynolds Number",      "Re",       "—",   "#e8eaf6", "#1a237e"),
            ("Skin Friction Cf",     "Cf",       "—",   "#fff3e0", "#e65100"),
            ("Wall Shear τ_w",       "tau_w",    "Pa",  "#fffde7", "#f57f17"),
            ("Friction Vel. u_τ",    "u_tau",    "m/s", "#edfff4", "#2e7d32"),
            ("First Cell Height y₁", "y1",       "m",   "#e8eaf6", "#1565c0"),
            ("  (in mm)",            "y1_mm",    "mm",  "#e3f2fd", "#1565c0"),
            ("Prism Layers",         "n_layers", "—",   "#f3e5f5", "#4a148c"),
        ]

        self._result_labels = {}
        for i, (label, key, unit, bg, color) in enumerate(result_defs):
            val = _result_row(res_grid, i, label, unit, bg, color)
            self._result_labels[key] = val

        root.addLayout(res_grid)

        root.addWidget(_hline())

        # ── Formula card ──────────────────────────────────────────────────────
        root.addWidget(_section_header("EMPIRICAL FORMULA USED"))

        self.formula_name_lbl = QLabel("—")
        self.formula_name_lbl.setStyleSheet(
            "font-weight: bold; font-size: 11px; color: #e65100; padding: 2px 4px;"
        )
        self.formula_name_lbl.setWordWrap(True)
        root.addWidget(self.formula_name_lbl)

        eq_frame = QFrame()
        eq_frame.setStyleSheet(
            "background: #e8eaf6; border-left: 4px solid #3949ab; border-radius: 3px;"
        )
        eq_layout = QVBoxLayout(eq_frame)
        eq_layout.setContentsMargins(12, 6, 12, 6)
        self.formula_eq_lbl = QLabel("Run a calculation first")
        self.formula_eq_lbl.setFont(QFont("Courier New", 11, QFont.Bold))
        self.formula_eq_lbl.setStyleSheet("color: #1a237e; background: transparent;")
        eq_layout.addWidget(self.formula_eq_lbl)
        root.addWidget(eq_frame)

        self.formula_det_lbl = QLabel("")
        self.formula_det_lbl.setStyleSheet(
            "color: #78909c; font-size: 10px; padding: 2px 4px;"
        )
        self.formula_det_lbl.setWordWrap(True)
        root.addWidget(self.formula_det_lbl)

        root.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── domain helpers ────────────────────────────────────────────────────────

    def _set_domain(self, domain: str):
        self._domain = domain
        self.ext_btn.setChecked(domain == "External")
        self.int_btn.setChecked(domain == "Internal")
        self._style_domain_btns()

    def _style_domain_btns(self):
        active   = _btn_style("#1976D2") + " padding: 5px 14px;"
        inactive = (
            "background: #e8eaf6; color: #546e7a; font-weight: bold;"
            "padding: 5px 14px; border-radius: 4px;"
        )
        self.ext_btn.setStyleSheet(active   if self._domain == "External" else inactive)
        self.int_btn.setStyleSheet(inactive if self._domain == "External" else active)

    # ── public ────────────────────────────────────────────────────────────────

    def populate_from_isa(self, velocity: float, density: float,
                          dynamic_viscosity: float, char_length: float):
        self.vel_input.setText(f"{velocity:.4f}")
        self.rho_input.setText(f"{density:.5e}")
        self.mu_input.setText(f"{dynamic_viscosity:.5e}")
        self.len_input.setText(f"{char_length:.4f}")

    def calculate(self):
        try:
            V   = float(self.vel_input.text())
            rho = float(self.rho_input.text())
            mu  = float(self.mu_input.text())
            L   = float(self.len_input.text())
            yp  = float(self.yp_input.text())
            if any(x <= 0 for x in (V, rho, mu, L, yp)):
                QMessageBox.warning(self, "Input Error",
                                    "All values must be positive.")
                return
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numbers.")
            return

        try:
            r = yplus_calculate(V, rho, mu, L, yp, self._domain)
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Error: {e}")
            return

        regime_color = "#2e7d32" if r["flow_type"] == "Laminar" else "#e65100"
        self._result_labels["regime"].setText(r["regime_label"])
        self._result_labels["regime"].setStyleSheet(
            f"font-weight: bold; font-size: 12px; color: {regime_color}; "
            "background: #edfff4; padding: 4px 6px;"
        )
        self._result_labels["Re"].setText(f"{r['Re']:,.0f}")
        self._result_labels["Cf"].setText(_fmt(r["Cf"]))
        self._result_labels["tau_w"].setText(f"{_fmt(r['tau_w'])} Pa")
        self._result_labels["u_tau"].setText(f"{_fmt(r['u_tau'])} m/s")
        self._result_labels["y1"].setText(f"{r['y1']:.6e} m")
        self._result_labels["y1_mm"].setText(f"{r['y1_mm']:.6e} mm")
        self._result_labels["n_layers"].setText(str(r["n_layers"]))

        f = r["formula"]
        self.formula_name_lbl.setText(f["name"])
        self.formula_eq_lbl.setText(f["latex"])
        self.formula_det_lbl.setText(f["detail"])


# ── Public ISATab ─────────────────────────────────────────────────────────────

class ISATab(QWidget):
    """
    Outer tab with two sub-tabs: ISA Calculator and y+ Calculator.
    transfer_requested signal is unchanged so main.py needs no edits.
    """

    transfer_requested = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 6px 20px; font-size: 11px; }"
            "QTabBar::tab:selected { font-weight: bold; color: #1a237e; "
            "border-bottom: 2px solid #1a237e; }"
        )

        self.isa_widget   = _ISAWidget()
        self.yplus_widget = _YPlusWidget()

        self.tabs.addTab(self.isa_widget,   "ISA Calculator")
        self.tabs.addTab(self.yplus_widget, "y+ Calculator")

        self.isa_widget.transfer_su2_requested.connect(self.transfer_requested)
        self.isa_widget.transfer_yplus_requested.connect(self._handle_yplus_transfer)

        layout.addWidget(self.tabs)

    def _handle_yplus_transfer(self, velocity: float, density: float,
                               dynamic_viscosity: float, char_length: float):
        self.yplus_widget.populate_from_isa(velocity, density, dynamic_viscosity, char_length)
        self.yplus_widget.calculate()
        self.tabs.setCurrentWidget(self.yplus_widget)

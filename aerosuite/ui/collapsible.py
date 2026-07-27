"""
Generic collapsible section — wraps arbitrary content behind a toggle
button, collapsed by default. Same interaction pattern as ReferencePanel,
generalized so any section (Advanced Numerics, Custom Placeholders, ...)
can use it without bespoke toggle plumbing.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt5.QtCore import Qt

from .style import TOGGLE_BUTTON_STYLE


class CollapsibleSection(QWidget):
    """A titled section whose body is hidden until the toggle is clicked."""

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)

        self._sync_label()
        self.body.setVisible(self._expanded)

    def addWidget(self, widget):
        self.body_layout.addWidget(widget)

    def addLayout(self, sub_layout):
        self.body_layout.addLayout(sub_layout)

    def _toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self._sync_label()

    def _sync_label(self):
        arrow = "▾" if self._expanded else "▸"
        self.toggle_btn.setText(f"{arrow}  {self._title}")

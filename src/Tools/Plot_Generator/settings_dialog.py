"""Settings dialog for the Plot Generator GUI."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

from Main_App.gui.components import make_action_button


class _SettingsDialog(QDialog):
    """Dialog for configuring plot options."""

    def __init__(self, parent: QWidget, color_a: str, color_b: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)

        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Condition A Color:"))
        self.color_a = color_a
        pick_a = make_action_button("Custom...", compact=True)
        pick_a.clicked.connect(lambda: self._choose_custom("a"))
        row_a.addWidget(pick_a)
        layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Condition B Color:"))
        self.color_b = color_b
        pick_b = make_action_button("Custom...", compact=True)
        pick_b.clicked.connect(lambda: self._choose_custom("b"))
        row_b.addWidget(pick_b)
        layout.addLayout(row_b)

        btns = QHBoxLayout()
        ok = make_action_button("OK", variant="primary")
        ok.clicked.connect(self.accept)
        cancel = make_action_button("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def _choose_custom(self, which: str) -> None:
        init = self.color_a if which == "a" else self.color_b
        color = QColorDialog.getColor(QColor(init), self)
        if color.isValid():
            if which == "a":
                self.color_a = color.name()
            else:
                self.color_b = color.name()

    def selected_colors(self) -> tuple[str, str]:
        return self.color_a.lower(), self.color_b.lower()

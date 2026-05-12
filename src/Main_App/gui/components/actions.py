"""Shared action-row primitives for app windows and dialogs."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ActionRow(QWidget):
    """Presentation-only horizontal row for command buttons."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        alignment: Qt.AlignmentFlag = Qt.AlignRight,
        spacing: int = 8,
    ) -> None:
        super().__init__(parent)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(spacing)
        if alignment == Qt.AlignRight:
            self.row_layout.addStretch(1)
        self._alignment = alignment

    def add_button(self, button: QPushButton) -> QPushButton:
        self.row_layout.addWidget(button)
        return button


def make_action_row(
    buttons: Iterable[QPushButton] = (),
    *,
    parent: QWidget | None = None,
    alignment: Qt.AlignmentFlag = Qt.AlignRight,
) -> ActionRow:
    row = ActionRow(parent, alignment=alignment)
    for button in buttons:
        row.add_button(button)
    return row

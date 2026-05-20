"""Shared form helpers for PySide6 UI surfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QWidget

from .buttons import make_action_button


def make_form_layout() -> QFormLayout:
    """Create the standard form layout used by main-shell cards."""
    layout = QFormLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setHorizontalSpacing(14)
    layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    layout.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
    return layout


class PathPickerRow(QWidget):
    """Presentation-only path field and action button row."""

    def __init__(
        self,
        button_text: str,
        parent: QWidget | None = None,
        *,
        placeholder: str = "",
        read_only: bool = True,
        compact_button: bool = False,
    ) -> None:
        super().__init__(parent)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(10)

        self.line_edit = QLineEdit(self)
        self.line_edit.setReadOnly(read_only)
        self.line_edit.setPlaceholderText(placeholder)

        self.button = make_action_button(button_text, compact=compact_button, parent=self)

        self.row_layout.addWidget(self.line_edit, 1)
        self.row_layout.addWidget(self.button, 0)

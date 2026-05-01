"""Shared non-blocking status banner widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

_SUPPORTED_VARIANTS = {"info", "warning", "error", "success"}


class StatusBanner(QWidget):
    """Presentation-only banner for explanatory inline status messages."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        variant: str = "info",
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.banner_layout = QHBoxLayout(self)
        self.banner_layout.setContentsMargins(10, 8, 10, 8)
        self.banner_layout.setSpacing(8)

        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.banner_layout.addWidget(self.label, 1)
        self.set_variant(variant)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def setText(self, text: str) -> None:
        """Qt-style alias for callers migrated from QLabel."""
        self.set_text(text)

    def text(self) -> str:
        return self.label.text()

    def setWordWrap(self, on: bool) -> None:
        self.label.setWordWrap(on)

    def set_variant(self, variant: str) -> None:
        if variant not in _SUPPORTED_VARIANTS:
            raise ValueError(f"Unsupported status banner variant: {variant!r}")
        self.setProperty("statusVariant", variant)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

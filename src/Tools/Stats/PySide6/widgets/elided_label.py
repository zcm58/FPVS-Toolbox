"""Elided QLabel helpers for long paths or lists."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel


class ElidedPathLabel(QLabel):
    """QLabel that elides long text in the middle while preserving full text."""

    def __init__(self, *args, **kwargs) -> None:
        """Set up this object so it is ready to be used by the Stats tool."""
        super().__init__(*args, **kwargs)
        self._full_text = ""
        self._display_text = ""
        initial_text = super().text()
        self.set_full_text(initial_text)

    def set_full_text(self, text: str) -> None:
        """Handle the set full text step for the Stats PySide6 workflow."""
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._update_elided_text()

    def full_text(self) -> str:
        """Handle the full text step for the Stats PySide6 workflow."""
        return self._full_text

    def displayed_text(self) -> str:
        """Handle the displayed text step for the Stats PySide6 workflow."""
        return self._display_text

    def text(self) -> str:  # type: ignore[override]
        """Handle the text step for the Stats PySide6 workflow."""
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802
        """Handle the setText step for the Stats PySide6 workflow."""
        self.set_full_text(text)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        """Handle the resizeEvent step for the Stats PySide6 workflow."""
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        """Handle the update elided text step for the Stats PySide6 workflow."""
        if not self._full_text:
            self._display_text = ""
            super().setText("")
            return
        available = max(self.width() - 8, 10)
        metrics = QFontMetrics(self.font())
        self._display_text = metrics.elidedText(self._full_text, Qt.ElideMiddle, available)
        super().setText(self._display_text)

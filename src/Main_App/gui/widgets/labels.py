"""Shared label primitives for PySide6 UI surfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from Main_App.gui.style_tokens import TEXT_PRIMARY
from Main_App.gui.typography import apply_font_role, css_font_size, css_font_weight

SUBSECTION_HEADER_COLOR = TEXT_PRIMARY
SUBSECTION_HEADER_PADDING = 0


def build_subsection_header_stylesheet() -> str:
    """Return the global QSS selector for shared subsection headers."""
    return f"""
        QLabel[subsectionHeader="true"] {{
            color: {SUBSECTION_HEADER_COLOR};
            font-size: {css_font_size("subsection_header")};
            font-weight: {css_font_weight("subsection_header")};
            padding: {SUBSECTION_HEADER_PADDING};
        }}
    """


class SubsectionHeaderLabel(QLabel):
    """Reusable in-card subsection or table-header label."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        alignment: Qt.AlignmentFlag | Qt.Alignment = Qt.AlignLeft | Qt.AlignVCenter,
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("subsectionHeader", True)
        self.setAlignment(alignment)
        apply_font_role(self, "subsection_header")

"""Shared label primitives for PySide6 UI surfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from Main_App.gui.style_tokens import TEXT_PRIMARY

SUBSECTION_HEADER_POINT_DELTA = 1
SUBSECTION_HEADER_WEIGHT = QFont.DemiBold
SUBSECTION_HEADER_CSS_WEIGHT = 600
SUBSECTION_HEADER_COLOR = TEXT_PRIMARY
SUBSECTION_HEADER_PADDING = 0


def build_subsection_header_stylesheet() -> str:
    """Return the global QSS selector for shared subsection headers."""
    return f"""
        QLabel[subsectionHeader="true"] {{
            color: {SUBSECTION_HEADER_COLOR};
            font-weight: {SUBSECTION_HEADER_CSS_WEIGHT};
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
        font = self.font()
        font.setWeight(SUBSECTION_HEADER_WEIGHT)
        point_size = font.pointSize()
        if point_size > 0:
            font.setPointSize(point_size + SUBSECTION_HEADER_POINT_DELTA)
        self.setFont(font)

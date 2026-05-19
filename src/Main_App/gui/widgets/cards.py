"""Shared card primitives for PySide6 layouts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.style_tokens import (
    COMPACT_SECTION_MAX_HEIGHT,
    SECTION_GRID_GAP,
    SECTION_HEADER_CONTENT_GAP,
    SECTION_PADDING,
)
from Main_App.gui.widgets.labels import SubsectionHeaderLabel


class CardHeader(QWidget):
    """Card header with a title and optional trailing action widgets."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        object_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setProperty("cardHeader", True)

        self.header_layout = QHBoxLayout(self)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(SECTION_HEADER_CONTENT_GAP)

        self.title_label = SubsectionHeaderLabel(title, self)
        self.title_label.setProperty("cardTitle", True)
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)

        self.action_slot = QWidget(self)
        self.action_layout = QHBoxLayout(self.action_slot)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(SECTION_HEADER_CONTENT_GAP)
        self.header_layout.addWidget(self.action_slot)

    def add_action_widget(self, widget: QWidget) -> None:
        """Add a trailing action widget without owning any behavior."""
        self.action_layout.addWidget(widget)


class SectionCard(QGroupBox):
    """Standard card shell with a header and content layout."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        object_name: str | None = None,
        content_layout: QLayout | None = None,
    ) -> None:
        super().__init__("", parent)
        if object_name:
            self.setObjectName(object_name)

        self.shell_layout = QVBoxLayout(self)
        self.shell_layout.setContentsMargins(
            SECTION_PADDING,
            SECTION_PADDING,
            SECTION_PADDING,
            SECTION_PADDING,
        )
        self.shell_layout.setSpacing(SECTION_HEADER_CONTENT_GAP)

        self.header = CardHeader(title, self)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.shell_layout.addWidget(self.header, 0)
        self.shell_layout.setAlignment(self.header, Qt.AlignTop)

        self.content = QWidget(self)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.content_layout = content_layout or QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(SECTION_HEADER_CONTENT_GAP)
        self.content.setLayout(self.content_layout)
        self.shell_layout.addWidget(self.content, 1)

    def set_compact(self, maximum_height: int = COMPACT_SECTION_MAX_HEIGHT) -> None:
        """Use a fixed-height card profile for short action/output sections."""
        self.setMaximumHeight(maximum_height)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)


def make_section_grid_layout(
    *,
    margins: int = 8,
    gap: int = SECTION_GRID_GAP,
    row_stretches: tuple[int, ...] = (),
    column_stretches: tuple[int, ...] = (),
) -> QGridLayout:
    """Create the standard grid used by embedded tool section cards."""
    layout = QGridLayout()
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setHorizontalSpacing(gap)
    layout.setVerticalSpacing(gap)
    for row, stretch in enumerate(row_stretches):
        layout.setRowStretch(row, stretch)
    for column, stretch in enumerate(column_stretches):
        layout.setColumnStretch(column, stretch)
    return layout

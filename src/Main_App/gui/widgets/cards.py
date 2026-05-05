"""Shared card primitives for PySide6 layouts."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.style_tokens import SECTION_PADDING


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
        self.header_layout.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setProperty("cardTitle", True)
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)

        self.action_slot = QWidget(self)
        self.action_layout = QHBoxLayout(self.action_slot)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(8)
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
        self.shell_layout.setSpacing(10)

        self.header = CardHeader(title, self)
        self.shell_layout.addWidget(self.header)

        self.content = QWidget(self)
        self.content_layout = content_layout or QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content.setLayout(self.content_layout)
        self.shell_layout.addWidget(self.content)

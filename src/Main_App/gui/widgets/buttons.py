"""Shared button factories for PySide6 UI surfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget

from Main_App.gui.style_tokens import EVENT_REMOVE_BUTTON_SIZE
from Main_App.gui.typography import font_for_role

_SUPPORTED_VARIANTS = {"primary", "secondary", "tertiary", "danger"}


def make_action_button(
    text: str,
    *,
    variant: str = "secondary",
    compact: bool = False,
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a presentation-only action button styled by Qt properties."""
    if variant not in _SUPPORTED_VARIANTS:
        raise ValueError(f"Unsupported action button variant: {variant!r}")

    button = QPushButton(text, parent)
    button.setProperty("variant", variant)
    button.setProperty(variant, True)
    button.setProperty("compact", compact)
    return button


def make_remove_button(
    *,
    parent: QWidget | None = None,
    tooltip: str = "Remove",
    object_name: str | None = None,
) -> QPushButton:
    """Create a compact outlined remove button with stable icon-button sizing."""
    button = make_action_button("x", variant="secondary", compact=True, parent=parent)
    button.setProperty("iconButton", True)
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedSize(EVENT_REMOVE_BUTTON_SIZE, EVENT_REMOVE_BUTTON_SIZE)
    icon_font = font_for_role("icon_glyph", button.font())
    icon_font.setPointSize(max(icon_font.pointSize(), 12))
    button.setFont(icon_font)
    if object_name:
        button.setObjectName(object_name)
    return button

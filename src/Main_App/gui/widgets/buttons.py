"""Shared button factories for PySide6 UI surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

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

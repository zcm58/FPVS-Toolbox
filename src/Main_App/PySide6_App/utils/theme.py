"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_light_palette(app: QApplication) -> None:
    """
    Apply a deterministic light palette regardless of OS theme,
    while preserving the platform's native widget style.
    """
    # Keep whatever style Qt chose (Windows / macOS / etc.)
    palette = app.palette()

    # Core light colors
    palette.setColor(QPalette.Window, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))

    # Text / foreground
    palette.setColor(QPalette.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))

    # Buttons / controls
    palette.setColor(QPalette.Button, QColor(240, 240, 240))

    # Tooltips
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))

    # Selection / highlight
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    # Disabled state
    disabled_text = QColor(128, 128, 128)
    palette.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)

    app.setPalette(palette)

"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_light_palette(app: QApplication) -> None:
    """Apply a deterministic Fusion + light palette regardless of OS theme."""
    app.setStyle("Fusion")
    palette = app.palette()

    palette.setColor(QPalette.Window, QColor("white"))
    palette.setColor(QPalette.Base, QColor("white"))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    palette.setColor(QPalette.Text, QColor("black"))
    palette.setColor(QPalette.WindowText, QColor("black"))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor("black"))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor("black"))
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.HighlightedText, QColor("white"))

    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(128, 128, 128))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(128, 128, 128))

    app.setPalette(palette)

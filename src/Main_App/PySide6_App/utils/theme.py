"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_light_palette(app: QApplication) -> None:
    """
    Apply a deterministic light palette regardless of OS theme.

    We keep the platform's native style (no Fusion) but override the palette and
    add a small QMenu stylesheet so that Windows dark mode can't turn menus dark.
    """
    palette = app.palette()

    # Core surfaces
    palette.setColor(QPalette.Window, QColor("white"))
    palette.setColor(QPalette.Base, QColor("white"))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))

    # Text / foreground
    palette.setColor(QPalette.Text, QColor("black"))
    palette.setColor(QPalette.WindowText, QColor("black"))
    palette.setColor(QPalette.ButtonText, QColor("black"))

    # Buttons and tooltips
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor("black"))

    # Selection / highlight
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.HighlightedText, QColor("white"))

    # Disabled text
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(128, 128, 128))
    palette.setColor(
        QPalette.Disabled,
        QPalette.ButtonText,
        QColor(128, 128, 128),
    )

    app.setPalette(palette)

    # Ensure menus stay light even when Windows is in dark mode.
    # This is intentionally minimal and scoped to QMenu only.
    menu_qss = """
    QMenu {
        background-color: white;
        color: black;
    }
    QMenu::item:selected {
        background-color: rgb(0, 120, 215);
        color: white;
    }
    """

    existing = app.styleSheet() or ""
    app.setStyleSheet((existing + "\n" + menu_qss).strip())

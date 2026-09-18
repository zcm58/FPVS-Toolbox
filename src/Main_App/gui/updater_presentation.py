"""Toolbox presentation adapter for the Studio-compatible updater surfaces."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from Main_App.gui.components import make_action_button
from Main_App.gui.theme import build_fpvs_app_stylesheet
from Main_App.gui.typography import apply_font_role


def action_button(text: str, parent: QWidget) -> QPushButton:
    return make_action_button(text, parent=parent)


def mark_primary_action(button: QPushButton) -> None:
    button.setProperty("variant", "primary")
    button.setProperty("primary", True)
    button.setProperty("secondary", False)


def mark_secondary_action(button: QPushButton) -> None:
    button.setProperty("variant", "secondary")
    button.setProperty("primary", False)
    button.setProperty("secondary", True)


def apply_toolbox_theme(widget: QWidget) -> None:
    widget.setProperty("fpvsSurface", True)
    widget.setStyleSheet(build_fpvs_app_stylesheet())
    title = getattr(widget, "title_label", None)
    if title is not None:
        apply_font_role(title, "update_title")


def elide_middle(text: str, maximum: int) -> str:
    if len(text) <= maximum:
        return text
    left = (maximum - 3) // 2
    return text[:left] + "..." + text[-(maximum - 3 - left):]

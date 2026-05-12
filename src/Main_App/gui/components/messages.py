"""Central message helpers for GUI surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def show_info(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return QMessageBox.information(parent, title, message)


def show_warning(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return QMessageBox.warning(parent, title, message)


def show_error(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return QMessageBox.critical(parent, title, message)


def confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    default: QMessageBox.StandardButton = QMessageBox.No,
) -> bool:
    reply = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.Yes | QMessageBox.No,
        default,
    )
    return reply == QMessageBox.Yes

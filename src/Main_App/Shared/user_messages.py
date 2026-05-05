"""PySide6-safe user message helpers.

These helpers replace old Tk messagebox calls. They show a QMessageBox only
when a QApplication exists on the GUI thread; worker/background callers log and
continue without blocking.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _message_box(parent: Any, title: str, message: str, kind: str) -> None:
    if os.getenv("FPVS_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
        return

    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:
        getattr(logger, "warning" if kind == "warning" else "error")(message)
        return

    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        getattr(logger, "warning" if kind == "warning" else "error")(message)
        return

    if kind in {"info", "error"} and parent is not None and (
        getattr(parent, "_suppress_completion_dialogs", False)
        or getattr(parent, "_cancel_requested", False)
    ):
        return

    if kind == "info" and str(title).lower().startswith("processing complete"):
        ok = getattr(parent, "_last_job_success", True) if parent is not None else True
        if not ok:
            QMessageBox.warning(
                parent,
                "Processing Finished",
                "No Excel files were generated. Check the log for details.",
            )
            return

    method = {
        "info": QMessageBox.information,
        "warning": QMessageBox.warning,
        "error": QMessageBox.critical,
    }.get(kind, QMessageBox.information)
    method(parent, title, message)


def show_info(title: str, message: str, parent: Any = None) -> None:
    _message_box(parent, title, message, "info")


def show_warning(title: str, message: str, parent: Any = None) -> None:
    _message_box(parent, title, message, "warning")


def show_error(title: str, message: str, parent: Any = None) -> None:
    _message_box(parent, title, message, "error")


def ask_yes_no(title: str, message: str, parent: Any = None, default: bool = False) -> bool:
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:
        logger.info("%s: %s", title, message)
        return default

    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        logger.info("%s: %s", title, message)
        return default

    return QMessageBox.question(parent, title, message) == QMessageBox.StandardButton.Yes

# Main_App/Legacy_App/eloreta_launcher.py
from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox

from Main_App.Shared.source_localization_optional import (
    SourceLocalizationUnavailableError,
    get_source_localization_dialog_class,
)


def open_eloreta_tool(parent=None) -> None:
    """Open the optional Source Localization GUI when it is available."""

    try:
        dialog_class = get_source_localization_dialog_class(operation="open_eloreta_tool")
    except SourceLocalizationUnavailableError as exc:
        log_func = getattr(parent, "log", None)
        if callable(log_func):
            log_func(exc.user_message, level=logging.WARNING)
        notifier = getattr(parent, "notify_source_localization_unavailable", None)
        if callable(notifier):
            notifier(exc.user_message)
        else:
            QMessageBox.warning(
                parent,
                "Source Localization Unavailable",
                exc.user_message,
            )
        return

    dlg = dialog_class(parent=parent)
    dlg.exec()

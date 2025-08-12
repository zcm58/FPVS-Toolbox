# Main_App/Legacy_App/eloreta_launcher.py
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

try:
    # Optional GUI; may not exist in your slimmed repo
    from Tools.SourceLocalization.qt_dialog import SourceLocalizationDialog
except Exception:
    SourceLocalizationDialog = None


def open_eloreta_tool(parent=None) -> None:
    """Open the (optional) source localization GUI, if available.

    If not available, inform the user and suggest running LORETA via the
    main processing pipeline (the 'Run LORETA during processing' checkbox).
    """
    if SourceLocalizationDialog is None:
        QMessageBox.information(
            parent,
            "LORETA GUI not available",
            (
                "The optional Source Localization GUI module "
                "(Tools.SourceLocalization.qt_dialog) is not installed.\n\n"
                "You can still run LORETA by checking "
                "‘Run LORETA during processing’ in the main app."
            ),
        )
        return

    dlg = SourceLocalizationDialog(parent=parent)
    dlg.exec()

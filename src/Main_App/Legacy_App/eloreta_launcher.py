# src/Main_App/Legacy_App/eloreta_launcher.py
"""Compatibility launcher for Source Localization from the Tools menu.

This now opens the PySide6 dialog (no Tk/CTk), keeping the legacy import path
that your menu already uses.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

# Import the new PySide6 dialog from the tool
from Tools.SourceLocalization.qt_dialog import SourceLocalizationDialog


def open_eloreta_tool(parent: QWidget | None = None) -> None:
    """Open the Source Localization (oddball eLORETA) dialog."""
    dlg = SourceLocalizationDialog(parent)
    # Let Qt delete the dialog when closed (avoids leaks when reopening)
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    dlg.show()

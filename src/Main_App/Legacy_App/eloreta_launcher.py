"""Utility for launching the source localization tool."""

from __future__ import annotations


def open_eloreta_tool(app):
    """Launch the eLORETA/sLORETA GUI.

    Parameters
    ----------
    app : object
        Parent window from which the tool is launched. May be a PySide6
        ``QWidget`` or ``None``.
    """

    try:  # Use a Qt message box when available
        from PySide6.QtWidgets import QMessageBox, QWidget
    except Exception:  # pragma: no cover - PySide6 not installed
        QMessageBox = None
        QWidget = object

    if isinstance(app, QWidget) and QMessageBox is not None:
        reply = QMessageBox.question(
            app,
            "LORETA Tool Warning",
            (
                "IMPORTANT: The LORETA Tool is currently under active development. "
                "Certain features may not work as intended. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return None

    # Import inside the function to avoid heavy dependencies at startup
    from Tools.SourceLocalization import SourceLocalizationWindow

    tool = SourceLocalizationWindow()

    try:  # Restore previous window geometry if available
        geometry = app.settings.get("gui", "eloreta_size", "900x700")
        tool.geometry(geometry)
    except Exception:  # pragma: no cover - optional
        pass

    return tool

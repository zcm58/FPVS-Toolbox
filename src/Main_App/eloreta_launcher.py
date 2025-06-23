"""Utility for launching the source localization tool."""

from __future__ import annotations


def open_eloreta_tool(app):
    """Launch the eLORETA/sLORETA GUI.

    Parameters
    ----------
    app : tkinter.Misc
        Parent window from which the tool is launched.
    """
    # Import inside the function to avoid heavy dependencies at startup
    from Tools.SourceLocalization import SourceLocalizationWindow

    tool = SourceLocalizationWindow(master=app)
    try:
        # Respect any stored geometry settings if available
        geometry = app.settings.get("gui", "eloreta_size", "900x700")
        tool.geometry(geometry)
    except Exception:
        # If the app has no settings or retrieval fails, ignore
        pass
    return tool

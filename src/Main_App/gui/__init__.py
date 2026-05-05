"""Canonical Main App GUI import surface."""

from __future__ import annotations

import importlib
from typing import Any

_MAIN_WINDOW_NAMES = {
    "MainWindow",
    "_should_show_no_excel_popup",
}
_SETTINGS_PANEL_NAMES = {
    "SettingsDialog",
}
_SIDEBAR_NAMES = {
    "SidebarButton",
}

__all__ = sorted(_MAIN_WINDOW_NAMES | _SETTINGS_PANEL_NAMES | _SIDEBAR_NAMES)


def __getattr__(name: str) -> Any:
    if name in _MAIN_WINDOW_NAMES:
        main_window = importlib.import_module("Main_App.gui.main_window")

        return getattr(main_window, name)
    if name in _SETTINGS_PANEL_NAMES:
        settings_panel = importlib.import_module("Main_App.gui.settings_panel")

        return getattr(settings_panel, name)
    if name in _SIDEBAR_NAMES:
        sidebar = importlib.import_module("Main_App.gui.sidebar")

        return getattr(sidebar, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

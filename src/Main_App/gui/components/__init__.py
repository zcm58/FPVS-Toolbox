"""Canonical shared GUI component layer for FPVS PySide6 surfaces."""

from __future__ import annotations

from Main_App.gui.widgets import (
    BrainPulseWidget,
    BusySpinner,
    CardHeader,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
)

from .actions import ActionRow, make_action_row
from .messages import confirm, show_error, show_info, show_warning
from .surfaces import AppDialog, SurfaceSize, configure_window_surface

__all__ = [
    "ActionRow",
    "AppDialog",
    "BrainPulseWidget",
    "BusySpinner",
    "CardHeader",
    "PathPickerRow",
    "SectionCard",
    "StatusBanner",
    "SurfaceSize",
    "confirm",
    "configure_window_surface",
    "make_action_button",
    "make_action_row",
    "make_form_layout",
    "show_error",
    "show_info",
    "show_warning",
]

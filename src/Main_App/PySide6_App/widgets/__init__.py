"""Compatibility wrapper for shared GUI widgets.

Implementations live in :mod:`Main_App.gui.widgets`.
"""

from Main_App.gui.widgets import (  # noqa: F401
    BrainPulseWidget,
    BusySpinner,
    CardHeader,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
)

__all__ = [
    "BrainPulseWidget",
    "BusySpinner",
    "CardHeader",
    "PathPickerRow",
    "SectionCard",
    "StatusBanner",
    "make_action_button",
    "make_form_layout",
]

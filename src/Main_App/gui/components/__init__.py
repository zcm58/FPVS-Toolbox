"""Canonical shared GUI component layer for FPVS PySide6 surfaces.

This package is the stable public import surface for reusable presentation
primitives. Imports here must remain side-effect free: no app initialization,
windows, filesystem access, project state reads, or worker startup.
"""

from __future__ import annotations

from .actions import ActionRow, make_action_row
from .messages import confirm, show_error, show_info, show_warning
from .surfaces import AppDialog, SurfaceSize, configure_window_surface
from Main_App.gui.widgets.brain_pulse import BrainPulseWidget
from Main_App.gui.widgets.busy_spinner import BusySpinner
from Main_App.gui.widgets.buttons import make_action_button, make_remove_button
from Main_App.gui.widgets.cards import CardHeader, SectionCard, make_section_grid_layout
from Main_App.gui.widgets.forms import PathPickerRow, make_form_layout
from Main_App.gui.widgets.labels import SubsectionHeaderLabel
from Main_App.gui.widgets.status import StatusBanner
from Main_App.gui.typography import (
    apply_font_role,
    fixed_width_font,
    font_for_role,
    matplotlib_font_kwargs,
)

__all__ = (
    "ActionRow",
    "AppDialog",
    "BrainPulseWidget",
    "BusySpinner",
    "CardHeader",
    "PathPickerRow",
    "SectionCard",
    "StatusBanner",
    "SubsectionHeaderLabel",
    "SurfaceSize",
    "apply_font_role",
    "confirm",
    "configure_window_surface",
    "fixed_width_font",
    "font_for_role",
    "make_action_button",
    "make_action_row",
    "make_form_layout",
    "make_remove_button",
    "make_section_grid_layout",
    "matplotlib_font_kwargs",
    "show_error",
    "show_info",
    "show_warning",
)

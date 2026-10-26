"""Settings entry point and ownership guards for guided pipeline setup."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QDialog

from Main_App.gui.components import show_error, show_info
from Main_App.gui.pipeline_setup_dialog import PipelineSetupDialog
from Main_App.gui.processing_workflows import _set_resume_post_processing_pending
from Main_App.gui.project_drafts import has_condition_changes
from Main_App.gui.shell_status import _set_processing_navigation_locked
from Main_App.gui.toolbox_cache_workflow import _cache_work_is_active
from Tools.Stats.analysis.dv_policy_group_significant import clear_group_significant_selection_cache

logger = logging.getLogger(__name__)


def guided_setup_unavailable_reason(settings, *, during_wizard: bool = False) -> str:
    """Recheck ownership on launch and immediately before the save worker starts."""
    if settings.project is None:
        return "Open a project to configure its processing pipeline."
    if settings.has_unsaved_changes():
        return "Save or cancel your Settings edits before opening guided setup."
    owner = getattr(settings, "host", None) or settings.parent()
    if owner is None or getattr(owner, "_start_guard", None) is None:
        return "Open Settings from the main window while processing is idle."
    if getattr(owner, "currentProject", settings.project) is not settings.project:
        return "Reopen Settings for the active project."
    if has_condition_changes(owner):
        return "Save or cancel your condition edits before opening guided setup."
    if _cache_work_is_active(owner, include_start_guard=not during_wizard):
        return "Wait for processing and tool work to finish before configuring the pipeline."
    return ""


def refresh_guided_setup_availability(settings) -> None:
    button = getattr(settings, "guided_setup_button", None)
    if button is None:
        return
    reason = guided_setup_unavailable_reason(settings)
    button.setEnabled(not reason)
    button.setToolTip(reason)


def show_pipeline_setup(settings) -> None:
    """Keep project switching and processing locked until the modal save finishes."""
    reason = guided_setup_unavailable_reason(settings)
    if reason:
        show_info(settings, "Guided setup unavailable", reason)
        return
    owner = getattr(settings, "host", None) or settings.parent()
    guard = owner._start_guard
    if not guard.start():
        show_info(settings, "Guided setup unavailable", "Wait for the current operation to finish.")
        return
    dialog = None
    saved = False
    requires_reprocessing = False
    try:
        _set_processing_navigation_locked(owner, True)
        dialog = PipelineSetupDialog(
            settings.project, settings,
            can_save=lambda: guided_setup_unavailable_reason(settings, during_wizard=True),
        )
        saved = dialog.exec() == QDialog.DialogCode.Accepted
        requires_reprocessing = saved and dialog.requires_reprocessing_saved
    except ValueError as exc:
        show_error(settings, "Guided setup unavailable", str(exc))
    except Exception:  # GUI boundary: report unexpected construction failures and release navigation ownership.
        logger.exception("pipeline_setup_dialog_failed")
        show_error(settings, "Guided setup unavailable", "Could not open guided setup. Reopen Settings and try again.")
    finally:
        _set_processing_navigation_locked(owner, False)
        guard.end()
        if dialog is not None:
            dialog.deleteLater()
    if saved:
        if requires_reprocessing:
            clear_group_significant_selection_cache()
            _set_resume_post_processing_pending(owner, False)
        # Retire the cached Settings controls so they cannot overwrite the saved draft.
        settings.accept()
    else:
        refresh_guided_setup_availability(settings)

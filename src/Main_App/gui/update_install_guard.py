"""Toolbox active-work protection at the updater handoff boundary."""
from typing import Any
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QWidget
from Main_App.gui.components import show_warning

def default_install_guard(parent: QWidget | None) -> bool:
    """Resolve active work and unsaved drafts before accepting updater handoff."""

    if parent is None:
        return True
    if _host_has_active_work(parent):
        _warn_active_work(parent)
        return False
    if not _confirm_project_draft_exit(parent):
        return False
    # Saving settings may schedule recalculation or enter a nested event loop.
    # Recheck before the independent helper can commit to waiting for app exit.
    if _host_has_active_work(parent):
        _warn_active_work(parent)
        return False
    return True


def _confirm_project_draft_exit(parent: QWidget) -> bool:
    # The standalone repair window has no parent and must not load Toolbox
    # project/tool modules or their scientific runtime.
    from Main_App.gui.project_drafts import confirm_project_draft_exit

    return confirm_project_draft_exit(parent)


def _has_active_tool_operations() -> bool:
    from Tools.Free_Harmonic_Clustering.gui import has_active_operations

    return has_active_operations()


def close_after_update(host: QWidget) -> bool:
    """Use normal close guards after the modal updater resolved draft consent."""
    host._update_exit_confirmed = True
    try:
        return host.close()
    finally:
        # A vetoed close must never waive a later draft prompt.
        host._update_exit_confirmed = False


def _warn_active_work(parent: QWidget) -> None:
    show_warning(
        parent,
        "Update Blocked",
        "Processing or export work is still running. Finish or stop the active operation "
        "before installing an update.",
    )


def _host_has_active_work(host: QWidget) -> bool:
    # Toolbox owns analysis/export workers under several embedded tool pages.
    # Do not start an install handoff while any child worker is still active.
    if _has_active_tool_operations():
        return True
    for page_name in ("_plot_generator_page", "_publication_maps_page"):
        page = getattr(host, page_name, None)
        checker = getattr(page, "has_active_generation", None)
        if callable(checker):
            try:
                if checker():
                    return True
            except RuntimeError:
                # A destroyed Qt page cannot own an active generation operation.
                pass
    if any(_handle_is_active(thread) for thread in host.findChildren(QThread)):
        return True
    if getattr(host, "_qc_source_prefetch_bridge", None) is not None:
        return True
    if getattr(host, "_frequency_domain_qc_save_thread", None) is not None:
        return True
    if bool(getattr(host, "busy", False)):
        return True
    if bool(getattr(host, "_run_active", False)):
        return True
    if bool(getattr(host, "_pending_finalize", False)):
        return True
    if bool(getattr(host, "_settings_post_processing_activity_active", False)):
        return True
    if bool(getattr(host, "_post_backlog", None)):
        return True
    for attr_name in (
        "processing_thread",
        "detection_thread",
        "_post_thread",
        "_thread",
        "_worker_thread",
        "_settings_full_fft_grid_qc_thread",
        "_settings_harmonic_recalc_thread",
        "_project_processing_cache_thread",
    ):
        if _handle_is_active(getattr(host, attr_name, None)):
            return True
    return getattr(host, "_post_worker", None) is not None


def _handle_is_active(handle: Any) -> bool:
    if handle is None:
        return False
    for method_name in ("isRunning", "is_alive"):
        method = getattr(handle, method_name, None)
        if callable(method):
            try:
                return bool(method())
            except RuntimeError:
                return False
    return False

"""Toolbox active-work protection at the updater handoff boundary."""
from typing import Any
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QWidget
from Main_App.gui.components import show_warning

def default_install_guard(parent: QWidget | None) -> bool:
    """Block installer launch while Toolbox has active processing/export work."""

    if parent is None:
        return True
    if not _host_has_active_work(parent):
        return True

    show_warning(
        parent,
        "Update Blocked",
        "Processing or export work is still running. Finish or stop the active operation "
        "before installing an update.",
    )
    return False


def _host_has_active_work(host: QWidget) -> bool:
    # Toolbox owns analysis/export workers under several embedded tool pages.
    # Do not start an install handoff while any child worker is still active.
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
    if bool(getattr(host, "_post_backlog", None)):
        return True
    for attr_name in (
        "processing_thread",
        "detection_thread",
        "_post_thread",
        "_thread",
        "_worker_thread",
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

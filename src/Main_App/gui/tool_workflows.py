"""Tool-launcher and menu-action helpers for the Main App GUI shell."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QMessageBox


def open_settings_window(host: Any, settings_dialog_cls: Callable[..., Any]) -> None:
    if host._settings_dialog and host._settings_dialog.isVisible():
        host._settings_dialog.raise_()
        host._settings_dialog.activateWindow()
        return
    dlg = settings_dialog_cls(host.settings, host, getattr(host, "currentProject", None))
    host._settings_dialog = dlg
    dlg.exec()
    if hasattr(host, "lbl_debug"):
        host.lbl_debug.setVisible(host.settings.debug_enabled())
    host._settings_dialog = None


def check_for_updates(host: Any, update_manager_module: Any) -> None:
    update_manager_module.check_for_updates_async(
        host, silent=False, notify_if_no_update=True, force=True
    )


def show_about_dialog(host: Any, version: str) -> None:
    QMessageBox.information(
        host,
        "About FPVS ToolBox",
        f"Version: {version} was developed by Zack Murphy at Mississippi State University.",
    )

"""Tool-launcher and menu-action helpers for the Main App GUI shell."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
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


def open_image_resizer(source_root: Path) -> None:
    cmd = [sys.executable]
    if getattr(sys, "frozen", False):
        cmd.append("--run-image-resizer")
    else:
        script = source_root / "src" / "Tools" / "Image_Resizer" / "pyside_resizer.py"
        cmd.append(str(script))
    subprocess.Popen(cmd, close_fds=True)


def open_plot_generator(host: Any, source_root: Path) -> None:
    cmd = [sys.executable]
    if getattr(sys, "frozen", False):
        cmd.append("--run-plot-generator")
    else:
        script = source_root / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"
        cmd.append(str(script))
    env = os.environ.copy()
    proj = getattr(host, "currentProject", None)
    if proj and hasattr(proj, "project_root"):
        env["FPVS_PROJECT_ROOT"] = str(proj.project_root)
    subprocess.Popen(cmd, close_fds=True, env=env)


def resolve_epoch_averaging_paths(host: Any) -> tuple[str, str] | None:
    if not host.currentProject:
        QMessageBox.warning(host, "No Project", "Please load a project first.")
        return None

    data_dir = host.currentProject.subfolders.get("data")
    if data_dir is None:
        data_dir = str(host.currentProject.input_folder)
    else:
        data_dir = str(host.currentProject.project_root / data_dir)
    excel_dir = str(
        host.currentProject.project_root
        / host.currentProject.subfolders.get("excel", "")
    )
    return data_dir, excel_dir


def open_epoch_averaging(
    host: Any,
    advanced_averaging_window_cls: Callable[..., Any],
) -> None:
    paths = resolve_epoch_averaging_paths(host)
    if paths is None:
        return
    data_dir, excel_dir = paths
    if not getattr(host, "_epoch_win", None):
        host._epoch_win = advanced_averaging_window_cls(
            parent=host, input_dir=data_dir, output_dir=excel_dir
        )
    host._epoch_win.show()
    host._epoch_win.raise_()
    host._epoch_win.activateWindow()


def show_about_dialog(host: Any, version: str) -> None:
    QMessageBox.information(
        host,
        "About FPVS ToolBox",
        f"Version: {version} was developed by Zack Murphy at Mississippi State University.",
    )

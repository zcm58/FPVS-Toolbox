#!/usr/bin/env python3
# ruff: noqa: E402
"""Entry point for launching the FPVS Toolbox GUI application (PySide6 only)."""

from Main_App.Performance.mp_env import set_blas_threads_single_process
set_blas_threads_single_process()

import sys
import multiprocessing as mp
from ctypes import windll
from pathlib import Path

from PySide6.QtCore import QCoreApplication

# High-DPI awareness (Windows)
try:
    windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
except Exception:
    pass

QCoreApplication.setOrganizationName("MississippiStateUniversity")
QCoreApplication.setOrganizationDomain("msstate.edu")
QCoreApplication.setApplicationName("FPVS Toolbox")

# Import logging/config after DPI + app metadata
from Main_App import configure_logging, get_settings, install_messagebox_logger  # noqa: E402


def _maybe_run_cli_tool() -> bool:
    """Runs a CLI sub-tool and returns True if one was invoked."""
    if "--run-image-resizer" in sys.argv:
        from Tools.Image_Resizer import pyside_resizer
        pyside_resizer.main()
        return True
    if "--run-plot-generator" in sys.argv:
        from Tools.Plot_Generator import plot_generator
        plot_generator.main()
        return True
    return False


def run_app() -> int:
    """Boot the PySide6 GUI."""
    # Configure logging before importing MainWindow to capture module logs.
    settings = get_settings()
    debug = settings.debug_enabled()
    configure_logging(debug)
    install_messagebox_logger(debug)

    from PySide6.QtWidgets import QApplication  # import here to avoid side effects on import
    from Main_App.PySide6_App.GUI.main_window import MainWindow

    app = QApplication([])

    # Optional stylesheet co-located with this file
    qss_path = Path(__file__).resolve().parent / "qdark_sidebar.qss"
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    return app.exec()


def main() -> None:
    """Entry point dispatcher."""
    if _maybe_run_cli_tool():
        return
    exit_code = run_app()
    sys.exit(exit_code)


if __name__ == "__main__":
    # Critical for frozen (PyInstaller) child process bootstrap on Windows.
    mp.freeze_support()
    # Ensure multiprocessing uses this EXE as its interpreter when frozen.
    if hasattr(sys, "frozen"):
        mp.set_executable(sys.executable)
    main()

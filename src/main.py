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
from config import FPVS_TOOLBOX_VERSION

try:
    windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
except Exception:
    pass

QCoreApplication.setOrganizationName("MississippiStateUniversity")
QCoreApplication.setOrganizationDomain("msstate.edu")
QCoreApplication.setApplicationName("FPVS Toolbox")
QCoreApplication.setApplicationVersion(FPVS_TOOLBOX_VERSION)

from Main_App import configure_logging, get_settings, install_messagebox_logger  # noqa: E402

def _maybe_run_cli_tool() -> bool:
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
    settings = get_settings()
    debug = settings.debug_enabled()
    configure_logging(debug)
    install_messagebox_logger(debug)

    from PySide6.QtWidgets import QApplication
    from Main_App.PySide6_App.GUI.main_window import MainWindow

    app = QApplication([])

    qss_path = Path(__file__).resolve().parent / "qdark_sidebar.qss"
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    return app.exec()

def main() -> None:
    if _maybe_run_cli_tool():
        return
    sys.exit(run_app())

if __name__ == "__main__":
    mp.freeze_support()
    if hasattr(sys, "frozen"):
        mp.set_executable(sys.executable)
    main()

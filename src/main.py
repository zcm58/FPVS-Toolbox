#!/usr/bin/env python3
# ruff: noqa: E402

"""Entry point for launching the FPVS Toolbox GUI application."""

from Main_App.Performance.mp_env import set_blas_threads_single_process

set_blas_threads_single_process()

USE_PYSIDE6 = True  # currently in dual GUI mode - set to False to use the legacy Tkinter GUI

from ctypes import windll
import sys
from PySide6.QtCore import QCoreApplication

try:
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

QCoreApplication.setOrganizationName("MississippiStateUniversity")
QCoreApplication.setOrganizationDomain("msstate.edu")
QCoreApplication.setApplicationName("FPVS Toolbox")

if USE_PYSIDE6:
    # Specifically check if PySide6 is installed.
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError("PySide6 not installed; install with 'pip install PySide6'") from exc

    from pathlib import Path
    # Import logging utilities now (safe), but DO NOT import MainWindow yet.
    from Main_App import configure_logging, get_settings, install_messagebox_logger
else:
    from fpvs_app import FPVSApp
    from Main_App import configure_logging, get_settings, install_messagebox_logger
    import multiprocessing


def main() -> None:
    """Entry point for running the FPVS Toolbox or its sub-tools."""
    if "--run-image-resizer" in sys.argv:
        from Tools.Image_Resizer import pyside_resizer
        pyside_resizer.main()
        return

    if "--run-plot-generator" in sys.argv:
        from Tools.Plot_Generator import plot_generator
        plot_generator.main()
        return

    if USE_PYSIDE6:
        # Configure logging BEFORE importing MainWindow so any module-level
        # logger.info(...) in that module won't emit unless debug is on.
        settings = get_settings()
        debug = settings.debug_enabled()
        configure_logging(debug)
        install_messagebox_logger(debug)

        # Import AFTER logging is configured.
        from Main_App.PySide6_App.GUI.main_window import MainWindow

        app = QApplication([])
        qss = Path(__file__).resolve().parent / "qdark_sidebar.qss"
        if qss.exists():
            with open(qss, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())

        window = MainWindow()
        window.show()
        app.exec()
    else:
        multiprocessing.freeze_support()

        settings = get_settings()
        debug = settings.debug_enabled()
        configure_logging(debug)
        install_messagebox_logger(debug)

        app = FPVSApp()
        app.mainloop()


if __name__ == "__main__":
    main()

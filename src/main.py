# main.py

#!/usr/bin/env python3
# ruff: noqa: E402

"""Entry point for launching the FPVS Toolbox GUI application."""

USE_PYSIDE6 = True

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
    try:
        from PySide6.QtWidgets import QApplication
        from pathlib import Path
        from Main_App.PySide6_App.GUI.main_window import MainWindow
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "PySide6 not installed; install with 'pip install PySide6'"
        ) from exc
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
        app = QApplication([])
        qss = Path(__file__).resolve().parent / "qdark_sidebar.qss"
        if qss.exists():
            with open(qss) as f:
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

# main.py

#!/usr/bin/env python3

"""Entry point for launching the FPVS Toolbox GUI application."""

from ctypes import windll

try:
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from fpvs_app import FPVSApp
from Main_App.debug_utils import configure_logging, get_settings, install_messagebox_logger
import multiprocessing
import sys

def main() -> None:
    """Entry point for running the FPVS Toolbox or its sub-tools."""
    multiprocessing.freeze_support()

    if "--run-image-resizer" in sys.argv:
        from Tools.Image_Resizer import pyside_resizer

        pyside_resizer.main()
        return

    if "--run-plot-generator" in sys.argv:
        from Tools.Plot_Generator import plot_generator

        plot_generator.main()
        return

    settings = get_settings()
    debug = settings.debug_enabled()
    configure_logging(debug)
    install_messagebox_logger(debug)
    app = FPVSApp()
    app.mainloop()


if __name__ == "__main__":
    main()

# main.py

#!/usr/bin/env python3

"""Entry point for launching the FPVS Toolbox GUI application."""

from ctypes import windll
import sys

from dependency_check import check_dependencies
try:
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

if not check_dependencies():
    sys.exit(1)

from fpvs_app import FPVSApp
from Main_App.debug_utils import configure_logging, get_settings

if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.debug_enabled())
    app = FPVSApp()
    app.mainloop()

# main.py

#!/usr/bin/env python3

"""Entry point for launching the FPVS Toolbox GUI application."""

from ctypes import windll
try:
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from fpvs_app import FPVSApp

if __name__ == "__main__":
    app = FPVSApp()
    app.mainloop()

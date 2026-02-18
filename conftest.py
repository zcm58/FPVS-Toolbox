from __future__ import annotations

import sys
import types

if "PySide6" not in sys.modules:
    qtcore = types.ModuleType("PySide6.QtCore")

    class _QCoreApplication:
        @staticmethod
        def instance():
            return None

    class _QStandardPaths:
        AppDataLocation = 0

        @staticmethod
        def writableLocation(_loc):
            return "/tmp"

    qtcore.QCoreApplication = _QCoreApplication
    qtcore.QStandardPaths = _QStandardPaths
    pyside = types.ModuleType("PySide6")
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore

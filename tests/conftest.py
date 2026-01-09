from __future__ import annotations

import sys
import types
from pathlib import Path


qtcore = types.ModuleType("PySide6.QtCore")


class _DummyQCoreApplication:
    @staticmethod
    def instance():
        return None


class _DummyQStandardPaths:
    AppDataLocation = 0

    @staticmethod
    def writableLocation(_location):
        return "."


class _DummyQSettings:
    def value(self, *_args, **_kwargs):
        return False


qtcore.QCoreApplication = _DummyQCoreApplication
qtcore.QStandardPaths = _DummyQStandardPaths
qtcore.QSettings = _DummyQSettings

pyside6 = types.ModuleType("PySide6")
pyside6.QtCore = qtcore

sys.modules.setdefault("PySide6", pyside6)
sys.modules.setdefault("PySide6.QtCore", qtcore)

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

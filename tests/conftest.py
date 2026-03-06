from __future__ import annotations

import os
import sys
import types
from pathlib import Path
import importlib
import importlib.util
from importlib.machinery import ModuleSpec

os.environ.setdefault("FPVS_TEST_MODE", "1")


def _safe_find_spec(module_name: str):
    """Return a module spec without failing on partially initialized modules."""
    try:
        return importlib.util.find_spec(module_name)
    except ValueError:
        # Some environments preload modules with __spec__ = None, which causes
        # find_spec() to raise ValueError. Clear the broken entry, then retry.
        loaded = sys.modules.get(module_name)
        if loaded is not None and getattr(loaded, "__spec__", None) is None:
            sys.modules.pop(module_name, None)
            try:
                return importlib.util.find_spec(module_name)
            except ValueError:
                return None
        return None


if _safe_find_spec("PySide6") is None:
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.__spec__ = ModuleSpec("PySide6.QtCore", loader=None)

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
    pyside6.__spec__ = ModuleSpec("PySide6", loader=None)
    pyside6.QtCore = qtcore

    sys.modules.setdefault("PySide6", pyside6)
    sys.modules.setdefault("PySide6.QtCore", qtcore)
else:
    pyside6 = importlib.import_module("PySide6")
    if _safe_find_spec("PySide6.QtGui") is not None:
        pyside6.QtGui = importlib.import_module("PySide6.QtGui")

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

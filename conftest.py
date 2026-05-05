from __future__ import annotations

import sys
import types

import pytest

_AUTO_MARK_RULES = {
    "gui": (
        "gui",
        "layout",
        "main_window",
        "settings",
        "status",
        "window",
        "dialog",
        "qt",
    ),
    "stats": (
        "anova",
        "baseline",
        "contrast",
        "harmonic",
        "lmm",
        "mixed_model",
        "multigroup",
        "outlier",
        "rm_anova",
        "stats",
    ),
    "project_io": (
        "export",
        "file_scanner",
        "manifest",
        "open_existing_project",
        "path",
        "project",
        "roundtrip",
        "scan",
    ),
    "processing": (
        "bca",
        "epoch",
        "fft",
        "pipeline",
        "post_process",
        "postprocess",
        "preproc",
        "process",
        "snr",
        "worker",
    ),
    "plot_generator": ("plot_generator",),
    "ratio": ("ratio_calculator",),
    "smoke": ("smoke",),
    "integration": ("e2e", "integration", "pipeline"),
}

_QT_HINTS = ("gui", "layout", "main_window", "qt", "window", "dialog")


def pytest_collection_modifyitems(config, items):
    for item in items:
        node = f"{item.path.as_posix()}::{item.name}".lower()
        for marker_name, hints in _AUTO_MARK_RULES.items():
            if any(hint in node for hint in hints):
                item.add_marker(getattr(pytest.mark, marker_name))
        if any(hint in node for hint in _QT_HINTS):
            item.add_marker(pytest.mark.qt)


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

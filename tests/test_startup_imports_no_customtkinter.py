"""Startup import checks for avoiding CustomTkinter on PySide6 launch."""

from __future__ import annotations

import sys


def _clear_customtkinter_modules() -> None:
    sys.modules.pop("customtkinter", None)


def _clear_legacy_stats_modules() -> None:
    for name in list(sys.modules):
        if name.startswith(("Tools.Stats.Legacy", "Tools.Stats.PySide6")):
            sys.modules.pop(name, None)


def test_mainwindow_import_does_not_load_customtkinter() -> None:
    _clear_customtkinter_modules()
    _clear_legacy_stats_modules()

    from Main_App.PySide6_App.GUI.main_window import MainWindow

    assert MainWindow is not None
    assert "customtkinter" not in sys.modules
    assert not any(name.startswith("Tools.Stats.Legacy") for name in sys.modules)
    assert not any(name.startswith("Tools.Stats.PySide6") for name in sys.modules)


def test_average_preprocessing_import_does_not_load_customtkinter() -> None:
    _clear_customtkinter_modules()

    import Tools.Average_Preprocessing as average_preprocessing

    assert average_preprocessing is not None
    assert "customtkinter" not in sys.modules

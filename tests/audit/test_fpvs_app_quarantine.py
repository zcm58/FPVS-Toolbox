from __future__ import annotations

import importlib
import sys

import pytest


def test_removed_fpvs_app_import_has_no_customtkinter_side_effects() -> None:
    sys.modules.pop("fpvs_app", None)
    sys.modules.pop("customtkinter", None)
    sys.modules.pop("tkinter", None)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("fpvs_app")

    assert "customtkinter" not in sys.modules
    assert "tkinter" not in sys.modules


def test_removed_fpvs_app_has_no_main_entrypoint() -> None:
    sys.modules.pop("fpvs_app", None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("fpvs_app")

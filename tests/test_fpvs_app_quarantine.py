from __future__ import annotations

import importlib
import sys

import pytest


def test_quarantined_fpvs_app_import_has_no_customtkinter_side_effects() -> None:
    sys.modules.pop("fpvs_app", None)
    sys.modules.pop("customtkinter", None)
    sys.modules.pop("tkinter", None)

    module = importlib.import_module("fpvs_app")

    assert module is not None
    assert "customtkinter" not in sys.modules
    assert "tkinter" not in sys.modules


def test_quarantined_fpvs_app_main_fails_fast() -> None:
    sys.modules.pop("fpvs_app", None)
    module = importlib.import_module("fpvs_app")

    with pytest.raises(RuntimeError, match="quarantined"):
        module.main()

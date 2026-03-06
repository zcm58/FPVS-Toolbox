from __future__ import annotations

import importlib
import sys

import pytest


def _clear_legacy_stats_ui_modules() -> None:
    sys.modules.pop("customtkinter", None)
    for name in list(sys.modules):
        if name in {
            "Tools.Stats.Legacy.stats",
            "Tools.Stats.Legacy.stats_ui",
        }:
            sys.modules.pop(name, None)


def test_legacy_stats_stub_import_has_no_customtkinter_side_effects() -> None:
    _clear_legacy_stats_ui_modules()

    module = importlib.import_module("Tools.Stats.Legacy.stats")

    assert module is not None
    assert "customtkinter" not in sys.modules


def test_legacy_stats_window_stub_fails_fast() -> None:
    _clear_legacy_stats_ui_modules()
    module = importlib.import_module("Tools.Stats.Legacy.stats")

    with pytest.raises(RuntimeError, match="quarantined"):
        module.StatsAnalysisWindow(master=None)


def test_legacy_stats_ui_stub_fails_fast_without_customtkinter() -> None:
    _clear_legacy_stats_ui_modules()
    module = importlib.import_module("Tools.Stats.Legacy.stats_ui")

    assert "customtkinter" not in sys.modules

    with pytest.raises(RuntimeError, match="quarantined"):
        module.create_widgets(object())


def test_legacy_stats_package_root_access_fails_fast() -> None:
    _clear_legacy_stats_ui_modules()
    package = importlib.import_module("Tools.Stats.Legacy")

    assert "customtkinter" not in sys.modules

    with pytest.raises(RuntimeError, match="quarantined"):
        getattr(package, "StatsAnalysisWindow")

    with pytest.raises(RuntimeError, match="quarantined"):
        getattr(package, "create_widgets")

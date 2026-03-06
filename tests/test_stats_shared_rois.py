from __future__ import annotations

import sys
import types


def test_shared_rois_import_does_not_load_tkinter_or_customtkinter() -> None:
    sys.modules.pop("customtkinter", None)
    sys.modules.pop("tkinter", None)

    from Tools.Stats import shared_rois

    assert shared_rois is not None
    assert "customtkinter" not in sys.modules
    assert "tkinter" not in sys.modules


def test_load_rois_from_settings_cleans_pairs() -> None:
    from Tools.Stats.shared_rois import load_rois_from_settings

    class _Manager:
        def get_roi_pairs(self):
            return [
                (" Frontal ", [" F3 ", " ", "F4"]),
                ("", ["Cz"]),
                ("Central", (" Cz ", "C3")),
                ("Bad", "nope"),
            ]

    assert load_rois_from_settings(_Manager()) == {
        "Frontal": ["F3", "F4"],
        "Central": ["Cz", "C3"],
    }


def test_apply_rois_to_modules_updates_loaded_modules_without_importing_stats_runners() -> None:
    sys.modules.pop("Tools.Stats.Legacy.stats_runners", None)

    from Tools.Stats import shared_rois
    from Tools.Stats.Legacy import stats_analysis

    captured: list[dict[str, list[str]]] = []
    original_set_rois = stats_analysis.set_rois
    stats_analysis.set_rois = lambda rois: captured.append(rois)

    legacy_stats = types.ModuleType("Tools.Stats.Legacy.stats")
    sys.modules["Tools.Stats.Legacy.stats"] = legacy_stats

    try:
        shared_rois.apply_rois_to_modules({"ROI": ["Cz"]})
    finally:
        stats_analysis.set_rois = original_set_rois
        sys.modules.pop("Tools.Stats.Legacy.stats", None)

    assert captured == [{"ROI": ["Cz"]}]
    assert getattr(legacy_stats, "ROIS") == {"ROI": ["Cz"]}
    assert "Tools.Stats.Legacy.stats_runners" not in sys.modules

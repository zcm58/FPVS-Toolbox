from __future__ import annotations

import sys


def test_shared_rois_import_does_not_load_tkinter_or_customtkinter() -> None:
    sys.modules.pop("customtkinter", None)
    sys.modules.pop("tkinter", None)

    from Tools.Stats.data import shared_rois

    assert shared_rois is not None
    assert "customtkinter" not in sys.modules
    assert "tkinter" not in sys.modules


def test_load_rois_from_settings_cleans_pairs() -> None:
    from Tools.Stats.data.shared_rois import load_rois_from_settings

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


def test_apply_rois_to_modules_updates_active_analysis_only() -> None:
    for name in list(sys.modules):
        if name.startswith("Tools.Stats.Legacy"):
            sys.modules.pop(name, None)

    from Tools.Stats.data import shared_rois
    from Tools.Stats.analysis import stats_analysis

    captured: list[dict[str, list[str]]] = []
    original_set_rois = stats_analysis.set_rois
    stats_analysis.set_rois = lambda rois: captured.append(rois)

    try:
        shared_rois.apply_rois_to_modules({"ROI": ["Cz"]})
    finally:
        stats_analysis.set_rois = original_set_rois

    assert captured == [{"ROI": ["Cz"]}]
    assert not any(name.startswith("Tools.Stats.Legacy") for name in sys.modules)

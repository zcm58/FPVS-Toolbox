from __future__ import annotations

from Main_App.processing.roi_settings import (
    ALL_ROIS_OPTION,
    load_rois_from_settings,
)
from Tools.Stats.data import shared_rois as stats_shared_rois


class _Settings:
    def __init__(self, pairs) -> None:
        self._pairs = pairs

    def get_roi_pairs(self):
        return self._pairs


def test_neutral_roi_settings_clean_runtime_values() -> None:
    assert load_rois_from_settings(
        _Settings(
            [
                (" Occipital ", [" O1 ", "", "Oz"]),
                ("", ["Cz"]),
                ("Invalid", "Cz"),
                ("Empty", ["", "  "]),
            ]
        )
    ) == {"Occipital": ["O1", "Oz"]}
    assert ALL_ROIS_OPTION == "(All ROIs)"


def test_stats_roi_adapter_reexports_neutral_contract() -> None:
    assert stats_shared_rois.load_rois_from_settings is load_rois_from_settings
    assert stats_shared_rois.ALL_ROIS_OPTION is ALL_ROIS_OPTION

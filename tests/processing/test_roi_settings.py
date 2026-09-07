from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from Main_App.io import (
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_SCALP_SET_FINGERPRINT,
)
from Main_App.processing.roi_settings import (
    ALL_ROIS_OPTION,
    ROI_DEFINITION_SOURCE_APPLICATION_GLOBAL_SETTINGS,
    RoiDefinitionError,
    build_roi_definition_snapshot,
    load_rois_from_settings,
    snapshot_rois_from_settings,
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


def test_snapshot_canonicalizes_labels_and_preserves_ordered_fixed_sets() -> None:
    snapshot = build_roi_definition_snapshot(
        [
            (" Left posterior ", (" po7 ", "O1")),
            ("Single", (" oz ",)),
            ("Overlapping", ("O1", "PO8")),
        ]
    )

    assert snapshot.as_mapping() == {
        "Left posterior": ["PO7", "O1"],
        "Single": ["Oz"],
        "Overlapping": ["O1", "PO8"],
    }
    assert snapshot.source == ROI_DEFINITION_SOURCE_APPLICATION_GLOBAL_SETTINGS
    assert snapshot.geometry_version == BIOSEMI64_GEOMETRY_VERSION
    assert snapshot.geometry_fingerprint == BIOSEMI64_COORDINATE_FINGERPRINT
    assert (
        snapshot.canonical_scalp_set_fingerprint
        == BIOSEMI64_SCALP_SET_FINGERPRINT
    )
    assert snapshot.to_payload()["fingerprint"] == snapshot.fingerprint
    with pytest.raises(FrozenInstanceError):
        snapshot.source = "project"  # type: ignore[misc]


def test_snapshot_fingerprint_normalizes_harmless_case_and_whitespace() -> None:
    first = build_roi_definition_snapshot(
        [("Posterior", ("PO7", "O1")), ("Midline", ("Oz",))]
    )
    normalized = build_roi_definition_snapshot(
        [(" Posterior ", (" po7 ", " o1")), ("Midline", ("oz",))]
    )
    reordered = build_roi_definition_snapshot(
        [("Midline", ("Oz",)), ("Posterior", ("PO7", "O1"))]
    )

    assert first.fingerprint == normalized.fingerprint
    assert first.fingerprint != reordered.fingerprint


@pytest.mark.parametrize(
    ("raw_pairs", "message"),
    [
        ([("", ("O1",))], "names cannot be blank"),
        ([("ROI", ())], "at least one electrode"),
        ([("ROI", ("O1", ""))], "blank electrode"),
        ([("ROI", ("O1", "not-a-channel"))], "unknown BioSemi64"),
        ([("ROI", ("O1", " o1 "))], "repeats electrode"),
        (
            [("Posterior", ("O1",)), (" posterior ", ("Oz",))],
            "unique ignoring case",
        ),
    ],
)
def test_snapshot_rejects_ambiguous_or_incomplete_definitions(
    raw_pairs: object,
    message: str,
) -> None:
    with pytest.raises(RoiDefinitionError, match=message):
        build_roi_definition_snapshot(raw_pairs)


@pytest.mark.parametrize(
    "raw_pairs",
    [
        "ROI=O1",
        [("ROI",)],
        [("ROI", ("O1",), "extra")],
        ["ROI"],
        [("ROI", "O1")],
        [(12, ("O1",))],
        [("ROI", (12,))],
    ],
)
def test_snapshot_rejects_malformed_lossless_inputs(raw_pairs: object) -> None:
    with pytest.raises(RoiDefinitionError):
        build_roi_definition_snapshot(raw_pairs)


def test_snapshot_from_settings_records_global_source_and_rejects_bad_provider() -> None:
    snapshot = snapshot_rois_from_settings(
        _Settings([("Posterior", ("PO7", "O1"))])
    )
    assert snapshot.source == "application_global_settings"
    assert snapshot.as_mapping() == {"Posterior": ["PO7", "O1"]}

    with pytest.raises(RoiDefinitionError, match="does not expose ROI pairs"):
        snapshot_rois_from_settings(object())

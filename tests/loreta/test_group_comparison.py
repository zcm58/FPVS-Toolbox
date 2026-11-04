"""Prepared two-group comparison must not silently substitute source maps."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer.group_comparison import (
    GroupComparisonUnavailable,
    build_group_comparison,
    comparison_candidates,
)
from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry
from Tools.LORETA_Visualizer.source_payloads import make_source_payload


def _map(group="a", *, condition="words", summary="raw_mean", entry_id=None, metadata=None):
    identity = {
        "condition_group_id": group,
        "condition_group_label": f"Group {group.upper()}",
        "condition_group_split_applied": True,
        "condition_canonical_condition_id": condition,
        "condition_canonical_condition_label": condition.title(),
        "producer_method": f"l2_mne_hauk_source_psd_cortical_normal_v1_{summary}",
        "base_producer_method": "l2_mne_hauk_source_psd_cortical_normal_v1",
        "participant_zscore_aggregation": summary,
        "source_value_unit": "z-score",
        "participant_count": 12 if group == "a" else 7,
        "selected_harmonics_hz": [1.2, 2.4],
        "template_subject": "fsaverage",
        "source_space": "fsaverage_surface",
    }
    identity.update(metadata or {})
    payload = make_source_payload(
        points=np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
        values=np.array([2., 4., 6.]),
        label="A deliberately unrelated display label",
        kind="surface_mesh",
        source_model="l2_mne",
        faces=np.array([[0, 1, 2]]),
        value_label="source z-score",
        metadata=identity,
        normalize_values=False,
    )
    entry = PreparedSourceManifestEntry(
        condition_id=entry_id or f"{group}_{condition}_{summary}",
        label=f"Prepared {group} {condition} {summary}",
        payload_path=Path("unused.json"),
        metadata={key: identity[key] for key in (
            "producer_method", "base_producer_method", "participant_zscore_aggregation",
        )},
    )
    return entry, payload


def _candidates(*maps):
    return comparison_candidates(tuple(entry for entry, _ in maps), {entry.condition_id: payload for entry, payload in maps})


def test_matches_canonical_identity_not_composite_ids_labels_or_paths():
    first = _map("a", entry_id="unexpected-title-and-summary")
    second = _map("b", entry_id="manifest:3:anything-at-all")
    rows = _candidates(second, first)
    pair = build_group_comparison(rows, second[0].condition_id)
    assert pair.group_ids == ("a", "b")
    assert pair.condition_id == "words"
    assert pair.condition_label == "Words"
    assert pair.summary_id == "raw_mean"
    assert pair.left.entry is first[0]
    assert pair.right.payload is second[1]
    assert pair.left.panel_label == "Group A (n = 12)"
    assert pair.right.panel_label == "Group B (n = 7)"


def test_project_group_order_controls_consistent_panel_order():
    first, second = _map(), _map("b")
    rows = _candidates(first, second, _map(condition="faces"), _map("b", condition="faces"))
    for selected in ("a_words_raw_mean", "b_words_raw_mean", "a_faces_raw_mean"):
        assert build_group_comparison(rows, selected, canonical_group_ids=("b", "a")).group_ids == ("b", "a")


@pytest.mark.parametrize("roster", [(), ("a",), ("a", "a"), ("a", "b", "c"), ("a", "")])
def test_requires_exactly_two_distinct_canonical_groups(roster):
    with pytest.raises(GroupComparisonUnavailable, match="exactly two"):
        build_group_comparison(_candidates(_map(), _map("b")), "a_words_raw_mean", canonical_group_ids=roster)


def test_rejects_source_groups_outside_current_project():
    with pytest.raises(GroupComparisonUnavailable, match="current project"):
        build_group_comparison(_candidates(_map(), _map("old_group")), "a_words_raw_mean", canonical_group_ids=("a", "b"))


def test_one_group_cannot_enable_imported_comparison():
    with pytest.raises(GroupComparisonUnavailable, match="exactly two"):
        build_group_comparison(_candidates(_map()), "a_words_raw_mean")


def test_missing_group_condition_never_substitutes_another_condition():
    rows = _candidates(_map(), _map("b", condition="faces"))
    with pytest.raises(GroupComparisonUnavailable, match="Group B has no source map for Words"):
        build_group_comparison(rows, "a_words_raw_mean")


def test_missing_summary_never_falls_back_to_mean():
    rows = _candidates(_map(), _map("b"), _map(summary="median"))
    with pytest.raises(GroupComparisonUnavailable, match="selected summary \\(median\\)"):
        build_group_comparison(rows, "a_words_median")


def test_missing_other_condition_does_not_block_complete_pair():
    rows = _candidates(_map(), _map("b"), _map(condition="faces"))
    assert build_group_comparison(rows, "a_words_raw_mean").condition_id == "words"


@pytest.mark.parametrize("changed", [
    {"producer_method": "different_inverse"},
    {"base_producer_method": "different_orientation"},
    {"source_method": "another_method"},
    {"source_value_unit": "uV"},
    {"selected_harmonics_hz": [1.2, 3.6]},
    {"template_subject": "other_template"},
    {"source_space": "fsaverage_volume"},
    {"participant_zscore_trim_fraction": .3},
])
def test_incompatible_numerical_identity_is_not_a_comparison(changed):
    rows = _candidates(_map(), _map("b", metadata=changed))
    with pytest.raises(GroupComparisonUnavailable, match="matching numerical method"):
        build_group_comparison(rows, "a_words_raw_mean")


@pytest.mark.parametrize("changed", [
    {"kind": "volume_points"}, {"coordinate_space": "different"},
    {"source_model": "eloreta"}, {"value_label": "source amplitude"},
])
def test_payload_model_metric_and_coordinates_must_match(changed):
    entry, payload = _map("b")
    rows = _candidates(_map(), (entry, replace(payload, **changed)))
    with pytest.raises(GroupComparisonUnavailable, match="matching numerical method"):
        build_group_comparison(rows, "a_words_raw_mean")


@pytest.mark.parametrize(("field", "first", "second"), [
    ("lambda2", 1 / 9, 1 / 16),
    ("inverse_backend", "mne_python", "manual_ridge"),
    ("loose_orientation", .2, 1.),
    ("fixed_orientation", False, True),
    ("depth_weighting", "none", "0.8"),
    ("noise_normalization", "none", "dSPM"),
    ("average_reference_applied", True, False),
    ("montage_name", "biosemi64", "standard_1020"),
    ("source_spacing_mm", 10., 5.),
    ("source_spacing", "ico5", "ico4"),
    ("volume_pos_mm", 10., 5.),
    ("forward_model_source_spacing", "ico5", "ico4"),
    ("forward_model_volume_pos_mm", 10., 5.),
    ("forward_model_mindist_mm", 5., 0.),
    ("forward_model_noise_covariance", "mne_ad_hoc_diagonal_eeg", "empirical"),
    ("forward_model_average_reference_projection", True, False),
    ("forward_model_model_sfreq_hz", 256., 250.),
    ("forward_model_source_psd_lambda2", 1 / 9, 1 / 16),
    ("forward_model_source_psd_method_params", {"eps": 1e-6}, {"eps": 1e-4}),
    ("forward_model_native_mne_leadfield_sha256", "leadfield_a", "leadfield_b"),
])
def test_explicit_model_configuration_cannot_differ_under_same_method_id(field, first, second):
    rows = _candidates(_map(metadata={field: first}), _map("b", metadata={field: second}))
    with pytest.raises(GroupComparisonUnavailable, match="matching numerical method"):
        build_group_comparison(rows, "a_words_raw_mean")
    rows = _candidates(_map(metadata={field: first}), _map("b", metadata={field: first}))
    assert build_group_comparison(rows, "a_words_raw_mean").group_ids == ("a", "b")


def test_duplicate_group_condition_summary_is_explicitly_ambiguous():
    rows = _candidates(_map(), _map("b"), _map("b", entry_id="second_b"))
    with pytest.raises(GroupComparisonUnavailable, match="Multiple source maps"):
        build_group_comparison(rows, "a_words_raw_mean")


def test_duplicate_entry_ids_rejected_before_mapping_lookup():
    first, second = _map(), _map("b", entry_id="a_words_raw_mean")
    with pytest.raises(GroupComparisonUnavailable, match="Duplicate source-map"):
        _candidates(first, second)


@pytest.mark.parametrize("field", ["condition_group_id", "condition_canonical_condition_id", "condition_group_split_applied"])
def test_legacy_maps_without_explicit_identity_are_not_guessed(field):
    entry, payload = _map()
    payload.metadata.pop(field)
    with pytest.raises(GroupComparisonUnavailable, match="Rebuild group source maps"):
        _candidates((entry, payload), _map("b"))


def test_string_truthy_group_split_flag_is_not_accepted():
    with pytest.raises(GroupComparisonUnavailable, match="explicit canonical"):
        _candidates(_map(metadata={"condition_group_split_applied": "True"}), _map("b"))


def test_unprefixed_explicit_group_metadata_is_supported():
    maps = [_map(), _map("b")]
    for _, payload in maps:
        for key in tuple(payload.metadata):
            if key.startswith("condition_"):
                payload.metadata[key.removeprefix("condition_")] = payload.metadata.pop(key)
    assert build_group_comparison(_candidates(*maps), "a_words_raw_mean").group_ids == ("a", "b")


def test_conflicting_payload_and_manifest_identity_is_rejected():
    entry, payload = _map()
    entry.metadata["group_id"] = "b"
    with pytest.raises(GroupComparisonUnavailable, match="conflicting group_id"):
        _candidates((entry, payload))


def test_conflicting_manifest_summary_is_rejected():
    entry, payload = _map()
    entry.metadata["participant_zscore_aggregation"] = "median"
    with pytest.raises(GroupComparisonUnavailable, match="conflicting participant_zscore_aggregation"):
        _candidates((entry, payload))


def test_missing_payload_does_not_drop_map_silently():
    entry, _ = _map()
    with pytest.raises(GroupComparisonUnavailable, match="Load the source map"):
        comparison_candidates((entry,), {})


def test_missing_producer_method_prevents_comparison():
    entry, payload = _map()
    entry.metadata.pop("producer_method")
    payload.metadata.pop("producer_method")
    with pytest.raises(GroupComparisonUnavailable, match="explicit numerical source method"):
        _candidates((entry, payload))


@pytest.mark.parametrize("count", [None, True, -1, 2.5, "bad", float("inf")])
def test_unavailable_participant_count_is_not_invented(count):
    rows = _candidates(_map(metadata={"participant_count": count}), _map("b"))
    assert build_group_comparison(rows, "a_words_raw_mean").left.panel_label == "Group A"


def test_masks_values_and_input_metadata_are_preserved_without_between_group_math():
    first, second = _map(), _map("b")
    first[1].metadata.update(cluster_mask_source_indices=[0, 2], arbitrary_provenance={"a": [1, 2]})
    second[1].metadata.update(cluster_mask_source_indices=[1], arbitrary_provenance={"b": [3, 4]})
    before = first[1].values.copy(), second[1].values.copy()
    pair = build_group_comparison(_candidates(first, second), "b_words_raw_mean")
    assert pair.left.payload is first[1]
    assert pair.right.payload is second[1]
    assert pair.left.payload.metadata["cluster_mask_source_indices"] == [0, 2]
    assert pair.right.payload.metadata["cluster_mask_source_indices"] == [1]
    np.testing.assert_equal(pair.left.payload.values, before[0])
    np.testing.assert_equal(pair.right.payload.values, before[1])


def test_selected_entry_must_exist_and_be_unambiguous():
    rows = _candidates(_map(), _map("b"))
    with pytest.raises(GroupComparisonUnavailable, match="Select one unambiguous"):
        build_group_comparison(rows, "missing")
    with pytest.raises(GroupComparisonUnavailable, match="Select one unambiguous"):
        build_group_comparison((*rows, rows[0]), "a_words_raw_mean")

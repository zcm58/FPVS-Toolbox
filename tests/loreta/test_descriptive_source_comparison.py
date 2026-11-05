from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT, PREPARED_SOURCE_PAYLOAD_FORMAT,
    validate_prepared_source_manifest_json, validate_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload, SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers import descriptive_comparison as comparison_module
from Tools.LORETA_Visualizer.source_producers.descriptive_comparison import (
    SourceComparisonUnavailable, build_descriptive_source_comparison,
)
from Tools.LORETA_Visualizer.source_producers.source_metrics import (
    add_source_amplitude_outputs, source_document_sha256,
)
from Tools.LORETA_Visualizer.source_producers.source_validity import source_validity_metadata, source_values_to_json


def _write(path, document):
    path.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")


def synthetic_comparison_bundle(tmp_path: Path, *, aggregation="mean", kind="surface_mesh", invalid=False):
    """Small complete producer bundle, usable for a visible synthetic GUI review."""
    tmp_path.mkdir(exist_ok=True, parents=True)
    cells = [
        ("g1_c1", "g1", "c1", {"P1": [0., -4., 8.], "P2": [20., -2., 4.], "P3": [100., -6., 0.], "only_A": [1000., 1000., 1000.]}),
        ("g1_c2", "g1", "c2", {"P1": [10., 2., 0.], "P2": [1., 4., 2.], "P3": [99., 0., 6.], "only_B": [-100., -100., -100.]}),
        ("g2_c1", "g2", "c1", {"Q1": [2., 2., 2.], "Q2": [4., 4., 4.]}),
    ]
    conditions, sidecar_cells, entries, outputs, original_z = [], [], [], [], {}
    for cell_id, group, condition, participants in cells:
        rows, saved_rows = [], []
        for identity, amplitude in participants.items():
            amplitude = np.asarray(amplitude)
            support = np.ones(3, dtype=bool)
            if invalid and cell_id == "g1_c2" and identity == "P1":
                support[2] = False
            z = amplitude / 2
            z[~support] = np.nan
            row = SimpleNamespace(
                participant_id=identity, values=z, target_source_values=amplitude + 2000,
                noise_mean_values=np.full(3, 2000.), noise_std_values=np.full(3, 2.),
                valid_source_mask=support, zero_noise_sd_source_count=int((~support).sum()),
            )
            rows.append(row)
            saved_rows.append({"participant_id": identity, "values": source_values_to_json(z, support), "source_validity": source_validity_metadata(support)})
        metadata = {"canonical_condition_id": condition, "canonical_condition_label": condition,
                    "group_id": group, "group_label": group, "group_split_applied": True}
        conditions.append(SimpleNamespace(condition_id=cell_id, label=cell_id, participant_values=rows, metadata=metadata))
        sidecar_cells.append({"condition_id": cell_id, "label": cell_id, "metadata": {}, "participants": saved_rows})
        valid = np.logical_and.reduce([row.valid_source_mask for row in rows])
        values = np.mean([row.values for row in rows], axis=0)
        values[~valid] = np.nan
        document = {
            "format": PREPARED_SOURCE_PAYLOAD_FORMAT, "label": cell_id, "kind": kind,
            "source_model": "synthetic_spectral_model", "coordinate_space": "fsaverage_surface",
            "value_label": "Source z-score", "points": [[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]],
            "values": source_values_to_json(values, valid),
            "metadata": {
                "base_producer_method": "synthetic_spectral_model", "selected_harmonics_hz": [2., 4.],
                "participant_zscore_aggregation": aggregation, "participant_zscore_trim_fraction": .2 if aggregation == "trimmed_mean" else None,
                "participant_ids": list(participants), "participant_count": len(participants),
                "source_value_unit": "z-score", "source_validity": source_validity_metadata(valid, scope="group_complete_case", participant_count=len(participants)),
                "cluster_mask": "source_space_cluster_permutation", "cluster_mask_status": "computed",
                "cluster_mask_source_indices": [0], "cluster_mask_primary_display": True,
                "cluster_p_values": [.01], "source_inference_correction_scope": "within_map",
            },
        }
        if kind == "surface_mesh":
            document["faces"] = [[0, 1, 2]]
        entry_id = f"{cell_id}_{aggregation}"
        path = tmp_path / f"{entry_id}.json"
        _write(path, document)
        original_z[entry_id] = deepcopy(document["values"])
        entries.append({"id": entry_id, "label": cell_id, "file": path.name, "metadata": {"participant_zscore_aggregation": aggregation}})
        outputs.append(ProducedPayload(entry_id, cell_id, path, validate_prepared_source_payload_json(path)))
    manifest_path, sidecar_path = tmp_path / "manifest.json", tmp_path / "participants.json"
    _write(manifest_path, {"format": PREPARED_SOURCE_MANIFEST_FORMAT, "conditions": entries, "metadata": {}})
    _write(sidecar_path, {"format": "synthetic_participant_maps", "conditions": sidecar_cells, "metadata": {}})
    base = SourceProducerRunResult("synthetic_spectral_model", tmp_path, manifest_path, tuple(outputs), validate_prepared_source_manifest_json(manifest_path))
    result = add_source_amplitude_outputs(base, participant_sidecar_path=sidecar_path, conditions=conditions,
                                         frequency_metadata={"n_times": 4000, "sfreq": 200., "window": "hann", "selected_harmonics_hz": [2., 4.]})
    return result, sidecar_path, original_z


@pytest.mark.parametrize("kind", ["surface_mesh", "volume_points"])
def test_amplitude_output_preserves_z_and_removes_sd_division(tmp_path, kind):
    result, sidecar_path, original_z = synthetic_comparison_bundle(tmp_path, kind=kind)
    manifest = json.loads(result.manifest_path.read_text())
    assert len(manifest["conditions"]) == 6
    for entry in manifest["conditions"]:
        payload = json.loads((tmp_path / entry["file"]).read_text())
        if entry["metadata"]["source_metric"] == "z_score":
            assert payload["values"] == original_z[entry["id"]]
            assert payload["metadata"]["cluster_mask_source_indices"] == [0]
        else:
            np.testing.assert_allclose(payload["values"], np.asarray(original_z[entry["id"].split("__")[0]]) * 2)
            assert payload["metadata"]["source_value_polarity"] == "signed"
            assert payload["metadata"]["source_value_unit"] == "source spectral amplitude"
            assert "cluster_mask_source_indices" not in payload["metadata"]
            assert "cluster_p_values" not in payload["metadata"]
    sidecar = json.loads(sidecar_path.read_text())
    assert "target_source_values" in sidecar["conditions"][0]["participants"][0]


@pytest.mark.parametrize("metric_suffix,scale", [("", .5), ("__baseline_corrected_amplitude", 1.)])
@pytest.mark.parametrize("aggregation,expected", [("mean", 10 / 3), ("median", 1.), ("trimmed_mean", 10 / 3)])
def test_paired_difference_precedes_summary_and_restricts_both_panels(tmp_path, metric_suffix, scale, aggregation, expected):
    result, _, _ = synthetic_comparison_bundle(tmp_path, aggregation=aggregation)
    prepared = build_descriptive_source_comparison(result.manifest_path, f"g1_c1_{aggregation}{metric_suffix}", f"g1_c2_{aggregation}{metric_suffix}", comparison_kind="conditions")
    assert prepared.metadata["left_participant_ids"] == ["P1", "P2", "P3"]
    assert prepared.metadata["left_omitted_participant_ids"] == ["only_A"]
    assert prepared.metadata["right_omitted_participant_ids"] == ["only_B"]
    assert prepared.difference_payload["values"][0] == pytest.approx(expected * scale)
    assert prepared.difference_payload["values"][1] == pytest.approx(-6 * scale)
    assert prepared.left_payload["metadata"]["participant_count"] == 3
    assert prepared.right_payload["metadata"]["participant_count"] == 3
    if aggregation == "median":
        assert prepared.left_payload["values"][0] == 20 * scale
        assert prepared.right_payload["values"][0] == 10 * scale
        assert prepared.difference_payload["values"][0] != prepared.left_payload["values"][0] - prepared.right_payload["values"][0]
    for payload in (prepared.left_payload, prepared.right_payload, prepared.difference_payload):
        assert payload["metadata"]["source_value_polarity"] == "signed"
        assert payload["metadata"]["descriptive_only"]
        assert "cluster_p_values" not in payload["metadata"]


def test_group_difference_retains_independent_cohorts(tmp_path):
    result, _, _ = synthetic_comparison_bundle(tmp_path)
    prepared = build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", "g2_c1_mean")
    assert prepared.metadata["left_participant_count"] == 4
    assert prepared.metadata["right_participant_count"] == 2
    assert prepared.metadata["left_omitted_participant_ids"] == []
    assert prepared.difference_payload["values"][0] == (280 - 3) / 2


def test_all_panels_share_valid_support_without_zero_filling(tmp_path):
    result, _, _ = synthetic_comparison_bundle(tmp_path, invalid=True)
    prepared = build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", "g1_c2_mean", comparison_kind="conditions")
    for payload in (prepared.left_payload, prepared.right_payload, prepared.difference_payload):
        assert payload["values"][2] is None
        assert len(payload["points"]) == 3
        assert payload["metadata"]["source_validity"]["invalid_source_indices"] == [2]


@pytest.mark.parametrize("kind,left,right", [("groups", "g1_c1_mean", "g1_c2_mean"), ("conditions", "g1_c1_mean", "g2_c1_mean"), ("conditions", "g1_c1_mean", "g1_c1_mean")])
def test_design_mismatch_is_rejected(tmp_path, kind, left, right):
    result, _, _ = synthetic_comparison_bundle(tmp_path)
    with pytest.raises(SourceComparisonUnavailable):
        build_descriptive_source_comparison(result.manifest_path, left, right, comparison_kind=kind)


def test_historical_bundle_requests_rebuild(tmp_path):
    manifest_path = tmp_path / "old.json"
    _write(manifest_path, {"metadata": {}, "conditions": []})
    with pytest.raises(SourceComparisonUnavailable, match="Rebuild source maps"):
        build_descriptive_source_comparison(manifest_path, "a", "b")


def test_persistently_modified_participant_file_is_rejected(tmp_path):
    result, sidecar_path, _ = synthetic_comparison_bundle(tmp_path)
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["conditions"][0]["participants"][0]["values"][0] = 999
    _write(sidecar_path, sidecar)
    with pytest.raises(SourceComparisonUnavailable, match="do not match"):
        build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", "g2_c1_mean")


def test_concurrent_bundle_mutation_is_rejected(tmp_path, monkeypatch):
    result, sidecar_path, _ = synthetic_comparison_bundle(tmp_path)
    original = comparison_module._prepared_panel
    calls = []
    def change_after_read(*args, **kwargs):
        document = original(*args, **kwargs)
        if not calls:
            sidecar_path.write_text(sidecar_path.read_text() + "\n", encoding="utf-8")
        calls.append(True)
        return document
    monkeypatch.setattr(comparison_module, "_prepared_panel", change_after_read)
    with pytest.raises(SourceComparisonUnavailable, match="changed during"):
        build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", "g2_c1_mean")


@pytest.mark.parametrize("change", ["harmonics", "sample_count", "sample_rate", "window", "lambda2", "geometry", "group_identity", "participant_identity"])
def test_validly_reencoded_incompatible_data_is_rejected(tmp_path, change):
    result, _, _ = synthetic_comparison_bundle(tmp_path)
    manifest = json.loads(result.manifest_path.read_text())
    entry = manifest["conditions"][2]
    path = tmp_path / entry["file"]
    payload = json.loads(path.read_text())
    if change == "harmonics":
        payload["metadata"]["selected_harmonics_hz"] = [2.]
    elif change in {"sample_count", "sample_rate", "window"}:
        key, value = {"sample_count": ("n_times", 2000), "sample_rate": ("sfreq", 100.), "window": ("window", "boxcar")}[change]
        payload["metadata"]["source_spectral_settings"][key] = value
    elif change == "lambda2":
        payload["metadata"]["lambda2"] = 1.
    elif change == "geometry":
        payload["points"][0][0] = 999
    elif change == "group_identity":
        payload["metadata"]["group_id"] = "wrong"
        entry["metadata"]["group_id"] = "wrong"
    else:
        payload["metadata"]["participant_ids"] = ["wrong", "Q2"]
    _write(path, payload)
    entry["metadata"]["source_payload_sha256"] = source_document_sha256(payload)
    _write(result.manifest_path, manifest)
    with pytest.raises(SourceComparisonUnavailable):
        build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", "g2_c1_mean")


@pytest.mark.parametrize("change,kind", [("no_pairs", "conditions"), ("duplicate", "conditions"), ("overlap", "groups"), ("invalid_support", "conditions")])
def test_incompatible_participant_cohorts_are_rejected(tmp_path, change, kind):
    result, sidecar_path, _ = synthetic_comparison_bundle(tmp_path)
    manifest = json.loads(result.manifest_path.read_text())
    sidecar = json.loads(sidecar_path.read_text())
    cell_index = 2 if kind == "groups" else 1
    rows = sidecar["conditions"][cell_index]["participants"]
    if change == "no_pairs":
        for row in rows:
            row["participant_id"] = "different_" + row["participant_id"]
    elif change == "duplicate":
        rows[1]["participant_id"] = rows[0]["participant_id"].lower()
    elif change == "overlap":
        rows[0]["participant_id"] = "p1"
    else:
        for row, support in zip(rows[:2], (np.array([True, False, False]), np.array([False, True, True]))):
            values = np.asarray(row["values"], dtype=float)
            values[~support] = np.nan
            row["values"] = source_values_to_json(values, support)
            row["source_validity"] = source_validity_metadata(support)
    _write(sidecar_path, sidecar)
    manifest["metadata"]["participant_sidecar_sha256"] = source_document_sha256(sidecar)
    entry = manifest["conditions"][cell_index]
    path = tmp_path / entry["file"]
    payload = json.loads(path.read_text())
    payload["metadata"]["participant_ids"] = [row["participant_id"] for row in rows]
    _write(path, payload)
    entry["metadata"]["source_payload_sha256"] = source_document_sha256(payload)
    _write(result.manifest_path, manifest)
    with pytest.raises(ValueError, match="No participants|Duplicate participant|overlapping participant|No common valid"):
        build_descriptive_source_comparison(result.manifest_path, "g1_c1_mean", entry["id"], comparison_kind=kind)


def test_trimmed_paired_difference_rejects_outliers_after_pairing(tmp_path):
    result, sidecar_path, _ = synthetic_comparison_bundle(tmp_path, aggregation="trimmed_mean")
    manifest = json.loads(result.manifest_path.read_text())
    sidecar = json.loads(sidecar_path.read_text())
    # Five pairs: A=[0,20,100,0,0], B=[10,1,99,-1000,1000].
    # Per-person differences [-10,19,1,1000,-1000] trim to [-10,1,19].
    for cell_index, extra_values in ((0, [0., 0.]), (1, [-1000., 1000.])):
        rows = sidecar["conditions"][cell_index]["participants"]
        for identity, value in zip(("P4", "P5"), extra_values):
            row = deepcopy(rows[0])
            row.update({"participant_id": identity, "values": [value / 2] * 3,
                        "target_source_values": [value + 2000] * 3})
            rows.append(row)
        entry = manifest["conditions"][cell_index]
        path = tmp_path / entry["file"]
        payload = json.loads(path.read_text())
        payload["metadata"]["participant_ids"] = [row["participant_id"] for row in rows]
        payload["metadata"]["participant_count"] = len(rows)
        _write(path, payload)
        entry["metadata"]["source_payload_sha256"] = source_document_sha256(payload)
    _write(sidecar_path, sidecar)
    manifest["metadata"]["participant_sidecar_sha256"] = source_document_sha256(sidecar)
    _write(result.manifest_path, manifest)
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    comparison = build_descriptive_source_comparison(result.manifest_path, "g1_c1_trimmed_mean", "g1_c2_trimmed_mean", comparison_kind="conditions")
    assert comparison.metadata["left_participant_count"] == 5
    assert comparison.difference_payload["values"][0] == pytest.approx(5 / 3)
    assert comparison.difference_payload["values"][0] != comparison.left_payload["values"][0] - comparison.right_payload["values"][0]
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before

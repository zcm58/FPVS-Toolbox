"""Canonical operand selection and asynchronous comparison state, without Qt."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer import gui
from Tools.LORETA_Visualizer.comparison_selection import (
    METRIC_AMPLITUDE, METRIC_Z_SCORE, comparison_bundle_signature,
    comparison_request, comparison_targets, entry_metric, metric_entries,
)
from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry, load_prepared_source_manifest_json
from Tools.LORETA_Visualizer.source_payloads import make_source_payload


def entry(tmp_path, group="a", condition="words", summary="mean", metric=METRIC_Z_SCORE):
    identity = f"{group}_{condition}_{summary}_{metric}"
    path = tmp_path / f"{identity}.json"
    path.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return PreparedSourceManifestEntry(identity, identity, path, {
        "group_id": group, "group_label": group.upper(),
        "canonical_condition_id": condition, "canonical_condition_label": condition.title(),
        "participant_zscore_aggregation": summary, "source_metric": metric,
        "source_cell_id": f"{group}_{condition}", "source_cell_label": f"{group.upper()} {condition.title()}",
        "_loaded_manifest_path": str(manifest),
    })


def test_targets_require_matching_canonical_cell_metric_and_summary(tmp_path):
    left = entry(tmp_path)
    group_b = entry(tmp_path, group="b")
    condition_b = entry(tmp_path, condition="faces")
    incompatible = (
        entry(tmp_path, group="b", condition="faces"),
        entry(tmp_path, group="b", summary="median"),
        entry(tmp_path, group="b", metric=METRIC_AMPLITUDE),
    )
    entries = (left, group_b, condition_b, *incompatible)
    assert comparison_targets(entries, left, kind="groups") == (group_b,)
    assert comparison_targets(entries, left, kind="conditions") == (condition_b,)


def test_condition_pairs_allow_one_ungrouped_cohort_but_groups_require_ids(tmp_path):
    left, right = entry(tmp_path, group=""), entry(tmp_path, group="", condition="faces")
    assert comparison_targets((right,), left, kind="conditions") == (right,)
    assert comparison_targets((right,), left, kind="groups") == ()


def test_ambiguous_identity_fails_and_labels_do_not_substitute_for_ids(tmp_path):
    left, right = entry(tmp_path), entry(tmp_path, group="b")
    ambiguous = replace(right, metadata={**right.metadata, "condition_group_id": "other"})
    with pytest.raises(ValueError, match="conflicting"):
        comparison_targets((ambiguous,), left, kind="groups")
    unknown = replace(left, metadata={**left.metadata, "canonical_condition_id": ""})
    assert comparison_targets((right,), unknown, kind="groups") == ()


def test_comparison_requires_one_bundle_and_exact_entries(tmp_path):
    left, right = entry(tmp_path), entry(tmp_path, group="b")
    request = comparison_request(left, right, kind="groups")
    assert request.left_entry_id == left.condition_id and request.right_entry_id == right.condition_id
    foreign = replace(right, metadata={**right.metadata, "_loaded_manifest_path": "different.json"})
    with pytest.raises(ValueError, match="same source bundle"):
        comparison_request(left, foreign, kind="groups")


def test_metric_and_summary_labels_keep_amplitude_out_of_z_groups(tmp_path):
    zmap, amplitude = entry(tmp_path), entry(tmp_path, metric=METRIC_AMPLITUDE)
    assert entry_metric(amplitude) == METRIC_AMPLITUDE
    assert metric_entries((zmap, amplitude), METRIC_Z_SCORE) == (zmap,)
    assert gui._manifest_entry_condition_id(amplitude) == "a_words"
    assert gui._manifest_entry_condition_label(amplitude) == "A Words"
    assert gui._source_summary_label("median", METRIC_AMPLITUDE) == "Median"
    legacy = replace(zmap, metadata={"participant_zscore_aggregation": "mean"})
    assert entry_metric(legacy) == METRIC_Z_SCORE


def test_sidecar_removal_invalidates_cached_bundle_signature(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    sidecar = tmp_path / "participants.json"
    sidecar.write_text("{}")
    original = comparison_bundle_signature(manifest)
    sidecar.unlink()
    assert comparison_bundle_signature(manifest) != original


def comparison_host(tmp_path):
    left, right = entry(tmp_path), entry(tmp_path, group="b")
    request = comparison_request(left, right, kind="groups")
    key = (request, comparison_bundle_signature(request.manifest_path), gui._comparison_file_signature((left, right)))
    events = []
    host = SimpleNamespace(
        _comparison_left_entry=lambda: left, _sync_comparison_targets=lambda: None,
        _comparison_target_error=None, comparison_target_combo=SimpleNamespace(currentData=lambda: right.condition_id),
        _comparison_manifest_entries=lambda: (left, right), _comparison_kind="groups",
        _descriptive_requested_key="old request", _descriptive_key=key, _descriptive_payloads=(1, 2, 3),
        _descriptive_failed_key=None, _group_comparison_request_id=4, _group_comparison_thread=object(),
        _render_descriptive_comparison=lambda: events.append("render"),
        _release_group_comparison_renderer=lambda: events.append("release"),
        _clear_activation_payload=lambda: events.append("clear"),
        export_figures_btn=SimpleNamespace(setEnabled=lambda value: events.append(("export", value))),
        _set_source_export_status=lambda *args, **kwargs: events.append((args, kwargs)),
    )
    return host, events, key


def test_returning_to_cached_operand_invalidates_inflight_other_result(tmp_path):
    host, events, key = comparison_host(tmp_path)
    gui.LoretaVisualizerWindow._refresh_descriptive_comparison(host)
    assert host._group_comparison_request_id == 5
    assert host._descriptive_requested_key == key
    assert events == ["render"]


def test_missing_sidecar_clears_old_maps_while_waiting_for_obsolete_worker(tmp_path):
    sidecar = tmp_path / "participants.json"
    sidecar.write_text("{}")
    host, events, _key = comparison_host(tmp_path)
    sidecar.unlink()
    gui.LoretaVisualizerWindow._refresh_descriptive_comparison(host)
    assert "clear" in events and "render" not in events and ("export", False) in events
    assert host._comparison_source_payloads == host._comparison_display_payloads == ()


@pytest.mark.parametrize("closing,enabled,request_id,key", [
    (True, True, 4, "current"), (False, False, 4, "current"),
    (False, True, 3, "current"), (False, True, 4, "obsolete"),
])
def test_stale_descriptive_results_are_ignored(closing, enabled, request_id, key):
    host = SimpleNamespace(
        _closing_requested=closing, _group_comparison_enabled=enabled,
        _group_comparison_request_id=4, _descriptive_requested_key="current",
        _render_descriptive_comparison=lambda: pytest.fail("Stale result rendered"),
    )
    gui.LoretaVisualizerWindow._on_descriptive_comparison_loaded(
        host, ({"id": request_id, "key": key}, (1, 2, 3), {}),
    )


def test_missing_exact_summary_cannot_fall_back_to_mean():
    host = SimpleNamespace(_selected_condition_id="words", _selected_summary_id="median",
                           _manifest_condition_groups={"words": SimpleNamespace(entries_by_summary={"mean": object()})})
    assert gui.LoretaVisualizerWindow._comparison_left_entry(host) is None


def test_signed_z_comparison_preserves_negatives_and_ignores_independent_mask():
    payload = make_source_payload(
        points=np.eye(3), values=np.array([-3., 1., 2.]), label="A−B", kind="volume_points",
        metadata={"source_value_polarity": "signed", "source_metric": "z_score", "source_value_unit": "z-score",
                  "cluster_mask": "source_space_cluster_permutation", "cluster_mask_source_indices": [2]},
        normalize_values=False,
    )
    assert gui._activation_display_payload(payload) is payload
    np.testing.assert_array_equal(gui._activation_scale_values(payload), [-3., 1., 2.])
    host = SimpleNamespace(activation_scale_combo=SimpleNamespace(currentData=lambda: gui.SCALE_CURRENT),
                           _zscore_display_threshold=1.64, _use_cluster_mask=True)
    assert gui.LoretaVisualizerWindow._scalar_range_for_payloads(host, (payload,)) == (-3., 3.)


def test_difference_export_label_records_direction_metric_and_pair_cohort():
    payload = SimpleNamespace(metadata={"participant_count": 3})
    host = SimpleNamespace(_group_comparison_enabled=True, _descriptive_payloads=(payload, payload, payload),
                           _descriptive_labels=("Words", "Faces"), _selected_metric=METRIC_AMPLITUDE,
                           _comparison_kind="conditions", _comparison_view="difference")
    label = gui.LoretaVisualizerWindow._selected_condition_label(host)
    assert "Words − Faces" in label and "Baseline-corrected amplitude" in label and "paired n = 3" in label


def test_figure_worker_exports_immutable_panel_snapshot_without_renderer(monkeypatch, tmp_path):
    calls, events = [], []
    panels = (object(), object())
    monkeypatch.setattr(gui, "write_publication_split_hemisphere_stack_figures",
                        lambda path, **kwargs: calls.append((path, kwargs)) or (path, path.with_suffix(".png")))
    worker = SimpleNamespace(request={"path": tmp_path / "comparison.pdf", "panels": panels},
                             exported=SimpleNamespace(emit=lambda result: events.append(result)),
                             failed=SimpleNamespace(emit=lambda error: pytest.fail(error)),
                             finished=SimpleNamespace(emit=lambda: events.append("finished")))
    gui.ComparisonFigureExportWorker.run(worker)
    assert calls[0][1]["panels"] is panels
    assert len(events[0]) == 2 and events[-1] == "finished"


def test_imported_raw_ids_reach_producer_with_case_punctuation_and_amplitude_suffix(tmp_path, monkeypatch):
    from test_descriptive_source_comparison import synthetic_comparison_bundle
    from Tools.LORETA_Visualizer.source_producers.descriptive_comparison import build_descriptive_source_comparison

    result, _sidecar, _original = synthetic_comparison_bundle(tmp_path)
    document = json.loads(result.manifest_path.read_text())
    raw_ids = ["manifest:Mixed Case:A__baseline_corrected_amplitude", "B:Faces!__baseline_corrected_amplitude"]
    for row, raw_id in zip(document["conditions"][3:5], raw_ids):
        row["id"] = raw_id
    result.manifest_path.write_text(json.dumps(document), encoding="utf-8")
    entries = load_prepared_source_manifest_json(result.manifest_path)
    entries = tuple(replace(row, metadata={**row.metadata, "_loaded_manifest_path": str(result.manifest_path)}) for row in entries)
    # The importer namespaces GUI identities; the producer must receive exact saved IDs.
    assert entries[3].condition_id != raw_ids[0]
    request = comparison_request(entries[3], entries[4], kind="conditions")
    assert (request.left_entry_id, request.right_entry_id) == tuple(raw_ids)
    prepared = build_descriptive_source_comparison(
        request.manifest_path, request.left_entry_id, request.right_entry_id, comparison_kind=request.comparison_kind,
    )
    assert prepared.left_payload["metadata"]["participant_count"] == 3
    assert prepared.difference_payload["values"][1] == -6
    events = []
    monkeypatch.setattr(gui, "prepared_source_payload_from_mapping", lambda document, **_kwargs: document)
    worker = SimpleNamespace(
        request={"id": 5, "specification": request, "display_transform": None,
                 "key": (request, comparison_bundle_signature(result.manifest_path))},
        loaded=SimpleNamespace(emit=events.append), failed=SimpleNamespace(emit=lambda *_args: pytest.fail(str(_args))),
        finished=SimpleNamespace(emit=lambda: events.append("finished")),
    )
    gui.DescriptiveComparisonWorker.run(worker)
    assert len(events[0][1]) == 3 and events[0][1][2]["values"][1] == -6
    assert events[-1] == "finished"


def test_comparison_dependency_failure_emits_failure_and_finishes(tmp_path, monkeypatch):
    from Tools.LORETA_Visualizer.source_producers import descriptive_comparison

    def unavailable(*_args, **_kwargs):
        raise ImportError("Comparison dependency unavailable")

    monkeypatch.setattr(descriptive_comparison, "build_descriptive_source_comparison", unavailable)
    left, right = entry(tmp_path), entry(tmp_path, group="b")
    specification = comparison_request(left, right, kind="groups")
    events = []
    worker = SimpleNamespace(
        request={"id": 8, "specification": specification},
        loaded=SimpleNamespace(emit=lambda *_args: pytest.fail("Unexpected result")),
        failed=SimpleNamespace(emit=lambda *args: events.append(args)),
        finished=SimpleNamespace(emit=lambda: events.append("finished")),
    )
    gui.DescriptiveComparisonWorker.run(worker)
    assert events == [(8, "Comparison dependency unavailable"), "finished"]


def test_difference_switch_to_mri_keeps_prepared_comparison_intent():
    payload = make_source_payload(points=np.eye(3), values=np.array([-2., 0., 2.]),
                                  label="A−B", kind="volume_points", normalize_values=False)
    calls = []
    host = SimpleNamespace(
        _mri_render_request_id=0, display_mode_combo=SimpleNamespace(currentData=lambda: gui.DISPLAY_MODE_MRI_SLICES),
        _group_comparison_enabled=True, _comparison_view="difference", _descriptive_payloads=(payload,) * 3,
        _source_activation_payload=payload, renderer=object(), _sync_source_map_selectors_enabled=lambda: None,
        _set_activation_payload=lambda value, **kwargs: calls.append((value, kwargs)),
    )
    gui.LoretaVisualizerWindow._on_display_mode_changed(host, 0)
    assert host._group_comparison_enabled and host._display_mode == gui.DISPLAY_MODE_MRI_SLICES
    assert calls == [(payload, {"comparison_payload": True})]

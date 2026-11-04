"""Prepared comparison worker and controller checks with plain Python doubles."""

from dataclasses import replace
from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer import gui
from Tools.LORETA_Visualizer.group_comparison import build_group_comparison, comparison_candidates
from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry
from Tools.LORETA_Visualizer.source_payloads import make_source_payload


def _maps(tmp_path, *, volume=False, mask=None):
    entries, payloads = [], {}
    for group, values in (("a", [2., 4., 6.]), ("b", [3., 8., 12.])):
        path = tmp_path / f"{group}.json"
        path.write_text("{}")
        metadata = {
            "condition_group_id": group, "condition_group_label": f"Group {group.upper()}",
            "condition_group_split_applied": True, "condition_canonical_condition_id": "words",
            "condition_canonical_condition_label": "Words", "participant_count": 8 if group == "a" else 12,
            "participant_zscore_aggregation": "mean", "source_value_unit": "z-score",
            "producer_method": "eloreta_volume_mean" if volume else "l2_mne_mean",
        }
        if mask is not None:
            metadata.update(cluster_mask="source_space_cluster_permutation", cluster_mask_source_indices=mask)
        entry = PreparedSourceManifestEntry(f"{group}_words_mean", f"Group {group} words raw mean z-score", path, metadata)
        payloads[entry.condition_id] = make_source_payload(
            points=np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]), values=np.array(values),
            label="Prepared map", kind="volume_points" if volume else "surface_mesh",
            source_model="eloreta_volume" if volume else "l2_mne",
            faces=None if volume else np.array([[0, 1, 2]]), value_label="source z-score",
            metadata=metadata, normalize_values=False,
        )
        entries.append(entry)
    return tuple(entries), payloads


def _worker(request):
    events = []
    def signal(name):
        return SimpleNamespace(emit=lambda *args: events.append((name, args)))
    return SimpleNamespace(request=request, loaded=signal("loaded"), failed=signal("failed"), finished=signal("finished")), events


def test_worker_reads_both_maps_and_preserves_project_group_order(tmp_path, monkeypatch):
    entries, payloads = _maps(tmp_path)
    reads = []

    def load(path, *, display_transform):
        reads.append((path, display_transform))
        return payloads[next(entry.condition_id for entry in entries if entry.payload_path == path)]

    monkeypatch.setattr(gui, "load_prepared_source_payload_json", load)
    request = {"id": 7, "entries": entries, "display_transform": object(), "canonical_group_ids": ("b", "a"), "project_root": None}
    worker, events = _worker(request)
    gui.GroupComparisonLoadWorker.run(worker)
    assert [name for name, _args in events] == ["loaded", "finished"]
    request_id, candidates, groups, signature = events[0][1][0]
    assert request_id == 7 and groups == ("b", "a")
    assert signature == gui._comparison_file_signature(entries)
    assert len(reads) == 2 and all(transform is request["display_transform"] for _path, transform in reads)
    assert build_group_comparison(candidates, entries[0].condition_id, canonical_group_ids=groups).group_ids == ("b", "a")


@pytest.mark.parametrize("groups", [(), ("a",), ("a", "b", "c")])
def test_worker_rejects_non_two_group_projects_before_payload_reads(tmp_path, monkeypatch, groups):
    entries, _payloads = _maps(tmp_path)
    monkeypatch.setattr(gui, "load_prepared_source_payload_json", lambda *_a, **_k: pytest.fail("Unexpected read"))
    worker, events = _worker({"id": 4, "entries": entries, "canonical_group_ids": groups, "project_root": None})
    gui.GroupComparisonLoadWorker.run(worker)
    assert [name for name, _args in events] == ["failed", "finished"]
    assert events[0][1][0] == 4 and "exactly two" in events[0][1][1]


def test_worker_rejects_source_files_that_change_during_loading(tmp_path, monkeypatch):
    entries, payloads = _maps(tmp_path)

    def load(path, **_kwargs):
        path.write_text("changed while reading")
        return payloads[next(entry.condition_id for entry in entries if entry.payload_path == path)]

    monkeypatch.setattr(gui, "load_prepared_source_payload_json", load)
    worker, events = _worker({"id": 9, "entries": entries, "canonical_group_ids": ("a", "b"), "project_root": None, "display_transform": None})
    gui.GroupComparisonLoadWorker.run(worker)
    assert [name for name, _args in events] == ["failed", "finished"]
    assert "changed while loading" in events[0][1][1]


@pytest.mark.parametrize("closing, enabled, request_id", [(True, True, 4), (False, False, 4), (False, True, 3)])
def test_obsolete_comparison_results_do_not_replace_current_view(closing, enabled, request_id):
    host = SimpleNamespace(
        _closing_requested=closing, _group_comparison_enabled=enabled, _group_comparison_request_id=4,
        _group_comparison_candidates=None, _refresh_group_comparison=lambda: pytest.fail("Stale render"),
    )
    gui.LoretaVisualizerWindow._on_group_comparison_loaded(host, (request_id, object(), ("a", "b"), ()))
    assert host._group_comparison_candidates is None


def _scale_host(mode, displays, candidates=(), pair=None):
    host = SimpleNamespace(
        _comparison_display_payloads=displays, _group_comparison_enabled=True,
        _group_comparison_candidates=candidates, _group_comparison_pair=pair,
        activation_scale_combo=SimpleNamespace(currentData=lambda: mode),
        activation_min_spin=SimpleNamespace(value=lambda: 0.5), activation_max_spin=SimpleNamespace(value=lambda: 7.0),
        _manifest_condition_groups={"maps": object()}, _selected_summary_id="mean",
        _zscore_display_threshold=1.64, _use_cluster_mask=True,
    )
    host._scalar_range_for_payloads = MethodType(gui.LoretaVisualizerWindow._scalar_range_for_payloads, host)
    return host


@pytest.mark.parametrize("mode, expected", [(gui.SCALE_CURRENT, (0., 12.)), (gui.SCALE_FIXED, (0.5, 7.))])
def test_current_comparison_scale_always_uses_both_groups(tmp_path, mode, expected):
    entries, payloads = _maps(tmp_path)
    displays = tuple(payloads[entry.condition_id] for entry in entries)
    host = _scale_host(mode, displays)
    assert gui.LoretaVisualizerWindow._resolve_activation_scalar_range(host, displays[0]) == expected


def test_all_conditions_scale_uses_exact_numerical_method_and_saved_volume_masks(tmp_path):
    entries, payloads = _maps(tmp_path, volume=True, mask=[0])
    candidates = comparison_candidates(entries, payloads)
    pair = build_group_comparison(candidates, entries[0].condition_id)
    incompatible = replace(candidates[0], method_signature=("different inverse",))
    incompatible = replace(incompatible, payload=replace(incompatible.payload, values=np.array([100., 200., 300.])))
    displays = tuple(gui._activation_display_payload(payloads[entry.condition_id]) for entry in entries)
    host = _scale_host(gui.SCALE_SHARED, displays, candidates + (incompatible,), pair)
    assert gui.LoretaVisualizerWindow._resolve_activation_scalar_range(host, displays[0]) == (0., 3.)


def test_realtime_controls_update_both_renderers_and_reset_uses_primary_framing():
    calls = []
    def renderer(name):
        return SimpleNamespace(**{
            method: lambda *args, _method=method, **kwargs: calls.append((name, _method, args))
            for method in ("set_brain_opacity", "set_activation_opacity", "rotate_split_hemisphere", "set_activation_visible", "reset_camera", "copy_view_from")
        })
    primary, secondary = renderer("a"), renderer("b")
    host = SimpleNamespace(
        renderer=primary, _comparison_renderer=secondary, _display_mode=gui.DISPLAY_MODE_SPLIT_HEMISPHERE,
        _update_transparency_label=lambda _v: None, _update_activation_opacity_label=lambda _v: None,
    )
    gui.LoretaVisualizerWindow._on_transparency_changed(host, 40)
    gui.LoretaVisualizerWindow._on_activation_opacity_changed(host, 60)
    gui.LoretaVisualizerWindow._rotate_split_hemisphere(host, "left", 12.)
    gui.LoretaVisualizerWindow._set_activation_visibility_enabled(host, False)
    gui.LoretaVisualizerWindow._reset_camera(host)
    assert calls[:8] == [
        ("a", "set_brain_opacity", (.4,)), ("b", "set_brain_opacity", (.4,)),
        ("a", "set_activation_opacity", (.6,)), ("b", "set_activation_opacity", (.6,)),
        ("a", "rotate_split_hemisphere", ("left", 12.)), ("b", "rotate_split_hemisphere", ("left", 12.)),
        ("a", "set_activation_visible", (False,)), ("b", "set_activation_visible", (False,)),
    ]
    assert calls[-2:] == [("a", "reset_camera", ()), ("b", "copy_view_from", (primary,))]


def test_spin_preference_is_retained_but_paused_during_comparison():
    calls = []
    host = SimpleNamespace(renderer=SimpleNamespace(set_transparent_spin_enabled=calls.append), _group_comparison_enabled=True)
    gui.LoretaVisualizerWindow._set_transparent_spin_enabled(host, True)
    assert host._transparent_spin_enabled is True and calls == [False]


def test_missing_summary_is_not_substituted_during_comparison():
    values, state = [], {"index": 0}
    combo = SimpleNamespace(
        clear=values.clear, blockSignals=lambda _blocked: False,
        addItem=lambda label, data: values.append((label, data)),
        count=lambda: len(values), itemData=lambda index: values[index][1],
        setCurrentIndex=lambda index: state.update(index=index),
    )
    host = SimpleNamespace(
        summary_combo=combo, _group_comparison_enabled=True, _selected_condition_id="words",
        _manifest_condition_groups={"words": SimpleNamespace(entries_by_summary={"mean": object()})},
        _sync_source_map_selectors_enabled=lambda: None,
    )
    gui.LoretaVisualizerWindow._sync_summary_combo_for_selected_condition(host, preferred_summary="median")
    assert host._selected_summary_id == "median"
    assert values[state["index"]] == ("Median z-score (unavailable)", "median")


def test_comparison_disables_single_group_export_entry_point():
    gui.LoretaVisualizerWindow._open_export_figures(SimpleNamespace(_group_comparison_enabled=True))


def test_mask_toggle_remains_available_when_only_second_group_has_a_mask(tmp_path):
    entries, payloads = _maps(tmp_path, volume=True)
    first, second = (payloads[entry.condition_id] for entry in entries)
    second.metadata.update(cluster_mask="source_space_cluster_permutation", cluster_mask_source_indices=[1])
    enabled = []
    host = SimpleNamespace(
        renderer=object(), _source_activation_payload=first, _comparison_source_payloads=(first, second),
        _use_cluster_mask=True,
        cluster_mask_check=SimpleNamespace(
            blockSignals=lambda _blocked: False, setChecked=lambda _checked: None, setEnabled=enabled.append,
        ),
    )
    gui.LoretaVisualizerWindow._sync_cluster_mask_control(host)
    assert enabled == [True]

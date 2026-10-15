"""Controller checks using plain Python stubs; no GUI objects are created."""

from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.gui import (
    LoretaVisualizerWindow,
    ProjectSourceMapExportWorker,
    PROJECT_SOURCE_EXPORT_HAUK_SOURCE_PSD,
    PROJECT_SOURCE_EXPORT_ELORETA_SOURCE_PSD,
    SCALE_CURRENT,
    SCALE_FIXED,
    SCALE_SHARED,
    _activation_display_payload,
)
from Tools.LORETA_Visualizer.source_payloads import make_source_payload
from Tools.LORETA_Visualizer.source_producers.cancellation import (
    SourceBuildCancellation,
    SourceBuildCancelled,
)


def _payload(values, *, volume=False, mask=None):
    metadata = {"source_value_unit": "z-score"}
    if mask is not None:
        metadata.update(
            cluster_mask="source_space_cluster_permutation",
            cluster_mask_source_indices=mask,
        )
    return make_source_payload(
        points=np.column_stack([np.arange(len(values)), np.zeros((len(values), 2))]),
        values=np.asarray(values),
        label="test source map",
        kind="volume_points" if volume else "surface_mesh",
        faces=None if volume else np.asarray([[0, 1, 2]]),
        source_model="eloreta_volume" if volume else "l2_mne_surface",
        value_label="source-space z-score",
        metadata=metadata,
        normalize_values=False,
    )


def _controller(mode, payloads=None):
    available = payloads or {}
    scale_state = {"mode": mode}
    controller = SimpleNamespace(
        activation_scale_combo=SimpleNamespace(
            currentData=lambda: scale_state["mode"],
            blockSignals=lambda _blocked: False,
            findData=lambda value: value,
            setCurrentIndex=lambda value: scale_state.update(mode=value),
        ),
        activation_min_spin=SimpleNamespace(value=lambda: 0.5),
        activation_max_spin=SimpleNamespace(value=lambda: 7.0),
        _manifest_condition_groups={
            key: SimpleNamespace(entries_by_summary={"median": object()}) for key in available
        },
        _selected_summary_id="median",
        _use_cluster_mask=True,
        _zscore_display_threshold=1.64,
        _condition_payload_for_export=available.__getitem__,
    )
    controller._scalar_range_for_payloads = MethodType(
        LoretaVisualizerWindow._scalar_range_for_payloads, controller
    )
    return controller


def test_shared_scale_matches_preview_and_stacked_export_without_summary_fallback():
    low = _payload([2.0, 3.0, 4.0])
    high = _payload([3.0, 7.0, 9.0])
    controller = _controller(SCALE_SHARED, {"low": low, "high": high})
    # A condition lacking median must not contribute its fallback mean.
    controller._manifest_condition_groups["mean_only"] = SimpleNamespace(
        entries_by_summary={"mean": object()}
    )

    preview = LoretaVisualizerWindow._resolve_activation_scalar_range(controller, low)
    exported = LoretaVisualizerWindow._stacked_split_scalar_range(controller, (low, high))

    assert preview == exported == (0.0, 9.0)


@pytest.mark.parametrize("mode, expected", [(SCALE_CURRENT, (0.0, 4.0)), (SCALE_FIXED, (0.5, 7.0))])
def test_current_and_fixed_scales_use_selected_map_or_explicit_limits(mode, expected):
    payload = _payload([2.0, 3.0, 4.0])
    controller = _controller(mode, {"other": _payload([30.0, 50.0, 90.0])})

    assert LoretaVisualizerWindow._resolve_activation_scalar_range(controller, payload) == expected


def test_shared_volume_scale_does_not_apply_original_mask_to_filtered_points_twice():
    payload = _payload([1.0, 2.0, 8.0], volume=True, mask=[2])
    # The export payload loader returns an already filtered display payload.
    display_payload = _activation_display_payload(payload, use_cluster_mask=True)
    assert len(display_payload.points) == 1
    controller = _controller(SCALE_SHARED, {"condition": display_payload})

    assert LoretaVisualizerWindow._resolve_activation_scalar_range(controller, payload) == (0.0, 8.0)


def test_missing_shared_payload_resets_preview_to_current_map_and_records_error():
    payload = _payload([2.0, 3.0, 4.0])
    controller = _controller(SCALE_SHARED, {"missing": payload})

    def missing_payload(_condition):
        raise OSError("Payload was removed")

    controller._condition_payload_for_export = missing_payload

    assert LoretaVisualizerWindow._resolve_activation_scalar_range(controller, payload) == (0.0, 4.0)
    assert controller.activation_scale_combo.currentData() == SCALE_CURRENT
    assert "Payload was removed" in controller._scale_error


def test_shared_export_refuses_incomplete_comparison():
    payload = _payload([2.0, 3.0, 4.0])
    controller = _controller(SCALE_SHARED, {"missing": payload})

    def missing_payload(_condition):
        raise OSError("Payload was removed")

    controller._condition_payload_for_export = missing_payload

    with pytest.raises(OSError, match="Payload was removed"):
        LoretaVisualizerWindow._stacked_split_scalar_range(controller, (payload, payload))


def test_comparison_export_refuses_a_different_summary_instead_of_falling_back():
    controller = SimpleNamespace(
        renderer=SimpleNamespace(mesh_display_transform=lambda: object()),
        _selected_summary_id="median",
        _manifest_condition_groups={
            "mean_only": SimpleNamespace(entries_by_summary={"mean": object()})
        },
    )
    with pytest.raises(RuntimeError, match="no source map for the selected summary"):
        LoretaVisualizerWindow._condition_payload_for_export(controller, "mean_only")


def _worker(exporter, cancellation=None):
    events = []
    def signal(name):
        return SimpleNamespace(emit=lambda *args: events.append((name, args)))

    worker = SimpleNamespace(
        _export_modes=(PROJECT_SOURCE_EXPORT_HAUK_SOURCE_PSD, PROJECT_SOURCE_EXPORT_ELORETA_SOURCE_PSD),
        cancellation=cancellation or SourceBuildCancellation(),
        _run_export_mode=exporter,
        progress=signal("progress"),
        exported=signal("exported"),
        failed=signal("failed"),
        cancelled=signal("cancelled"),
        finished=signal("finished"),
    )
    return worker, events


def test_cancelled_worker_preserves_successful_first_method_and_finishes():
    completed = object()

    def exporter(mode):
        if mode == PROJECT_SOURCE_EXPORT_HAUK_SOURCE_PSD:
            return completed
        raise SourceBuildCancelled()

    worker, events = _worker(exporter)
    ProjectSourceMapExportWorker.run(worker)

    assert [name for name, _ in events] == ["progress", "progress", "exported", "cancelled", "finished"]
    result = next(args[0] for name, args in events if name == "exported")
    assert result.results == (completed,)
    assert result.failures == ()


def test_worker_cancelled_before_start_never_runs_exporter():
    token = SourceBuildCancellation()
    token.request()

    def unexpected_exporter(_mode):
        raise AssertionError("Cancelled work must not start.")

    worker, events = _worker(unexpected_exporter, cancellation=token)
    ProjectSourceMapExportWorker.run(worker)

    assert [name for name, _ in events] == ["cancelled", "finished"]

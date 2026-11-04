"""Preview worker orchestration with plain Python stubs and synthetic payloads."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer import gui
from Tools.LORETA_Visualizer.source_payloads import make_source_payload


def _payload(values, mask):
    return make_source_payload(
        points=np.column_stack([np.arange(len(values)), np.zeros((len(values), 2))]),
        values=np.asarray(values, dtype=float),
        label="Synthetic source map",
        kind="volume_points",
        source_model="eloreta_volume",
        value_label="source-space z-score",
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_source_indices": mask,
        },
        normalize_values=False,
    )


def _request():
    original = _payload([1.0, 2.0, 8.0], [2])
    return {
        "id": 17,
        "reference_paths": (Path("condition_a.json"), Path("condition_b.json")),
        "use_cluster_mask": True,
        "render_kwargs": {
            "payload": gui._activation_display_payload(original),
            "inspection_payload": original,
            "display_transform": object(),
            "fsaverage_dir": Path("synthetic-anatomy"),
            "anatomy": None,
            "slice_indices": None,
            "scalar_range": (0.0, 8.0),
        },
    }


def _run(request):
    events = []

    def signal(name):
        return SimpleNamespace(emit=lambda *args: events.append((name, args)))

    worker = SimpleNamespace(
        request=request, rendered=signal("rendered"), failed=signal("failed"), finished=signal("finished")
    )
    gui.MriSliceRenderWorker.run(worker)
    return events


def test_worker_builds_all_condition_reference_with_one_mask_application(monkeypatch):
    request = _request()
    source_a = request["render_kwargs"]["inspection_payload"]
    source_b = _payload([3.0, 5.0, 9.0], [1])
    sources = dict(zip(request["reference_paths"], (source_a, source_b)))
    anatomy, result = object(), object()
    seen, filtered = {}, []
    real_display_filter = gui._activation_display_payload

    def filter_once(payload, **kwargs):
        filtered.append(payload)
        return real_display_filter(payload, **kwargs)

    def load_payload(path, **kwargs):
        assert kwargs["display_transform"] is request["render_kwargs"]["display_transform"]
        return sources[path]

    def choose_indices(payload, **kwargs):
        seen["reference"] = payload
        assert kwargs["anatomy"] is anatomy
        return (4, 5, 6)

    def render(**kwargs):
        seen["render"] = kwargs
        return result

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", lambda _path: anatomy)
    monkeypatch.setattr(gui, "load_prepared_source_payload_json", load_payload)
    monkeypatch.setattr(gui, "_activation_display_payload", filter_once)
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", choose_indices)
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", render)

    events = _run(request)

    assert len(filtered) == 2 and filtered[0] is source_a and filtered[1] is source_b
    assert seen["reference"].values.tolist() == [8.0, 5.0]
    assert seen["reference"].points[:, 0].tolist() == [2.0, 1.0]
    assert seen["render"]["payload"] is request["render_kwargs"]["payload"]
    assert seen["render"]["inspection_payload"] is source_a
    assert source_a.values.tolist() == [1.0, 2.0, 8.0]
    assert seen["render"]["slice_indices"] == (4, 5, 6)
    assert request["render_kwargs"]["slice_indices"] is None
    assert request["render_kwargs"]["anatomy"] is None
    assert [name for name, _ in events] == ["rendered", "finished"]
    assert events[0][1][0] == (request, result, anatomy)


def test_worker_honors_cached_anatomy_and_manual_slice_indices(monkeypatch):
    request = _request()
    anatomy, result = object(), object()
    request["render_kwargs"].update(anatomy=anatomy, slice_indices=(7, 8, 9))
    seen = {}

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Saved navigation must not reload anatomy or recompute the reference.")

    def render(**kwargs):
        seen.update(kwargs)
        return result

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", unexpected)
    monkeypatch.setattr(gui, "load_prepared_source_payload_json", unexpected)
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", unexpected)
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", render)

    events = _run(request)

    assert seen["slice_indices"] == (7, 8, 9)
    assert seen["anatomy"] is anatomy
    assert seen["inspection_payload"] is request["render_kwargs"]["inspection_payload"]
    assert [name for name, _ in events] == ["rendered", "finished"]


@pytest.mark.parametrize("stage", ["anatomy", "reference", "render"])
def test_worker_emits_finished_after_failure_at_each_stage(monkeypatch, stage):
    request = _request()

    def failure(*_args, **_kwargs):
        raise OSError(f"Synthetic {stage} failure")

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", lambda _path: object())
    monkeypatch.setattr(
        gui, "load_prepared_source_payload_json", lambda *_args, **_kwargs: request["render_kwargs"]["inspection_payload"]
    )
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", lambda *_args, **_kwargs: (1, 2, 3))
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", lambda **_kwargs: object())
    monkeypatch.setattr(gui, {
        "anatomy": "load_fsaverage_mri_volume",
        "reference": "load_prepared_source_payload_json",
        "render": "render_mri_orthogonal_slice_image",
    }[stage], failure)

    events = _run(request)

    assert events == [("failed", (17, f"Synthetic {stage} failure")), ("finished", ())]


def test_obsolete_preview_reuses_matching_anatomy_without_applying_image(tmp_path):
    anatomy = object()
    applied = []
    window = SimpleNamespace(
        _closing_requested=False, _mri_render_request_id=2, _fsaverage_dir=tmp_path,
        _mri_anatomy_cache=None, _mri_anatomy_cache_dir=None,
        _mri_slice_indices_cache=(8, 9, 10), _mri_slice_indices_cache_key=("new",),
        _display_mode=gui.DISPLAY_MODE_MRI_SLICES,
        mri_slice_view=SimpleNamespace(set_render_result=applied.append),
    )
    request = {"id": 1, "reference_key": ("old",), "render_kwargs": {"fsaverage_dir": tmp_path}}
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (request, SimpleNamespace(peak_voxel=(1, 2, 3)), anatomy))

    assert window._mri_anatomy_cache is anatomy
    assert window._mri_anatomy_cache_dir == tmp_path
    assert window._mri_slice_indices_cache == (8, 9, 10)
    assert window._mri_slice_indices_cache_key == ("new",)
    assert applied == []


@pytest.mark.parametrize("closed,matches", [(True, True), (False, False)])
def test_preview_does_not_cache_or_show_closed_or_other_anatomy(tmp_path, closed, matches):
    original = object()
    applied = []
    window = SimpleNamespace(
        _closing_requested=closed, _mri_render_request_id=2, _fsaverage_dir=tmp_path,
        _mri_anatomy_cache=original, _mri_anatomy_cache_dir=tmp_path,
        _display_mode=gui.DISPLAY_MODE_MRI_SLICES,
        mri_slice_view=SimpleNamespace(set_render_result=applied.append),
    )
    request = {
        "id": 2, "reference_key": ("old",),
        "render_kwargs": {"fsaverage_dir": tmp_path if matches else tmp_path / "other"},
    }
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (request, SimpleNamespace(peak_voxel=(1, 2, 3)), object()))

    assert window._mri_anatomy_cache is original
    assert applied == []


@pytest.mark.parametrize("width,height,dpr", [(900, 600, 1.0), (900, 600, 2.0), (300, 180, 1.0)])
def test_preview_pixels_follow_viewport_and_device_scale(width, height, dpr):
    view = SimpleNamespace(
        contentsRect=lambda: SimpleNamespace(size=lambda: SimpleNamespace(width=lambda: width, height=lambda: height)),
        devicePixelRatioF=lambda: dpr,
    )
    figsize, dpi = gui.LoretaVisualizerWindow._mri_slice_preview_figure_settings(SimpleNamespace(mri_slice_view=view))
    assert np.asarray(figsize) * dpi == pytest.approx([width * dpr, height * dpr])
    assert dpi == round(100 * dpr)


def test_preview_pixel_budget_preserves_viewport_aspect_ratio():
    view = SimpleNamespace(
        contentsRect=lambda: SimpleNamespace(size=lambda: SimpleNamespace(width=lambda: 2400, height=lambda: 1800)),
        devicePixelRatioF=lambda: 3.0,
    )
    figsize, dpi = gui.LoretaVisualizerWindow._mri_slice_preview_figure_settings(SimpleNamespace(mri_slice_view=view))
    width, height = np.asarray(figsize) * dpi
    assert width <= 2400 and height <= 1600
    assert width / height == pytest.approx(4 / 3, abs=0.001)


@pytest.mark.parametrize("cache_matches", [True, False])
def test_queued_preview_dispatch_uses_latest_matching_anatomy(monkeypatch, tmp_path, cache_matches):
    anatomy, workers = object(), []
    request = {"id": 2, "render_kwargs": {"fsaverage_dir": tmp_path, "anatomy": None}}
    def signal():
        return SimpleNamespace(connect=lambda _slot: None)
    def worker_factory(render_request):
        workers.append(render_request)
        return SimpleNamespace(
            moveToThread=lambda _thread: None, run=lambda: None, deleteLater=lambda: None,
            rendered=signal(), failed=signal(), finished=signal(),
        )
    monkeypatch.setattr(gui, "QThread", lambda _parent: SimpleNamespace(
        started=signal(), finished=signal(), quit=lambda: None, deleteLater=lambda: None, start=lambda: None,
    ))
    monkeypatch.setattr(gui, "MriSliceRenderWorker", worker_factory)
    window = SimpleNamespace(
        _mri_render_thread=None, _mri_render_pending=request, _closing_requested=False,
        _mri_anatomy_cache=anatomy, _mri_anatomy_cache_dir=tmp_path if cache_matches else tmp_path / "other",
        _fsaverage_dir=tmp_path, _on_mri_slice_rendered=lambda _result: None,
        _on_mri_slice_render_failed=lambda *_args: None, _mri_slice_render_finished=lambda: None,
        export_figures_btn=SimpleNamespace(setEnabled=lambda _enabled: None),
    )
    gui.LoretaVisualizerWindow._start_pending_mri_render(window)

    assert workers[0]["render_kwargs"]["anatomy"] is (anatomy if cache_matches else None)
    assert request["render_kwargs"]["anatomy"] is None
    assert window._mri_render_pending is None


@pytest.mark.parametrize("state", ["available", "missing", "unreadable"])
def test_mesh_load_checks_native_mri_availability_without_loading_or_resampling(monkeypatch, tmp_path, state):
    result, events = SimpleNamespace(fsaverage_dir=tmp_path), []
    monkeypatch.setattr(gui, "load_fsaverage_brain_mesh", lambda **_kwargs: result)
    def find_anatomy(_root):
        if state == "unreadable":
            raise PermissionError("Synthetic access failure")
        return None if state == "missing" else tmp_path / "T1.mgz"
    monkeypatch.setattr(gui, "find_fsaverage_mri_path", find_anatomy)
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Native MRI loading belongs to the preview worker.")
    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", unexpected)
    def signal(name):
        return SimpleNamespace(emit=lambda *args: events.append((name, args)))
    worker = SimpleNamespace(
        _allow_fetch=False, loaded=signal("loaded"), failed=signal("failed"),
        mri_template_failed=signal("mri_unavailable"), finished=signal("finished"),
    )
    worker._mri_anatomy_availability_error = lambda root: gui.FsaverageLoadWorker._mri_anatomy_availability_error(worker, root)
    gui.FsaverageLoadWorker.run(worker)

    assert [event for event, _args in events] == (["mri_unavailable"] if state != "available" else []) + ["loaded", "finished"]
    assert events[-2] == ("loaded", (result,))
    if state == "missing":
        assert "MRI anatomy is missing" in events[0][1][0]
    elif state == "unreadable":
        assert "Unable to access fsaverage MRI anatomy" in events[0][1][0]


@pytest.mark.parametrize("inactive", [None, "hidden", "other_mode", "closing", "no_payload", "no_scale"])
def test_resize_requests_only_visible_current_mri_with_existing_scale(inactive):
    calls, timers = [], []
    old_settings, new_settings = ((9.0, 6.0), 100), ((12.0, 6.0), 100)
    window = SimpleNamespace(
        _closing_requested=inactive == "closing",
        _display_mode="other" if inactive == "other_mode" else gui.DISPLAY_MODE_MRI_SLICES,
        mri_slice_view=SimpleNamespace(isVisible=lambda: inactive != "hidden"),
        _current_activation_payload=None if inactive == "no_payload" else object(),
        _mri_preview_scalar_range=None if inactive == "no_scale" else (1.0, 7.0),
        _mri_preview_requested_settings=old_settings,
        _mri_slice_preview_figure_settings=lambda: new_settings,
        _mri_preview_resize_timer=SimpleNamespace(start=lambda: timers.append(True)),
        _render_mri_slice_payload=lambda payload, **kwargs: calls.append((payload, kwargs)),
    )
    window._mri_preview_resize_is_active = lambda: gui.LoretaVisualizerWindow._mri_preview_resize_is_active(window)
    gui.LoretaVisualizerWindow._schedule_mri_preview_resize(window)
    gui.LoretaVisualizerWindow._render_mri_preview_after_resize(window)

    if inactive is None:
        assert timers == [True]
        assert calls == [(window._current_activation_payload, {"scalar_range": (1.0, 7.0)})]
        calls.clear()
        window._mri_preview_requested_settings = new_settings
        gui.LoretaVisualizerWindow._render_mri_preview_after_resize(window)
        assert calls == []
    else:
        assert timers == []
        assert calls == []


def _drag_controller(tmp_path):
    payload = _payload([1.0, 2.0, 8.0], [2])
    applied, reference_reads, size_reads, dispatches = [], [], [], []
    window = SimpleNamespace(
        renderer=SimpleNamespace(mesh_display_transform=lambda: object()),
        mri_slice_view=SimpleNamespace(
            set_render_result=lambda result, **kwargs: applied.append((result, kwargs)),
            clear_slice_image=lambda _message: None,
        ),
        _closing_requested=False, _display_mode=gui.DISPLAY_MODE_MRI_SLICES,
        _fsaverage_dir=tmp_path, _mri_anatomy_error=None,
        _mri_anatomy_cache=object(), _mri_anatomy_cache_dir=tmp_path,
        _mri_render_request_id=0, _mri_render_context_id=0,
        _mri_render_context_payload=None, _mri_render_reference_key=None,
        _mri_render_last_applied_id=0, _mri_drag_active=False,
        _mri_render_pending=None, _mri_preview_requested_settings=None,
        _mri_preview_scalar_range=None, _mri_slice_indices_cache=(4, 5, 6),
        _mri_slice_indices_cache_key=("reference",), _manifest_condition_groups={},
        _selected_summary_id="mean", _use_cluster_mask=True, _activation_visible=True,
        _source_activation_payload=payload, _current_activation_payload=payload,
        _selected_condition_label=lambda: "Synthetic condition",
    )

    def reference_key():
        reference_reads.append(True)
        return ("reference",)

    def settings():
        size_reads.append(True)
        return (9.0, 6.0), 100

    window._mri_slice_reference_cache_key = reference_key
    window._mri_slice_preview_figure_settings = settings
    window.mri_slice_view.cancel_drag = lambda: gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, False)
    window._start_pending_mri_render = lambda: dispatches.append(window._mri_render_pending)
    window._render_mri_slice_payload = lambda payload, **kwargs: gui.LoretaVisualizerWindow._render_mri_slice_payload(
        window, payload, **kwargs,
    )
    return window, applied, reference_reads, size_reads, dispatches


def test_drag_navigation_reuses_reference_scale_and_size_and_coalesces_latest(tmp_path):
    window, _applied, references, sizes, dispatches = _drag_controller(tmp_path)
    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(1.0, 8.0))
    first = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    for index in range(20):
        gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (index, 8, 9))

    assert references == [True]
    assert sizes == [True]
    assert window._mri_render_pending["id"] == 21
    assert window._mri_render_pending["context_id"] == first["context_id"]
    assert window._mri_render_pending["navigation"] is True
    assert window._mri_render_pending["render_kwargs"]["scalar_range"] == (1.0, 8.0)
    assert window._mri_render_pending["render_kwargs"]["slice_indices"] == (19, 8, 9)
    assert window._mri_render_pending["render_kwargs"]["preview_cache"] is first["render_kwargs"]["preview_cache"]
    assert dispatches[-1] is window._mri_render_pending
    # Ending/cancelling a gesture never queues work for a newly hidden view.
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, False)
    assert len(dispatches) == 21
    assert not window._mri_drag_active


def test_new_view_context_cancels_drag_and_replaces_worker_cache(tmp_path):
    window, _applied, _references, _sizes, _dispatches = _drag_controller(tmp_path)
    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(1.0, 8.0))
    original = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    running = window._mri_render_pending

    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(0.0, 4.0))

    assert not window._mri_drag_active
    assert window._mri_render_pending["context_id"] != original["context_id"]
    assert window._mri_preview_cache is not running["render_kwargs"]["preview_cache"]
    # The in-flight request retains its own cache until the worker finishes.
    assert running["render_kwargs"]["preview_cache"] is original["render_kwargs"]["preview_cache"]


def test_drag_start_rejects_preceding_navigation_before_accepting_new_gesture(tmp_path):
    window, applied, _references, _sizes, _dispatches = _drag_controller(tmp_path)
    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(1.0, 8.0))
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    before_gesture = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(
        window, (before_gesture, SimpleNamespace(peak_voxel=(7, 8, 9)), object()),
    )
    assert applied == []
    # Press requests its captured plane even when the pointer did not move.
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    gesture_request = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, False)
    final_result = SimpleNamespace(peak_voxel=(7, 8, 9))
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (gesture_request, final_result, object()))
    assert applied == [(final_result, {})]


def test_drag_applies_completed_same_context_frames_without_reverting_pointer(tmp_path):
    window, applied, _references, _sizes, _dispatches = _drag_controller(tmp_path)
    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(1.0, 8.0))
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    running = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (10, 11, 12))
    latest = window._mri_render_pending
    result = SimpleNamespace(peak_voxel=(7, 8, 9))
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (running, result, object()))

    assert applied == [(result, {"preserve_cursor": True})]
    assert window._mri_slice_indices_cache == (10, 11, 12)
    assert window._mri_render_pending is latest
    # Duplicate/older completion cannot make the preview run backwards.
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (running, result, object()))
    assert len(applied) == 1

    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, False)
    final_result = SimpleNamespace(peak_voxel=(10, 11, 12))
    gui.LoretaVisualizerWindow._on_mri_slice_rendered(window, (latest, final_result, object()))
    assert applied[-1] == (final_result, {})
    assert window._mri_slice_indices_cache == (10, 11, 12)


@pytest.mark.parametrize("changed", ["context", "payload", "mode", "closing", "stopped", "non_navigation"])
def test_drag_never_applies_frames_from_obsolete_view_context(tmp_path, changed):
    window, applied, _references, _sizes, _dispatches = _drag_controller(tmp_path)
    window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(1.0, 8.0))
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    running = window._mri_render_pending
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (10, 11, 12))
    if changed == "context":
        # Same payload but a changed scale/layout/mask is a new render context.
        window._render_mri_slice_payload(window._current_activation_payload, scalar_range=(0.0, 4.0))
    elif changed == "payload":
        window._current_activation_payload = _payload([1.0, 5.0, 9.0], [2])
    elif changed == "mode":
        window._display_mode = gui.DISPLAY_MODE_TRANSPARENT_MESH
    elif changed == "closing":
        window._closing_requested = True
    elif changed == "stopped":
        window._mri_drag_active = False
    else:
        running["navigation"] = False

    gui.LoretaVisualizerWindow._on_mri_slice_rendered(
        window, (running, SimpleNamespace(peak_voxel=(7, 8, 9)), object()),
    )
    assert applied == []
    assert window._mri_slice_indices_cache == (10, 11, 12)


@pytest.mark.parametrize("closed,mode", [(True, gui.DISPLAY_MODE_MRI_SLICES), (False, gui.DISPLAY_MODE_TRANSPARENT_MESH)])
def test_hidden_or_closing_mri_rejects_late_navigation_and_drag_start(tmp_path, closed, mode):
    window, _applied, references, _sizes, dispatches = _drag_controller(tmp_path)
    window._closing_requested, window._display_mode = closed, mode
    gui.LoretaVisualizerWindow._on_mri_drag_active_changed(window, True)
    gui.LoretaVisualizerWindow._on_mri_slice_indices_requested(window, (7, 8, 9))
    assert not window._mri_drag_active
    assert references == []
    assert dispatches == []

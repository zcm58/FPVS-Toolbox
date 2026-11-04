"""MRI drag mapping and pending-frame behavior without a visible widget."""

from dataclasses import replace
from types import MethodType, SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRectF

from Tools.LORETA_Visualizer.slice_viewer import MriSliceImageLabel
from Tools.LORETA_Visualizer.volume_slices import MriSliceHitRegion, MriSliceRenderResult


def _state(*, fixed_axis=2):
    moving_axes = [axis for axis in range(3) if axis != fixed_axis]
    transform = np.zeros((3, 3))
    transform[moving_axes[0], 0] = 1
    transform[moving_axes[1], 1] = -1
    transform[moving_axes[1], 2] = 10
    transform[fixed_axis, 2] = 5
    region = MriSliceHitRegion(
        plane=("sagittal", "coronal", "axial")[fixed_axis],
        image_bounds=(0., 0., 100., 100.), panel_shape=(11, 11),
        pixel_to_voxel=transform, fixed_voxel_axis=fixed_axis,
    )
    result = MriSliceRenderResult(
        image_rgb=np.zeros((100, 300, 3), dtype=np.uint8), peak_voxel=(5, 5, 5),
        scalar_range=(0., 3.), source_point_count=1, rendered_point_count=1,
        hit_regions=(region,), anatomy_shape=(11, 11, 11),
        nearest_source_value=2., nearest_source_distance_mm=0., value_label="z-score",
    )
    requests, phases = [], []
    state = SimpleNamespace(
        _result=result, _cursor_voxel=(5, 5, 5), _drag_region=region,
        _drag_image_rect=QRectF(10., 20., 600., 200.), _drag_image_shape=(100, 300),
        slice_indices_requested=SimpleNamespace(emit=requests.append),
        drag_active_changed=SimpleNamespace(emit=phases.append),
        requests=requests, phases=phases, tooltip="initial", repaints=0,
    )
    state.setToolTip = lambda text: setattr(state, "tooltip", text)
    state.update = lambda: setattr(state, "repaints", state.repaints + 1)
    state._set_slice_pixmap = lambda _image: None
    for name in ("_request_voxel", "_request_drag_position", "cancel_drag", "set_render_result"):
        setattr(state, name, MethodType(getattr(MriSliceImageLabel, name), state))
    return state


@pytest.mark.parametrize("fixed_axis", (0, 1, 2))
def test_drag_follows_prepared_axis_mapping_and_never_changes_fixed_slice(fixed_axis):
    state = _state(fixed_axis=fixed_axis)
    state._request_drag_position(QPointF(160., 70.))  # Image pixel (75, 25).
    expected = [8, 8, 8]
    expected[fixed_axis] = 5
    assert state.requests == [tuple(expected)]
    assert state._cursor_voxel == tuple(expected)
    assert state.tooltip == ""
    assert state.repaints == 1
    assert np.all(state._result.image_rgb == 0)


def test_drag_clips_to_origin_panel_when_pointer_crosses_another_panel_or_leaves_widget():
    state = _state()
    state._request_drag_position(QPointF(610., -500.))
    assert state.requests == [(10, 10, 5)]
    state._request_drag_position(QPointF(-500., 1000.))
    assert state.requests[-1] == (0, 0, 5)


def test_duplicate_voxel_movements_do_not_queue_or_repaint_again():
    state = _state()
    state._request_drag_position(QPointF(160., 70.))
    state._request_drag_position(QPointF(160.1, 70.1))
    assert state.requests == [(8, 8, 5)]
    assert state.repaints == 1


def test_gesture_start_can_request_current_voxel_after_older_frames_are_invalidated():
    state = _state()
    state._request_voxel(np.asarray((5, 5, 5)), force=True)
    state._request_voxel(np.asarray((5, 5, 5)))
    assert state.requests == [(5, 5, 5)]


def test_intermediate_frame_retains_latest_pointer_and_hides_stale_readout():
    state = _state()
    state._request_drag_position(QPointF(160., 70.))
    original_region = state._drag_region
    old_frame = replace(state._result, peak_voxel=(6, 6, 5))
    state.set_render_result(old_frame)
    assert state._cursor_voxel == (8, 8, 5)
    assert state._result is old_frame
    assert state._drag_region is original_region
    assert state.tooltip == ""


def test_lower_resolution_frame_does_not_change_gesture_coordinate_mapping():
    state = _state()
    old_frame = state._result
    region = replace(old_frame.hit_regions[0], image_bounds=(0., 0., 50., 50.))
    preview = replace(old_frame, image_rgb=np.zeros((50, 150, 3), dtype=np.uint8), hit_regions=(region,))
    state.set_render_result(preview)
    state._request_drag_position(QPointF(160., 70.))
    assert state.requests == [(8, 8, 5)]


def test_pending_frame_after_release_can_preserve_pointer_until_final_frame():
    state = _state()
    original = state._result
    state._request_drag_position(QPointF(160., 70.))
    state.cancel_drag()
    state.set_render_result(original, preserve_cursor=True)
    assert state._cursor_voxel == (8, 8, 5)
    assert state.tooltip == ""
    state.set_render_result(replace(original, peak_voxel=(8, 8, 5)))
    assert "Nearest original grid value: 2 z-score" in state.tooltip
    assert "Click or drag" in state.tooltip


def test_changed_anatomy_cancels_drag_even_if_cursor_preservation_requested():
    state = _state()
    state.set_render_result(replace(state._result, anatomy_shape=(20, 20, 20), peak_voxel=(7, 7, 7)), preserve_cursor=True)
    assert state._cursor_voxel == (7, 7, 7)
    assert state._drag_region is None
    assert state.phases == [False]


def test_cancel_drag_is_idempotent_and_clears_all_gesture_geometry():
    state = _state()
    state.cancel_drag()
    state.cancel_drag()
    state._request_drag_position(QPointF(160., 70.))
    assert state.phases == [False]
    assert state.requests == []
    assert state._drag_region is None
    assert state._drag_image_rect is None
    assert state._drag_image_shape is None

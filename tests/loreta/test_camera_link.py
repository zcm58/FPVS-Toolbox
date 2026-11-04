"""Linked-camera behavior with native cameras and plain scheduler stubs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from vtkmodules.vtkRenderingCore import vtkCamera

from Tools.LORETA_Visualizer import camera_link
from Tools.LORETA_Visualizer.renderer import BrainRendererWidget
from Tools.LORETA_Visualizer import renderer as rendering


class _Signal:
    def connect(self, callback):
        self.callback = callback

    def disconnect(self, callback):
        assert self.callback == callback
        self.callback = None


class _Timer:
    def __init__(self, parent):
        self.parent = parent
        self.timeout = _Signal()
        self.active = False
        self.starts = 0
        self.deleted = False

    def setSingleShot(self, value):  # noqa: N802
        assert value is True

    def isActive(self):  # noqa: N802
        return self.active

    def start(self, interval):
        assert interval == 0
        self.active = True
        self.starts += 1

    def stop(self):
        self.active = False

    def deleteLater(self):  # noqa: N802
        self.deleted = True

    def fire(self):
        assert self.active
        self.active = False
        self.timeout.callback()


class _Plotter:
    def __init__(self):
        self.camera = vtkCamera()
        self.camera_set = False
        self.renders = 0
        self.closed = False
        self.modify_on_render = False
        self.window_size = (800, 800)
        self.resets = 0

    def render(self):
        assert not self.closed
        self.renders += 1
        if self.modify_on_render:
            self.camera.Modified()

    def close(self):
        self.closed = True

    def reset_camera(self, **_kwargs):
        self.resets += 1

    def reset_camera_clipping_range(self):
        pass


@pytest.fixture(autouse=True)
def fake_scheduler(monkeypatch):
    monkeypatch.setattr(camera_link, "QTimer", _Timer)


def _owner():
    result = SimpleNamespace(_plotter=_Plotter(), _camera_link=None, pauses=0)

    def pause():
        result.pauses += 1

    result._pause_transparent_spin_for_interaction = pause
    return result


def _renderer():
    result = BrainRendererWidget.__new__(BrainRendererWidget)
    result._plotter = _Plotter()
    result._camera_link = None
    result._split_left_rotation_degrees = 0.0
    result._split_right_rotation_degrees = 0.0
    result._split_hemisphere_active = False
    return result


def _state(camera):
    return (
        camera.GetPosition(),
        camera.GetFocalPoint(),
        camera.GetViewUp(),
        camera.GetParallelProjection(),
        camera.GetParallelScale(),
        camera.GetViewAngle(),
        camera.GetClippingRange(),
        camera.GetWindowCenter(),
    )


def test_camera_changes_copy_every_view_property_bidirectionally_and_coalesce():
    first, second = _owner(), _owner()
    camera = first._plotter.camera
    camera.SetPosition(3, -7, 9)
    camera.SetFocalPoint(1, 2, 3)
    camera.SetViewUp(0, 0, 1)
    camera.SetParallelProjection(True)
    camera.SetParallelScale(2.7)
    camera.SetViewAngle(42)
    camera.SetClippingRange(0.5, 120)
    camera.SetWindowCenter(0.1, -0.2)
    link = camera_link.LinkedBrainCameras(first, second)
    assert _state(second._plotter.camera) == _state(camera)
    assert second._plotter.camera_set
    for angle in range(30):
        camera.Azimuth(angle)
    assert link._timer.starts == 1
    assert second._plotter.renders == 0
    link._timer.fire()
    assert second._plotter.renders == 1
    assert first._plotter.renders == 0
    assert not link._timer.active
    assert _state(second._plotter.camera) == _state(camera)

    second._plotter.camera.Zoom(1.5)
    second._plotter.camera.Elevation(17)
    assert _state(camera) == _state(second._plotter.camera)
    assert link._timer.starts == 2
    link._timer.fire()
    assert first._plotter.renders == 1
    assert second._plotter.renders == 1
    link.close()


def test_render_internal_camera_modifications_cannot_create_a_redraw_loop():
    first, second = _owner(), _owner()
    first._plotter.modify_on_render = True
    second._plotter.modify_on_render = True
    link = camera_link.LinkedBrainCameras(first, second)
    link._timer.fire()
    assert second._plotter.renders == 1
    assert first._plotter.renders == 0
    assert link._pending == set()
    assert not link._timer.active
    first._plotter.camera.Modified()
    second._plotter.camera.Modified()
    link._timer.fire()
    assert second._plotter.renders == 2
    assert first._plotter.renders == 1
    assert not link._timer.active
    link.close()


def test_native_camera_copy_invalidates_cached_projection_in_both_directions():
    first, second = _owner(), _owner()
    link = camera_link.LinkedBrainCameras(first, second)
    link._timer.fire()
    before = second._plotter.camera.GetMTime()
    first._plotter.camera.SetPosition(3, -4, 5)
    assert second._plotter.camera.GetMTime() > before
    assert second._plotter.camera.GetPosition() == (3.0, -4.0, 5.0)
    before = first._plotter.camera.GetMTime()
    second._plotter.camera.SetParallelScale(4.2)
    assert first._plotter.camera.GetMTime() > before
    assert first._plotter.camera.GetParallelScale() == 4.2
    link.close()


def test_close_removes_both_observers_pending_work_and_owner_references():
    first, second = _owner(), _owner()
    link = camera_link.LinkedBrainCameras(first, second)
    first._camera_link = second._camera_link = link
    assert first._plotter.camera.HasObserver("ModifiedEvent")
    assert second._plotter.camera.HasObserver("ModifiedEvent")
    timer = link._timer
    link.close()
    link.close()
    assert not first._plotter.camera.HasObserver("ModifiedEvent")
    assert not second._plotter.camera.HasObserver("ModifiedEvent")
    assert first._camera_link is None
    assert second._camera_link is None
    assert not timer.active
    assert timer.deleted
    assert timer.timeout.callback is None
    assert link._owners == ()
    assert link._cameras == ()
    first._plotter.camera.Zoom(2)
    link._render_pending()
    assert first._plotter.renders == second._plotter.renders == 0


def test_interaction_pauses_either_owner_spin():
    first, second = _owner(), _owner()
    link = camera_link.LinkedBrainCameras(first, second)
    link.pause_spin_for_interaction()
    assert first.pauses == second.pauses == 1
    link.close()
    link.pause_spin_for_interaction()
    assert first.pauses == second.pauses == 1


def test_link_reuse_replacement_and_renderer_shutdown_release_peer():
    first, second, third = _renderer(), _renderer(), _renderer()
    first.link_camera(second)
    link = first._camera_link
    assert second._camera_link is link
    second.link_camera(first)
    assert first._camera_link is link
    first.link_camera(third)
    assert link._closed
    assert second._camera_link is None
    assert not second._plotter.camera.HasObserver("ModifiedEvent")
    assert first._camera_link is third._camera_link
    plotter = first._plotter
    final_link = first._camera_link
    first.shutdown()
    assert final_link._closed
    assert third._camera_link is None
    assert not third._plotter.camera.HasObserver("ModifiedEvent")
    assert plotter.closed
    assert first._plotter is None
    third._plotter.camera.Azimuth(15)
    assert not final_link._timer.active


def test_copy_view_matches_camera_and_split_rotations_without_changing_payload(monkeypatch):
    first, second = _renderer(), _renderer()
    first._split_left_rotation_degrees = 36
    first._split_right_rotation_degrees = -12
    first._plotter.camera.SetPosition(2, -3, 4)
    first._plotter.camera.SetParallelScale(1.5)
    second._split_hemisphere_active = True
    second._last_activation_payload = object()
    payload = second._last_activation_payload
    geometry_calls = []
    monkeypatch.setattr(second, "_render_split_hemispheres", lambda **kw: geometry_calls.append(kw))
    before = second._plotter.camera.GetMTime()
    second.copy_view_from(first)
    assert second._plotter.camera.GetMTime() > before
    assert _state(first._plotter.camera) == _state(second._plotter.camera)
    assert second._split_left_rotation_degrees == 36
    assert second._split_right_rotation_degrees == -12
    assert geometry_calls == [{"render": False}]
    assert second._plotter.renders == 1
    assert second._plotter.camera_set
    assert second._last_activation_payload is payload


def test_camera_api_ignores_self_and_closed_peers():
    first, second = _renderer(), _renderer()
    first.link_camera(first)
    first.copy_view_from(first)
    assert first._camera_link is None
    assert first._plotter.renders == 0
    second._plotter = None
    first.link_camera(second)
    first.copy_view_from(second)
    first.unlink_camera()
    assert first._camera_link is None
    assert first._plotter.renders == 0


def test_anatomy_getter_preserves_shared_mesh_identity():
    renderer = _renderer()
    mesh = object()
    renderer._current_mesh = mesh
    assert renderer.current_brain_mesh() is mesh


def test_publication_reset_keeps_both_hemispheres_inside_a_narrow_viewport():
    renderer = _renderer()
    renderer._plotter.window_size = (400, 800)
    renderer._set_publication_camera()
    camera = renderer._plotter.camera
    half_horizontal_span = camera.GetParallelScale() * 0.5
    required_half_span = (
        abs(rendering._LEFT_HEMISPHERE_OFFSET[0]) + rendering._PUBLICATION_HEMISPHERE_RADIUS
    )
    assert half_horizontal_span >= required_half_span * 1.08 - 1e-12
    assert camera.GetPosition() == (0.0, -8.0, 0.25)
    assert camera.GetParallelProjection()
    assert renderer._viewport_aspect == 0.5


@pytest.mark.parametrize("parallel", [True, False])
def test_resize_round_trip_preserves_orbit_and_user_zoom(parallel):
    renderer = _renderer()
    renderer._split_hemisphere_active = parallel
    renderer._viewport_aspect = 1.0
    camera = renderer._plotter.camera
    camera.SetParallelProjection(parallel)
    camera.SetParallelScale(1.5)
    camera.SetFocalPoint(1, 2, 3)
    camera.SetPosition(4, -5, 9)
    camera.SetViewUp(0, 0, 1)
    camera.SetViewAngle(24)
    initial = _state(camera)
    renderer._plotter.window_size = (400, 800)
    renderer._resize_camera_for_viewport()
    assert camera.GetFocalPoint() == initial[1]
    assert camera.GetViewUp() == initial[2]
    assert camera.GetViewAngle() == 24
    if parallel:
        assert camera.GetParallelScale() > 1.5
        assert camera.GetPosition() == initial[0]
    else:
        assert camera.GetDistance() > vtkCamera().GetDistance()
    renderer._plotter.window_size = (800, 800)
    renderer._resize_camera_for_viewport()
    assert _state(camera) == initial
    assert renderer._plotter.renders == 2


def test_only_primary_adjusts_linked_resize_and_initial_fit_caches_actual_aspect():
    first, second = _renderer(), _renderer()
    first._viewport_aspect = second._viewport_aspect = 1.0
    first._plotter.camera.SetParallelProjection(True)
    first._plotter.camera.SetParallelScale(2.0)
    first.link_camera(second)
    first._plotter.window_size = second._plotter.window_size = (400, 800)
    first._resize_camera_for_viewport()
    expected_scale = first._plotter.camera.GetParallelScale()
    second._resize_camera_for_viewport()
    assert second._plotter.camera.GetParallelScale() == expected_scale
    assert first._plotter.camera.GetParallelScale() == expected_scale
    assert second._plotter.renders == 0
    first._camera_link._timer.fire()
    assert second._plotter.renders == 1
    first.unlink_camera()
    first.fit_camera_to_viewport()
    assert first._plotter.resets == 1
    assert first._viewport_aspect == 0.5
    assert first._plotter.camera_set

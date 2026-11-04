"""Render scheduling/geometry checks with plain plotter stubs and no GUI runtime."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import sys

import numpy as np
import pyvista as pv
import pytest

from Tools.LORETA_Visualizer import renderer as rendering
from Tools.LORETA_Visualizer.source_payloads import make_source_payload
from Tools.LORETA_Visualizer.synthetic_brain import BrainVolumeContextMesh, make_synthetic_brain_mesh


class _Property:
    def __getattr__(self, name):
        return lambda *args: None


class _Actor:
    def __init__(self, surface, **options):
        self.surface = surface
        self.options = options
        self.ranges = []
        self.mapper = SimpleNamespace(SetScalarRange=lambda *values: self.ranges.append(values))

    def GetProperty(self):  # noqa: N802
        return _Property()

    def SetVisibility(self, visible):  # noqa: N802
        self.visible = visible


class _Plotter:
    def __init__(self, *_args, **kwargs):
        self.options = kwargs
        self.actors = []
        self.removed = []
        self.renders = 0
        self.lights = []
        self.anti_aliasing = None
        self.camera_position = None
        self.isometric_views = 0

    def view_isometric(self, *, render=True):
        self.camera_position = "iso"
        self.camera_set = False
        self.isometric_views += 1
        if render:
            self.render()

    def add_mesh(self, surface, **kwargs):
        assert kwargs["render"] is False
        actor = _Actor(surface, **kwargs)
        self.actors.append(actor)
        return actor

    def remove_actor(self, actor, **kwargs):
        self.removed.append(actor)

    def render(self):
        self.renders += 1

    def enable_anti_aliasing(self, kind):
        self.anti_aliasing = kind

    def remove_all_lights(self):
        self.lights.clear()

    def add_light(self, light):
        self.lights.append(light)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _renderer():
    result = rendering.BrainRendererWidget.__new__(rendering.BrainRendererWidget)
    result._plotter = _Plotter()
    result._brain_opacity = 0.48
    result._activation_opacity = 0.72
    result._activation_visible = True
    result._activation_scalar_range = (0.0, 8.0)
    result._cortical_paint_z_threshold = 1.64
    result._cortical_paint_use_cluster_mask = True
    result._cortical_paint_active = True
    result._split_hemisphere_active = True
    result._split_left_actor = None
    result._split_right_actor = None
    result._split_left_render_cache = None
    result._split_right_render_cache = None
    result._split_left_rotation_degrees = 0.0
    result._split_right_rotation_degrees = 0.0
    points = np.array([[-1.0, -0.5, 0.0], [-1.0, 0.5, 0.0], [-0.5, 0.0, 1.0]])
    result._split_left_state = rendering._SplitHemisphereState(
        points,
        np.array([3, 0, 1, 2]),
        np.array([np.nan, 2.0, 5.0]),
        np.array([0.0, 0.5, 1.0]),
    )
    result._split_right_state = rendering._SplitHemisphereState(
        -points,
        np.array([3, 0, 1, 2]),
        np.array([np.nan, 2.0, 5.0]),
        np.array([0.0, 0.5, 1.0]),
    )
    return result


def test_split_updates_keep_actors_topology_and_normals_without_recomputation(monkeypatch):
    renderer = _renderer()
    normal_calls = []
    original = rendering.BrainRendererWidget._to_surface_polydata

    def counted(pyvista, points, faces):
        normal_calls.append(len(points))
        return original(pyvista, points, faces)

    monkeypatch.setattr(rendering.BrainRendererWidget, "_to_surface_polydata", staticmethod(counted))
    renderer._render_split_hemispheres(render=True)
    actors = (renderer._split_left_actor, renderer._split_right_actor)
    surface = renderer._split_left_render_cache.surface
    original_faces = surface.faces.copy()
    original_normals = surface.point_data["Normals"].copy()
    renderer.rotate_split_hemisphere("left", 12.0)
    np.testing.assert_allclose(
        surface.points,
        rendering._publication_hemisphere_points(
            renderer._split_left_state.points, side="left", extra_yaw_degrees=12.0
        ),
        atol=1e-14,
    )
    np.testing.assert_allclose(
        surface.point_data["Normals"], original_normals @ rendering._rotation_z(12.0).T, atol=1e-7
    )
    renderer.set_activation_scalar_range(1.0, 10.0)
    renderer.set_activation_visible(False)
    np.testing.assert_array_equal(surface.faces, original_faces)
    assert actors == (renderer._split_left_actor, renderer._split_right_actor)
    assert normal_calls == [3, 3]
    assert renderer._plotter.removed == []
    np.testing.assert_array_equal(
        surface["publication_rgb"],
        rendering._publication_surface_rgb(
            renderer._split_left_state.values,
            renderer._split_left_state.shade_values,
            scalar_range=(1.0, 10.0),
            activation_visible=False,
        ),
    )
    # Absolute layout prevents accumulated roundoff across repeated rotations/reset.
    renderer.rotate_split_hemisphere("left", -12.0)
    np.testing.assert_allclose(
        surface.points,
        rendering._publication_hemisphere_points(renderer._split_left_state.points, side="left"),
        atol=1e-14,
    )


def test_new_values_with_same_geometry_reuse_surface_and_actor():
    renderer = _renderer()
    renderer._render_split_hemispheres(render=False)
    actor = renderer._split_left_actor
    old = renderer._split_left_state
    renderer._split_left_state = rendering._SplitHemisphereState(
        old.points.copy(), old.faces.copy(), np.array([7.0, 1.0, np.nan]), old.shade_values.copy()
    )
    renderer._render_split_hemispheres(render=True)
    assert renderer._split_left_actor is actor
    assert len(renderer._plotter.actors) == 2
    np.testing.assert_array_equal(
        actor.surface["publication_rgb"],
        rendering._publication_surface_rgb(
            renderer._split_left_state.values, old.shade_values, scalar_range=(0.0, 8.0), activation_visible=True
        ),
    )


def test_unchanged_display_setters_do_not_render_or_rebuild(monkeypatch):
    renderer = _renderer()
    monkeypatch.setattr(
        renderer, "set_activation_payload", lambda *_args: pytest.fail("Unchanged settings must not rebuild.")
    )
    renderer.set_brain_opacity(0.48)
    renderer.set_activation_opacity(0.72)
    renderer.set_activation_visible(True)
    renderer.set_activation_scalar_range(0.0, 8.0)
    renderer.set_cortical_paint_z_threshold(1.64)
    renderer.set_cortical_paint_cluster_mask_enabled(True)
    assert renderer._plotter.renders == 0


@pytest.mark.parametrize("cortical", [False, True])
def test_vmax_only_changes_mapper_without_rebuilding_geometry(monkeypatch, cortical):
    renderer = _renderer()
    renderer._split_hemisphere_active = False
    renderer._cortical_paint_active = cortical
    renderer._volume_overlay_active = not cortical
    actor = _Actor(None)
    renderer._brain_actor = actor
    renderer._activation_actor = actor
    renderer._last_activation_payload = object()
    rebuilt = []
    monkeypatch.setattr(renderer, "set_activation_payload", lambda payload: rebuilt.append(payload))
    renderer.set_activation_scalar_range(0.0, 12.0)
    assert rebuilt == []
    assert actor.ranges == [(0.0, 12.0)]
    assert renderer._plotter.renders == 1
    renderer.set_activation_scalar_range(1.0, 12.0)
    assert rebuilt == [renderer._last_activation_payload]


def test_backend_disables_idle_timer_but_initial_frame_is_explicit(monkeypatch):
    from Tools.LORETA_Visualizer import graphics_support

    renderer = _renderer()
    monkeypatch.setattr(graphics_support, "require_desktop_opengl", lambda _parent: None)
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=_Plotter))
    monkeypatch.setattr(rendering.BrainRendererWidget, "_install_transparent_spin_event_filter", lambda *_args: None)
    renderer._initialize_backend(SimpleNamespace(addWidget=lambda _widget: None), initial_opacity=0.48)
    assert renderer._plotter.options["auto_update"] is False
    assert renderer._plotter.renders == 1
    assert renderer._plotter.anti_aliasing == "fxaa"
    assert len(renderer._plotter.lights) == 2
    assert all(light.is_camera_light for light in renderer._plotter.lights)


def test_quality_features_fail_without_preventing_renderer_use():
    rendering._configure_render_quality(SimpleNamespace(), pv)


def test_partial_backend_initialization_retains_ownership_for_shutdown(monkeypatch):
    from Tools.LORETA_Visualizer import graphics_support

    renderer = _renderer()
    plotter = _Plotter()
    closed = []
    plotter.close = lambda: closed.append(True)
    monkeypatch.setattr(graphics_support, "require_desktop_opengl", lambda _parent: None)
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=lambda *_a, **_k: plotter))

    def fail_after_context_creation(*_args):
        raise RuntimeError("Simulated context setup failure")

    monkeypatch.setattr(renderer, "_install_transparent_spin_event_filter", fail_after_context_creation)
    with pytest.raises(RuntimeError, match="context setup failure"):
        renderer._initialize_backend(SimpleNamespace(addWidget=lambda _widget: None), initial_opacity=0.48)
    assert renderer._plotter is plotter
    renderer.shutdown()
    assert closed == [True]
    assert renderer._plotter is None


@pytest.mark.parametrize("smooth_shell", [False, True])
def test_volume_entry_and_reset_use_isometric_but_payload_refresh_keeps_camera(smooth_shell):
    renderer = _renderer()
    renderer._display_mode = rendering.DISPLAY_MODE_TRANSPARENT_MESH
    renderer._transparent_spin_enabled = False
    renderer._cortical_paint_active = False
    renderer._split_hemisphere_active = False
    renderer._brain_actor = _Actor(None)
    renderer._brain_actor_context = "cortical"
    renderer._surface = object()
    renderer._volume_context_surface = object()
    renderer._volume_smooth_shell_enabled = smooth_shell
    payload = SimpleNamespace(kind=rendering.SOURCE_KIND_VOLUME_POINTS)
    renderer._last_activation_payload = payload

    renderer._restore_base_brain_actor(payload=payload, render=False)

    assert renderer._plotter.camera_position == "iso"
    assert renderer._plotter.camera_set is True
    assert renderer._plotter.isometric_views == 1
    assert renderer._plotter.renders == 0
    user_camera = ((3.0, -2.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    renderer._plotter.camera_position = user_camera

    renderer._restore_base_brain_actor(payload=payload, render=False)

    assert renderer._plotter.camera_position == user_camera
    assert renderer._plotter.isometric_views == 1
    renderer.reset_camera()
    assert renderer._plotter.camera_position == "iso"
    assert renderer._plotter.camera_set is True
    assert renderer._plotter.isometric_views == 2
    assert renderer._plotter.renders == 1


def _volume_renderer():
    renderer = _renderer()
    renderer._display_mode = rendering.DISPLAY_MODE_TRANSPARENT_MESH
    renderer._transparent_spin_enabled = False
    renderer._cortical_paint_active = False
    renderer._split_hemisphere_active = False
    renderer._activation_actor = None
    renderer._last_activation_payload = None
    renderer._current_mesh = make_synthetic_brain_mesh(lat_steps=6, lon_steps=12)
    renderer._surface = renderer._to_polydata(pv, renderer._current_mesh)
    renderer._volume_context_surface = pv.Sphere(radius=1.4, theta_resolution=12, phi_resolution=8)
    renderer._brain_actor = _Actor(renderer._surface)
    renderer._brain_actor_context = "cortical"
    return renderer


def test_backdrop_switch_preserves_source_support_overlay_geometry_and_camera(monkeypatch):
    renderer = _volume_renderer()
    grid = np.linspace(-0.25, 0.25, 4)
    original_points = np.stack(np.meshgrid(grid, grid, grid, indexing="ij"), axis=-1).reshape(-1, 3)
    valid = np.ones(len(original_points), dtype=bool)
    valid[22] = False
    payload = make_source_payload(
        points=original_points[valid], values=np.linspace(2., 8., valid.sum()),
        kind=rendering.SOURCE_KIND_VOLUME_POINTS, label="Synthetic volume",
        metadata={"synthetic": True, "cluster_mask_source_indices": [1, 3]}, normalize_values=False,
    )
    renderer.set_activation_payload(payload, volume_support_points=original_points, volume_support_valid_mask=valid)
    assert renderer.volume_smooth_shell_enabled() is False
    assert renderer._brain_actor.surface is renderer._surface
    assert renderer._volume_overlay_active is True
    actor = renderer._activation_actor
    geometry = actor.surface
    before = (geometry.points.copy(), geometry.faces.copy(), geometry["activation"].copy())
    source_points, source_values = payload.points.copy(), payload.values.copy()
    support = renderer._last_volume_support_points
    support_valid = renderer._last_volume_support_valid_mask
    scalar_range = renderer._activation_scalar_range
    user_camera = ((3., -2., 1.), (0.1, 0.2, 0.3), (0., 0., 1.))
    renderer._plotter.camera_position = user_camera
    camera = pv.Camera()
    camera.SetParallelScale(0.7)
    camera.SetViewAngle(18.0)
    renderer._plotter.camera = camera
    renders_before = renderer._plotter.renders
    monkeypatch.setattr(renderer, "set_activation_payload", lambda *_a, **_k: pytest.fail("Backdrop rebuilt sources"))
    monkeypatch.setattr(renderer, "_add_activation_overlay", lambda *_a: pytest.fail("Backdrop rebuilt overlay"))

    for smooth in (True, True, False, False):
        renderer.set_volume_smooth_shell_enabled(smooth)
        expected = renderer._volume_context_surface if smooth else renderer._surface
        assert renderer._brain_actor.surface is expected
        assert renderer._brain_actor.options["reset_camera"] is False
        assert renderer._activation_actor is actor
        assert renderer._last_activation_payload is payload
        assert renderer._last_volume_support_points is support
        assert renderer._last_volume_support_valid_mask is support_valid
        assert renderer._activation_scalar_range == scalar_range
        assert renderer._plotter.camera_position == user_camera
        assert renderer._plotter.camera is camera
        assert camera.GetParallelScale() == 0.7
        assert camera.GetViewAngle() == 18.0
    assert renderer._plotter.renders - renders_before == 2
    assert actor not in renderer._plotter.removed
    for actual, expected in zip((geometry.points, geometry.faces, geometry["activation"]), before):
        np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(payload.points, source_points)
    np.testing.assert_array_equal(payload.values, source_values)
    np.testing.assert_array_equal(support, original_points)
    np.testing.assert_array_equal(support_valid, valid)
    assert payload.metadata["cluster_mask_source_indices"] == [1, 3]


def test_unavailable_shell_keeps_pial_and_preference_survives_mesh_load():
    renderer = _volume_renderer()
    renderer._volume_context_surface = None
    payload = SimpleNamespace(kind=rendering.SOURCE_KIND_VOLUME_POINTS)
    renderer._last_activation_payload = payload
    renderer._restore_base_brain_actor(payload=payload, render=False)
    old_actor = renderer._brain_actor
    renderer.set_volume_smooth_shell_enabled(True)
    assert renderer.volume_smooth_shell_enabled() is True
    assert renderer._brain_actor is old_actor
    assert renderer._plotter.renders == 0

    mesh = renderer._current_mesh
    updated_mesh = replace(mesh, volume_context=BrainVolumeContextMesh(mesh.points * 1.2, mesh.faces))
    renderer.replace_brain_mesh(updated_mesh, reset_camera=False)
    assert renderer.volume_smooth_shell_enabled() is True
    renderer._restore_base_brain_actor(payload=payload, render=False)
    assert renderer._brain_actor.surface is renderer._volume_context_surface


@pytest.mark.parametrize("mode,kind", [
    (rendering.DISPLAY_MODE_SPLIT_HEMISPHERE, rendering.SOURCE_KIND_VOLUME_POINTS),
    (rendering.DISPLAY_MODE_CORTICAL_SURFACE, rendering.SOURCE_KIND_VOLUME_POINTS),
    (rendering.DISPLAY_MODE_MRI_SLICES, rendering.SOURCE_KIND_VOLUME_POINTS),
    (rendering.DISPLAY_MODE_TRANSPARENT_MESH, rendering.SOURCE_KIND_SURFACE_POINTS),
])
def test_shell_preference_does_not_change_other_display_modes(monkeypatch, mode, kind):
    renderer = _volume_renderer()
    renderer._display_mode = mode
    renderer._last_activation_payload = SimpleNamespace(kind=kind)
    monkeypatch.setattr(renderer, "_restore_base_brain_actor", lambda **_k: pytest.fail("Inactive backdrop changed"))
    renderer.set_volume_smooth_shell_enabled(True)
    assert renderer.volume_smooth_shell_enabled() is True
    assert renderer._plotter.renders == 0


def test_nonvolume_reset_and_requested_spin_keep_their_camera_owners(monkeypatch):
    renderer = _renderer()
    renderer._display_mode = rendering.DISPLAY_MODE_TRANSPARENT_MESH
    renderer._transparent_spin_enabled = False
    renderer._split_hemisphere_active = False
    renderer._last_activation_payload = SimpleNamespace(kind=rendering.SOURCE_KIND_SURFACE_POINTS)
    renderer.reset_camera()
    assert renderer._plotter.camera_position == "xy"
    assert renderer._plotter.isometric_views == 0

    renderer._last_activation_payload = SimpleNamespace(kind=rendering.SOURCE_KIND_VOLUME_POINTS)
    renderer._transparent_spin_enabled = True
    spin_resets = []
    monkeypatch.setattr(renderer, "_start_transparent_spin", lambda **kwargs: spin_resets.append(kwargs))
    renderer.reset_camera()
    assert spin_resets == [{"reset_orientation": True}]
    assert renderer._plotter.isometric_views == 0

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.renderer import (
    DISPLAY_MODE_SPLIT_HEMISPHERE,
    DISPLAY_MODE_TRANSPARENT_MESH,
    BrainRendererWidget,
)
from Tools.LORETA_Visualizer.scalar_fields import LORETA_SCALAR_COLORS, LORETA_SMOOTH_SCALAR_COLORS
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_VOLUME_POINTS,
    make_source_payload,
)
from Tools.LORETA_Visualizer.synthetic_brain import make_synthetic_brain_mesh
from Tools.LORETA_Visualizer.volume_overlay import (
    DEFAULT_VOLUME_CONTOUR_MAX_COUNT,
    DEFAULT_VOLUME_CONTOUR_MIN_COUNT,
    build_smoothed_volume_overlay,
)


def test_smoothed_volume_overlay_interpolates_sparse_points_to_grid() -> None:
    points = _volume_fixture_points()
    values = np.linspace(0.2, 4.0, len(points), dtype=float)
    display_bounds = ((-1.2, -1.2, -1.2), (1.2, 1.2, 1.2))

    overlay = build_smoothed_volume_overlay(
        points,
        values,
        display_bounds=display_bounds,
        max_dimension=24,
        min_dimension=12,
    )

    assert overlay is not None
    assert max(overlay.dimensions) == 24
    assert overlay.values.shape == overlay.dimensions
    assert np.count_nonzero(overlay.values > 0.0) > len(points)
    assert np.allclose(overlay.values[0, :, :], 0.0)
    assert np.allclose(overlay.values[-1, :, :], 0.0)
    assert len(overlay.contour_values) == 6
    assert overlay.rendered_point_count == len(points)
    assert overlay.origin[0] > display_bounds[0][0]
    assert overlay.origin[1] > display_bounds[0][1]
    assert overlay.origin[2] > display_bounds[0][2]


def test_smoothed_volume_overlay_omits_values_below_display_floor() -> None:
    points = _volume_fixture_points()
    values = np.linspace(-2.0, 4.0, len(points), dtype=float)

    overlay = build_smoothed_volume_overlay(
        points,
        values,
        display_bounds=((-1.2, -1.2, -1.2), (1.2, 1.2, 1.2)),
        min_visible_value=0.0,
        max_dimension=22,
        min_dimension=12,
    )

    assert overlay is not None
    assert overlay.rendered_point_count < len(points)
    assert min(overlay.contour_values) > 0.0


def test_smoothed_volume_overlay_contours_scale_with_display_range() -> None:
    points = _volume_fixture_points()
    display_bounds = ((-1.2, -1.2, -1.2), (1.2, 1.2, 1.2))

    low_range = build_smoothed_volume_overlay(
        points,
        np.linspace(0.1, 1.2, len(points), dtype=float),
        display_bounds=display_bounds,
    )
    high_range = build_smoothed_volume_overlay(
        points,
        np.linspace(0.1, 6.0, len(points), dtype=float),
        display_bounds=display_bounds,
    )

    assert low_range is not None
    assert high_range is not None
    assert len(low_range.contour_values) == DEFAULT_VOLUME_CONTOUR_MIN_COUNT
    assert len(high_range.contour_values) > len(low_range.contour_values)
    assert len(high_range.contour_values) <= DEFAULT_VOLUME_CONTOUR_MAX_COUNT


def test_renderer_uses_smoothed_overlay_for_volume_points() -> None:
    import pyvista as pv

    points = _volume_fixture_points()
    values = np.linspace(0.2, 4.0, len(points), dtype=float)
    payload = make_source_payload(
        points=points,
        values=values,
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakeOverlayPlotter()
    renderer._activation_scalar_range = (0.0, 4.0)
    renderer._activation_opacity = 0.72
    renderer._activation_visible = True
    renderer._current_mesh = make_synthetic_brain_mesh()
    renderer._volume_overlay_active = False

    renderer._add_activation_overlay(pv, payload)

    assert renderer._volume_overlay_active is True
    assert renderer._activation_actor is not None
    assert renderer._plotter.added_kwargs["smooth_shading"] is True
    assert renderer._plotter.added_kwargs["interpolate_before_map"] is True
    assert len(renderer._plotter.added_kwargs["cmap"]) == len(LORETA_SMOOTH_SCALAR_COLORS)
    assert len(renderer._plotter.added_kwargs["cmap"]) > len(LORETA_SCALAR_COLORS)
    assert "render_points_as_spheres" not in renderer._plotter.added_kwargs
    assert "style" not in renderer._plotter.added_kwargs
    assert renderer._plotter.added_mesh.n_points > 0
    assert renderer._plotter.added_mesh.n_points != len(points)


@pytest.mark.parametrize("retained_count", [1, 2])
def test_smoothed_volume_overlay_builds_3d_kernel_for_small_masks(retained_count: int) -> None:
    support = _volume_support_fixture_points()
    center_order = np.argsort(np.linalg.norm(support, axis=1))
    points = support[center_order[:retained_count]]
    values = np.linspace(1.44, 1.74, retained_count, dtype=float)

    overlay = build_smoothed_volume_overlay(
        points,
        values,
        support_points=support,
        source_spacing=0.16,
        max_dimension=24,
        min_dimension=12,
    )

    assert overlay is not None
    assert overlay.rendered_point_count == retained_count
    assert overlay.support_point_count == len(support)
    assert all(dimension >= 12 for dimension in overlay.dimensions)
    assert np.count_nonzero(overlay.values > 0.0) > retained_count
    assert overlay.contour_values


def test_smoothed_volume_overlay_uses_full_source_support_bounds() -> None:
    support = _volume_support_fixture_points()
    active = support[(support[:, 1] < -0.35) & (support[:, 2] < 0.2)]
    values = np.linspace(1.1, 2.4, len(active), dtype=float)

    overlay = build_smoothed_volume_overlay(
        active,
        values,
        support_points=support,
        source_spacing=0.16,
        max_dimension=26,
        min_dimension=12,
    )

    assert overlay is not None
    grid_min = np.asarray(overlay.origin, dtype=float)
    grid_max = grid_min + np.asarray(overlay.spacing) * (np.asarray(overlay.dimensions) - 1)
    assert overlay.rendered_point_count == len(active)
    assert overlay.support_point_count == len(support)
    assert np.all(grid_min <= np.min(support, axis=0))
    assert np.all(grid_max >= np.max(support, axis=0))
    assert np.any(grid_min < np.min(active, axis=0))
    assert np.any(grid_max > np.max(active, axis=0))


def test_renderer_does_not_use_pial_surface_as_volume_source_boundary() -> None:
    import pyvista as pv

    points = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [0.12, 0.0, 0.0],
            [0.9, 0.0, 0.0],
            [-0.9, 0.0, 0.0],
        ],
        dtype=float,
    )
    payload = make_source_payload(
        points=points,
        values=np.asarray([1.0, 2.0, 8.0, 9.0], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._surface = pv.Sphere(radius=0.35, theta_resolution=24, phi_resolution=24)

    display_payload = renderer.display_payload_for_current_mesh(payload)

    assert display_payload is payload
    assert len(display_payload.points) == len(points)
    assert np.allclose(display_payload.values, [1.0, 2.0, 8.0, 9.0])
    assert "display_surface_clip" not in display_payload.metadata


def test_renderer_sparse_volume_never_uses_screen_aligned_point_sprite() -> None:
    import pyvista as pv

    support = _volume_support_fixture_points()
    point = support[np.argmin(np.linalg.norm(support, axis=1))].reshape(1, 3)
    payload = make_source_payload(
        points=point,
        values=np.asarray([1.74], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        metadata={"source_value_unit": "z-score", "volume_pos_mm": 10.0},
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakeOverlayPlotter()
    renderer._surface = pv.Sphere(radius=0.35, theta_resolution=24, phi_resolution=24)
    renderer._activation_scalar_range = (0.0, 1.74)
    renderer._activation_opacity = 0.72
    renderer._activation_visible = True
    renderer._current_mesh = make_synthetic_brain_mesh()
    renderer._last_activation_payload = payload
    renderer._last_volume_support_points = support
    renderer._volume_overlay_active = False

    renderer._add_activation_overlay(pv, payload)

    assert renderer._volume_overlay_active is True
    assert renderer._activation_actor is not None
    assert renderer._plotter.added_mesh.n_points > len(payload.points)
    assert "style" not in renderer._plotter.added_kwargs
    assert "point_size" not in renderer._plotter.added_kwargs
    assert "render_points_as_spheres" not in renderer._plotter.added_kwargs


def test_renderer_uses_true_3d_glyph_fallback_when_contouring_fails(monkeypatch) -> None:
    import pyvista as pv

    support = _volume_support_fixture_points()
    point = support[np.argmin(np.linalg.norm(support, axis=1))].reshape(1, 3)
    payload = make_source_payload(
        points=point,
        values=np.asarray([1.74], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        metadata={"source_value_unit": "z-score", "volume_pos_mm": 10.0},
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakeOverlayPlotter()
    renderer._activation_scalar_range = (0.0, 1.74)
    renderer._activation_opacity = 0.72
    renderer._activation_visible = True
    renderer._current_mesh = make_synthetic_brain_mesh()
    renderer._last_activation_payload = payload
    renderer._last_volume_support_points = support
    renderer._volume_overlay_active = False
    monkeypatch.setattr(
        BrainRendererWidget,
        "_add_smoothed_volume_overlay",
        lambda *_args, **_kwargs: False,
    )

    renderer._add_activation_overlay(pv, payload)

    assert renderer._volume_overlay_active is True
    assert renderer._activation_actor is not None
    assert renderer._plotter.added_mesh.n_cells > 0
    assert renderer._plotter.added_mesh.n_points > len(payload.points)
    bounds = np.asarray(renderer._plotter.added_mesh.bounds, dtype=float).reshape(3, 2)
    assert np.all(bounds[:, 1] - bounds[:, 0] > 0.0)
    assert "style" not in renderer._plotter.added_kwargs
    assert "point_size" not in renderer._plotter.added_kwargs


def test_empty_volume_overlay_has_no_actor_or_point_fallback() -> None:
    import pyvista as pv

    payload = make_source_payload(
        points=np.empty((0, 3), dtype=float),
        values=np.empty((0,), dtype=float),
        label="Empty eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakeOverlayPlotter()
    renderer._activation_actor = None
    renderer._volume_overlay_active = False

    renderer._add_activation_overlay(pv, payload)

    assert renderer._volume_overlay_active is True
    assert renderer._activation_actor is None
    assert renderer._plotter.added_mesh is None


def test_volume_payload_uses_whole_brain_context_while_l2_stays_cortical() -> None:
    cortical_surface = object()
    whole_brain_surface = object()
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._surface = cortical_surface
    renderer._volume_context_surface = whole_brain_surface
    renderer._display_mode = DISPLAY_MODE_TRANSPARENT_MESH
    volume_payload = make_source_payload(
        points=np.asarray([[0.0, -0.7, -0.4]], dtype=float),
        values=np.asarray([1.7], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        normalize_values=False,
    )
    l2_payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0]], dtype=float),
        values=np.asarray([1.0, 2.0, 3.0], dtype=float),
        label="Hauk L2-MNE",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_hauk_source_psd_cortical_normal_v1_mean",
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        normalize_values=False,
    )

    assert renderer._base_brain_surface_for_payload(volume_payload) == (
        whole_brain_surface,
        "whole_brain_anatomy",
    )
    assert renderer._base_brain_surface_for_payload(l2_payload) == (cortical_surface, "cortical")

    renderer._display_mode = DISPLAY_MODE_SPLIT_HEMISPHERE
    assert renderer._base_brain_surface_for_payload(volume_payload) == (cortical_surface, "cortical")


def test_transparent_spin_frames_the_active_whole_brain_context() -> None:
    context_points = np.asarray(
        [
            [-1.0, -1.5, -2.0],
            [1.0, -1.5, -2.0],
            [-1.0, 1.5, 1.0],
            [1.0, 1.5, 1.0],
        ],
        dtype=float,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._surface = SimpleNamespace(points=np.asarray([[-0.1, 0.0, 0.0], [0.1, 0.0, 0.0]]))
    renderer._volume_context_surface = SimpleNamespace(points=context_points)
    renderer._brain_actor_context = "whole_brain_anatomy"
    renderer._current_mesh = make_synthetic_brain_mesh(lat_steps=6, lon_steps=12)

    focal = renderer._transparent_spin_focal_point()
    distance = renderer._transparent_spin_camera_distance(focal)

    assert np.allclose(focal, np.mean(context_points, axis=0))
    assert distance > 5.0


def test_smooth_scalar_color_ramp_keeps_palette_endpoints() -> None:
    assert len(LORETA_SMOOTH_SCALAR_COLORS) == 256
    assert LORETA_SMOOTH_SCALAR_COLORS[0] == LORETA_SCALAR_COLORS[0]
    assert LORETA_SMOOTH_SCALAR_COLORS[-1] == LORETA_SCALAR_COLORS[-1]


def _volume_fixture_points() -> np.ndarray:
    axis = np.linspace(-0.18, 0.18, 4, dtype=float)
    points = np.asarray(
        [
            (x, y, z)
            for x in axis
            for y in axis
            for z in axis
            if np.linalg.norm((x, y, z)) <= 0.29
        ],
        dtype=float,
    )
    return points + np.asarray([0.12, -0.18, 0.05], dtype=float)


def _volume_support_fixture_points() -> np.ndarray:
    axis = np.linspace(-0.64, 0.64, 9, dtype=float)
    return np.asarray(
        [
            (x, y, z)
            for x in axis
            for y in axis
            for z in axis
            if (x / 0.65) ** 2 + (y / 0.82) ** 2 + (z / 0.58) ** 2 <= 1.0
        ],
        dtype=float,
    )


class _FakeOverlayActor:
    def __init__(self) -> None:
        self.visible: bool | None = None

    def SetVisibility(self, visible: bool) -> None:  # noqa: N802
        self.visible = bool(visible)


class _FakeOverlayPlotter:
    def __init__(self) -> None:
        self.added_mesh = None
        self.added_kwargs = {}

    def add_mesh(self, mesh, **kwargs):  # noqa: ANN001, ANN202
        self.added_mesh = mesh
        self.added_kwargs = dict(kwargs)
        return _FakeOverlayActor()

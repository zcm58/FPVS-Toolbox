from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.renderer import BrainRendererWidget
from Tools.LORETA_Visualizer.scalar_fields import LORETA_SCALAR_COLORS, LORETA_SMOOTH_SCALAR_COLORS
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_POINTS, make_source_payload
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
    assert renderer._plotter.added_mesh.n_points > 0
    assert renderer._plotter.added_mesh.n_points != len(points)


def test_renderer_clips_volume_payload_to_brain_surface() -> None:
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

    clipped = renderer.display_payload_for_current_mesh(payload)

    assert len(clipped.points) == 2
    assert np.allclose(clipped.values, [1.0, 2.0])
    assert clipped.metadata["display_surface_clip_rendered_point_count"] == 2


def test_renderer_display_payload_clip_removes_hidden_high_values_from_scale_inputs() -> None:
    import pyvista as pv

    points = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [0.12, 0.0, 0.0],
            [0.9, 0.0, 0.0],
        ],
        dtype=float,
    )
    payload = make_source_payload(
        points=points,
        values=np.asarray([1.0, 2.0, 20.0], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._surface = pv.Sphere(radius=0.35, theta_resolution=24, phi_resolution=24)

    clipped = renderer.display_payload_for_current_mesh(payload)

    assert len(clipped.points) == 2
    assert float(np.nanmax(clipped.values)) == 2.0
    assert clipped.metadata["display_surface_clip_original_point_count"] == 3


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

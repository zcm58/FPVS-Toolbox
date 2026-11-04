"""Display interpolation must preserve holes in prepared source measurements."""

from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_VOLUME_POINTS,
    SourcePayload,
)
from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform
from Tools.LORETA_Visualizer.volume_overlay import build_smoothed_volume_overlay
from Tools.LORETA_Visualizer.volume_slices import (
    MriAnatomyVolume,
    build_mri_slice_panels,
    nearest_prepared_source_value,
)


def _source_grid():
    return np.array([[-1.0, 0, 0], [0, 0, 0], [1.0, 0, 0]]), np.array([4.0, np.nan, 4.0])


@pytest.mark.parametrize("filtered", [False, True])
def test_volume_smoothing_preserves_missing_nearest_source(filtered):
    points, values = _source_grid()
    valid = np.isfinite(values)
    kwargs = {"support_points": points, "support_valid_source_mask": valid} if filtered else {}
    overlay = build_smoothed_volume_overlay(
        points[valid] if filtered else points,
        values[valid] if filtered else values,
        source_spacing=1.0, max_dimension=15, min_dimension=15,
        edge_zero_margin=0, **kwargs,
    )

    assert overlay is not None
    center = tuple(size // 2 for size in overlay.dimensions)
    assert np.isnan(overlay.values[center])
    assert np.any(overlay.values > 0.0)


def test_original_grid_inspection_reports_missing_at_nearest_source():
    points, values = _source_grid()
    payload = SourcePayload(points, values, "Missing middle source", kind=SOURCE_KIND_VOLUME_POINTS)

    assert nearest_prepared_source_value(
        payload, (0.0, 0.0, 0.0), display_transform=MeshDisplayTransform.identity(),
    ) == (None, 0.0)
    assert nearest_prepared_source_value(
        payload, (-1.0, 0.0, 0.0), display_transform=MeshDisplayTransform.identity(),
    ) == (4.0, 0.0)


def test_mri_slice_interpolation_keeps_invalid_grid_hole():
    points, values = _source_grid()
    voxels = points + 4.0
    anatomy = MriAnatomyVolume(np.ones((9, 9, 9)), np.eye(4), np.eye(4), Path("unused"))
    panels, _peak = build_mri_slice_panels(
        anatomy, voxels, values, scalar_range=(0.0, 4.0), slice_indices=(4, 4, 4),
    )

    for panel in panels:
        rows, columns = np.indices(panel.overlay.shape)
        pixels = np.column_stack((columns.ravel(), rows.ravel(), np.ones(rows.size)))
        coordinates = pixels @ panel.pixel_to_voxel.T
        center = np.all(coordinates == np.array([4.0, 4.0, 4.0]), axis=1)
        assert center.sum() == 1
        assert np.isnan(panel.overlay.ravel()[center][0])


@pytest.mark.parametrize("export", [False, True])
def test_filtered_mri_preview_and_export_preserve_original_validity(monkeypatch, tmp_path, export):
    from unittest.mock import Mock
    from Tools.LORETA_Visualizer import volume_slices

    points, values = _source_grid()
    points += 4.0
    original = SourcePayload(points, values, "Original", kind=SOURCE_KIND_VOLUME_POINTS)
    valid = np.isfinite(values)
    displayed = SourcePayload(points[valid], values[valid], "Filtered", kind=SOURCE_KIND_VOLUME_POINTS)
    anatomy = MriAnatomyVolume(np.ones((9, 9, 9)), np.eye(4), np.eye(4), Path("unused"))
    captured = []

    def capture_preview(panels, **_kwargs):
        captured.extend(panels)
        return np.zeros((9, 9, 3), dtype=np.uint8), ()

    def capture_export(panels, **_kwargs):
        captured.extend(panels)
        figure = Mock()
        figure.get_facecolor.return_value = "white"
        return figure

    kwargs = dict(
        payload=displayed, display_transform=MeshDisplayTransform.identity(),
        fsaverage_dir=tmp_path, scalar_range=(0.0, 4.0), anatomy=anatomy,
        slice_indices=(4, 4, 4),
    )
    if export:
        monkeypatch.setattr(volume_slices, "build_mri_slice_figure", capture_export)
        volume_slices.write_mri_orthogonal_slice_figures(
            tmp_path / "slices.png", support_payload=original, **kwargs,
        )
    else:
        monkeypatch.setattr(volume_slices, "_draw_mri_slice_figure", capture_preview)
        result = volume_slices.render_mri_orthogonal_slice_image(inspection_payload=original, **kwargs)
        assert result.nearest_source_value is None
        assert result.nearest_source_distance_mm == 0.0
        assert result.rendered_point_count == 2
    for panel in captured:
        rows, columns = np.indices(panel.overlay.shape)
        pixels = np.column_stack((columns.ravel(), rows.ravel(), np.ones(rows.size)))
        coordinates = pixels @ panel.pixel_to_voxel.T
        center = np.all(coordinates == np.array([4.0, 4.0, 4.0]), axis=1)
        assert np.isnan(panel.overlay.ravel()[center][0])

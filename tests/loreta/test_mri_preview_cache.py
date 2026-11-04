"""Interactive reuse must preserve the ordinary native MRI rendering exactly."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer import volume_slices as slices
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_POINTS, SourcePayload
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_FSAVERAGE_VOLUME, MeshDisplayTransform


def _inputs():
    x, y, z = np.indices((24, 24, 24))
    anatomy = slices.MriAnatomyVolume(
        data=(x + y * 2 + z * 3).astype(np.uint8), vox_to_ras=np.eye(4), ras_to_vox=np.eye(4),
        source_path=Path("synthetic.mgz"), intensity_window=(0.0, 138.0),
        crop_center_voxels=(11.5, 11.5, 11.5), field_of_view_mm=24.,
    )
    points = np.stack(np.meshgrid([4., 8., 12., 16., 20.], [4., 8., 12., 16., 20.], [4., 8., 12., 16., 20.], indexing="ij"), -1).reshape(-1, 3)
    values = 5. * np.exp(-np.sum(((points - 12.) / 8.) ** 2, axis=1))
    values[np.all(points == [12., 12., 12.], axis=1)] = np.nan
    support = SourcePayload(
        points=points, values=values, label="Synthetic source", kind=SOURCE_KIND_VOLUME_POINTS,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME, value_label="Z", metadata={"synthetic": True},
    )
    selected = np.isfinite(values) & (values > 1.)
    payload = replace(support, points=points[selected], values=values[selected])
    return anatomy, payload, support


def _render(anatomy, payload, support, **kwargs):
    options = dict(
        display_transform=MeshDisplayTransform.identity(), fsaverage_dir=Path("unused"), anatomy=anatomy,
        scalar_range=(0., 5.), figsize=(4., 3.5), dpi=60, inspection_payload=support, label="Synthetic",
    )
    options.update(kwargs)
    return slices.render_mri_orthogonal_slice_image(payload, **options)


def _assert_equal(actual, expected):
    np.testing.assert_array_equal(actual.image_rgb, expected.image_rgb)
    assert actual.peak_voxel == expected.peak_voxel
    assert actual.cursor_ras_mm == expected.cursor_ras_mm
    assert actual.scalar_range == expected.scalar_range
    assert actual.anatomy_shape == expected.anatomy_shape
    assert actual.nearest_source_value == expected.nearest_source_value
    assert actual.nearest_source_distance_mm == expected.nearest_source_distance_mm
    for actual_region, expected_region in zip(actual.hit_regions, expected.hit_regions):
        assert actual_region.plane == expected_region.plane
        assert actual_region.image_bounds == expected_region.image_bounds
        assert actual_region.panel_shape == expected_region.panel_shape
        np.testing.assert_array_equal(actual_region.pixel_to_voxel, expected_region.pixel_to_voxel)


@pytest.mark.parametrize("layout,figsize", [("auto", (4., 3.5)), ("row", (7., 3.))])
def test_reused_preview_matches_fresh_image_geometry_and_missing_source_holes(layout, figsize):
    anatomy, payload, support = _inputs()
    cache = slices.MriSlicePreviewCache()
    try:
        first_figure = None
        for indices in ((8, 12, 8), (12, 12, 12), (15, 12, 15), (8, 12, 8)):
            actual = _render(anatomy, payload, support, slice_indices=indices, preview_cache=cache, layout=layout, figsize=figsize)
            expected = _render(anatomy, payload, support, slice_indices=indices, layout=layout, figsize=figsize)
            _assert_equal(actual, expected)
            if first_figure is None:
                first_figure = cache._figure
            assert cache._figure is first_figure
            for axis in cache._figure.axes[:3]:
                alpha = np.asarray(axis.images[1].get_alpha())
                assert np.all(np.isfinite(alpha))
                assert np.all(alpha[np.ma.getmaskarray(axis.images[1].get_array())] == 0.)
    finally:
        cache.clear()


def test_drag_reuses_the_fixed_plane_without_recomputing_its_overlay(monkeypatch):
    anatomy, payload, support = _inputs()
    cache = slices.MriSlicePreviewCache()
    original = slices._slice_panel
    calls = []

    def observed(*args, **kwargs):
        calls.append(kwargs["plane"])
        return original(*args, **kwargs)

    monkeypatch.setattr(slices, "_slice_panel", observed)
    try:
        _render(anatomy, payload, support, slice_indices=(8, 12, 8), preview_cache=cache)
        calls.clear()
        _render(anatomy, payload, support, slice_indices=(9, 12, 9), preview_cache=cache)
        assert calls == ["axial", "sagittal"]
    finally:
        cache.clear()


@pytest.mark.parametrize("change", ["values", "points", "validity", "anatomy", "affine", "scale", "visibility", "size", "label"])
def test_changed_context_cannot_reuse_stale_panels_or_figure(change):
    anatomy, payload, support = _inputs()
    cache = slices.MriSlicePreviewCache()
    kwargs = {"slice_indices": (12, 12, 12)}
    try:
        _render(anatomy, payload, support, preview_cache=cache, **kwargs)
        if change == "values":
            payload = replace(payload, values=payload.values * .5)
        elif change == "points":
            payload = replace(payload, points=payload.points + [1., 0., 0.])
        elif change == "validity":
            support = replace(support, values=np.nan_to_num(support.values, nan=2.))
        elif change == "anatomy":
            anatomy = replace(anatomy, data=np.flip(anatomy.data, axis=0))
        elif change == "affine":
            affine = np.diag([-1., 1., 1., 1.])
            affine[0, 3] = 23.
            anatomy = replace(anatomy, vox_to_ras=affine, ras_to_vox=np.linalg.inv(affine))
        elif change == "scale":
            kwargs["scalar_range"] = (1., 6.)
        elif change == "visibility":
            kwargs["activation_visible"] = False
        elif change == "size":
            kwargs["figsize"] = (6., 3.)
        elif change == "label":
            kwargs["label"] = "A new condition"
        actual = _render(anatomy, payload, support, preview_cache=cache, **kwargs)
        expected = _render(anatomy, payload, support, **kwargs)
        _assert_equal(actual, expected)
    finally:
        cache.clear()


def test_panel_cache_is_bounded_and_clear_releases_figure_and_anatomy():
    anatomy, payload, support = _inputs()
    cache = slices.MriSlicePreviewCache()
    for index in range(20):
        _render(anatomy, payload, support, preview_cache=cache, slice_indices=(index, 12, index))
    assert len(cache._panels) == cache.MAX_PANELS
    assert 0 < cache._panel_bytes <= cache.MAX_PANEL_BYTES
    assert cache._figure is not None
    cache.clear()
    assert not cache._panels
    assert cache._panel_bytes == 0
    assert cache._figure is None
    assert cache._anatomy is None

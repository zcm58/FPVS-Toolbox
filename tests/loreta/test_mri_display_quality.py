"""Native anatomical sampling and stable display rules for MRI source overlays."""

from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer.volume_slices import (
    MriAnatomyVolume,
    build_mri_slice_panels,
    build_mri_slice_figure,
    load_fsaverage_mri_volume,
    render_mri_orthogonal_slice_image,
)
from Tools.LORETA_Visualizer.source_payloads import SourcePayload, SOURCE_KIND_VOLUME_POINTS
from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform


def test_native_t1_is_preferred_without_building_or_using_half_mm_cache(tmp_path):
    nib = pytest.importorskip("nibabel")
    mri = tmp_path / "fsaverage" / "mri"
    mri.mkdir(parents=True)
    data = np.arange(8 ** 3, dtype=np.float32).reshape(8, 8, 8)
    t1 = nib.MGHImage(data, np.eye(4))
    nib.save(t1, mri / "T1.mgz")
    nib.save(nib.MGHImage(np.ones_like(data), np.eye(4)), mri / "brain.mgz")
    cache = tmp_path / "old-display-cache"
    cache.mkdir()
    sentinel = cache / "brain_0p5mm.nii"
    sentinel.write_bytes(b"preserve existing cache")

    anatomy = load_fsaverage_mri_volume(mri.parent, display_template_cache_dir=cache)

    assert anatomy.source_path == mri / "T1.mgz"
    np.testing.assert_array_equal(anatomy.data, data)
    np.testing.assert_array_equal(anatomy.vox_to_ras, t1.header.get_vox2ras_tkr())
    assert sentinel.read_bytes() == b"preserve existing cache"
    assert set(cache.iterdir()) == {sentinel}


def test_native_brain_is_a_labeled_fallback_when_t1_is_missing(tmp_path):
    nib = pytest.importorskip("nibabel")
    mri = tmp_path / "fsaverage" / "mri"
    mri.mkdir(parents=True)
    data = np.ones((8, 8, 8), dtype=np.float32)
    nib.save(nib.MGHImage(data, np.eye(4)), mri / "brain.mgz")

    anatomy = load_fsaverage_mri_volume(mri.parent)

    assert anatomy.source_path.name == "brain.mgz"
    assert anatomy.data.shape == (8, 8, 8)
    assert anatomy.intensity_window is not None


def test_anatomy_window_and_physical_fov_do_not_change_with_slice_or_plane():
    x, y, z = np.indices((40, 40, 40))
    anatomy_values = np.where(((x - 20) ** 2 + (y - 20) ** 2 + (z - 20) ** 2) < 15 ** 2, 20 + x + z, 0)
    anatomy = MriAnatomyVolume(anatomy_values, np.eye(4), np.eye(4), Path("synthetic.nii"))
    kwargs = dict(anatomy=anatomy, source_voxels=np.array([[20.0, 20.0, 20.0]]), values=np.array([2.0]), scalar_range=(0.0, 3.0))
    first, _ = build_mri_slice_panels(slice_indices=(20, 20, 20), **kwargs)
    second, _ = build_mri_slice_panels(slice_indices=(25, 25, 25), **kwargs)

    assert len({panel.anatomy_window for panel in (*first, *second)}) == 1
    assert len({panel.anatomy.shape for panel in (*first, *second)}) == 1
    for before, after in zip(first, second):
        moving_axis = before.fixed_voxel_axis
        np.testing.assert_array_equal(
            np.delete(before.pixel_to_voxel, moving_axis, axis=0),
            np.delete(after.pixel_to_voxel, moving_axis, axis=0),
        )


def test_sparse_display_selection_keeps_original_grid_smoothing_width():
    anatomy = MriAnatomyVolume(np.ones((65, 65, 65)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    original = np.array([[x, 32.0, 32.0] for x in range(12, 53, 10)])
    selected = original[[0, -1]]
    panels, _ = build_mri_slice_panels(
        anatomy, selected, np.array([4.0, 4.0]), scalar_range=(0.0, 4.0),
        slice_indices=(32, 32, 32), support_source_voxels=original,
        support_valid_source_mask=np.ones(len(original), dtype=bool),
    )

    for panel in panels[:2]:
        rows, columns = np.indices(panel.overlay.shape)
        pixels = np.column_stack((columns.ravel(), rows.ravel(), np.ones(rows.size)))
        coordinates = pixels @ panel.pixel_to_voxel.T
        center = np.all(coordinates == [32.0, 32.0, 32.0], axis=1)
        assert center.sum() == 1
        assert panel.overlay.ravel()[center][0] == 0.0


def test_missing_overlay_holes_have_finite_transparent_alpha():
    anatomy = MriAnatomyVolume(np.ones((9, 9, 9)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    panels, _ = build_mri_slice_panels(
        anatomy, np.array([[3.0, 4.0, 4.0], [4.0, 4.0, 4.0], [5.0, 4.0, 4.0]]),
        np.array([4.0, np.nan, 4.0]), scalar_range=(0.0, 4.0), slice_indices=(4, 4, 4),
    )
    figure = build_mri_slice_figure(panels, scalar_range=(0.0, 4.0), dpi=72)
    try:
        figure.canvas.draw()
        for axis, panel in zip(figure.axes[:3], panels):
            alpha = np.asarray(axis.images[1].get_alpha())
            assert np.all(np.isfinite(alpha))
            assert np.all(alpha[~np.isfinite(panel.overlay)] == 0.0)
    finally:
        figure.clear()


@pytest.mark.parametrize("figsize,grid", [((9.7, 7.8), True), ((12.0, 5.0), False)])
def test_preview_uses_viewport_layout_with_correct_hit_regions(figsize, grid):
    anatomy = MriAnatomyVolume(np.ones((9, 9, 9)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    payload = SourcePayload(
        np.array([[4.0, 4.0, 4.0]]), np.array([2.0]), "Synthetic",
        kind=SOURCE_KIND_VOLUME_POINTS,
    )
    result = render_mri_orthogonal_slice_image(
        payload, display_transform=MeshDisplayTransform.identity(), anatomy=anatomy,
        fsaverage_dir="unused", scalar_range=(0.0, 3.0), figsize=figsize, dpi=100,
    )

    axial, coronal, sagittal = result.hit_regions
    if grid:
        assert sagittal.image_bounds[1] > axial.image_bounds[1] + axial.image_bounds[3]
        assert sagittal.image_bounds[0] == pytest.approx(axial.image_bounds[0])
    else:
        assert axial.image_bounds[0] < coronal.image_bounds[0] < sagittal.image_bounds[0]
        assert sagittal.image_bounds[1] == pytest.approx(axial.image_bounds[1])
    assert len({round(region.image_bounds[2], 6) for region in result.hit_regions}) == 1
    for region in result.hit_regions:
        image_x, image_y = region.image_position(result.peak_voxel)
        np.testing.assert_allclose(region.voxel_at(image_x, image_y), result.peak_voxel)

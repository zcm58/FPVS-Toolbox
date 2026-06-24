from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_POINTS, make_source_payload
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_FSAVERAGE_VOLUME, MeshDisplayTransform
from Tools.LORETA_Visualizer.volume_slices import (
    DEFAULT_MRI_SLICE_GAUSSIAN_NEIGHBORS,
    DEFAULT_MRI_SLICE_FIGURE_DPI,
    DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN,
    DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN,
    DEFAULT_MRI_SLICE_SUPPORT_SIGMA,
    LORETA_DISPLAY_MRI_VOXEL_SIZE_MM,
    MriAnatomyVolume,
    build_mri_slice_panels,
    ensure_loreta_display_mri_template,
    load_fsaverage_mri_volume,
    mri_slice_indices_for_payload,
    payload_points_in_native_space,
    ras_points_to_voxels,
    render_mri_orthogonal_slice_image,
    write_mri_orthogonal_slice_figures,
)
from Tools.LORETA_Visualizer.volume_overlay import DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS


def test_volume_slice_payload_points_map_from_display_to_mri_voxels(tmp_path) -> None:
    fsaverage_dir = _write_tiny_mri(tmp_path)
    anatomy = _load_tiny_display_mri(fsaverage_dir, tmp_path)
    desired_voxels = np.asarray(
        [
            [16.0, 16.0, 18.0],
            [20.0, 16.0, 18.0],
            [16.0, 20.0, 18.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform(
        center=np.asarray([0.0, 0.0, 0.0], dtype=float),
        radius=64.0,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )
    native_points = _ras_points_for_voxels(anatomy, desired_voxels)
    payload = make_source_payload(
        points=transform.to_display_points(native_points, coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME),
        values=np.asarray([1.0, 2.0, 3.0], dtype=float),
        label="Synthetic eLORETA",
        kind=SOURCE_KIND_VOLUME_POINTS,
        normalize_values=False,
    )

    recovered_native_points = payload_points_in_native_space(payload, transform)
    voxels = ras_points_to_voxels(recovered_native_points, anatomy)
    panels, peak_voxel = build_mri_slice_panels(anatomy, voxels, payload.values, scalar_range=(0.0, 3.5))

    assert np.allclose(recovered_native_points, native_points)
    assert np.allclose(voxels, desired_voxels)
    assert peak_voxel == (16, 20, 18)
    assert [panel.label for panel in panels] == ["Axial", "Coronal", "Sagittal"]
    assert all(panel.overlay.shape == panel.anatomy.shape for panel in panels)
    assert max(float(np.max(panel.overlay)) for panel in panels) > 0.0


def test_load_fsaverage_mri_requires_skull_stripped_brain_mgz_and_builds_half_millimeter_display_template(
    tmp_path,
) -> None:
    nib = pytest.importorskip("nibabel")
    fsaverage_dir = tmp_path / "fsaverage"
    mri_dir = fsaverage_dir / "mri"
    mri_dir.mkdir(parents=True)
    nib.save(nib.MGHImage(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), str(mri_dir / "T1.mgz"))

    with pytest.raises(FileNotFoundError, match=r"mri\\brain\.mgz|mri/brain\.mgz"):
        load_fsaverage_mri_volume(fsaverage_dir, display_template_cache_dir=tmp_path / "mri_template_cache")

    nib.save(nib.MGHImage(np.full((8, 8, 8), 2.0, dtype=np.float32), np.eye(4)), str(mri_dir / "brain.mgz"))

    anatomy = load_fsaverage_mri_volume(fsaverage_dir, display_template_cache_dir=tmp_path / "mri_template_cache")

    assert anatomy.source_path.name == "brain_0p5mm.nii"
    assert anatomy.source_path.is_relative_to(tmp_path / "mri_template_cache")
    assert tuple(int(value) for value in anatomy.data.shape) == (16, 16, 16)
    assert np.isclose(np.linalg.norm(anatomy.vox_to_ras[:3, 0]), LORETA_DISPLAY_MRI_VOXEL_SIZE_MM)
    assert float(np.nanmax(anatomy.data)) == 2.0


def test_loreta_display_mri_template_cache_refreshes_when_source_changes(tmp_path) -> None:
    nib = pytest.importorskip("nibabel")
    fsaverage_dir = tmp_path / "fsaverage"
    mri_dir = fsaverage_dir / "mri"
    mri_dir.mkdir(parents=True)
    source_path = mri_dir / "brain.mgz"
    cache_dir = tmp_path / "mri_template_cache"
    nib.save(nib.MGHImage(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), str(source_path))

    first_template = ensure_loreta_display_mri_template(source_path, display_template_cache_dir=cache_dir)
    first_mtime = first_template.stat().st_mtime_ns
    nib.save(nib.MGHImage(np.full((8, 8, 8), 3.0, dtype=np.float32), np.eye(4)), str(source_path))
    second_template = ensure_loreta_display_mri_template(source_path, display_template_cache_dir=cache_dir)

    assert second_template == first_template
    assert second_template.stat().st_mtime_ns >= first_mtime
    assert float(np.nanmax(nib.load(str(second_template)).get_fdata(dtype=np.float32))) == 3.0


def test_volume_slice_panels_crop_to_anatomy_for_high_detail_rendering() -> None:
    data = np.zeros((64, 64, 64), dtype=float)
    data[24:40, 22:42, 26:38] = 100.0
    anatomy = MriAnatomyVolume(
        data=data,
        vox_to_ras=np.eye(4),
        ras_to_vox=np.eye(4),
        source_path=Path("synthetic_brain.nii.gz"),
    )
    source_voxels = np.asarray([[32.0, 32.0, 32.0], [34.0, 33.0, 33.0], [30.0, 31.0, 31.0]], dtype=float)
    values = np.asarray([1.0, 2.0, 3.0], dtype=float)

    panels, _peak_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=(0.0, 3.5),
        slice_indices=(32, 32, 32),
    )

    assert all(panel.anatomy.shape[0] < 64 for panel in panels)
    assert all(panel.anatomy.shape == panel.overlay.shape for panel in panels)
    assert all(panel.anatomy.shape[0] == panel.anatomy.shape[1] for panel in panels)


def test_volume_slice_panels_can_use_standard_indices_independent_of_condition_peak(tmp_path) -> None:
    fsaverage_dir = _write_tiny_mri(tmp_path)
    anatomy = _load_tiny_display_mri(fsaverage_dir, tmp_path)
    source_voxels = np.asarray(
        [
            [6.0, 7.0, 8.0],
            [24.0, 25.0, 26.0],
            [25.0, 25.0, 26.0],
        ],
        dtype=float,
    )
    values = np.asarray([1.0, 5.0, 4.0], dtype=float)

    panels, selected_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=(0.0, 5.0),
        slice_indices=(6, 7, 8),
    )

    assert selected_voxel == (6, 7, 8)
    assert [panel.slice_index for panel in panels] == [8, 7, 6]


def test_volume_slice_indices_can_be_selected_from_reference_payload(tmp_path) -> None:
    fsaverage_dir = _write_tiny_mri(tmp_path)
    anatomy = _load_tiny_display_mri(fsaverage_dir, tmp_path)
    desired_voxels = np.asarray(
        [
            [10.0, 11.0, 12.0],
            [22.0, 23.0, 24.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform(
        center=np.asarray([0.0, 0.0, 0.0], dtype=float),
        radius=64.0,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )
    native_points = _ras_points_for_voxels(anatomy, desired_voxels)
    payload = make_source_payload(
        points=transform.to_display_points(native_points, coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME),
        values=np.asarray([2.0, 7.0], dtype=float),
        label="Reference eLORETA",
        kind=SOURCE_KIND_VOLUME_POINTS,
        normalize_values=False,
    )

    assert mri_slice_indices_for_payload(payload, display_transform=transform, anatomy=anatomy) == (22, 23, 24)


def test_volume_slice_interpolation_uses_transparent_mesh_gaussian_policy() -> None:
    assert DEFAULT_MRI_SLICE_GAUSSIAN_NEIGHBORS == DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS
    assert DEFAULT_MRI_SLICE_SUPPORT_SIGMA == 1.75


def test_render_mri_slice_image_filters_nonpositive_and_out_of_bounds_values(tmp_path) -> None:
    fsaverage_dir = _write_tiny_mri(tmp_path)
    anatomy = _load_tiny_display_mri(fsaverage_dir, tmp_path)
    desired_voxels = np.asarray(
        [
            [16.0, 16.0, 18.0],
            [18.0, 18.0, 19.0],
            [14.0, 14.0, 17.0],
            [80.0, 80.0, 80.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform(
        center=np.asarray([0.0, 0.0, 0.0], dtype=float),
        radius=64.0,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )
    native_points = _ras_points_for_voxels(anatomy, desired_voxels)
    payload = make_source_payload(
        points=transform.to_display_points(native_points, coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME),
        values=np.asarray([2.0, 0.0, -1.0, 4.0], dtype=float),
        label="Synthetic eLORETA",
        kind=SOURCE_KIND_VOLUME_POINTS,
        normalize_values=False,
    )

    result = render_mri_orthogonal_slice_image(
        payload,
        display_transform=transform,
        fsaverage_dir=fsaverage_dir,
        scalar_range=(0.0, 3.5),
        label="Synthetic eLORETA",
        slice_indices=(12, 13, 14),
        anatomy=anatomy,
        dpi=96,
    )

    assert result.rendered_point_count == 1
    assert result.source_point_count == 4
    assert result.peak_voxel == (12, 13, 14)
    assert result.image_rgb.ndim == 3
    assert result.image_rgb.shape[2] == 3
    assert int(np.max(result.image_rgb)) > int(np.min(result.image_rgb))


def test_write_mri_slice_figures_creates_matching_pdf_and_png(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    fsaverage_dir = _write_tiny_mri(tmp_path)
    anatomy = _load_tiny_display_mri(fsaverage_dir, tmp_path)
    desired_voxels = np.asarray(
        [
            [16.0, 16.0, 18.0],
            [18.0, 16.0, 18.0],
            [16.0, 18.0, 18.0],
            [18.0, 18.0, 19.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform(
        center=np.asarray([0.0, 0.0, 0.0], dtype=float),
        radius=64.0,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )
    native_points = _ras_points_for_voxels(anatomy, desired_voxels)
    payload = make_source_payload(
        points=transform.to_display_points(native_points, coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME),
        values=np.asarray([1.0, 2.0, 3.0, 2.5], dtype=float),
        label="Synthetic eLORETA",
        kind=SOURCE_KIND_VOLUME_POINTS,
        normalize_values=False,
    )

    pdf_path, png_path = write_mri_orthogonal_slice_figures(
        tmp_path / "mri_slices.pdf",
        payload=payload,
        display_transform=transform,
        fsaverage_dir=fsaverage_dir,
        scalar_range=(0.0, 3.5),
        label="Synthetic eLORETA",
        anatomy=anatomy,
    )

    assert pdf_path.is_file()
    assert png_path.is_file()
    with Image.open(png_path) as image:
        expected_size = (
            int(round(DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN * DEFAULT_MRI_SLICE_FIGURE_DPI)),
            int(round(DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN * DEFAULT_MRI_SLICE_FIGURE_DPI)),
        )
        assert image.size == expected_size
        pixels = np.asarray(image)
    assert int(np.max(pixels)) > int(np.min(pixels))


def _write_tiny_mri(tmp_path):
    nib = pytest.importorskip("nibabel")
    fsaverage_dir = tmp_path / "fsaverage"
    mri_dir = fsaverage_dir / "mri"
    mri_dir.mkdir(parents=True)
    x, y, z = np.meshgrid(
        np.linspace(-1.0, 1.0, 32),
        np.linspace(-1.0, 1.0, 32),
        np.linspace(-1.0, 1.0, 32),
        indexing="ij",
    )
    anatomy = np.exp(-3.0 * (x**2 + y**2 + z**2))
    image = nib.MGHImage(anatomy.astype(np.float32), np.eye(4))
    nib.save(image, str(mri_dir / "brain.mgz"))
    return fsaverage_dir


def _load_tiny_display_mri(fsaverage_dir: Path, tmp_path: Path) -> MriAnatomyVolume:
    return load_fsaverage_mri_volume(
        fsaverage_dir,
        display_template_cache_dir=tmp_path / "mri_template_cache",
    )


def _ras_points_for_voxels(anatomy: MriAnatomyVolume, voxels: np.ndarray) -> np.ndarray:
    voxel_values = np.asarray(voxels, dtype=float)
    homogenous = np.column_stack((voxel_values, np.ones(len(voxel_values), dtype=float)))
    return (anatomy.vox_to_ras @ homogenous.T).T[:, :3].astype(float)

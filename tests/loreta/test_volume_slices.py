from __future__ import annotations

from pathlib import Path
import os

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
    build_mri_slice_figure,
    ensure_loreta_display_mri_template,
    load_fsaverage_mri_volume,
    mri_slice_indices_for_payload,
    nearest_prepared_source_value,
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


def test_display_mri_writer_does_not_follow_predictable_staging_hardlink(tmp_path) -> None:
    from Tools.LORETA_Visualizer.volume_slices import _write_loreta_display_mri_template
    nib = pytest.importorskip("nibabel")
    source = tmp_path / "brain.mgz"
    nib.save(nib.MGHImage(np.full((4, 4, 4), 3.0, dtype=np.float32), np.eye(4)), str(source))
    target = tmp_path / "output" / "brain_0p5mm.nii"
    target.parent.mkdir()
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"outside content")
    staging = target.with_name("brain_0p5mm.tmp.nii")
    os.link(victim, staging)

    _write_loreta_display_mri_template(source, target)

    assert victim.read_bytes() == b"outside content"
    assert staging.read_bytes() == b"outside content"
    result = nib.load(str(target))
    assert result.shape == (8, 8, 8)
    assert np.all(result.get_fdata(dtype=np.float32) == 3.0)
    assert np.allclose(result.affine, nib.load(str(source)).header.get_vox2ras_tkr() @ np.diag([0.5, 0.5, 0.5, 1.0]))
    assert set(target.parent.iterdir()) == {target, staging}


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
    # MGH tkregister voxel axes are L/I/A: axial fixes voxel axis 1,
    # coronal fixes voxel axis 2, and sagittal fixes voxel axis 0.
    assert [panel.slice_index for panel in panels] == [7, 8, 6]


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
    assert len(result.hit_regions) == 3
    for region in result.hit_regions:
        x, y = region.image_position(result.peak_voxel)
        assert np.allclose(region.voxel_at(x, y), result.peak_voxel)


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
        assert image.info["Description"] == "Slice coordinates: fsaverage MRI RAS, millimetres."
        expected_size = (
            int(round(DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN * DEFAULT_MRI_SLICE_FIGURE_DPI)),
            int(round(DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN * DEFAULT_MRI_SLICE_FIGURE_DPI)),
        )
        assert image.size == expected_size
        pixels = np.asarray(image)
    assert int(np.max(pixels)) > int(np.min(pixels))


def test_slice_planes_follow_native_fsaverage_affine_and_neurological_orientation() -> None:
    x, y, z = np.indices((5, 6, 7))
    data = 100 * x + 10 * y + z
    affine = np.asarray([
        [-2.0, 0.0, 0.0, 8.0],
        [0.0, 0.0, 2.0, -6.0],
        [0.0, -2.0, 0.0, 10.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    anatomy = MriAnatomyVolume(data, affine, np.linalg.inv(affine), Path("synthetic.nii"))
    panels, selected = build_mri_slice_panels(
        anatomy, np.asarray([[2.0, 3.0, 4.0]]), np.asarray([2.0]),
        scalar_range=(0.0, 3.0), slice_indices=(2, 3, 4),
    )

    assert selected == (2, 3, 4)
    axial, coronal, sagittal = panels
    assert np.array_equal(axial.anatomy, data[:, 3, :].T[::-1, ::-1])
    assert np.array_equal(coronal.anatomy, data[:, :, 4].T[:, ::-1])
    assert np.array_equal(sagittal.anatomy, data[2, :, :])
    assert [panel.ras_coordinate_mm for panel in panels] == [4.0, 2.0, 4.0]
    assert [panel.fixed_voxel_axis for panel in panels] == [1, 2, 0]
    assert axial.orientation_labels == ("L", "R", "A", "P")
    assert coronal.orientation_labels == ("L", "R", "S", "I")
    assert sagittal.orientation_labels == ("P", "A", "S", "I")
    for panel in panels:
        for row in (0, panel.anatomy.shape[0] - 1):
            for column in (0, panel.anatomy.shape[1] - 1):
                voxel = np.rint(panel.pixel_to_voxel @ [column, row, 1.0]).astype(int)
                assert panel.anatomy[row, column] == data[tuple(voxel)]


def test_slice_planes_reject_oblique_affine_instead_of_mislabeling_anatomy() -> None:
    affine = np.eye(4)
    angle = np.pi / 4
    affine[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    anatomy = MriAnatomyVolume(np.ones((6, 6, 6)), affine, np.linalg.inv(affine), Path("oblique.nii"))
    with pytest.raises(ValueError, match="axis-aligned"):
        build_mri_slice_panels(
            anatomy, np.asarray([[2.0, 2.0, 2.0]]), np.asarray([2.0]), scalar_range=(0.0, 3.0),
        )


def test_grid_inspection_reads_original_signed_value_without_display_clipping() -> None:
    payload = make_source_payload(
        points=np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        values=np.asarray([8.0, -3.0]), label="Synthetic grid", kind=SOURCE_KIND_VOLUME_POINTS,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME, normalize_values=False,
    )
    transform = MeshDisplayTransform(np.zeros(3), 1.0, native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME)
    value, distance = nearest_prepared_source_value(payload, (4.0, 5.0, 6.5), display_transform=transform)
    assert value == -3.0
    assert distance == 0.5


def test_slice_navigation_maps_cropped_anatomy_back_to_original_voxels() -> None:
    data = np.zeros((64, 64, 64))
    data[25:40, 27:38, 28:36] = 1.0
    anatomy = MriAnatomyVolume(data, np.eye(4), np.eye(4), Path("cropped.nii"))
    panels, _ = build_mri_slice_panels(
        anatomy, np.asarray([[32.0, 32.0, 32.0]]), np.asarray([2.0]),
        scalar_range=(0.0, 3.0), slice_indices=(32, 32, 32),
    )
    for panel in panels:
        assert min(panel.anatomy.shape) < 64
        nonzero = np.argwhere(panel.anatomy > 0.0)
        for row, column in nonzero:
            voxel = np.rint(panel.pixel_to_voxel @ [column, row, 1.0]).astype(int)
            assert data[tuple(voxel)] == 1.0


def test_render_inspection_reads_unmasked_grid_without_changing_display_values() -> None:
    anatomy = MriAnatomyVolume(np.ones((8, 8, 8)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    transform = MeshDisplayTransform(np.zeros(3), 1.0, native_coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME)
    raw_payload = make_source_payload(
        points=np.asarray([[3.0, 3.0, 3.0], [5.0, 5.0, 5.0]]), values=np.asarray([8.0, -3.0]),
        label="Raw grid", kind=SOURCE_KIND_VOLUME_POINTS,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME, normalize_values=False,
    )
    display_payload = make_source_payload(
        points=raw_payload.points[:1], values=raw_payload.values[:1], label="Display grid",
        kind=SOURCE_KIND_VOLUME_POINTS, coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME, normalize_values=False,
    )
    result = render_mri_orthogonal_slice_image(
        display_payload, inspection_payload=raw_payload, display_transform=transform,
        anatomy=anatomy, fsaverage_dir=Path("unused"), scalar_range=(0.0, 3.0),
        slice_indices=(5, 5, 5), dpi=72,
    )
    assert result.rendered_point_count == 1
    assert result.nearest_source_value == -3.0
    assert result.nearest_source_distance_mm == 0.0
    assert result.inspection_uses_unfiltered_payload
    assert result.cursor_ras_mm == (5.0, 5.0, 5.0)
    assert np.array_equal(raw_payload.values, [8.0, -3.0])


@pytest.mark.parametrize("font_family", ["Arial", "DejaVu Sans"])
@pytest.mark.parametrize("dpi", [96, 600])
@pytest.mark.parametrize("shape", [(8, 8, 8), (8, 32, 8)])
@pytest.mark.parametrize("label", ["", "Synthetic source map"])
def test_coordinate_titles_and_colorbar_fit_publication_width(monkeypatch, font_family, dpi, shape, label) -> None:
    from Main_App.exports import figure_style

    # Exercise Linux's wider fallback even on a machine with Arial installed.
    # This changes test rendering only; publication defaults remain Arial.
    monkeypatch.setattr(figure_style, "FIGURE_FONT_FAMILY", font_family)
    affine = np.eye(4)
    affine[:3, 3] = 120.5
    anatomy = MriAnatomyVolume(np.ones(shape), affine, np.linalg.inv(affine), Path("synthetic.nii"))
    panels, _ = build_mri_slice_panels(
        anatomy, np.asarray([[4.0, 4.0, 4.0]]), np.asarray([2.0]), scalar_range=(0.0, 3.5),
    )
    figure = build_mri_slice_figure(panels, scalar_range=(0.0, 3.5), dpi=dpi, label=label)
    try:
        for tick in figure.axes[3].get_yticklabels():
            tick.set_fontfamily(font_family)
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        titles = [axis.title.get_bbox_patch().get_window_extent(renderer) for axis in figure.axes[:3]]
        assert titles[0].x1 < titles[1].x0
        assert titles[1].x1 < titles[2].x0
        for title in titles:
            assert 0 <= title.x0 < title.x1 <= figure.bbox.x1
            assert 0 <= title.y0 < title.y1 <= figure.bbox.y1
        if label:
            assert max(title.y1 for title in titles) < figure._suptitle.get_window_extent(renderer).y0
        for tick in figure.axes[3].get_yticklabels():
            assert tick.get_window_extent(renderer).x1 <= figure.bbox.x1
    finally:
        figure.clear()


def test_slice_worker_uses_agg_canvas_without_creating_a_pyplot_manager(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib._pylab_helpers import Gcf

    def reject_backend_switch(*_args, **_kwargs):
        pytest.fail("MRI rendering must not switch the application Matplotlib backend.")

    monkeypatch.setattr(matplotlib, "use", reject_backend_switch)
    managers_before = Gcf.get_all_fig_managers()
    anatomy = MriAnatomyVolume(np.ones((8, 8, 8)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    panels, _ = build_mri_slice_panels(
        anatomy, np.asarray([[4.0, 4.0, 4.0]]), np.asarray([2.0]), scalar_range=(0.0, 3.5),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        figure = executor.submit(build_mri_slice_figure, panels, scalar_range=(0.0, 3.5), dpi=72).result()
    try:
        assert isinstance(figure.canvas, FigureCanvasAgg)
        assert Gcf.get_all_fig_managers() == managers_before
    finally:
        figure.clear()


def test_slice_figure_orientation_ignores_global_lower_image_origin() -> None:
    import matplotlib

    anatomy = MriAnatomyVolume(np.ones((8, 8, 8)), np.eye(4), np.eye(4), Path("synthetic.nii"))
    panels, _ = build_mri_slice_panels(
        anatomy, np.asarray([[4.0, 4.0, 4.0]]), np.asarray([2.0]), scalar_range=(0.0, 3.5),
    )
    with matplotlib.rc_context({"image.origin": "lower"}):
        figure = build_mri_slice_figure(panels, scalar_range=(0.0, 3.5), dpi=72)
        try:
            for axis in figure.axes[:3]:
                assert len(axis.images) == 2
                assert all(image.origin == "upper" for image in axis.images)
                assert axis.yaxis_inverted()
            assert matplotlib.rcParams["image.origin"] == "lower"
        finally:
            figure.clear()


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

"""MRI orthogonal slice rendering for prepared volume source payloads.

This module is a display/export adapter. It loads anatomical fsaverage MRI
context, maps already-prepared volume payload points into MRI voxel space, and
interpolates those existing values for visualization only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    apply_matplotlib_figure_style,
    figure_text_kwargs,
)

from Tools.LORETA_Visualizer.scalar_fields import LORETA_SMOOTH_SCALAR_COLORS
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_POINTS, SourcePayload
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    COORDINATE_SPACE_FSAVERAGE_VOLUME,
    MeshDisplayTransform,
)
from Tools.LORETA_Visualizer.volume_overlay import DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4
ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM = 140.0
DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN = ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM / MM_PER_INCH
DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN = 3.2
DEFAULT_MRI_SLICE_RENDER_DPI = 300
DEFAULT_MRI_SLICE_FIGURE_DPI = FIGURE_EXPORT_DPI
DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE = 0.0
DEFAULT_MRI_SLICE_GAUSSIAN_NEIGHBORS = DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS
DEFAULT_MRI_SLICE_SUPPORT_SIGMA = 1.75
DEFAULT_MRI_SLICE_CROP_PADDING_FRACTION = 0.10
DEFAULT_MRI_SLICE_CROP_MIN_PADDING_PIXELS = 8

PlaneName = Literal["axial", "coronal", "sagittal"]

FSAVERAGE_MRI_RELATIVE_PATH = Path("mri") / "brain.mgz"


@dataclass(frozen=True)
class MriAnatomyVolume:
    """Loaded MRI anatomy in the same RAS frame used by fsaverage surfaces."""

    data: np.ndarray
    vox_to_ras: np.ndarray
    ras_to_vox: np.ndarray
    source_path: Path


@dataclass(frozen=True)
class MriSlicePanel:
    """One orthogonal MRI panel plus its display-only source overlay."""

    label: str
    plane: PlaneName
    anatomy: np.ndarray
    overlay: np.ndarray
    slice_index: int


@dataclass(frozen=True)
class MriSliceRenderResult:
    """Rendered MRI slice image and the voxel-space diagnostics behind it."""

    image_rgb: np.ndarray
    peak_voxel: tuple[int, int, int]
    scalar_range: tuple[float, float]
    source_point_count: int
    rendered_point_count: int


def find_fsaverage_mri_path(fsaverage_dir: str | Path) -> Path | None:
    """Return the required fsaverage MRI anatomy file if it exists."""

    candidate = Path(fsaverage_dir) / FSAVERAGE_MRI_RELATIVE_PATH
    return candidate if candidate.is_file() else None


def load_fsaverage_mri_volume(fsaverage_dir: str | Path) -> MriAnatomyVolume:
    """Load the fsaverage MRI anatomy used as the slice backdrop."""

    mri_path = find_fsaverage_mri_path(fsaverage_dir)
    if mri_path is None:
        expected_path = Path(fsaverage_dir) / FSAVERAGE_MRI_RELATIVE_PATH
        raise FileNotFoundError(f"Required fsaverage MRI anatomy is missing: {expected_path}.")

    try:
        import nibabel as nib
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("nibabel is required to render MRI slice figures.") from exc

    image = nib.load(str(mri_path))
    data = np.asarray(image.dataobj, dtype=float)
    data = np.squeeze(data)
    if data.ndim != 3:
        raise ValueError(f"Expected a 3D MRI volume, found shape {data.shape!r} in {mri_path}.")
    if not np.any(np.isfinite(data)):
        raise ValueError(f"MRI volume contains no finite voxels: {mri_path}.")

    vox_to_ras = _vox_to_ras_transform(image)
    try:
        ras_to_vox = np.linalg.inv(vox_to_ras)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"MRI voxel-to-RAS transform is singular: {mri_path}.") from exc

    return MriAnatomyVolume(
        data=data.astype(float, copy=False),
        vox_to_ras=np.asarray(vox_to_ras, dtype=float),
        ras_to_vox=np.asarray(ras_to_vox, dtype=float),
        source_path=mri_path,
    )


def render_mri_orthogonal_slice_image(
    payload: SourcePayload,
    *,
    display_transform: MeshDisplayTransform,
    fsaverage_dir: str | Path,
    scalar_range: tuple[float, float],
    label: str = "",
    activation_visible: bool = True,
    anatomy: MriAnatomyVolume | None = None,
    slice_indices: tuple[int, int, int] | None = None,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_RENDER_DPI,
) -> MriSliceRenderResult:
    """Render an RGB MRI slice image for the embedded GUI."""

    anatomy = anatomy or load_fsaverage_mri_volume(fsaverage_dir)
    native_points = payload_points_in_native_space(payload, display_transform)
    source_voxels = ras_points_to_voxels(native_points, anatomy)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    source_voxels, values = _valid_visible_source_voxels(
        source_voxels,
        values,
        shape=anatomy.data.shape,
        min_visible_value=DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE,
    )
    panels, peak_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=scalar_range,
        slice_indices=slice_indices,
    )
    image_rgb = draw_mri_slice_figure_to_rgb(
        panels,
        scalar_range=scalar_range,
        label=label,
        activation_visible=activation_visible,
        figsize=figsize,
        dpi=dpi,
    )
    return MriSliceRenderResult(
        image_rgb=image_rgb,
        peak_voxel=peak_voxel,
        scalar_range=(float(scalar_range[0]), float(scalar_range[1])),
        source_point_count=int(len(payload.points)),
        rendered_point_count=int(len(source_voxels)),
    )


def write_mri_orthogonal_slice_figures(
    output_path: str | Path,
    *,
    payload: SourcePayload,
    display_transform: MeshDisplayTransform,
    fsaverage_dir: str | Path,
    scalar_range: tuple[float, float],
    label: str = "",
    activation_visible: bool = True,
    anatomy: MriAnatomyVolume | None = None,
    slice_indices: tuple[int, int, int] | None = None,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_FIGURE_DPI,
) -> tuple[Path, Path]:
    """Write matched publication-ready PDF and PNG orthogonal MRI slice figures."""

    anatomy = anatomy or load_fsaverage_mri_volume(fsaverage_dir)
    native_points = payload_points_in_native_space(payload, display_transform)
    source_voxels = ras_points_to_voxels(native_points, anatomy)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    source_voxels, values = _valid_visible_source_voxels(
        source_voxels,
        values,
        shape=anatomy.data.shape,
        min_visible_value=DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE,
    )
    panels, _peak_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=scalar_range,
        slice_indices=slice_indices,
    )
    figure = build_mri_slice_figure(
        panels,
        scalar_range=scalar_range,
        label=label,
        activation_visible=activation_visible,
        figsize=figsize,
        dpi=dpi,
    )
    pdf_path, png_path = _paired_export_paths(output_path)
    try:
        figure.savefig(pdf_path, format="pdf", dpi=dpi, facecolor=figure.get_facecolor(), transparent=False)
        figure.savefig(png_path, format="png", dpi=dpi, facecolor=figure.get_facecolor(), transparent=False)
    finally:
        import matplotlib.pyplot as plt

        plt.close(figure)
    return pdf_path, png_path


def payload_points_in_native_space(
    payload: SourcePayload,
    display_transform: MeshDisplayTransform,
) -> np.ndarray:
    """Return payload points in fsaverage native RAS coordinates."""

    if payload.kind != SOURCE_KIND_VOLUME_POINTS:
        raise ValueError("MRI slice rendering requires a volume point source payload.")
    points = np.asarray(payload.points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Source payload points must be an N x 3 array.")
    if len(points) == 0:
        raise ValueError("Source payload contains no points to render.")

    coordinate_space = str(payload.coordinate_space)
    if coordinate_space == COORDINATE_SPACE_DISPLAY:
        return display_transform.from_display_points(points)
    if coordinate_space in {
        display_transform.native_coordinate_space,
        COORDINATE_SPACE_FSAVERAGE,
        COORDINATE_SPACE_FSAVERAGE_VOLUME,
    }:
        return points.astype(float)
    raise ValueError(
        f"Cannot render MRI slices for payload coordinate space {coordinate_space!r} "
        f"with a {display_transform.native_coordinate_space!r} display transform."
    )


def ras_points_to_voxels(points: np.ndarray, anatomy: MriAnatomyVolume) -> np.ndarray:
    """Transform native RAS source points into floating MRI voxel indices."""

    source_points = np.asarray(points, dtype=float)
    if source_points.ndim != 2 or source_points.shape[1] != 3:
        raise ValueError("RAS points must be an N x 3 array.")
    homogenous = np.column_stack((source_points, np.ones(len(source_points), dtype=float)))
    return (anatomy.ras_to_vox @ homogenous.T).T[:, :3].astype(float)


def mri_slice_indices_for_payload(
    payload: SourcePayload,
    *,
    display_transform: MeshDisplayTransform,
    anatomy: MriAnatomyVolume,
) -> tuple[int, int, int]:
    """Return the voxel triplet used to standardize orthogonal MRI slices."""

    native_points = payload_points_in_native_space(payload, display_transform)
    source_voxels = ras_points_to_voxels(native_points, anatomy)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    source_voxels, values = _valid_visible_source_voxels(
        source_voxels,
        values,
        shape=anatomy.data.shape,
        min_visible_value=DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE,
    )
    return _peak_voxel(source_voxels, values, shape=anatomy.data.shape)


def build_mri_slice_panels(
    anatomy: MriAnatomyVolume,
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    scalar_range: tuple[float, float],
    slice_indices: tuple[int, int, int] | None = None,
) -> tuple[tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel], tuple[int, int, int]]:
    """Build axial/coronal/sagittal anatomy and overlay panels."""

    source_voxels, source_values = _valid_visible_source_voxels(
        source_voxels,
        values,
        shape=anatomy.data.shape,
        min_visible_value=DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE,
    )
    peak_voxel = (
        _peak_voxel(source_voxels, source_values, shape=anatomy.data.shape)
        if slice_indices is None
        else _clip_slice_indices(slice_indices, shape=anatomy.data.shape)
    )
    sigma = _source_voxel_sigma(source_voxels)
    panels = (
        _slice_panel(
            anatomy.data,
            source_voxels,
            source_values,
            plane="axial",
            fixed_index=peak_voxel[2],
            scalar_range=scalar_range,
            sigma=sigma,
        ),
        _slice_panel(
            anatomy.data,
            source_voxels,
            source_values,
            plane="coronal",
            fixed_index=peak_voxel[1],
            scalar_range=scalar_range,
            sigma=sigma,
        ),
        _slice_panel(
            anatomy.data,
            source_voxels,
            source_values,
            plane="sagittal",
            fixed_index=peak_voxel[0],
            scalar_range=scalar_range,
            sigma=sigma,
        ),
    )
    return panels, peak_voxel


def draw_mri_slice_figure_to_rgb(
    panels: tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel],
    *,
    scalar_range: tuple[float, float],
    label: str = "",
    activation_visible: bool = True,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_RENDER_DPI,
) -> np.ndarray:
    """Draw panels to an RGB image array."""

    figure = build_mri_slice_figure(
        panels,
        scalar_range=scalar_range,
        label=label,
        activation_visible=activation_visible,
        figsize=figsize,
        dpi=dpi,
    )
    try:
        figure.canvas.draw()
        rgba = np.asarray(figure.canvas.buffer_rgba())
        return np.asarray(rgba[..., :3], dtype=np.uint8).copy()
    finally:
        import matplotlib.pyplot as plt

        plt.close(figure)


def build_mri_slice_figure(
    panels: tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel],
    *,
    scalar_range: tuple[float, float],
    label: str = "",
    activation_visible: bool = True,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_FIGURE_DPI,
):
    """Build a Matplotlib orthogonal MRI slice figure."""

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.cm import ScalarMappable

    apply_matplotlib_figure_style()
    cmap = LinearSegmentedColormap.from_list("fpvs_loreta_activation", list(LORETA_SMOOTH_SCALAR_COLORS))
    vmin, vmax = _valid_scalar_range(scalar_range)

    figure = plt.figure(figsize=figsize, dpi=dpi, facecolor="black")
    grid = figure.add_gridspec(
        1,
        4,
        width_ratios=(1.0, 1.0, 1.0, 0.055),
        left=0.03,
        right=0.965,
        top=0.84 if label else 0.91,
        bottom=0.12,
        wspace=0.08,
    )
    if label:
        figure.suptitle(
            label,
            color="white",
            y=0.965,
            **figure_text_kwargs("condition_label"),
        )

    overlay_artist = None
    for index, panel in enumerate(panels):
        axis = figure.add_subplot(grid[0, index])
        axis.set_facecolor("black")
        axis.imshow(_normalize_anatomy(panel.anatomy), cmap="gray", interpolation="lanczos")
        if activation_visible:
            masked_overlay = np.ma.masked_where(~np.isfinite(panel.overlay) | (panel.overlay <= vmin), panel.overlay)
            overlay_alpha = np.ma.masked_array(
                np.clip((panel.overlay - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0) * 0.80,
                mask=np.ma.getmaskarray(masked_overlay),
            )
        else:
            masked_overlay = np.ma.masked_all(panel.overlay.shape)
            overlay_alpha = 0.0
        overlay_artist = axis.imshow(
            masked_overlay,
            cmap=cmap,
            norm=Normalize(vmin=vmin, vmax=vmax),
            interpolation="bilinear",
            alpha=overlay_alpha,
        )
        axis.set_title(
            panel.label,
            color="#0B66FF",
            pad=8,
            bbox={
                "boxstyle": "round,pad=0.30,rounding_size=0.75",
                "facecolor": "white",
                "edgecolor": "white",
                "linewidth": 0.0,
            },
            **figure_text_kwargs("panel_label"),
        )
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)

    color_axis = figure.add_subplot(grid[0, 3])
    color_axis.set_facecolor("black")
    mappable = overlay_artist or ScalarMappable(norm=Normalize(vmin=vmin, vmax=vmax), cmap=cmap)
    colorbar = figure.colorbar(mappable, cax=color_axis)
    colorbar.outline.set_edgecolor("white")
    colorbar.ax.tick_params(colors="white", length=2)
    for tick_label in colorbar.ax.get_yticklabels():
        tick_label.set_color("white")
        tick_label.set_fontfamily("Arial")
    return figure


def _vox_to_ras_transform(image: object) -> np.ndarray:
    header = getattr(image, "header", None)
    get_tkr = getattr(header, "get_vox2ras_tkr", None)
    if callable(get_tkr):
        transform = get_tkr()
        if transform is not None:
            return np.asarray(transform, dtype=float)
    return np.asarray(getattr(image, "affine"), dtype=float)


def _valid_visible_source_voxels(
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    shape: tuple[int, int, int],
    min_visible_value: float,
) -> tuple[np.ndarray, np.ndarray]:
    voxels = np.asarray(source_voxels, dtype=float)
    source_values = np.asarray(values, dtype=float).reshape(-1)
    if voxels.ndim != 2 or voxels.shape[1] != 3:
        raise ValueError("Source voxel coordinates must be an N x 3 array.")
    if len(voxels) != len(source_values):
        raise ValueError("Source voxel coordinates and values must have matching lengths.")
    finite = np.isfinite(source_values) & np.all(np.isfinite(voxels), axis=1)
    bounds = np.asarray(shape, dtype=float) - 1.0
    inside = np.all((voxels >= 0.0) & (voxels <= bounds), axis=1)
    visible = source_values > float(min_visible_value)
    keep = finite & inside & visible
    if not np.any(keep):
        raise ValueError("No positive source values fall inside the MRI anatomy volume.")
    return voxels[keep].astype(float), source_values[keep].astype(float)


def _peak_voxel(source_voxels: np.ndarray, values: np.ndarray, *, shape: tuple[int, int, int]) -> tuple[int, int, int]:
    peak_index = int(np.nanargmax(values))
    rounded = np.rint(source_voxels[peak_index]).astype(int)
    clipped = np.clip(rounded, 0, np.asarray(shape, dtype=int) - 1)
    return int(clipped[0]), int(clipped[1]), int(clipped[2])


def _source_voxel_sigma(source_voxels: np.ndarray) -> float:
    if len(source_voxels) < 2:
        return 2.0
    try:
        from scipy.spatial import cKDTree
    except (ImportError, ModuleNotFoundError):
        return 3.0

    tree = cKDTree(source_voxels)
    distances, _indices = tree.query(source_voxels, k=min(2, len(source_voxels)))
    distances = np.asarray(distances, dtype=float)
    nearest = distances[:, 1] if distances.ndim == 2 and distances.shape[1] > 1 else distances
    finite = nearest[np.isfinite(nearest) & (nearest > 1e-9)]
    spacing = float(np.nanmedian(finite)) if len(finite) else 4.0
    return max(spacing * 0.65, 1.5)


def _clip_slice_indices(slice_indices: tuple[int, int, int], *, shape: tuple[int, int, int]) -> tuple[int, int, int]:
    requested = np.asarray(slice_indices, dtype=int).reshape(3)
    clipped = np.clip(requested, 0, np.asarray(shape, dtype=int) - 1)
    return int(clipped[0]), int(clipped[1]), int(clipped[2])


def _slice_panel(
    anatomy_data: np.ndarray,
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    plane: PlaneName,
    fixed_index: int,
    scalar_range: tuple[float, float],
    sigma: float,
) -> MriSlicePanel:
    raw_anatomy = _raw_anatomy_plane(anatomy_data, plane=plane, fixed_index=fixed_index)
    raw_overlay = _raw_overlay_plane(
        anatomy_data.shape,
        source_voxels,
        values,
        plane=plane,
        fixed_index=fixed_index,
        scalar_range=scalar_range,
        sigma=sigma,
    )
    anatomy_plane, overlay_plane = _crop_panel_to_anatomy(
        _orient_plane(raw_anatomy),
        _orient_plane(raw_overlay),
    )
    return MriSlicePanel(
        label=_plane_label(plane),
        plane=plane,
        anatomy=anatomy_plane,
        overlay=overlay_plane,
        slice_index=int(fixed_index),
    )


def _raw_anatomy_plane(anatomy_data: np.ndarray, *, plane: PlaneName, fixed_index: int) -> np.ndarray:
    if plane == "axial":
        return anatomy_data[:, :, fixed_index]
    if plane == "coronal":
        return anatomy_data[:, fixed_index, :]
    return anatomy_data[fixed_index, :, :]


def _raw_overlay_plane(
    shape: tuple[int, int, int],
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    plane: PlaneName,
    fixed_index: int,
    scalar_range: tuple[float, float],
    sigma: float,
) -> np.ndarray:
    coordinate_grid, raw_shape = _plane_coordinate_grid(shape, plane=plane, fixed_index=fixed_index)
    interpolated = _gaussian_interpolated_values(
        coordinate_grid,
        source_voxels,
        values,
        sigma=sigma,
        scalar_range=scalar_range,
    )
    return interpolated.reshape(raw_shape)


def _plane_coordinate_grid(
    shape: tuple[int, int, int],
    *,
    plane: PlaneName,
    fixed_index: int,
) -> tuple[np.ndarray, tuple[int, int]]:
    nx, ny, nz = (int(value) for value in shape)
    if plane == "axial":
        x_axis = np.arange(nx, dtype=float)
        y_axis = np.arange(ny, dtype=float)
        x, y = np.meshgrid(x_axis, y_axis, indexing="ij")
        coords = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, float(fixed_index))))
        return coords, (nx, ny)
    if plane == "coronal":
        x_axis = np.arange(nx, dtype=float)
        z_axis = np.arange(nz, dtype=float)
        x, z = np.meshgrid(x_axis, z_axis, indexing="ij")
        coords = np.column_stack((x.ravel(), np.full(x.size, float(fixed_index)), z.ravel()))
        return coords, (nx, nz)
    y_axis = np.arange(ny, dtype=float)
    z_axis = np.arange(nz, dtype=float)
    y, z = np.meshgrid(y_axis, z_axis, indexing="ij")
    coords = np.column_stack((np.full(y.size, float(fixed_index)), y.ravel(), z.ravel()))
    return coords, (ny, nz)


def _gaussian_interpolated_values(
    grid_points: np.ndarray,
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    sigma: float,
    scalar_range: tuple[float, float],
) -> np.ndarray:
    try:
        from scipy.spatial import cKDTree
    except (ImportError, ModuleNotFoundError):
        return _nearest_values(grid_points, source_voxels, values, scalar_range=scalar_range)

    neighbor_count = max(1, min(DEFAULT_MRI_SLICE_GAUSSIAN_NEIGHBORS, len(source_voxels)))
    tree = cKDTree(source_voxels)
    distances, indices = tree.query(
        grid_points,
        k=neighbor_count,
        distance_upper_bound=float(sigma) * DEFAULT_MRI_SLICE_SUPPORT_SIGMA,
    )
    distances = np.asarray(distances, dtype=float)
    indices = np.asarray(indices, dtype=np.int64)
    if neighbor_count == 1:
        distances = distances.reshape(-1, 1)
        indices = indices.reshape(-1, 1)
    valid = np.isfinite(distances) & (indices >= 0) & (indices < len(source_voxels))
    weights = np.zeros_like(distances, dtype=float)
    weights[valid] = np.exp(-0.5 * np.square(distances[valid] / float(sigma)))
    neighbor_values = np.zeros_like(distances, dtype=float)
    neighbor_values[valid] = values[indices[valid]]
    weight_sums = np.sum(weights, axis=1)
    output = np.zeros(len(grid_points), dtype=float)
    nonzero = weight_sums > 0.0
    output[nonzero] = np.sum(weights[nonzero] * neighbor_values[nonzero], axis=1) / weight_sums[nonzero]
    vmin, vmax = _valid_scalar_range(scalar_range)
    return np.clip(output, vmin, vmax)


def _nearest_values(
    grid_points: np.ndarray,
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    scalar_range: tuple[float, float],
) -> np.ndarray:
    distances = np.linalg.norm(grid_points[:, None, :] - source_voxels[None, :, :], axis=2)
    nearest = np.argmin(distances, axis=1)
    output = values[nearest]
    vmin, vmax = _valid_scalar_range(scalar_range)
    return np.clip(output, vmin, vmax)


def _orient_plane(plane: np.ndarray) -> np.ndarray:
    return np.flipud(np.asarray(plane, dtype=float).T)


def _crop_panel_to_anatomy(anatomy: np.ndarray, overlay: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    anatomy_values = np.asarray(anatomy, dtype=float)
    overlay_values = np.asarray(overlay, dtype=float)
    mask = _anatomy_content_mask(anatomy_values)
    if mask is None:
        return anatomy_values, overlay_values
    row_bounds, col_bounds = _square_crop_bounds(mask)
    row_start, row_stop = row_bounds
    col_start, col_stop = col_bounds
    return (
        anatomy_values[row_start:row_stop, col_start:col_stop],
        overlay_values[row_start:row_stop, col_start:col_stop],
    )


def _anatomy_content_mask(anatomy: np.ndarray) -> np.ndarray | None:
    finite = np.asarray(anatomy, dtype=float)
    valid = finite[np.isfinite(finite)]
    if len(valid) == 0:
        return None
    max_value = float(np.nanmax(valid))
    min_value = float(np.nanmin(valid))
    if not np.isfinite(max_value) or max_value <= min_value:
        return None
    threshold = min_value + (max_value - min_value) * 0.025
    mask = np.isfinite(finite) & (finite > threshold)
    if not np.any(mask):
        return None
    return mask


def _square_crop_bounds(mask: np.ndarray) -> tuple[tuple[int, int], tuple[int, int]]:
    rows, cols = np.where(mask)
    row_start = int(np.min(rows))
    row_stop = int(np.max(rows)) + 1
    col_start = int(np.min(cols))
    col_stop = int(np.max(cols)) + 1
    height, width = mask.shape
    crop_height = row_stop - row_start
    crop_width = col_stop - col_start
    padding = max(
        DEFAULT_MRI_SLICE_CROP_MIN_PADDING_PIXELS,
        int(round(max(crop_height, crop_width) * DEFAULT_MRI_SLICE_CROP_PADDING_FRACTION)),
    )
    row_start = max(0, row_start - padding)
    row_stop = min(height, row_stop + padding)
    col_start = max(0, col_start - padding)
    col_stop = min(width, col_stop + padding)
    row_start, row_stop = _expand_bounds_to_size(row_start, row_stop, height, target_size=max(row_stop - row_start, col_stop - col_start))
    col_start, col_stop = _expand_bounds_to_size(col_start, col_stop, width, target_size=max(row_stop - row_start, col_stop - col_start))
    return (row_start, row_stop), (col_start, col_stop)


def _expand_bounds_to_size(start: int, stop: int, limit: int, *, target_size: int) -> tuple[int, int]:
    size = stop - start
    if size >= target_size:
        return start, stop
    extra = int(target_size - size)
    before = extra // 2
    after = extra - before
    start = max(0, start - before)
    stop = min(limit, stop + after)
    if stop - start < target_size:
        if start == 0:
            stop = min(limit, target_size)
        elif stop == limit:
            start = max(0, limit - target_size)
    return start, stop


def _normalize_anatomy(plane: np.ndarray) -> np.ndarray:
    values = np.asarray(plane, dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return np.zeros_like(values, dtype=float)
    low, high = np.nanpercentile(finite, [1.0, 99.5])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.nanmin(finite))
        high = float(np.nanmax(finite))
    if high <= low:
        return np.zeros_like(values, dtype=float)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _valid_scalar_range(scalar_range: tuple[float, float]) -> tuple[float, float]:
    vmin = float(scalar_range[0])
    vmax = float(scalar_range[1])
    if not np.isfinite(vmin):
        vmin = 0.0
    if not np.isfinite(vmax):
        vmax = vmin + 1.0
    vmin = max(0.0, vmin)
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax


def _plane_label(plane: PlaneName) -> str:
    if plane == "axial":
        return "Axial"
    if plane == "coronal":
        return "Coronal"
    return "Sagittal"


def _paired_export_paths(output_path: str | Path) -> tuple[Path, Path]:
    pdf_path = Path(output_path)
    if pdf_path.suffix.lower() != ".pdf":
        pdf_path = pdf_path.with_suffix(".pdf")
    png_path = pdf_path.with_suffix(".png")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    return pdf_path, png_path

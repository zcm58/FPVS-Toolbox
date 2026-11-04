"""MRI orthogonal slice rendering for prepared volume source payloads.

This module is a display/export adapter. It loads anatomical fsaverage MRI
context, maps already-prepared volume payload points into MRI voxel space, and
interpolates those existing values for visualization only.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, replace
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Literal

import numpy as np
from Main_App.io.atomic_write import atomic_write
from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    figure_text_kwargs,
    matplotlib_figure_rcparams,
)

from Tools.LORETA_Visualizer.fsaverage_cache import fpvs_toolbox_root
from Tools.LORETA_Visualizer.scalar_fields import LORETA_SMOOTH_SCALAR_COLORS
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_POINTS, SourcePayload
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    COORDINATE_SPACE_FSAVERAGE_VOLUME,
    MeshDisplayTransform,
)
from Tools.LORETA_Visualizer.volume_overlay import DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS, nearest_source_validity

logger = logging.getLogger(__name__)
_MRI_FIGURE_LOCK = RLock()


def _serialized_mri_figure(function):
    """Keep Matplotlib's shared rendering state out of concurrent MRI jobs."""

    @wraps(function)
    def locked(*args, **kwargs):
        with _MRI_FIGURE_LOCK:
            import matplotlib

            with matplotlib.rc_context(matplotlib_figure_rcparams()):
                return function(*args, **kwargs)

    return locked

MM_PER_INCH = 25.4
ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM = 140.0
DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN = ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM / MM_PER_INCH
DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN = 3.2
DEFAULT_MRI_SLICE_RENDER_DPI = 300
DEFAULT_MRI_SLICE_FIGURE_DPI = FIGURE_EXPORT_DPI
DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE = 0.0
DEFAULT_MRI_SLICE_GAUSSIAN_NEIGHBORS = DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS
DEFAULT_MRI_SLICE_SUPPORT_SIGMA = 1.75
DEFAULT_MRI_SLICE_OVERLAY_ALPHA = 0.48

PlaneName = Literal["axial", "coronal", "sagittal"]

FSAVERAGE_MRI_RELATIVE_PATH = Path("mri") / "brain.mgz"
LORETA_MRI_TEMPLATE_CACHE_RELATIVE_DIR = Path(".fpvs_cache") / "loreta_visualizer" / "mri_templates"
LORETA_DISPLAY_MRI_TEMPLATE_NAME = "brain_0p5mm.nii"
LORETA_DISPLAY_MRI_VOXEL_SIZE_MM = 0.5
FSAVERAGE_NATIVE_MRI_VOXEL_SIZE_MM = 1.0


@dataclass(frozen=True)
class MriAnatomyVolume:
    """Loaded MRI anatomy in the same RAS frame used by fsaverage surfaces."""

    data: np.ndarray
    vox_to_ras: np.ndarray
    ras_to_vox: np.ndarray
    source_path: Path
    intensity_window: tuple[float, float] | None = None
    crop_center_voxels: tuple[float, float, float] | None = None
    field_of_view_mm: float | None = None


@dataclass(frozen=True)
class MriSlicePanel:
    """One orthogonal MRI panel plus its display-only source overlay."""

    label: str
    plane: PlaneName
    anatomy: np.ndarray
    overlay: np.ndarray
    slice_index: int
    pixel_to_voxel: np.ndarray
    fixed_voxel_axis: int
    fixed_voxel_step: int
    ras_coordinate_mm: float
    orientation_labels: tuple[str, str, str, str]
    anatomy_window: tuple[float, float] | None = None
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True)
class MriSliceHitRegion:
    """Image-pixel bounds and geometry of one rendered anatomical plane."""

    plane: PlaneName
    image_bounds: tuple[float, float, float, float]
    panel_shape: tuple[int, int]
    pixel_to_voxel: np.ndarray
    fixed_voxel_axis: int
    fixed_voxel_step: int = 1

    def voxel_at(self, x: float, y: float) -> np.ndarray:
        """Map an image position to MRI voxel coordinates, without interpolation."""

        left, top, width, height = self.image_bounds
        rows, columns = self.panel_shape
        column = (float(x) - left) * columns / width - 0.5
        row = (float(y) - top) * rows / height - 0.5
        return self.pixel_to_voxel @ np.asarray([column, row, 1.0])

    def image_position(self, voxel: tuple[int, int, int]) -> tuple[float, float]:
        """Map an MRI voxel to this panel's image position."""

        basis = self.pixel_to_voxel[:, :2]
        column, row = np.linalg.lstsq(basis, np.asarray(voxel) - self.pixel_to_voxel[:, 2], rcond=None)[0]
        left, top, width, height = self.image_bounds
        rows, columns = self.panel_shape
        return left + (column + 0.5) * width / columns, top + (row + 0.5) * height / rows


@dataclass(frozen=True)
class MriSliceRenderResult:
    """Rendered MRI slice image and the voxel-space diagnostics behind it."""

    image_rgb: np.ndarray
    peak_voxel: tuple[int, int, int]
    scalar_range: tuple[float, float]
    source_point_count: int
    rendered_point_count: int
    hit_regions: tuple[MriSliceHitRegion, ...] = ()
    anatomy_shape: tuple[int, int, int] = (0, 0, 0)
    cursor_ras_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    nearest_source_value: float | None = None
    nearest_source_distance_mm: float | None = None
    value_label: str = ""
    inspection_uses_unfiltered_payload: bool = False
    anatomy_source_name: str = ""


class MriSlicePreviewCache:
    """Bounded native panels and one Agg canvas for sequential preview workers.

    This cache is display-only and never used by publication exports. Anatomy
    is the immutable, already-loaded volume owned by the page. Source arrays,
    support and scalar limits are fingerprinted so changed maps cannot reuse
    older overlays. Drop the page's reference on context changes; an in-flight
    worker may safely retain its own reference until it completes.
    """

    MAX_PANELS = 16
    MAX_PANEL_BYTES = 16 * 1024 * 1024

    def __init__(self) -> None:
        self._anatomy: MriAnatomyVolume | None = None
        self._panel_signature: tuple | None = None
        self._panels: OrderedDict[tuple[str, int], MriSlicePanel] = OrderedDict()
        self._panel_bytes = 0
        self._figure = None
        self._figure_signature: tuple | None = None

    def clear(self) -> None:
        """Release worker-owned cached data; callers must not race a render."""
        with _MRI_FIGURE_LOCK:
            self._panels.clear()
            self._panel_bytes = 0
            self._panel_signature = None
            self._anatomy = None
            if self._figure is not None:
                self._figure.clear()
            self._figure = None
            self._figure_signature = None

    def _prepare_panels(self, anatomy: MriAnatomyVolume, signature: tuple) -> None:
        with _MRI_FIGURE_LOCK:
            if self._anatomy is not anatomy or self._panel_signature != signature:
                self._panels.clear()
                self._panel_bytes = 0
                self._anatomy = anatomy
                self._panel_signature = signature

    def _panel(self, key: tuple[str, int]) -> MriSlicePanel | None:
        with _MRI_FIGURE_LOCK:
            result = self._panels.get(key)
            if result is not None:
                self._panels.move_to_end(key)
            return result

    def _remember_panel(self, key: tuple[str, int], panel: MriSlicePanel) -> None:
        with _MRI_FIGURE_LOCK:
            size = panel.anatomy.nbytes + panel.overlay.nbytes + panel.pixel_to_voxel.nbytes
            if size > self.MAX_PANEL_BYTES:
                return
            previous = self._panels.pop(key, None)
            if previous is not None:
                self._panel_bytes -= previous.anatomy.nbytes + previous.overlay.nbytes + previous.pixel_to_voxel.nbytes
            while self._panels and (
                len(self._panels) >= self.MAX_PANELS or self._panel_bytes + size > self.MAX_PANEL_BYTES
            ):
                _old_key, old = self._panels.popitem(last=False)
                self._panel_bytes -= old.anatomy.nbytes + old.overlay.nbytes + old.pixel_to_voxel.nbytes
            self._panels[key] = panel
            self._panel_bytes += size


def _array_fingerprint(values: np.ndarray) -> tuple:
    array = np.ascontiguousarray(values)
    return array.shape, array.dtype.str, hashlib.sha256(memoryview(array)).digest()


def find_fsaverage_mri_path(fsaverage_dir: str | Path) -> Path | None:
    """Prefer the native full-head T1; retain skull-stripped brain as fallback."""
    for relative in (Path("mri") / "T1.mgz", FSAVERAGE_MRI_RELATIVE_PATH):
        candidate = Path(fsaverage_dir) / relative
        if candidate.is_file():
            return candidate
    return None


def load_fsaverage_mri_volume(
    fsaverage_dir: str | Path,
    *,
    display_template_cache_dir: str | Path | None = None,
) -> MriAnatomyVolume:
    """Load native fsaverage anatomy once, preserving its surface-RAS geometry.

    The cache-directory keyword remains accepted for older callers. Native
    viewing never generates, overwrites or reads the historical 0.5 mm cache.
    """

    mri_path = find_fsaverage_mri_path(fsaverage_dir)
    if mri_path is None:
        raise FileNotFoundError(f"Required fsaverage MRI anatomy is missing: {Path(fsaverage_dir) / 'mri'} / T1.mgz or brain.mgz.")

    try:
        import nibabel as nib
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("nibabel is required to render MRI slice figures.") from exc

    image = nib.load(str(mri_path), mmap=True)
    # An MGZ proxy decompresses on access. Keep the native array (16 MB for
    # fsaverage uint8), instead of repeatedly decoding each requested plane.
    data = np.asarray(image.dataobj)
    shape = tuple(int(value) for value in image.shape)
    if len(shape) != 3:
        raise ValueError(f"Expected a 3D MRI volume, found shape {shape!r} in {mri_path}.")

    vox_to_ras = _vox_to_ras_transform(image)
    try:
        ras_to_vox = np.linalg.inv(vox_to_ras)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"MRI voxel-to-RAS transform is singular: {mri_path}.") from exc
    window, center, field_of_view = _anatomy_display_parameters(data, vox_to_ras)

    return MriAnatomyVolume(
        data=data,
        vox_to_ras=np.asarray(vox_to_ras, dtype=float),
        ras_to_vox=np.asarray(ras_to_vox, dtype=float),
        source_path=mri_path,
        intensity_window=window,
        crop_center_voxels=center,
        field_of_view_mm=field_of_view,
    )


def ensure_loreta_display_mri_template(
    source_mri_path: str | Path,
    *,
    display_template_cache_dir: str | Path | None = None,
) -> Path:
    """Return the visualizer-only 0.5 mm MRI template, generating it if needed."""

    source_path = Path(source_mri_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Required fsaverage MRI anatomy is missing: {source_path}.")
    cache_dir = (
        Path(display_template_cache_dir).expanduser().resolve()
        if display_template_cache_dir is not None
        else default_loreta_display_mri_cache_dir()
    )
    cache_key = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:12]
    output_path = cache_dir / cache_key / LORETA_DISPLAY_MRI_TEMPLATE_NAME
    if _display_mri_template_current(output_path, source_path):
        return output_path
    return _write_loreta_display_mri_template(source_path, output_path)


def default_loreta_display_mri_cache_dir() -> Path:
    """Return the root-local, untracked cache for visualizer-only MRI underlays."""

    return fpvs_toolbox_root() / LORETA_MRI_TEMPLATE_CACHE_RELATIVE_DIR


@_serialized_mri_figure
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
    inspection_payload: SourcePayload | None = None,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_RENDER_DPI,
    layout: str = "auto",
    preview_cache: MriSlicePreviewCache | None = None,
) -> MriSliceRenderResult:
    """Render an RGB MRI slice image for the embedded GUI."""

    anatomy = anatomy or load_fsaverage_mri_volume(fsaverage_dir)
    native_points = payload_points_in_native_space(payload, display_transform)
    source_voxels = ras_points_to_voxels(native_points, anatomy)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    inspected_payload = inspection_payload if inspection_payload is not None else payload
    support_voxels = ras_points_to_voxels(payload_points_in_native_space(inspected_payload, display_transform), anatomy)
    panels, peak_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=scalar_range,
        slice_indices=slice_indices,
        support_source_voxels=support_voxels,
        support_valid_source_mask=np.isfinite(inspected_payload.values),
        preview_cache=preview_cache,
    )
    image_rgb, hit_regions = _draw_mri_slice_figure(
        panels,
        scalar_range=scalar_range,
        label=label,
        activation_visible=activation_visible,
        figsize=figsize,
        dpi=dpi,
        layout=layout,
        preview_cache=preview_cache,
    )
    cursor_ras = voxel_to_ras(peak_voxel, anatomy)
    nearest_value, nearest_distance = nearest_prepared_source_value(
        inspected_payload, cursor_ras, display_transform=display_transform,
    )
    return MriSliceRenderResult(
        image_rgb=image_rgb,
        peak_voxel=peak_voxel,
        scalar_range=(float(scalar_range[0]), float(scalar_range[1])),
        source_point_count=int(len(payload.points)),
        rendered_point_count=int(np.count_nonzero(
            np.isfinite(values) & (values > DEFAULT_MRI_SLICE_MIN_VISIBLE_VALUE)
            & np.all((source_voxels >= 0.0) & (source_voxels <= np.asarray(anatomy.data.shape) - 1), axis=1)
        )),
        hit_regions=hit_regions,
        anatomy_shape=tuple(int(value) for value in anatomy.data.shape),
        cursor_ras_mm=cursor_ras,
        nearest_source_value=nearest_value,
        nearest_source_distance_mm=nearest_distance,
        value_label=inspected_payload.value_label,
        inspection_uses_unfiltered_payload=inspection_payload is not None,
        anatomy_source_name=anatomy.source_path.name,
    )


@_serialized_mri_figure
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
    support_payload: SourcePayload | None = None,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_FIGURE_DPI,
) -> tuple[Path, Path]:
    """Write matched publication-ready PDF and PNG orthogonal MRI slice figures."""

    anatomy = anatomy or load_fsaverage_mri_volume(fsaverage_dir)
    native_points = payload_points_in_native_space(payload, display_transform)
    source_voxels = ras_points_to_voxels(native_points, anatomy)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    original_payload = support_payload if support_payload is not None else payload
    support_voxels = ras_points_to_voxels(payload_points_in_native_space(original_payload, display_transform), anatomy)
    panels, _peak_voxel = build_mri_slice_panels(
        anatomy,
        source_voxels,
        values,
        scalar_range=scalar_range,
        slice_indices=slice_indices,
        support_source_voxels=support_voxels,
        support_valid_source_mask=np.isfinite(original_payload.values),
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
        coordinate_description = (
            f"Slice coordinates: fsaverage MRI RAS, millimetres. Underlay: {anatomy.source_path.name}, native sampling."
        )
        figure.savefig(pdf_path, format="pdf", dpi=dpi, facecolor=figure.get_facecolor(), transparent=False,
                       metadata={"Subject": coordinate_description})
        figure.savefig(png_path, format="png", dpi=dpi, facecolor=figure.get_facecolor(), transparent=False,
                       metadata={"Description": coordinate_description})
    finally:
        figure.clear()
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


def voxel_to_ras(voxel: tuple[int, int, int], anatomy: MriAnatomyVolume) -> tuple[float, float, float]:
    """Return fsaverage MRI RAS millimetres for an original MRI voxel."""

    ras = anatomy.vox_to_ras @ np.asarray([*voxel, 1.0], dtype=float)
    return float(ras[0]), float(ras[1]), float(ras[2])


def nearest_prepared_source_value(
    payload: SourcePayload,
    ras_mm: tuple[float, float, float],
    *,
    display_transform: MeshDisplayTransform,
) -> tuple[float | None, float | None]:
    """Inspect an original prepared grid value; never sample the smoothed overlay."""

    native_points = payload_points_in_native_space(payload, display_transform)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    finite = np.all(np.isfinite(native_points), axis=1)
    if not np.any(finite):
        return None, None
    distances = np.linalg.norm(native_points[finite] - np.asarray(ras_mm), axis=1)
    nearest = int(np.argmin(distances))
    value = values[finite][nearest]
    return (float(value) if np.isfinite(value) else None), float(distances[nearest])


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
    support_source_voxels: np.ndarray | None = None,
    support_valid_source_mask: np.ndarray | None = None,
    preview_cache: MriSlicePreviewCache | None = None,
) -> tuple[tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel], tuple[int, int, int]]:
    """Build axial/coronal/sagittal anatomy and overlay panels."""

    validity_voxels = np.asarray(source_voxels if support_source_voxels is None else support_source_voxels, dtype=float)
    validity_mask = (
        np.isfinite(np.asarray(values, dtype=float))
        if support_valid_source_mask is None else np.asarray(support_valid_source_mask)
    )
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
    voxel_spacing = np.linalg.norm(anatomy.vox_to_ras[:3, :3], axis=0)
    # Filtering controls visibility, never the width of the interpolation kernel.
    sigma = _source_voxel_sigma(validity_voxels * voxel_spacing)
    if anatomy.intensity_window is None or anatomy.crop_center_voxels is None or anatomy.field_of_view_mm is None:
        window, center, field_of_view = _anatomy_display_parameters(anatomy.data, anatomy.vox_to_ras)
    else:
        window, center, field_of_view = anatomy.intensity_window, anatomy.crop_center_voxels, anatomy.field_of_view_mm
    if preview_cache is not None:
        preview_cache._prepare_panels(anatomy, (
            _array_fingerprint(source_voxels), _array_fingerprint(source_values),
            _array_fingerprint(validity_voxels), _array_fingerprint(validity_mask),
            _array_fingerprint(anatomy.vox_to_ras), tuple(scalar_range),
            tuple(window), tuple(center), float(field_of_view),
        ))
    ras_axes, _ras_signs = _ras_voxel_axes(anatomy.vox_to_ras)
    panels = []
    for plane in ("axial", "coronal", "sagittal"):
        fixed_ras = {"axial": 2, "coronal": 1, "sagittal": 0}[plane]
        key = (plane, peak_voxel[ras_axes[fixed_ras]])
        panel = preview_cache._panel(key) if preview_cache is not None else None
        if panel is None:
            panel = _slice_panel(
                anatomy,
                source_voxels,
                source_values,
                plane=plane,
                selected_voxel=peak_voxel,
                scalar_range=scalar_range,
                sigma=sigma,
                validity_voxels=validity_voxels,
                validity_mask=validity_mask,
                anatomy_window=window,
                crop_center=center,
                field_of_view_mm=field_of_view,
            )
            if preview_cache is not None:
                preview_cache._remember_panel(key, panel)
        else:
            # Preserve exact displayed RAS even for tiny affine cross-terms
            # within the axis-aligned tolerance, without rebuilding the plane.
            panel = replace(panel, ras_coordinate_mm=voxel_to_ras(peak_voxel, anatomy)[fixed_ras])
        panels.append(panel)
    return tuple(panels), peak_voxel


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

    image_rgb, _hit_regions = _draw_mri_slice_figure(
        panels, scalar_range=scalar_range, label=label,
        activation_visible=activation_visible, figsize=figsize, dpi=dpi,
    )
    return image_rgb


@_serialized_mri_figure
def _draw_mri_slice_figure(
    panels: tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel],
    *,
    scalar_range: tuple[float, float],
    label: str,
    activation_visible: bool,
    figsize: tuple[float, float],
    dpi: int,
    layout: str = "row",
    preview_cache: MriSlicePreviewCache | None = None,
) -> tuple[np.ndarray, tuple[MriSliceHitRegion, ...]]:

    signature = (
        tuple(scalar_range), label, bool(activation_visible), tuple(figsize), dpi, layout,
        tuple((panel.anatomy.shape, panel.pixel_spacing_mm, panel.orientation_labels) for panel in panels),
    )
    figure = preview_cache._figure if preview_cache is not None else None
    if figure is None or preview_cache._figure_signature != signature:
        if figure is not None:
            figure.clear()
        if preview_cache is not None:
            preview_cache._figure = None
            preview_cache._figure_signature = None
        figure = build_mri_slice_figure(
            panels, scalar_range=scalar_range, label=label,
            activation_visible=activation_visible, figsize=figsize, dpi=dpi, layout=layout,
        )
        if preview_cache is not None:
            preview_cache._figure = figure
            preview_cache._figure_signature = signature
    else:
        vmin, vmax = _valid_scalar_range(scalar_range)
        for axis, panel in zip(figure.axes[:3], panels):
            axis.images[0].set_data(_normalize_anatomy(panel.anatomy, window=panel.anatomy_window))
            masked_overlay, overlay_alpha = _panel_overlay_display(panel, vmin, vmax, activation_visible)
            axis.images[1].set_data(masked_overlay)
            axis.images[1].set_alpha(overlay_alpha)
            coordinate_axis = {"axial": "z", "coronal": "y", "sagittal": "x"}[panel.plane]
            axis.title.set_text(f"{panel.label}\n{coordinate_axis}={panel.ras_coordinate_mm:+g} mm")
    try:
        figure.canvas.draw()
        rgba = np.asarray(figure.canvas.buffer_rgba())
        image_rgb = np.asarray(rgba[..., :3], dtype=np.uint8).copy()
        height = image_rgb.shape[0]
        hit_regions = []
        for axis, panel in zip(figure.axes[:3], panels):
            bounds = axis.get_window_extent()
            hit_regions.append(MriSliceHitRegion(
                plane=panel.plane,
                image_bounds=(float(bounds.x0), float(height - bounds.y1), float(bounds.width), float(bounds.height)),
                panel_shape=panel.anatomy.shape,
                pixel_to_voxel=panel.pixel_to_voxel,
                fixed_voxel_axis=panel.fixed_voxel_axis,
                fixed_voxel_step=panel.fixed_voxel_step,
            ))
        return image_rgb, tuple(hit_regions)
    finally:
        if preview_cache is None:
            figure.clear()


def _panel_overlay_display(panel: MriSlicePanel, vmin: float, vmax: float, activation_visible: bool):
    if not activation_visible:
        return np.ma.masked_all(panel.overlay.shape), 0.0
    masked_overlay = np.ma.masked_where(~np.isfinite(panel.overlay) | (panel.overlay <= vmin), panel.overlay)
    overlay_alpha = np.where(
        np.ma.getmaskarray(masked_overlay), 0.0,
        np.clip((panel.overlay - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0) * DEFAULT_MRI_SLICE_OVERLAY_ALPHA,
    )
    return masked_overlay, overlay_alpha


@_serialized_mri_figure
def build_mri_slice_figure(
    panels: tuple[MriSlicePanel, MriSlicePanel, MriSlicePanel],
    *,
    scalar_range: tuple[float, float],
    label: str = "",
    activation_visible: bool = True,
    figsize: tuple[float, float] = (DEFAULT_MRI_SLICE_FIGURE_WIDTH_IN, DEFAULT_MRI_SLICE_FIGURE_HEIGHT_IN),
    dpi: int = DEFAULT_MRI_SLICE_FIGURE_DPI,
    layout: str = "row",
):
    """Build a Matplotlib orthogonal MRI slice figure."""

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.cm import ScalarMappable

    cmap = LinearSegmentedColormap.from_list("fpvs_loreta_activation", list(LORETA_SMOOTH_SCALAR_COLORS))
    vmin, vmax = _valid_scalar_range(scalar_range)

    figure = Figure(figsize=figsize, dpi=dpi, facecolor="black")
    FigureCanvasAgg(figure)
    resolved_layout = "grid" if layout == "auto" and figsize[0] / figsize[1] < 1.7 else layout
    if resolved_layout == "auto":
        resolved_layout = "row"
    if resolved_layout not in {"row", "grid"}:
        raise ValueError("MRI slice layout must be row, grid, or auto.")
    if resolved_layout == "grid":
        grid = figure.add_gridspec(
            2, 2, left=0.025, right=0.975, top=0.88 if label else 0.93,
            bottom=0.04, wspace=0.04, hspace=0.24,
        )
        image_cells = (grid[0, 0], grid[0, 1], grid[1, 0])
        color_cell = grid[1, 1]
    else:
        grid = figure.add_gridspec(
            1, 4, width_ratios=(1.0, 1.0, 1.0, 0.055), left=0.015,
            right=0.92, top=0.81 if label else 0.91, bottom=0.05, wspace=0.08,
        )
        image_cells = (grid[0, 0], grid[0, 1], grid[0, 2])
        color_cell = grid[0, 3]
    if label:
        figure.suptitle(
            label,
            color="white",
            y=0.965,
            **figure_text_kwargs("condition_label"),
        )

    overlay_artist = None
    for index, panel in enumerate(panels):
        axis = figure.add_subplot(image_cells[index])
        axis.set_facecolor("black")
        axis.imshow(
            _normalize_anatomy(panel.anatomy, window=panel.anatomy_window),
            cmap="gray", vmin=0.0, vmax=1.0, interpolation="nearest", origin="upper",
        )
        masked_overlay, overlay_alpha = _panel_overlay_display(panel, vmin, vmax, activation_visible)
        overlay_artist = axis.imshow(
            masked_overlay,
            cmap=cmap,
            norm=Normalize(vmin=vmin, vmax=vmax),
            interpolation="nearest",
            alpha=overlay_alpha,
            origin="upper",
        )
        coordinate_axis = {"axial": "z", "coronal": "y", "sagittal": "x"}[panel.plane]
        axis.set_title(
            f"{panel.label}\n{coordinate_axis}={panel.ras_coordinate_mm:+g} mm",
            color="white",
            pad=5,
            **figure_text_kwargs("axis_label"),
        )
        for text, position, alignment in zip(
            panel.orientation_labels,
            ((0.02, 0.5), (0.98, 0.5), (0.5, 0.98), (0.5, 0.02)),
            (("left", "center"), ("right", "center"), ("center", "top"), ("center", "bottom")),
        ):
            axis.text(
                *position, text, transform=axis.transAxes, color="white",
                ha=alignment[0], va=alignment[1],
                bbox={"facecolor": "black", "alpha": 0.55, "edgecolor": "none", "pad": 1},
                **figure_text_kwargs("small"),
            )
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_aspect(panel.pixel_spacing_mm[1] / panel.pixel_spacing_mm[0])
        for spine in axis.spines.values():
            spine.set_visible(False)

    color_axis = figure.add_subplot(color_cell)
    if resolved_layout == "grid":
        bounds = color_axis.get_position()
        color_axis.set_position([
            bounds.x0 + bounds.width * 0.15, bounds.y0 + bounds.height * 0.45,
            bounds.width * 0.70, bounds.height * 0.065,
        ])
    color_axis.set_facecolor("black")
    mappable = overlay_artist or ScalarMappable(norm=Normalize(vmin=vmin, vmax=vmax), cmap=cmap)
    colorbar = figure.colorbar(mappable, cax=color_axis, orientation="horizontal" if resolved_layout == "grid" else "vertical")
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


def _display_mri_template_current(output_path: Path, source_path: Path) -> bool:
    if not output_path.is_file():
        return False
    try:
        return output_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns
    except OSError:
        return False


def _write_loreta_display_mri_template(source_path: Path, output_path: Path) -> Path:
    """Build the 0.5 mm display template without modifying fsaverage itself."""

    try:
        import nibabel as nib
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("nibabel is required to prepare the 0.5 mm MRI display template.") from exc

    try:
        from scipy.ndimage import affine_transform
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("scipy is required to prepare the 0.5 mm MRI display template.") from exc

    source_image = nib.load(str(source_path))
    source_data = np.asarray(source_image.dataobj, dtype=np.float32)
    source_data = np.squeeze(source_data)
    if source_data.ndim != 3:
        raise ValueError(f"Expected a 3D fsaverage MRI volume, found shape {source_data.shape!r} in {source_path}.")
    if not np.any(np.isfinite(source_data)):
        raise ValueError(f"fsaverage MRI volume contains no finite voxels: {source_path}.")

    scale = FSAVERAGE_NATIVE_MRI_VOXEL_SIZE_MM / LORETA_DISPLAY_MRI_VOXEL_SIZE_MM
    output_shape = tuple(max(1, int(round(dimension * scale))) for dimension in source_data.shape)
    source_to_output = np.eye(3, dtype=float) / scale
    output_data = affine_transform(
        source_data,
        matrix=source_to_output,
        offset=0.0,
        output_shape=output_shape,
        order=3,
        mode="nearest",
        prefilter=True,
    )

    output_data = _coerce_resampled_mri_dtype(output_data, source_image.get_data_dtype())
    scale_transform = np.diag(
        [
            LORETA_DISPLAY_MRI_VOXEL_SIZE_MM / FSAVERAGE_NATIVE_MRI_VOXEL_SIZE_MM,
            LORETA_DISPLAY_MRI_VOXEL_SIZE_MM / FSAVERAGE_NATIVE_MRI_VOXEL_SIZE_MM,
            LORETA_DISPLAY_MRI_VOXEL_SIZE_MM / FSAVERAGE_NATIVE_MRI_VOXEL_SIZE_MM,
            1.0,
        ]
    )
    output_affine = _vox_to_ras_transform(source_image) @ scale_transform

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(output_path, binary=True) as stream:
        nib.Nifti1Image(output_data, output_affine).to_file_map({"image": nib.FileHolder(fileobj=stream)})
    return output_path


def _coerce_resampled_mri_dtype(data: np.ndarray, source_dtype: np.dtype) -> np.ndarray:
    values = np.asarray(data, dtype=np.float32)
    dtype = np.dtype(source_dtype)
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return np.clip(np.rint(values), info.min, info.max).astype(dtype, copy=False)
    return values.astype(np.float32, copy=False)


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
    anatomy: MriAnatomyVolume,
    source_voxels: np.ndarray,
    values: np.ndarray,
    *,
    plane: PlaneName,
    selected_voxel: tuple[int, int, int],
    scalar_range: tuple[float, float],
    sigma: float,
    validity_voxels: np.ndarray,
    validity_mask: np.ndarray,
    anatomy_window: tuple[float, float],
    crop_center: tuple[float, float, float],
    field_of_view_mm: float,
) -> MriSlicePanel:
    # fsaverage's native voxel axes are L/I/A, not R/A/S. Derive the
    # anatomical plane and orientation from its affine instead of axis numbers.
    ras_axes, ras_signs = _ras_voxel_axes(anatomy.vox_to_ras)
    horizontal_ras, vertical_ras, fixed_ras = {
        "axial": (0, 1, 2), "coronal": (0, 2, 1), "sagittal": (1, 2, 0),
    }[plane]
    column_axis, row_axis, fixed_axis = (ras_axes[axis] for axis in (horizontal_ras, vertical_ras, fixed_ras))
    fixed_index = selected_voxel[fixed_axis]
    selection = [slice(None)] * 3
    selection[fixed_axis] = fixed_index
    remaining_axes = [axis for axis in range(3) if axis != fixed_axis]
    anatomy_plane = np.asarray(anatomy.data[tuple(selection)], dtype=float).transpose(
        remaining_axes.index(row_axis), remaining_axes.index(column_axis),
    )
    column_step = int(ras_signs[horizontal_ras])
    row_step = -int(ras_signs[vertical_ras])
    if row_step < 0:
        anatomy_plane = anatomy_plane[::-1, :]
    if column_step < 0:
        anatomy_plane = anatomy_plane[:, ::-1]

    pixel_to_voxel = np.zeros((3, 3), dtype=float)
    pixel_to_voxel[column_axis, 0] = column_step
    pixel_to_voxel[row_axis, 1] = row_step
    pixel_to_voxel[fixed_axis, 2] = fixed_index
    if column_step < 0:
        pixel_to_voxel[column_axis, 2] = anatomy.data.shape[column_axis] - 1
    if row_step < 0:
        pixel_to_voxel[row_axis, 2] = anatomy.data.shape[row_axis] - 1

    spacing = np.linalg.norm(anatomy.vox_to_ras[:3, :3], axis=0)
    center_column = (crop_center[column_axis] - pixel_to_voxel[column_axis, 2]) / column_step
    center_row = (crop_center[row_axis] - pixel_to_voxel[row_axis, 2]) / row_step
    panel_shape = (
        max(1, int(np.ceil(field_of_view_mm / spacing[row_axis]))),
        max(1, int(np.ceil(field_of_view_mm / spacing[column_axis]))),
    )
    row_start = int(np.floor(center_row - (panel_shape[0] - 1) / 2))
    column_start = int(np.floor(center_column - (panel_shape[1] - 1) / 2))
    anatomy_plane = _crop_or_pad_plane(anatomy_plane, row_start, column_start, panel_shape)
    pixel_to_voxel[:, 2] += pixel_to_voxel[:, 0] * column_start + pixel_to_voxel[:, 1] * row_start

    rows, columns = np.indices(anatomy_plane.shape, dtype=float)
    pixels = np.column_stack((columns.ravel(), rows.ravel(), np.ones(rows.size)))
    coordinate_grid = pixels @ pixel_to_voxel.T
    overlay_plane = _gaussian_interpolated_values(
        coordinate_grid * spacing, source_voxels * spacing, values, sigma=sigma, scalar_range=scalar_range,
    ).reshape(anatomy_plane.shape)
    display_validity = nearest_source_validity(coordinate_grid * spacing, validity_voxels * spacing, validity_mask)
    overlay_plane[~display_validity.reshape(anatomy_plane.shape)] = np.nan
    ras_coordinate = voxel_to_ras(selected_voxel, anatomy)[fixed_ras]
    return MriSlicePanel(
        label=_plane_label(plane),
        plane=plane,
        anatomy=anatomy_plane,
        overlay=overlay_plane,
        slice_index=int(fixed_index),
        pixel_to_voxel=pixel_to_voxel,
        fixed_voxel_axis=fixed_axis,
        fixed_voxel_step=int(ras_signs[fixed_ras]),
        ras_coordinate_mm=ras_coordinate,
        orientation_labels={
            "axial": ("L", "R", "A", "P"),
            "coronal": ("L", "R", "S", "I"),
            "sagittal": ("P", "A", "S", "I"),
        }[plane],
        anatomy_window=anatomy_window,
        pixel_spacing_mm=(float(spacing[column_axis]), float(spacing[row_axis])),
    )


def _ras_voxel_axes(vox_to_ras: np.ndarray) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Identify each RAS axis in an axis-aligned affine, rejecting oblique data."""

    transform = np.asarray(vox_to_ras, dtype=float)
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise ValueError("MRI voxel-to-RAS transform must be a finite 4 x 4 matrix.")
    rotation_scale = transform[:3, :3]
    lengths = np.linalg.norm(rotation_scale, axis=0)
    if np.any(lengths <= 0.0):
        raise ValueError("MRI voxel-to-RAS transform is singular.")
    directions = rotation_scale / lengths
    axes = tuple(int(axis) for axis in np.argmax(np.abs(directions), axis=1))
    ideal_directions = np.zeros((3, 3), dtype=float)
    ideal_directions[np.arange(3), axes] = np.sign(directions[np.arange(3), axes])
    if len(set(axes)) != 3 or not np.allclose(directions, ideal_directions, rtol=0.0, atol=1e-6):
        raise ValueError("MRI slice navigation requires axis-aligned fsaverage MRI anatomy.")
    signs = tuple(int(np.sign(directions[ras_axis, voxel_axis])) for ras_axis, voxel_axis in enumerate(axes))
    return axes, signs


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


def _anatomy_display_parameters(
    data: np.ndarray, vox_to_ras: np.ndarray,
) -> tuple[tuple[float, float], tuple[float, float, float], float]:
    """Choose one contrast window and physical field of view for the volume."""
    values = np.asarray(data)
    if values.ndim != 3:
        raise ValueError("MRI anatomy must be a 3D volume.")
    finite = np.isfinite(values)
    if not np.any(finite):
        raise ValueError("MRI anatomy contains no finite voxels.")
    positive = values[finite & (values > 0)]
    high = float(np.percentile(positive, 99.5)) if positive.size else 1.0
    window = (0.0, max(high, np.finfo(float).eps))
    foreground = finite & (values > (float(np.max(positive)) * 0.025 if positive.size else 0.0))
    bounds = []
    for axis in range(3):
        occupied = np.flatnonzero(np.any(foreground, axis=tuple(index for index in range(3) if index != axis)))
        bounds.append((int(occupied[0]), int(occupied[-1]) + 1) if occupied.size else (0, values.shape[axis]))
    spacing = np.linalg.norm(np.asarray(vox_to_ras)[:3, :3], axis=0)
    if not np.all(np.isfinite(spacing)) or np.any(spacing <= 0.0):
        raise ValueError("MRI voxel spacing must be finite and positive.")
    span = max((stop - start) * spacing[axis] for axis, (start, stop) in enumerate(bounds))
    padding = max(2.0, float(span) * 0.025)
    center = tuple(float((start + stop - 1) / 2) for start, stop in bounds)
    return window, center, float(span + 2 * padding)


def _crop_or_pad_plane(
    plane: np.ndarray, row_start: int, column_start: int, shape: tuple[int, int],
) -> np.ndarray:
    """Retain native voxels and pad the fixed physical viewport with background."""
    result = np.zeros(shape, dtype=plane.dtype)
    source_row_start, source_column_start = max(0, row_start), max(0, column_start)
    source_row_stop = min(plane.shape[0], row_start + shape[0])
    source_column_stop = min(plane.shape[1], column_start + shape[1])
    if source_row_start < source_row_stop and source_column_start < source_column_stop:
        result[
            source_row_start - row_start:source_row_stop - row_start,
            source_column_start - column_start:source_column_stop - column_start,
        ] = plane[source_row_start:source_row_stop, source_column_start:source_column_stop]
    return result


def _normalize_anatomy(plane: np.ndarray, *, window: tuple[float, float] | None = None) -> np.ndarray:
    values = np.asarray(plane, dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return np.zeros_like(values, dtype=float)
    low, high = np.nanpercentile(finite, [1.0, 99.5]) if window is None else window
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

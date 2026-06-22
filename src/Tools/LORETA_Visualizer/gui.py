"""Embedded PySide6 page for the LORETA 3D brain visualizer."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QDialogButtonBox,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    AppDialog,
    SectionCard,
    StatusBanner,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
)
from Tools.LORETA_Visualizer.cortical_paint import (
    DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    payload_cluster_mask_is_empty,
    payload_cluster_mask_is_underpowered,
    payload_cluster_mask_minimum_p,
    payload_cluster_mask,
    payload_has_cluster_mask,
    source_payload_uses_zscores,
    uses_cortical_surface_paint,
)
from Tools.LORETA_Visualizer.fsaverage_mesh import FsaverageMeshError, FsaverageMeshResult, load_fsaverage_brain_mesh
from Tools.LORETA_Visualizer.prepared_payload_importer import (
    PreparedSourceManifestEntry,
    PreparedSourcePayloadImportError,
    load_prepared_source_manifest_json,
    load_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.renderer import (
    DISPLAY_MODE_CORTICAL_SURFACE,
    DISPLAY_MODE_SPLIT_HEMISPHERE,
    DISPLAY_MODE_TRANSPARENT_MESH,
    SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES,
    BrainRendererWidget,
    RenderBackendError,
)
from Tools.LORETA_Visualizer.scalar_fields import (
    DEFAULT_SCALAR_MAX,
    DEFAULT_SCALAR_MIN,
    LORETA_SCALAR_COLORS,
    format_scalar_value,
    resolve_scalar_limits,
)
from Tools.LORETA_Visualizer.source_payloads import (
    SourcePayload,
    empty_source_payload,
    filter_source_payload_by_mask,
    filter_source_payload_values_above,
)

logger = logging.getLogger(__name__)

DEFAULT_OPACITY_PERCENT = 48
DEFAULT_ACTIVATION_OPACITY_PERCENT = 72
DEFAULT_DISPLAY_MODE = DISPLAY_MODE_SPLIT_HEMISPHERE
PROJECT_SOURCE_EXPORT_HAUK_ZSCORE = "hauk_zscore"
PROJECT_SOURCE_EXPORT_ELORETA_VOLUME = "eloreta_volume_hauk_zscore"
PROJECT_SOURCE_EXPORT_ALL_ZSCORE = "all_zscore"
PROJECT_SOURCE_EXPORT_DEFAULT_MODES = (
    PROJECT_SOURCE_EXPORT_HAUK_ZSCORE,
    PROJECT_SOURCE_EXPORT_ELORETA_VOLUME,
)
PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST = "participant_first"
PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST = "deprecated_group_first"
SOURCE_OPTIONS_ACTION_LOAD_PAYLOAD = "load_payload"
SOURCE_OPTIONS_ACTION_LOAD_MANIFEST = "load_manifest"
SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE = "rebuild_zscore"
EXPORT_FIGURES_ACTION_SPLIT_FIGURES = "split_figures"
EXPORT_FIGURES_ACTION_STACKED_SPLIT_FIGURES = "stacked_split_figures"
ZSCORE_DISPLAY_THRESHOLD_CUSTOM_ID = "custom"
ZSCORE_DISPLAY_THRESHOLD_PRESETS: tuple[tuple[str, float], ...] = (
    ("z >= 1.64 (~one-tailed p < .05)", 1.64),
    ("z >= 1.96 (~two-tailed p < .05)", 1.96),
    ("z >= 2.58 (~two-tailed p < .01)", 2.58),
    ("z >= 3.29 (~two-tailed p < .001)", 3.29),
    ("z >= 3.89 (~two-tailed p < .0001)", 3.89),
)
DEFAULT_STACKED_CORTICAL_ZSCORE_SCALAR_RANGE = (0.0, 3.5)
DISPLAY_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Split Hemispheres", DISPLAY_MODE_SPLIT_HEMISPHERE),
    ("Fsaverage cortical surface", DISPLAY_MODE_CORTICAL_SURFACE),
    ("Transparent brain mesh", DISPLAY_MODE_TRANSPARENT_MESH),
)
SOURCE_METHOD_L2_MNE_SURFACE = "l2_mne_surface"
SOURCE_METHOD_ELORETA_VOLUME = "eloreta_volume"
SOURCE_METHOD_PREPARED = "prepared_source"
SOURCE_METHOD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("L2-MNE surface", SOURCE_METHOD_L2_MNE_SURFACE),
    ("eLORETA volume", SOURCE_METHOD_ELORETA_VOLUME),
)
SOURCE_METHOD_DEFAULT_DISPLAY_MODE = {
    SOURCE_METHOD_L2_MNE_SURFACE: DISPLAY_MODE_SPLIT_HEMISPHERE,
    SOURCE_METHOD_ELORETA_VOLUME: DISPLAY_MODE_TRANSPARENT_MESH,
    SOURCE_METHOD_PREPARED: DEFAULT_DISPLAY_MODE,
}
SOURCE_SUMMARY_RAW_MEAN = "mean"
SOURCE_SUMMARY_MEDIAN = "median"
SOURCE_SUMMARY_TRIMMED_MEAN = "trimmed_mean"
SOURCE_SUMMARY_DIRECT = "__source_map__"
SOURCE_SUMMARY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Raw mean z-score", SOURCE_SUMMARY_RAW_MEAN),
    ("Median z-score", SOURCE_SUMMARY_MEDIAN),
    ("20% trimmed mean z-score", SOURCE_SUMMARY_TRIMMED_MEAN),
)
SOURCE_SUMMARY_ORDER = tuple(summary_id for _label, summary_id in SOURCE_SUMMARY_OPTIONS)


@dataclass
class _ManifestConditionGroup:
    condition_id: str
    label: str
    entries_by_summary: dict[str, PreparedSourceManifestEntry]


@dataclass
class _ManifestMethodGroup:
    method_id: str
    label: str
    condition_groups: dict[str, _ManifestConditionGroup]


@dataclass(frozen=True)
class ProjectSourceMapExportFailure:
    """One failed source-map export within a batch rebuild."""

    export_mode: str
    message: str


@dataclass(frozen=True)
class ProjectSourceMapExportBatchResult:
    """One user-facing source-map rebuild action, potentially spanning methods."""

    requested_modes: tuple[str, ...]
    results: tuple[object, ...]
    failures: tuple[ProjectSourceMapExportFailure, ...] = ()

    @property
    def output_dir(self) -> Path | None:
        for result in reversed(self.results):
            output_dir = getattr(result, "output_dir", None)
            if isinstance(output_dir, Path):
                return output_dir
        return None

    @property
    def manifest_path(self) -> Path | None:
        for result in reversed(self.results):
            manifest_path = getattr(result, "manifest_path", None)
            if isinstance(manifest_path, Path):
                return manifest_path
        return None


class FsaverageLoadWorker(QObject):
    """Load fsaverage mesh data without touching widgets."""

    loaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, *, allow_fetch: bool) -> None:
        super().__init__()
        self._allow_fetch = allow_fetch

    @Slot()
    def run(self) -> None:
        try:
            result = load_fsaverage_brain_mesh(allow_fetch=self._allow_fetch)
        except FsaverageMeshError as exc:
            self.failed.emit(str(exc))
        except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError, TimeoutError) as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(result)
        finally:
            self.finished.emit()


class ProjectSourceMapExportWorker(QObject):
    """Write project beta source maps without touching widgets."""

    progress = Signal(str)
    exported = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        project_root: Path,
        export_modes: tuple[str, ...],
        include_flagged_subjects: bool,
        zscore_model: str,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._export_modes = export_modes
        self._include_flagged_subjects = include_flagged_subjects
        self._zscore_model = zscore_model

    @Slot()
    def run(self) -> None:
        results: list[object] = []
        failures: list[ProjectSourceMapExportFailure] = []
        try:
            for index, export_mode in enumerate(self._export_modes, start=1):
                self.progress.emit(
                    f"Building {_source_export_mode_label(export_mode)} ({index}/{len(self._export_modes)})..."
                )
                try:
                    results.append(self._run_export_mode(export_mode))
                except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError) as exc:
                    failures.append(ProjectSourceMapExportFailure(export_mode=export_mode, message=str(exc)))
                    self.progress.emit(f"{_source_export_mode_label(export_mode)} failed: {exc}")
            if results:
                self.exported.emit(
                    ProjectSourceMapExportBatchResult(
                        requested_modes=self._export_modes,
                        results=tuple(results),
                        failures=tuple(failures),
                    )
                )
            else:
                failure_text = "; ".join(
                    f"{_source_export_mode_label(item.export_mode)}: {item.message}" for item in failures
                )
                self.failed.emit(failure_text or "No project source-map exporters ran.")
        finally:
            self.finished.emit()

    def _run_export_mode(self, export_mode: str) -> object:
        if export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
            from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
                write_project_l2_mne_hauk_zscore_payloads,
            )

            if self._zscore_model == PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST:
                self.progress.emit("Starting deprecated group-first L2-MNE source-space z-score rebuild...")
            else:
                self.progress.emit("Starting participant-first L2-MNE source-space z-score rebuild...")
            return write_project_l2_mne_hauk_zscore_payloads(
                project_root=self._project_root,
                include_flagged_subjects=self._include_flagged_subjects,
                zscore_model=self._zscore_model,
                progress_callback=self.progress.emit,
            )
        if export_mode == PROJECT_SOURCE_EXPORT_ELORETA_VOLUME:
            from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
                write_project_eloreta_volume_hauk_zscore_payloads,
            )

            self.progress.emit("Starting beta eLORETA volume source-space z-score rebuild...")
            return write_project_eloreta_volume_hauk_zscore_payloads(
                project_root=self._project_root,
                include_flagged_subjects=self._include_flagged_subjects,
                progress_callback=self.progress.emit,
            )
        raise ValueError(f"Unsupported project source export mode: {export_mode}")


def resolve_loreta_import_start_dir(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
) -> str:
    """Return the preferred starting folder for LORETA JSON file dialogs."""
    if last_import_dir is not None and last_import_dir.is_dir():
        return str(last_import_dir)
    if project_root is not None and project_root.is_dir():
        from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
            default_project_eloreta_volume_output_dir,
        )
        from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
            default_project_l2_mne_hauk_zscore_output_dir,
        )
        from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
            default_project_l2_mne_output_dir,
        )

        for source_dir in (
            default_project_l2_mne_hauk_zscore_output_dir(project_root),
            default_project_eloreta_volume_output_dir(project_root),
            default_project_l2_mne_output_dir(project_root),
        ):
            if source_dir.is_dir():
                return str(source_dir)
        return str(project_root)
    return ""


def default_project_zscore_manifest_path(project_root: Path | None) -> Path | None:
    """Return the default project z-score manifest path when it already exists."""
    if project_root is None or not project_root.is_dir():
        return None
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
        DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME,
        default_project_l2_mne_hauk_zscore_output_dir,
    )

    manifest_path = (
        default_project_l2_mne_hauk_zscore_output_dir(project_root)
        / DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME
    )
    return manifest_path if manifest_path.is_file() else None


def default_project_source_manifest_paths(project_root: Path | None) -> tuple[Path, ...]:
    """Return existing default project source manifests in preferred display order."""
    if project_root is None or not project_root.is_dir():
        return ()
    paths: list[Path] = []
    zscore_manifest = default_project_zscore_manifest_path(project_root)
    if zscore_manifest is not None:
        paths.append(zscore_manifest)
    try:
        from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
            DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME,
            default_project_eloreta_volume_output_dir,
        )
    except (ImportError, ModuleNotFoundError):
        return tuple(paths)
    eloreta_manifest = (
        default_project_eloreta_volume_output_dir(project_root)
        / DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME
    )
    if eloreta_manifest.is_file():
        paths.append(eloreta_manifest)
    return tuple(paths)


def default_split_figure_export_path(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
    condition_label: str,
) -> str:
    """Return a helpful default path for publication split figure exports."""
    start_dir_text = resolve_loreta_import_start_dir(
        project_root=project_root,
        last_import_dir=last_import_dir,
    )
    stem = _safe_export_stem(f"loreta_split_hemispheres_{condition_label}")
    if start_dir_text:
        return str(Path(start_dir_text) / f"{stem}.pdf")
    return f"{stem}.pdf"


def default_stacked_split_figure_export_path(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
    top_condition_label: str,
    bottom_condition_label: str,
) -> str:
    """Return a helpful default path for stacked publication split figure exports."""
    top_code = split_figure_condition_code(top_condition_label)
    bottom_code = split_figure_condition_code(bottom_condition_label)
    start_dir_text = resolve_loreta_import_start_dir(
        project_root=project_root,
        last_import_dir=last_import_dir,
    )
    stem = _safe_export_stem(f"loreta_split_hemispheres_{top_code}_{bottom_code}")
    if start_dir_text:
        return str(Path(start_dir_text) / f"{stem}.pdf")
    return f"{stem}.pdf"


def split_figure_condition_code(condition_label: str) -> str:
    """Return the compact condition code used in stacked split-hemisphere figures."""
    label = str(condition_label).strip()
    lowered = label.lower()
    if "color response" in lowered:
        return "CR"
    if "semantic response" in lowered:
        return "SR"
    words = re.findall(r"[A-Za-z0-9]+", label)
    if not words:
        return "MAP"
    return "".join(word[0] for word in words[:3]).upper()


def split_figure_condition_display_label(condition_label: str) -> str:
    """Return the publication label shown above stacked split-hemisphere panels."""
    label = str(condition_label).strip()
    lowered = label.lower()
    if "color response" in lowered:
        return "Color Response"
    if "semantic response" in lowered:
        return "Semantic Response"
    return label


def _source_summary_label(summary_id: str) -> str:
    for label, candidate_id in SOURCE_SUMMARY_OPTIONS:
        if candidate_id == summary_id:
            return label
    return "Source map"


def _source_method_label(method_id: str) -> str:
    for label, candidate_id in SOURCE_METHOD_OPTIONS:
        if candidate_id == method_id:
            return label
    return "Prepared source"


def _manifest_entry_source_method_id(entry: PreparedSourceManifestEntry) -> str:
    metadata = entry.metadata
    identifiers = (
        metadata.get("source_method"),
        metadata.get("producer_method"),
        metadata.get("base_producer_method"),
        metadata.get("source_model"),
        entry.label,
        entry.condition_id,
    )
    joined = " ".join(str(value).lower() for value in identifiers if value is not None)
    if "eloreta" in joined or "eloreta_volume" in joined:
        return SOURCE_METHOD_ELORETA_VOLUME
    if "l2_mne" in joined or "l2-mne" in joined or "hauk_zscore" in joined:
        return SOURCE_METHOD_L2_MNE_SURFACE
    return SOURCE_METHOD_PREPARED


def _manifest_entry_summary_id(entry: PreparedSourceManifestEntry) -> str:
    summary_id = str(entry.metadata.get("participant_zscore_aggregation", "")).strip().lower()
    if summary_id in SOURCE_SUMMARY_ORDER:
        return summary_id
    return SOURCE_SUMMARY_DIRECT


def _manifest_entry_raw_id(entry: PreparedSourceManifestEntry) -> str:
    condition_id = str(entry.condition_id).strip()
    manifest_match = re.match(r"^manifest:\d+:(?P<raw_id>.+)$", condition_id)
    if manifest_match is not None:
        return manifest_match.group("raw_id")
    return condition_id


def _manifest_entry_condition_id(entry: PreparedSourceManifestEntry) -> str:
    summary_id = _manifest_entry_summary_id(entry)
    condition_id = _manifest_entry_raw_id(entry)
    if summary_id != SOURCE_SUMMARY_DIRECT:
        suffixes = {
            SOURCE_SUMMARY_RAW_MEAN: ("_raw_mean", "_mean"),
            SOURCE_SUMMARY_MEDIAN: ("_median",),
            SOURCE_SUMMARY_TRIMMED_MEAN: ("_20_trimmed_mean", "_trimmed_mean"),
        }.get(summary_id, (f"_{summary_id}",))
        for suffix in suffixes:
            if condition_id.endswith(suffix):
                return condition_id[: -len(suffix)] or condition_id
    return condition_id


def _manifest_entry_condition_label(entry: PreparedSourceManifestEntry) -> str:
    label = str(entry.label).strip()
    if _manifest_entry_summary_id(entry) == SOURCE_SUMMARY_DIRECT:
        return label
    return re.sub(
        r"\s+(raw mean|median|\d+%\s+trimmed mean)\s+z-score$",
        "",
        label,
        flags=re.IGNORECASE,
    ).strip() or label


def _group_manifest_conditions(
    entries: tuple[PreparedSourceManifestEntry, ...],
) -> dict[str, _ManifestConditionGroup]:
    groups: dict[str, _ManifestConditionGroup] = {}
    for entry in entries:
        condition_id = _manifest_entry_condition_id(entry)
        summary_id = _manifest_entry_summary_id(entry)
        group = groups.get(condition_id)
        if group is None:
            group = _ManifestConditionGroup(
                condition_id=condition_id,
                label=_manifest_entry_condition_label(entry),
                entries_by_summary={},
            )
            groups[condition_id] = group
        if summary_id in group.entries_by_summary:
            summary_id = entry.condition_id
        group.entries_by_summary[summary_id] = entry
    return groups


def _group_manifest_methods(
    entries: tuple[PreparedSourceManifestEntry, ...],
) -> dict[str, _ManifestMethodGroup]:
    grouped_entries: dict[str, list[PreparedSourceManifestEntry]] = {}
    for entry in entries:
        grouped_entries.setdefault(_manifest_entry_source_method_id(entry), []).append(entry)
    methods: dict[str, _ManifestMethodGroup] = {}
    for method_id, method_entries in grouped_entries.items():
        method_tuple = tuple(method_entries)
        methods[method_id] = _ManifestMethodGroup(
            method_id=method_id,
            label=_source_method_label(method_id),
            condition_groups=_group_manifest_conditions(method_tuple),
        )
    return methods


def _ordered_source_summary_ids(group: _ManifestConditionGroup) -> tuple[str, ...]:
    known = [summary_id for summary_id in SOURCE_SUMMARY_ORDER if summary_id in group.entries_by_summary]
    unknown = [summary_id for summary_id in group.entries_by_summary if summary_id not in SOURCE_SUMMARY_ORDER]
    return tuple(known + unknown)


def _safe_export_stem(text: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text).strip())
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return stem or "loreta_split_hemispheres"


def _object_name_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _coerce_existing_project_root(value: object) -> Path | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        root = Path(value)
    except TypeError:
        return None
    if root.exists():
        return root.resolve()
    return None


def _project_root_from_object(candidate: object | None) -> Path | None:
    if candidate is None:
        return None
    project = getattr(candidate, "currentProject", None)
    root = _coerce_existing_project_root(getattr(project, "project_root", None))
    if root is not None:
        return root
    return _coerce_existing_project_root(getattr(candidate, "project_root", None))


def _activation_color_ramp_stylesheet(colors: tuple[str, ...] = LORETA_SCALAR_COLORS) -> str:
    stops = []
    max_index = max(len(colors) - 1, 1)
    for index, color in enumerate(colors):
        stops.append(f"stop:{index / max_index:.3f} {color}")
    return (
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"{', '.join(stops)});"
        "border: 1px solid #d6dee8;"
        "border-radius: 2px;"
    )


def _activation_value_readout(
    payload: SourcePayload | None,
    *,
    zscore_display_threshold: float = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    cortical_threshold_display: bool = True,
    use_cluster_mask: bool = True,
) -> str:
    if payload is None:
        return "Value: source activation"
    label = payload.value_label.strip() or "source activation"
    source_unit = str(payload.metadata.get("source_value_unit", "")).strip()
    sensor_unit = str(payload.metadata.get("sensor_value_unit", "")).strip()
    filter_text = _activation_display_filter_readout(
        payload,
        zscore_display_threshold=zscore_display_threshold,
        cortical_threshold_display=cortical_threshold_display,
        use_cluster_mask=use_cluster_mask,
    )
    if source_unit and sensor_unit:
        return f"Value: {label}; unit: {source_unit}; input: {sensor_unit}{filter_text}"
    if source_unit:
        return f"Value: {label}; unit: {source_unit}{filter_text}"
    if sensor_unit:
        return f"Value: {label}; input: {sensor_unit}{filter_text}"
    return f"Value: {label}{filter_text}"


def _activation_display_filter_readout(
    payload: SourcePayload,
    *,
    zscore_display_threshold: float = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    cortical_threshold_display: bool = True,
    use_cluster_mask: bool = True,
) -> str:
    if cortical_threshold_display and uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
        if not use_cluster_mask:
            if payload_has_cluster_mask(payload) or payload_cluster_mask_is_underpowered(payload):
                return f"; display: exploratory z >= {format_scalar_value(zscore_display_threshold)}"
            return f"; display: z >= {format_scalar_value(zscore_display_threshold)}"
        if payload_cluster_mask_is_underpowered(payload):
            return f"; display: exploratory z >= {format_scalar_value(zscore_display_threshold)}"
        if payload_cluster_mask_is_empty(payload):
            return f"; display: exploratory z >= {format_scalar_value(zscore_display_threshold)}"
        if payload_has_cluster_mask(payload):
            return "; display: Hauk et al. (2025) cluster mask"
        return f"; display: z >= {format_scalar_value(zscore_display_threshold)}"
    filter_name = payload.metadata.get("display_value_filter")
    if filter_name == "cluster_mask":
        return "; display: Hauk et al. (2025) cluster mask"
    if filter_name != "values_above_threshold":
        return ""
    threshold = payload.metadata.get("display_value_filter_threshold")
    try:
        threshold_text = format_scalar_value(float(threshold))
    except (TypeError, ValueError):
        threshold_text = "threshold"
    return f"; display: > {threshold_text}"


def _source_payload_uses_zscores(payload: SourcePayload) -> bool:
    return source_payload_uses_zscores(payload)


def _activation_display_payload(
    payload: SourcePayload,
    *,
    transparent_mesh_display: bool = False,
    use_cluster_mask: bool = True,
) -> SourcePayload:
    if _source_payload_uses_zscores(payload) and (
        transparent_mesh_display or not uses_cortical_surface_paint(payload)
    ):
        if use_cluster_mask:
            cluster_mask = payload_cluster_mask(payload)
            if cluster_mask is not None and np.any(cluster_mask):
                return filter_source_payload_by_mask(payload, cluster_mask, filter_label="cluster_mask")
        return filter_source_payload_values_above(payload, threshold=0.0)
    return payload


def _activation_scale_values(
    payload: SourcePayload,
    *,
    zscore_display_threshold: float = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    cortical_threshold_display: bool = True,
    use_cluster_mask: bool = True,
) -> np.ndarray:
    values = np.asarray(payload.values, dtype=float)
    if cortical_threshold_display and uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
        cluster_mask = payload_cluster_mask(payload) if use_cluster_mask else None
        if cluster_mask is not None and np.any(cluster_mask):
            return values[cluster_mask & np.isfinite(values)]
        return values[values >= float(zscore_display_threshold)]
    return values


def _underpowered_cluster_mask_status_text(payload: SourcePayload) -> str | None:
    if not (
        _source_payload_uses_zscores(payload)
        and payload_cluster_mask_is_underpowered(payload)
    ):
        return None
    participant_count = payload.metadata.get("participant_count")
    minimum_p = payload_cluster_mask_minimum_p(payload)
    sample_text = ""
    try:
        sample_text = f" ({int(participant_count)} participants)"
    except (TypeError, ValueError):
        pass
    p_text = f"; minimum possible cluster p = {format_scalar_value(minimum_p)}" if np.isfinite(minimum_p) else ""
    render_text = "Opaque cortical renders" if uses_cortical_surface_paint(payload) else "Volume renders"
    return (
        f"Due to the small sample size{sample_text}, the cluster-based permutation mask cannot be "
        f"applied at the selected alpha{p_text}. {render_text} are underpowered, "
        "not group-masked, and should be considered exploratory."
    )


def _display_mode_allowed_for_payload(payload: SourcePayload, display_mode: str) -> bool:
    if uses_cortical_surface_paint(payload):
        return display_mode in {
            DISPLAY_MODE_SPLIT_HEMISPHERE,
            DISPLAY_MODE_CORTICAL_SURFACE,
            DISPLAY_MODE_TRANSPARENT_MESH,
        }
    return display_mode == DISPLAY_MODE_TRANSPARENT_MESH


def _preferred_display_mode_for_payload(payload: SourcePayload) -> str:
    if uses_cortical_surface_paint(payload):
        return DISPLAY_MODE_SPLIT_HEMISPHERE
    return DISPLAY_MODE_TRANSPARENT_MESH


def _source_export_status_text(
    export_mode: str,
    *,
    automatic: bool,
    include_flagged_subjects: bool,
    zscore_model: str = PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
) -> str:
    flag_text = "including flagged participants" if include_flagged_subjects else "excluding flagged participants"
    if export_mode == PROJECT_SOURCE_EXPORT_ALL_ZSCORE:
        action = "Preparing" if automatic else "Building"
        return f"{action} L2-MNE surface and eLORETA volume source-space z-score maps ({flag_text})..."
    if automatic:
        return f"Preparing participant-first project source-space z-score maps ({flag_text})..."
    if export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
        if zscore_model == PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST:
            return f"Building deprecated group-first source-space z-score JSON from the active project ({flag_text})..."
        return f"Building participant-first source-space z-score JSON from the active project ({flag_text})..."
    if export_mode == PROJECT_SOURCE_EXPORT_ELORETA_VOLUME:
        return f"Building beta eLORETA volume source-space z-score JSON from the active project ({flag_text})..."
    return f"Building beta L2-MNE source JSON from the active project ({flag_text})..."


def _source_export_mode_label(export_mode: str) -> str:
    if export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
        return "L2-MNE surface source maps"
    if export_mode == PROJECT_SOURCE_EXPORT_ELORETA_VOLUME:
        return "eLORETA volume source maps"
    return "source maps"


def _project_source_export_failure_text(message: str) -> str:
    detail = str(message).strip()
    lowered = detail.lower()
    if (
        "stats-ready workbook" in lowered
        or "harmonic_selection" in lowered
        or "selected harmonics" in lowered
        or "fullfft amplitude" in lowered
        or "fullfft workbooks" in lowered
        or "fullfft source z-score" in lowered
    ):
        return (
            "Project source maps are not ready yet. Re-run preprocessing for this project, then open Stats and run "
            "Export Stats-Ready Workbook before returning to LORETA Visualizer."
            f" Details: {detail}"
        )
    return f"Project source export failed: {detail}"


class SourceMapOptionsDialog(AppDialog):
    """Small modal for source-map rebuild and import options."""

    def __init__(
        self,
        parent: QWidget,
        *,
        include_flagged_subjects: bool,
        zscore_display_threshold: float,
        use_cluster_mask: bool,
        source_map_visible: bool,
        transparent_spin_enabled: bool,
        project_available: bool,
        export_busy: bool,
    ) -> None:
        super().__init__("Options", parent, size=SurfaceSize(width=480, height=440, min_width=430))
        self.selected_action: str | None = None
        self._syncing_threshold_controls = False

        method_label = QLabel(
            "Project maps use participant-first source-space z-scores from project FullFFT target/noise bins "
            "and Stats-selected oddball harmonics. Choose the source method to rebuild below.",
            self,
        )
        method_label.setObjectName("loreta_source_options_method_label")
        method_label.setWordWrap(True)
        self.root_layout.addWidget(method_label)

        tabs = QTabWidget(self)
        tabs.setObjectName("loreta_source_options_tabs")
        self.root_layout.addWidget(tabs)

        display_tab = QWidget(tabs)
        display_layout = QVBoxLayout(display_tab)
        display_layout.setContentsMargins(8, 8, 8, 8)
        display_layout.setSpacing(8)

        threshold_label = QLabel("Cortical z-score display threshold", display_tab)
        threshold_label.setObjectName("loreta_zscore_threshold_label")
        display_layout.addWidget(threshold_label)

        self.zscore_threshold_combo = QComboBox(display_tab)
        self.zscore_threshold_combo.setObjectName("loreta_zscore_threshold_combo")
        for label, threshold in ZSCORE_DISPLAY_THRESHOLD_PRESETS:
            self.zscore_threshold_combo.addItem(label, threshold)
        self.zscore_threshold_combo.addItem("Custom", ZSCORE_DISPLAY_THRESHOLD_CUSTOM_ID)
        self.zscore_threshold_combo.currentIndexChanged.connect(self._on_zscore_threshold_preset_changed)
        display_layout.addWidget(self.zscore_threshold_combo)

        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.setSpacing(8)
        threshold_spin_label = QLabel("Exploratory z cutoff", display_tab)
        threshold_spin_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.zscore_threshold_spin = QDoubleSpinBox(display_tab)
        self.zscore_threshold_spin.setObjectName("loreta_zscore_threshold_spin")
        self.zscore_threshold_spin.setRange(0.0, 10.0)
        self.zscore_threshold_spin.setDecimals(2)
        self.zscore_threshold_spin.setSingleStep(0.01)
        self.zscore_threshold_spin.valueChanged.connect(self._on_zscore_threshold_spin_changed)
        threshold_row.addWidget(threshold_spin_label, 0)
        threshold_row.addWidget(self.zscore_threshold_spin, 1)
        display_layout.addLayout(threshold_row)

        self.use_cluster_mask_check = QCheckBox("Use cluster mask when available", display_tab)
        self.use_cluster_mask_check.setObjectName("loreta_use_cluster_mask_check")
        self.use_cluster_mask_check.setChecked(bool(use_cluster_mask))
        self.use_cluster_mask_check.setToolTip(
            "Turn off for exploratory viewing with the selected z-score cutoff instead of the saved cluster mask."
        )
        display_layout.addWidget(self.use_cluster_mask_check)

        self.source_map_visible_check = QCheckBox("Show source map", display_tab)
        self.source_map_visible_check.setObjectName("loreta_source_map_visible_check")
        self.source_map_visible_check.setChecked(bool(source_map_visible))
        self.source_map_visible_check.setToolTip("Turn off to inspect the anatomical cortical surface without source colors.")
        display_layout.addWidget(self.source_map_visible_check)

        self.transparent_spin_check = QCheckBox("Spin transparent mesh view", display_tab)
        self.transparent_spin_check.setObjectName("loreta_transparent_spin_check")
        self.transparent_spin_check.setChecked(bool(transparent_spin_enabled))
        self.transparent_spin_check.setToolTip(
            "Slowly rotate the transparent mesh view; user interaction pauses it for 10 seconds."
        )
        display_layout.addWidget(self.transparent_spin_check)

        threshold_note = QLabel(
            "For Hauk et al., 2025 cluster-masked maps, this cutoff is used when "
            "the mask is unavailable, underpowered, empty, or disabled for exploratory viewing.",
            display_tab,
        )
        threshold_note.setObjectName("loreta_zscore_threshold_note")
        threshold_note.setWordWrap(True)
        display_layout.addWidget(threshold_note)
        display_layout.addStretch(1)
        tabs.addTab(display_tab, "Display")

        data_tab = QWidget(tabs)
        data_layout = QVBoxLayout(data_tab)
        data_layout.setContentsMargins(8, 8, 8, 8)
        data_layout.setSpacing(8)
        tabs.addTab(data_tab, "Data")

        data_note = QLabel(
            "Project rebuilds generate participant-first L2-MNE surface and eLORETA volume z-score maps.",
            data_tab,
        )
        data_note.setObjectName("loreta_source_options_data_note")
        data_note.setWordWrap(True)
        data_layout.addWidget(data_note)

        self.include_flagged_check = QCheckBox("Include Stats QC flagged participants in source-map calculations", self)
        self.include_flagged_check.setObjectName("loreta_include_flagged_subjects_check")
        self.include_flagged_check.setChecked(bool(include_flagged_subjects))
        self.include_flagged_check.setToolTip(
            "Leave unchecked to exclude participants listed in Flagged Participants.xlsx."
        )
        data_layout.addWidget(self.include_flagged_check)

        if export_busy:
            availability_text = "A source-map rebuild is already running. Rebuild actions will be available when it finishes."
        elif project_available:
            availability_text = "Rebuilds write project-local JSON and load the resulting manifest."
        else:
            availability_text = "Open a project to rebuild source maps."
        availability_label = QLabel(availability_text, self)
        availability_label.setObjectName("loreta_source_options_availability_label")
        availability_label.setWordWrap(True)
        data_layout.addWidget(availability_label)

        self.rebuild_zscore_btn = make_action_button("Rebuild source maps", compact=True, parent=self)
        self.rebuild_zscore_btn.setObjectName("loreta_options_rebuild_zscore_btn")
        self.rebuild_zscore_btn.setToolTip("Write L2-MNE surface and eLORETA volume source-space z-score JSON.")
        self.rebuild_zscore_btn.clicked.connect(lambda: self._select_action(SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE))
        data_layout.addWidget(self.rebuild_zscore_btn)

        self.load_source_payload_btn = make_action_button("Load source JSON", compact=True, parent=self)
        self.load_source_payload_btn.setObjectName("loreta_options_load_source_payload_btn")
        self.load_source_payload_btn.setToolTip("Load a prepared source payload JSON file.")
        self.load_source_payload_btn.clicked.connect(lambda: self._select_action(SOURCE_OPTIONS_ACTION_LOAD_PAYLOAD))
        data_layout.addWidget(self.load_source_payload_btn)

        self.load_source_manifest_btn = make_action_button("Load manifest", compact=True, parent=self)
        self.load_source_manifest_btn.setObjectName("loreta_options_load_source_manifest_btn")
        self.load_source_manifest_btn.setToolTip("Load a prepared source condition manifest.")
        self.load_source_manifest_btn.clicked.connect(lambda: self._select_action(SOURCE_OPTIONS_ACTION_LOAD_MANIFEST))
        data_layout.addWidget(self.load_source_manifest_btn)
        data_layout.addStretch(1)

        rebuild_enabled = project_available and not export_busy
        self.rebuild_zscore_btn.setEnabled(rebuild_enabled)
        self._set_threshold_controls_value(zscore_display_threshold)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)

    def _select_action(self, action: str) -> None:
        self.selected_action = action
        self.accept()

    def _set_threshold_controls_value(self, threshold: float) -> None:
        self._syncing_threshold_controls = True
        try:
            value = max(0.0, float(threshold))
            self.zscore_threshold_spin.setValue(value)
            preset_index = self.zscore_threshold_combo.count() - 1
            for index in range(self.zscore_threshold_combo.count()):
                item_data = self.zscore_threshold_combo.itemData(index)
                if isinstance(item_data, float) and abs(item_data - value) < 0.005:
                    preset_index = index
                    break
            self.zscore_threshold_combo.setCurrentIndex(preset_index)
        finally:
            self._syncing_threshold_controls = False

    def _on_zscore_threshold_preset_changed(self, _index: int) -> None:
        if self._syncing_threshold_controls:
            return
        item_data = self.zscore_threshold_combo.currentData()
        if isinstance(item_data, float):
            self._syncing_threshold_controls = True
            try:
                self.zscore_threshold_spin.setValue(item_data)
            finally:
                self._syncing_threshold_controls = False

    def _on_zscore_threshold_spin_changed(self, value: float) -> None:
        if self._syncing_threshold_controls:
            return
        self._syncing_threshold_controls = True
        try:
            preset_index = self.zscore_threshold_combo.count() - 1
            for index in range(self.zscore_threshold_combo.count()):
                item_data = self.zscore_threshold_combo.itemData(index)
                if isinstance(item_data, float) and abs(item_data - float(value)) < 0.005:
                    preset_index = index
                    break
            self.zscore_threshold_combo.setCurrentIndex(preset_index)
        finally:
            self._syncing_threshold_controls = False


class ExportFiguresDialog(AppDialog):
    """Compact launcher for available LORETA figure exports."""

    def __init__(
        self,
        parent: QWidget,
        *,
        can_export_split_figures: bool,
        can_export_stacked_split_figures: bool,
    ) -> None:
        super().__init__("Export Figures", parent, size=SurfaceSize(width=420, height=230, min_width=380))
        self.selected_action: str | None = None

        self.split_figures_btn = make_action_button("Export split hemisphere figures", compact=True, parent=self)
        self.split_figures_btn.setObjectName("loreta_export_figures_split_figures_btn")
        self.split_figures_btn.setEnabled(can_export_split_figures)
        self.split_figures_btn.setToolTip(
            "Export the current publication split-hemisphere view as 600 DPI PDF and PNG files."
            if can_export_split_figures
            else "Switch to Split Hemispheres with a loaded source map to export this figure."
        )
        self.split_figures_btn.clicked.connect(lambda: self._select_action(EXPORT_FIGURES_ACTION_SPLIT_FIGURES))
        self.root_layout.addWidget(self.split_figures_btn)

        self.stacked_split_figures_btn = make_action_button("Export condition stack figures", compact=True, parent=self)
        self.stacked_split_figures_btn.setObjectName("loreta_export_figures_stacked_split_figures_btn")
        self.stacked_split_figures_btn.setEnabled(can_export_stacked_split_figures)
        self.stacked_split_figures_btn.setToolTip(
            "Choose two conditions and export them as 600 DPI PDF and PNG files."
            if can_export_stacked_split_figures
            else "Load at least two source-map conditions before exporting a condition stack."
        )
        self.stacked_split_figures_btn.clicked.connect(
            lambda: self._select_action(EXPORT_FIGURES_ACTION_STACKED_SPLIT_FIGURES)
        )
        self.root_layout.addWidget(self.stacked_split_figures_btn)

        coming_next_label = QLabel(
            "Coming next: current view, transparent mesh, brain mesh, batch figure export.",
            self,
        )
        coming_next_label.setObjectName("loreta_export_figures_coming_next_label")
        coming_next_label.setWordWrap(True)
        self.root_layout.addWidget(coming_next_label)
        self.root_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)

    def _select_action(self, action: str) -> None:
        self.selected_action = action
        self.accept()


class StackedSplitFigureExportDialog(AppDialog):
    """Modal for choosing the two conditions in a stacked split-hemisphere figure."""

    def __init__(
        self,
        parent: QWidget,
        *,
        condition_options: tuple[tuple[str, str], ...],
        current_condition_id: str,
    ) -> None:
        super().__init__("Export Stacked Split Figures", parent, size=SurfaceSize(width=420, height=220, min_width=380))
        self._condition_options = condition_options

        top_label = QLabel("Top panel", self)
        top_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.root_layout.addWidget(top_label)
        self.top_condition_combo = QComboBox(self)
        self.top_condition_combo.setObjectName("loreta_stack_export_top_condition_combo")
        self.root_layout.addWidget(self.top_condition_combo)

        bottom_label = QLabel("Bottom panel", self)
        bottom_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.root_layout.addWidget(bottom_label)
        self.bottom_condition_combo = QComboBox(self)
        self.bottom_condition_combo.setObjectName("loreta_stack_export_bottom_condition_combo")
        self.root_layout.addWidget(self.bottom_condition_combo)

        for condition_id, label in condition_options:
            self.top_condition_combo.addItem(label, condition_id)
            self.bottom_condition_combo.addItem(label, condition_id)
        self._set_default_indices(current_condition_id)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)

    def selected_conditions(self) -> tuple[tuple[str, str], tuple[str, str]]:
        top_index = self.top_condition_combo.currentIndex()
        bottom_index = self.bottom_condition_combo.currentIndex()
        return self._condition_options[top_index], self._condition_options[bottom_index]

    def _set_default_indices(self, current_condition_id: str) -> None:
        top_index = self._find_condition_index("color response")
        bottom_index = self._find_condition_index("semantic response")
        current_index = self._find_condition_id_index(current_condition_id)
        if top_index < 0:
            top_index = current_index if current_index >= 0 else 0
        if bottom_index < 0 or bottom_index == top_index:
            bottom_index = 1 if len(self._condition_options) > 1 and top_index != 1 else 0
        self.top_condition_combo.setCurrentIndex(max(0, top_index))
        self.bottom_condition_combo.setCurrentIndex(max(0, bottom_index))

    def _find_condition_index(self, phrase: str) -> int:
        needle = phrase.lower()
        for index, (_condition_id, label) in enumerate(self._condition_options):
            if needle in label.lower():
                return index
        return -1

    def _find_condition_id_index(self, condition_id: str) -> int:
        for index, (candidate_id, _label) in enumerate(self._condition_options):
            if candidate_id == condition_id:
                return index
        return -1


class LoretaVisualizerWindow(QWidget):
    """Embedded workspace page for Phase 1 real-time brain rendering."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project_root: str | None = None,
        *,
        embedded: bool = True,
    ) -> None:
        super().__init__(parent)
        surface_size = SurfaceSize(width=1120, height=780)
        if not embedded:
            surface_size = SurfaceSize(width=1120, height=780, min_width=980)
        configure_window_surface(self, title="LORETA Visualizer", size=surface_size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._project_root = self._resolve_project_root(project_root)
        self.renderer: BrainRendererWidget | None = None
        self.status_banner: StatusBanner | None = None
        self._mesh_thread: QThread | None = None
        self._mesh_worker: FsaverageLoadWorker | None = None
        self._source_export_thread: QThread | None = None
        self._source_export_worker: ProjectSourceMapExportWorker | None = None
        self._selected_condition_id = ""
        self._selected_summary_id = SOURCE_SUMMARY_RAW_MEAN
        self._source_activation_payload: SourcePayload | None = None
        self._current_activation_payload: SourcePayload | None = None
        self._last_import_dir: Path | None = None
        self._manifest_conditions: dict[str, PreparedSourceManifestEntry] = {}
        self._manifest_method_groups: dict[str, _ManifestMethodGroup] = {}
        self._manifest_condition_groups: dict[str, _ManifestConditionGroup] = {}
        self._selected_source_method_id = SOURCE_METHOD_L2_MNE_SURFACE
        self._auto_project_zscore_attempted = False
        self._include_flagged_subjects = False
        self._zscore_display_threshold = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD
        self._use_cluster_mask = True
        self._activation_visible = True
        self._transparent_spin_enabled = False
        self._display_mode = DEFAULT_DISPLAY_MODE

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 2, 8, 8)
        root.setSpacing(8)

        self.mesh_status = StatusBanner(
            "Preparing fsaverage brain mesh...",
            self,
            variant="info",
        )
        root.addWidget(self.mesh_status, 0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        root.addLayout(body, 1)

        self.viewport = QWidget(self)
        self.viewport.setObjectName("loreta_visualizer_viewport")
        self.viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewport_layout = QVBoxLayout(self.viewport)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport_layout.setSpacing(0)
        body.addWidget(self.viewport, 1)

        body.addWidget(self._build_controls(), 0)
        self._initialize_renderer()
        if self.renderer is not None:
            self._start_fsaverage_load(allow_fetch=True)

    def _resolve_project_root(self, provided_root: str | os.PathLike[str] | None) -> Path | None:
        root = _coerce_existing_project_root(provided_root)
        if root is not None:
            return root
        widget_root = _project_root_from_object(self.window())
        if widget_root is not None:
            return widget_root
        parent_root = _project_root_from_object(self.parent())
        if parent_root is not None:
            return parent_root
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        root = _coerce_existing_project_root(env_root)
        if root is not None:
            return root
        parent: QObject | None = self.parent()
        while parent is not None:
            root = _project_root_from_object(parent)
            if root is not None:
                return root
            parent = parent.parent()
        return None

    def _refresh_project_root(self) -> Path | None:
        root = self._resolve_project_root(None)
        if root is None:
            root = _coerce_existing_project_root(self._project_root)
        self._project_root = root
        return root

    def _build_controls(self) -> SectionCard:
        controls = SectionCard("Source Map", self, object_name="loreta_view_controls")
        controls.setFixedWidth(260)
        controls.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        controls.header.setVisible(False)
        controls.shell_layout.setSpacing(0)
        controls.content_layout.setSpacing(8)

        def add_control_section(text: str, *, accent: bool = False) -> tuple[QWidget, QVBoxLayout]:
            _ = (text, accent)
            if controls.content_layout.count() > 0:
                controls.content_layout.addSpacing(10)
            return controls, controls.content_layout

        def make_field_label(text: str, parent: QWidget) -> QLabel:
            label = QLabel(text, parent)
            label.setProperty("caption", True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return label

        def add_label_value_row(target_layout: QVBoxLayout, label: QLabel, value_label: QLabel) -> None:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(label, 1)
            row.addWidget(value_label, 0)
            target_layout.addLayout(row)

        selection_section, selection_layout = add_control_section("Selection", accent=True)

        source_method_label = make_field_label("Method", selection_section)
        selection_layout.addWidget(source_method_label)

        self.source_method_combo = QComboBox(selection_section)
        self.source_method_combo.setObjectName("loreta_source_method_combo")
        self.source_method_combo.currentIndexChanged.connect(self._on_source_method_changed)
        selection_layout.addWidget(self.source_method_combo)

        condition_label = make_field_label("Condition", selection_section)
        selection_layout.addWidget(condition_label)

        self.condition_combo = QComboBox(selection_section)
        self.condition_combo.setObjectName("loreta_condition_combo")
        self.condition_combo.setPlaceholderText("No source maps loaded")
        self.condition_combo.currentIndexChanged.connect(self._on_condition_changed)
        selection_layout.addWidget(self.condition_combo)

        summary_label = make_field_label("Summary", selection_section)
        selection_layout.addWidget(summary_label)

        self.summary_combo = QComboBox(selection_section)
        self.summary_combo.setObjectName("loreta_source_summary_combo")
        self.summary_combo.currentIndexChanged.connect(self._on_summary_changed)
        selection_layout.addWidget(self.summary_combo)

        display_mode_label = make_field_label("Display", selection_section)
        selection_layout.addWidget(display_mode_label)

        self.display_mode_combo = QComboBox(selection_section)
        self.display_mode_combo.setObjectName("loreta_display_mode_combo")
        for label, mode in DISPLAY_MODE_OPTIONS:
            self.display_mode_combo.addItem(label, mode)
        self.display_mode_combo.currentIndexChanged.connect(self._on_display_mode_changed)
        selection_layout.addWidget(self.display_mode_combo)
        self._set_display_mode_combo_data(self._display_mode)

        color_section, color_layout = add_control_section("Color")

        self.activation_auto_scale_check = QCheckBox("Auto color scale", color_section)
        self.activation_auto_scale_check.setObjectName("loreta_activation_auto_scale_check")
        self.activation_auto_scale_check.setChecked(True)
        self.activation_auto_scale_check.toggled.connect(self._on_activation_auto_scale_changed)
        color_layout.addWidget(self.activation_auto_scale_check)

        self.activation_scale_mode_label = make_field_label("Auto color scale", color_section)
        self.activation_scale_mode_label.setObjectName("loreta_activation_scale_mode_label")
        color_layout.addWidget(self.activation_scale_mode_label)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(6)
        self.activation_scale_min_label = QLabel("", color_section)
        self.activation_scale_min_label.setObjectName("loreta_activation_scale_min_label")
        self.activation_scale_min_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.activation_color_ramp = QLabel("", color_section)
        self.activation_color_ramp.setObjectName("loreta_activation_color_ramp")
        self.activation_color_ramp.setFixedHeight(12)
        self.activation_color_ramp.setMinimumWidth(72)
        self.activation_color_ramp.setStyleSheet(_activation_color_ramp_stylesheet())
        self.activation_scale_max_label = QLabel("", color_section)
        self.activation_scale_max_label.setObjectName("loreta_activation_scale_max_label")
        self.activation_scale_max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        scale_row.addWidget(self.activation_scale_min_label, 0)
        scale_row.addWidget(self.activation_color_ramp, 1)
        scale_row.addWidget(self.activation_scale_max_label, 0)
        color_layout.addLayout(scale_row)

        range_label = make_field_label("Color range", color_section)
        color_layout.addWidget(range_label)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 0, 0, 0)
        range_row.setSpacing(6)
        self.activation_min_spin = QDoubleSpinBox(color_section)
        self.activation_min_spin.setObjectName("loreta_activation_min_spin")
        self.activation_min_spin.setDecimals(2)
        self.activation_min_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.activation_min_spin.setSingleStep(0.05)
        self.activation_min_spin.setValue(DEFAULT_SCALAR_MIN)
        self.activation_min_spin.valueChanged.connect(self._on_activation_range_changed)
        self.activation_max_spin = QDoubleSpinBox(color_section)
        self.activation_max_spin.setObjectName("loreta_activation_max_spin")
        self.activation_max_spin.setDecimals(2)
        self.activation_max_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.activation_max_spin.setSingleStep(0.05)
        self.activation_max_spin.setValue(DEFAULT_SCALAR_MAX)
        self.activation_max_spin.valueChanged.connect(self._on_activation_range_changed)
        range_row.addWidget(self.activation_min_spin)
        range_row.addWidget(make_field_label("to", color_section), 0)
        range_row.addWidget(self.activation_max_spin)
        color_layout.addLayout(range_row)

        view_section, view_layout = add_control_section("View")

        self.opacity_label = make_field_label("Brain opacity", view_section)

        self.transparency_value_label = make_field_label("", view_section)
        self.transparency_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        add_label_value_row(view_layout, self.opacity_label, self.transparency_value_label)

        self.transparency_slider = QSlider(Qt.Horizontal, view_section)
        self.transparency_slider.setObjectName("loreta_transparency_slider")
        self.transparency_slider.setRange(5, 100)
        self.transparency_slider.setValue(DEFAULT_OPACITY_PERCENT)
        self.transparency_slider.valueChanged.connect(self._on_transparency_changed)
        view_layout.addWidget(self.transparency_slider)

        self.activation_opacity_label = make_field_label("Source opacity", view_section)

        self.activation_opacity_value_label = make_field_label("", view_section)
        self.activation_opacity_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        add_label_value_row(view_layout, self.activation_opacity_label, self.activation_opacity_value_label)

        self.activation_opacity_slider = QSlider(Qt.Horizontal, view_section)
        self.activation_opacity_slider.setObjectName("loreta_activation_opacity_slider")
        self.activation_opacity_slider.setRange(0, 100)
        self.activation_opacity_slider.setValue(DEFAULT_ACTIVATION_OPACITY_PERCENT)
        self.activation_opacity_slider.valueChanged.connect(self._on_activation_opacity_changed)
        view_layout.addWidget(self.activation_opacity_slider)

        self.split_rotation_label = make_field_label("Hemisphere rotation", view_section)
        view_layout.addWidget(self.split_rotation_label)

        self.left_split_rotation_row = QWidget(view_section)
        left_split_rotation_layout = QHBoxLayout(self.left_split_rotation_row)
        left_split_rotation_layout.setContentsMargins(0, 0, 0, 0)
        left_split_rotation_layout.setSpacing(6)
        left_split_rotation_layout.addWidget(QLabel("Left", self.left_split_rotation_row), 1)
        self.left_split_rotate_minus_btn = make_action_button("-", compact=True, parent=self.left_split_rotation_row)
        self.left_split_rotate_minus_btn.setObjectName("loreta_left_split_rotate_minus_btn")
        self.left_split_rotate_minus_btn.setToolTip("Rotate left hemisphere counterclockwise")
        self.left_split_rotate_minus_btn.clicked.connect(
            lambda: self._rotate_split_hemisphere("left", -SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES)
        )
        self.left_split_rotate_plus_btn = make_action_button("+", compact=True, parent=self.left_split_rotation_row)
        self.left_split_rotate_plus_btn.setObjectName("loreta_left_split_rotate_plus_btn")
        self.left_split_rotate_plus_btn.setToolTip("Rotate left hemisphere clockwise")
        self.left_split_rotate_plus_btn.clicked.connect(
            lambda: self._rotate_split_hemisphere("left", SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES)
        )
        left_split_rotation_layout.addWidget(self.left_split_rotate_minus_btn, 0)
        left_split_rotation_layout.addWidget(self.left_split_rotate_plus_btn, 0)
        view_layout.addWidget(self.left_split_rotation_row)

        self.right_split_rotation_row = QWidget(view_section)
        right_split_rotation_layout = QHBoxLayout(self.right_split_rotation_row)
        right_split_rotation_layout.setContentsMargins(0, 0, 0, 0)
        right_split_rotation_layout.setSpacing(6)
        right_split_rotation_layout.addWidget(QLabel("Right", self.right_split_rotation_row), 1)
        self.right_split_rotate_minus_btn = make_action_button("-", compact=True, parent=self.right_split_rotation_row)
        self.right_split_rotate_minus_btn.setObjectName("loreta_right_split_rotate_minus_btn")
        self.right_split_rotate_minus_btn.setToolTip("Rotate right hemisphere counterclockwise")
        self.right_split_rotate_minus_btn.clicked.connect(
            lambda: self._rotate_split_hemisphere("right", -SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES)
        )
        self.right_split_rotate_plus_btn = make_action_button("+", compact=True, parent=self.right_split_rotation_row)
        self.right_split_rotate_plus_btn.setObjectName("loreta_right_split_rotate_plus_btn")
        self.right_split_rotate_plus_btn.setToolTip("Rotate right hemisphere clockwise")
        self.right_split_rotate_plus_btn.clicked.connect(
            lambda: self._rotate_split_hemisphere("right", SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES)
        )
        right_split_rotation_layout.addWidget(self.right_split_rotate_minus_btn, 0)
        right_split_rotation_layout.addWidget(self.right_split_rotate_plus_btn, 0)
        view_layout.addWidget(self.right_split_rotation_row)

        self.reset_camera_btn = make_action_button("Reset view", compact=True, parent=view_section)
        self.reset_camera_btn.setObjectName("loreta_reset_camera_btn")
        self.reset_camera_btn.setToolTip("Reset view")
        self.reset_camera_btn.clicked.connect(self._reset_camera)
        view_layout.addWidget(self.reset_camera_btn)

        actions_section, actions_layout = add_control_section("Actions")

        self.export_figures_btn = make_action_button(
            "Export Figures...",
            variant="primary",
            compact=True,
            parent=actions_section,
        )
        self.export_figures_btn.setObjectName("loreta_export_figures_btn")
        self.export_figures_btn.setToolTip("Open figure export actions.")
        self.export_figures_btn.clicked.connect(self._open_export_figures)
        actions_layout.addWidget(self.export_figures_btn)

        self.source_options_btn = make_action_button("Options...", compact=True, parent=actions_section)
        self.source_options_btn.setObjectName("loreta_source_options_btn")
        self.source_options_btn.setToolTip("Open display, source-map rebuild, import, and participant QC options.")
        self.source_options_btn.clicked.connect(self._open_source_map_options)
        actions_layout.addWidget(self.source_options_btn)
        controls.content_layout.addStretch(1)

        self._update_transparency_label(DEFAULT_OPACITY_PERCENT)
        self._update_activation_opacity_label(DEFAULT_ACTIVATION_OPACITY_PERCENT)
        self._sync_activation_range_enabled()
        self._sync_activation_render_mode_controls()
        self._update_activation_scale_readout(DEFAULT_SCALAR_MIN, DEFAULT_SCALAR_MAX)
        self._update_condition_status()
        return controls

    def _initialize_renderer(self) -> None:
        try:
            self.renderer = BrainRendererWidget(
                self.viewport,
                initial_opacity=DEFAULT_OPACITY_PERCENT / 100.0,
            )
        except RenderBackendError as exc:
            self.renderer = None
            self.status_banner = StatusBanner(
                f"3D rendering is unavailable: {exc}",
                self.viewport,
                variant="error",
            )
            self.viewport_layout.addWidget(self.status_banner)
            self._set_controls_enabled(False)
            return

        self.viewport_layout.addWidget(self.renderer, 1)
        self.renderer.set_display_mode(self._display_mode)
        self.renderer.set_cortical_paint_cluster_mask_enabled(self._use_cluster_mask)
        self.renderer.set_transparent_spin_enabled(self._transparent_spin_enabled)
        self._set_controls_enabled(True)
        self._clear_activation_payload()

    def _set_controls_enabled(self, enabled: bool) -> None:
        opacity_enabled = enabled and not self._activation_uses_opaque_cortical_mode()
        self.transparency_slider.setEnabled(opacity_enabled)
        self.activation_opacity_slider.setEnabled(opacity_enabled)
        self.activation_auto_scale_check.setEnabled(enabled)
        self._sync_activation_range_enabled()
        self._sync_source_map_selectors_enabled()
        self.display_mode_combo.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)
        self.export_figures_btn.setEnabled(enabled)
        self.source_options_btn.setEnabled(enabled)
        self._sync_activation_render_mode_controls()
        self._sync_project_source_button()

    def _sync_project_source_button(self) -> None:
        if hasattr(self, "source_options_btn"):
            self.source_options_btn.setEnabled(self.renderer is not None)
            if self._source_export_thread is not None:
                self.source_options_btn.setToolTip(
                    "A source-map rebuild is running. Options remain available, but rebuild actions are paused."
                )
            else:
                self.source_options_btn.setToolTip("Open display, source-map rebuild, import, and participant QC options.")

    def _sync_source_map_selectors_enabled(self) -> None:
        if (
            not hasattr(self, "source_method_combo")
            or not hasattr(self, "condition_combo")
            or not hasattr(self, "summary_combo")
        ):
            return
        has_conditions = bool(self._manifest_condition_groups)
        renderer_available = self.renderer is not None
        self.source_method_combo.setEnabled(
            renderer_available and bool(self._manifest_method_groups) and self.source_method_combo.count() > 1
        )
        self.condition_combo.setEnabled(renderer_available and has_conditions)
        self.summary_combo.setEnabled(renderer_available and has_conditions and self.summary_combo.count() > 1)

    def _on_transparency_changed(self, value: int) -> None:
        self._update_transparency_label(value)
        renderer = self.renderer
        if renderer is not None:
            renderer.set_brain_opacity(value / 100.0)

    def _update_transparency_label(self, value: int) -> None:
        self.transparency_value_label.setText(f"{value}%")

    def _on_activation_opacity_changed(self, value: int) -> None:
        self._update_activation_opacity_label(value)
        renderer = self.renderer
        if renderer is not None:
            renderer.set_activation_opacity(value / 100.0)

    def _update_activation_opacity_label(self, value: int) -> None:
        self.activation_opacity_value_label.setText(f"{value}%")

    def _on_activation_auto_scale_changed(self, _checked: bool) -> None:
        self._sync_activation_range_enabled()
        self._apply_activation_scalar_range()

    def _on_activation_range_changed(self, _value: float) -> None:
        self._apply_activation_scalar_range()

    def _sync_activation_range_enabled(self) -> None:
        renderer_available = self.renderer is not None
        manual_enabled = renderer_available and not self.activation_auto_scale_check.isChecked()
        self.activation_min_spin.setEnabled(manual_enabled)
        self.activation_max_spin.setEnabled(manual_enabled)
        if hasattr(self, "activation_scale_mode_label"):
            self.activation_scale_mode_label.setText(
                "Auto color scale" if self.activation_auto_scale_check.isChecked() else "Manual color scale"
            )

    def _activation_uses_cortical_paint(self) -> bool:
        payload = self._current_activation_payload
        return payload is not None and uses_cortical_surface_paint(payload)

    def _activation_uses_opaque_cortical_mode(self) -> bool:
        return self._activation_uses_cortical_paint() and self._display_mode != DISPLAY_MODE_TRANSPARENT_MESH

    def _sync_activation_render_mode_controls(self) -> None:
        if not hasattr(self, "activation_opacity_slider"):
            return
        opaque_cortical_mode = self._activation_uses_opaque_cortical_mode()
        split_mode_active = opaque_cortical_mode and self._display_mode == DISPLAY_MODE_SPLIT_HEMISPHERE
        opacity_enabled = self.renderer is not None and not opaque_cortical_mode
        self.transparency_slider.setEnabled(opacity_enabled)
        self.activation_opacity_slider.setEnabled(opacity_enabled)
        for widget in (
            self.opacity_label,
            self.transparency_slider,
            self.transparency_value_label,
            self.activation_opacity_label,
            self.activation_opacity_slider,
            self.activation_opacity_value_label,
        ):
            widget.setVisible(not opaque_cortical_mode)
        for widget in (
            self.split_rotation_label,
            self.left_split_rotation_row,
            self.right_split_rotation_row,
        ):
            widget.setVisible(split_mode_active)
            widget.setEnabled(self.renderer is not None and split_mode_active)
        self.activation_color_ramp.setStyleSheet(_activation_color_ramp_stylesheet())

    def _set_display_mode_combo_data(self, display_mode: str) -> None:
        if not hasattr(self, "display_mode_combo"):
            return
        previous_block_state = self.display_mode_combo.blockSignals(True)
        try:
            for index in range(self.display_mode_combo.count()):
                if self.display_mode_combo.itemData(index) == display_mode:
                    self.display_mode_combo.setCurrentIndex(index)
                    return
        finally:
            self.display_mode_combo.blockSignals(previous_block_state)

    def _on_display_mode_changed(self, _index: int) -> None:
        mode = self.display_mode_combo.currentData()
        if not isinstance(mode, str):
            return
        payload = self._source_activation_payload
        if payload is not None and not _display_mode_allowed_for_payload(payload, mode):
            self._display_mode = _preferred_display_mode_for_payload(payload)
            self._set_display_mode_combo_data(self._display_mode)
            self._set_source_export_status(
                "Volume source maps render in Transparent brain mesh mode.",
                variant="info",
            )
            return
        self._display_mode = mode
        renderer = self.renderer
        if renderer is not None:
            if self._source_activation_payload is not None:
                self._set_activation_payload(self._source_activation_payload)
            else:
                renderer.set_display_mode(mode)
                renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
                renderer.set_activation_visible(self._activation_visible)
                self._sync_activation_render_mode_controls()
                self._apply_activation_scalar_range()

    def _on_source_method_changed(self, _index: int) -> None:
        method_id = self.source_method_combo.currentData()
        if not isinstance(method_id, str):
            return
        if method_id == self._selected_source_method_id and self._manifest_condition_groups:
            return
        self._selected_source_method_id = method_id
        self._display_mode = SOURCE_METHOD_DEFAULT_DISPLAY_MODE.get(method_id, DEFAULT_DISPLAY_MODE)
        self._set_display_mode_combo_data(self._display_mode)
        self._populate_condition_combo_for_selected_method(preferred_condition=self._selected_condition_id)
        self._sync_summary_combo_for_selected_condition(preferred_summary=self._selected_summary_id)
        self._refresh_current_activation()

    def _rotate_split_hemisphere(self, side: str, degrees: float) -> None:
        renderer = self.renderer
        if renderer is not None:
            renderer.rotate_split_hemisphere(side, degrees)

    def _set_activation_visibility_enabled(self, checked: bool) -> None:
        self._activation_visible = bool(checked)
        renderer = self.renderer
        if renderer is not None:
            renderer.set_activation_visible(self._activation_visible)

    def _on_condition_changed(self, _index: int) -> None:
        condition_id = self.condition_combo.currentData()
        if isinstance(condition_id, str):
            self._selected_condition_id = condition_id
            self._sync_summary_combo_for_selected_condition(preferred_summary=self._selected_summary_id)
        self._update_condition_status()
        self._refresh_current_activation()

    def _on_summary_changed(self, _index: int) -> None:
        summary_id = self.summary_combo.currentData()
        if isinstance(summary_id, str):
            self._selected_summary_id = summary_id
        self._refresh_current_activation()

    def _update_condition_status(self) -> None:
        manifest_entry = self._selected_manifest_entry()
        if manifest_entry is not None:
            return

    def _zoom_in(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_in()

    def _zoom_out(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_out()

    def _reset_camera(self) -> None:
        if self.renderer is not None:
            self.renderer.reset_camera()

    def _open_export_figures(self) -> None:
        renderer = self.renderer
        can_export_split_figures = (
            renderer is not None
            and renderer.display_mode() == DISPLAY_MODE_SPLIT_HEMISPHERE
            and renderer.can_export_split_hemisphere_figure()
        )
        can_export_stacked_split_figures = (
            self._selected_source_method_id == SOURCE_METHOD_L2_MNE_SURFACE
            and len(self._condition_options()) >= 2
        )
        dialog = ExportFiguresDialog(
            self,
            can_export_split_figures=can_export_split_figures,
            can_export_stacked_split_figures=can_export_stacked_split_figures,
        )
        if not dialog.exec():
            return
        if dialog.selected_action == EXPORT_FIGURES_ACTION_SPLIT_FIGURES:
            self._export_split_hemisphere_figures()
        elif dialog.selected_action == EXPORT_FIGURES_ACTION_STACKED_SPLIT_FIGURES:
            self._export_stacked_split_hemisphere_figures()

    def _export_split_hemisphere_figures(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        if renderer.display_mode() != DISPLAY_MODE_SPLIT_HEMISPHERE or not renderer.can_export_split_hemisphere_figure():
            self._set_source_export_status(
                "Switch to Split Hemispheres with a loaded source map before exporting figures.",
                variant="warning",
            )
            return
        project_root = self._refresh_project_root()
        default_path = default_split_figure_export_path(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
            condition_label=self._selected_condition_label(),
        )
        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export publication split hemisphere figures",
            default_path,
            "PDF files (*.pdf)",
        )
        if not file_name:
            return
        output_path = Path(file_name)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        try:
            pdf_path, png_path = renderer.write_split_hemisphere_figures(output_path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_split_figure_export_failed", extra={"path": str(output_path), "error": str(exc)})
            self._set_source_export_status(f"Split hemisphere figure export failed: {exc}", variant="warning")
            return
        self._last_import_dir = pdf_path.parent
        self._set_source_export_status(f"Exported split hemisphere figures: {pdf_path}; {png_path}", variant="success")

    def _export_stacked_split_hemisphere_figures(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        condition_options = self._condition_options()
        if len(condition_options) < 2:
            self._set_source_export_status(
                "Load at least two source-map conditions before exporting stacked figures.",
                variant="warning",
            )
            return
        dialog = StackedSplitFigureExportDialog(
            self,
            condition_options=condition_options,
            current_condition_id=self._selected_condition_id,
        )
        if not dialog.exec():
            return
        (top_id, top_label), (bottom_id, bottom_label) = dialog.selected_conditions()
        if top_id == bottom_id:
            self._set_source_export_status("Choose two different conditions for the stacked figure.", variant="warning")
            return
        try:
            top_payload = self._condition_payload_for_export(top_id)
            bottom_payload = self._condition_payload_for_export(bottom_id)
            scalar_range = self._stacked_split_scalar_range((top_payload, bottom_payload))
            panels = (
                renderer.split_hemisphere_figure_panel_for_payload(
                    top_payload,
                    label=split_figure_condition_display_label(top_label),
                    scalar_range=scalar_range,
                ),
                renderer.split_hemisphere_figure_panel_for_payload(
                    bottom_payload,
                    label=split_figure_condition_display_label(bottom_label),
                    scalar_range=scalar_range,
                ),
            )
        except (OSError, RuntimeError, TypeError, ValueError, PreparedSourcePayloadImportError) as exc:
            logger.warning("loreta_stacked_split_figure_prepare_failed", extra={"error": str(exc)})
            self._set_source_export_status(f"Stacked split figure export failed: {exc}", variant="warning")
            return

        project_root = self._refresh_project_root()
        default_path = default_stacked_split_figure_export_path(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
            top_condition_label=top_label,
            bottom_condition_label=bottom_label,
        )
        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export stacked split hemisphere figures",
            default_path,
            "PDF files (*.pdf)",
        )
        if not file_name:
            return
        output_path = Path(file_name)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        try:
            pdf_path, png_path = renderer.write_split_hemisphere_stack_figures(output_path, panels=panels)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_stacked_split_figure_export_failed", extra={"path": str(output_path), "error": str(exc)})
            self._set_source_export_status(f"Stacked split figure export failed: {exc}", variant="warning")
            return
        self._last_import_dir = pdf_path.parent
        self._set_source_export_status(f"Exported stacked split figures: {pdf_path}; {png_path}", variant="success")

    def _selected_condition_label(self) -> str:
        group = self._manifest_condition_groups.get(self._selected_condition_id)
        if group is not None:
            return group.label
        return "source map"

    def _selected_manifest_entry(self) -> PreparedSourceManifestEntry | None:
        return self._manifest_entry_for(self._selected_condition_id, self._selected_summary_id)

    def _manifest_entry_for(
        self,
        condition_id: str,
        summary_id: str | None = None,
    ) -> PreparedSourceManifestEntry | None:
        group = self._manifest_condition_groups.get(condition_id)
        if group is None:
            return None
        requested_summary = summary_id or self._selected_summary_id
        entry = group.entries_by_summary.get(requested_summary)
        if entry is not None:
            return entry
        for fallback_summary in _ordered_source_summary_ids(group):
            return group.entries_by_summary[fallback_summary]
        return None

    def _condition_options(self) -> tuple[tuple[str, str], ...]:
        return tuple((group.condition_id, group.label) for group in self._manifest_condition_groups.values())

    def _condition_payload_for_export(self, condition_id: str) -> SourcePayload:
        renderer = self.renderer
        if renderer is None:
            raise RuntimeError("3D renderer is not available.")
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            raise RuntimeError("No mesh transform is available.")
        manifest_entry = self._manifest_entry_for(condition_id, self._selected_summary_id)
        if manifest_entry is None:
            raise RuntimeError("No prepared source-map payload is available for the selected condition.")
        payload = load_prepared_source_payload_json(
            manifest_entry.payload_path,
            display_transform=display_transform,
        )
        payload.metadata.update(
            {
                "manifest_condition_id": manifest_entry.condition_id,
                "manifest_condition_label": manifest_entry.label,
                "manifest_metadata": manifest_entry.metadata,
            }
        )
        return _activation_display_payload(payload, use_cluster_mask=self._use_cluster_mask)

    def _stacked_split_scalar_range(self, payloads: tuple[SourcePayload, SourcePayload]) -> tuple[float, float]:
        scale_chunks = [
            _activation_scale_values(
                payload,
                zscore_display_threshold=self._zscore_display_threshold,
                cortical_threshold_display=uses_cortical_surface_paint(payload),
                use_cluster_mask=self._use_cluster_mask,
            )
            for payload in payloads
        ]
        scale_arrays = [chunk.reshape(-1) for chunk in scale_chunks if len(chunk)]
        scale_values = np.concatenate(scale_arrays) if scale_arrays else np.empty(0, dtype=float)
        all_cortical_zscore = all(
            uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload)
            for payload in payloads
        )
        if all_cortical_zscore:
            if self.activation_auto_scale_check.isChecked():
                return DEFAULT_STACKED_CORTICAL_ZSCORE_SCALAR_RANGE
            has_cluster_mask = self._use_cluster_mask and any(payload_has_cluster_mask(payload) for payload in payloads)
            if has_cluster_mask:
                return resolve_scalar_limits(
                    scale_values,
                    auto_scale=self.activation_auto_scale_check.isChecked(),
                    manual_min=self.activation_min_spin.value(),
                    manual_max=self.activation_max_spin.value(),
                )
            lower_bound = self._zscore_display_threshold
            if self.activation_auto_scale_check.isChecked():
                finite = scale_values[np.isfinite(scale_values)]
                vmax = float(np.nanmax(finite)) if len(finite) else lower_bound + 1.0
                return resolve_scalar_limits(
                    np.asarray([lower_bound, vmax], dtype=float),
                    auto_scale=False,
                    manual_min=lower_bound,
                    manual_max=vmax,
                )
            return resolve_scalar_limits(
                scale_values,
                auto_scale=False,
                manual_min=max(lower_bound, self.activation_min_spin.value()),
                manual_max=self.activation_max_spin.value(),
            )
        return resolve_scalar_limits(
            scale_values,
            auto_scale=self.activation_auto_scale_check.isChecked(),
            manual_min=self.activation_min_spin.value(),
            manual_max=self.activation_max_spin.value(),
        )

    def _open_source_map_options(self) -> None:
        if self.renderer is None:
            return
        project_root = self._refresh_project_root()
        dialog = SourceMapOptionsDialog(
            self,
            include_flagged_subjects=self._include_flagged_subjects,
            zscore_display_threshold=self._zscore_display_threshold,
            use_cluster_mask=self._use_cluster_mask,
            source_map_visible=self._activation_visible,
            transparent_spin_enabled=self._transparent_spin_enabled,
            project_available=project_root is not None,
            export_busy=self._source_export_thread is not None,
        )
        dialog.exec()
        self._include_flagged_subjects = dialog.include_flagged_check.isChecked()
        self._set_zscore_display_threshold(dialog.zscore_threshold_spin.value())
        self._set_cluster_mask_enabled(dialog.use_cluster_mask_check.isChecked())
        self._set_activation_visibility_enabled(dialog.source_map_visible_check.isChecked())
        self._set_transparent_spin_enabled(dialog.transparent_spin_check.isChecked())
        if dialog.selected_action == SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE:
            self._build_project_zscore_source_maps()
        elif dialog.selected_action == SOURCE_OPTIONS_ACTION_LOAD_PAYLOAD:
            self._load_prepared_source_payload()
        elif dialog.selected_action == SOURCE_OPTIONS_ACTION_LOAD_MANIFEST:
            self._load_prepared_source_manifest()

    def _load_prepared_source_payload(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        project_root = self._refresh_project_root()
        initial_dir = resolve_loreta_import_start_dir(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
        )
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load prepared source payload",
            initial_dir,
            "Prepared source payload (*.json);;JSON files (*.json)",
        )
        if not file_name:
            return
        self._import_prepared_source_payload(Path(file_name))

    def _set_zscore_display_threshold(self, threshold: float) -> None:
        self._zscore_display_threshold = max(0.0, float(threshold))
        renderer = self.renderer
        if renderer is not None:
            renderer.set_cortical_paint_z_threshold(self._zscore_display_threshold)
        self._apply_activation_scalar_range()

    def _set_cluster_mask_enabled(self, enabled: bool) -> None:
        self._use_cluster_mask = bool(enabled)
        renderer = self.renderer
        if renderer is not None:
            renderer.set_cortical_paint_cluster_mask_enabled(self._use_cluster_mask)
            if self._source_activation_payload is not None:
                self._set_activation_payload(self._source_activation_payload)
        self._apply_activation_scalar_range()

    def _set_transparent_spin_enabled(self, enabled: bool) -> None:
        self._transparent_spin_enabled = bool(enabled)
        renderer = self.renderer
        if renderer is not None:
            renderer.set_transparent_spin_enabled(self._transparent_spin_enabled)

    def _load_prepared_source_manifest(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        project_root = self._refresh_project_root()
        initial_dir = resolve_loreta_import_start_dir(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
        )
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load prepared source manifest",
            initial_dir,
            "Prepared source manifest (*.json);;JSON files (*.json)",
        )
        if not file_name:
            return
        self._import_prepared_source_manifest(Path(file_name))

    def _build_project_zscore_source_maps(self) -> None:
        self._build_project_source_maps_for_modes(PROJECT_SOURCE_EXPORT_DEFAULT_MODES)

    def _ensure_default_project_zscore_maps(self) -> None:
        project_root = self._refresh_project_root()
        if self._auto_project_zscore_attempted or project_root is None or self.renderer is None:
            return
        self._auto_project_zscore_attempted = True
        manifest_paths = default_project_source_manifest_paths(project_root)
        if manifest_paths:
            self._set_source_export_status("Loading project source-space z-score maps...", variant="info")
            self._last_import_dir = manifest_paths[0].parent
            self._import_prepared_source_manifests(manifest_paths)
            return
        self._build_project_source_maps_for_modes(PROJECT_SOURCE_EXPORT_DEFAULT_MODES, automatic=True)

    def _build_project_source_maps_for_mode(self, export_mode: str, *, automatic: bool = False) -> None:
        self._build_project_source_maps_for_modes((export_mode,), automatic=automatic)

    def _build_project_source_maps_for_modes(self, export_modes: tuple[str, ...], *, automatic: bool = False) -> None:
        project_root = self._refresh_project_root()
        if project_root is None:
            self._set_source_export_status("Open a project before building beta source JSON.", variant="warning")
            return
        modes = tuple(dict.fromkeys(export_modes))
        if not modes:
            self._set_source_export_status("No source-map exporters are available.", variant="warning")
            return
        if self._source_export_thread is not None:
            self._set_source_export_status(
                "Source-map rebuild is already running. You can keep using the viewer while it finishes.",
                variant="info",
            )
            return
        include_flagged_subjects = self._include_flagged_subjects
        zscore_model = PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST
        status_text = _source_export_status_text(
            PROJECT_SOURCE_EXPORT_ALL_ZSCORE if len(modes) > 1 else modes[0],
            automatic=automatic,
            include_flagged_subjects=include_flagged_subjects,
            zscore_model=zscore_model,
        )
        self._set_source_export_status(status_text, variant="info")
        self._sync_project_source_button()
        logger.info(
            "loreta_project_source_maps_export_started",
            extra={
                "project_root": str(project_root),
                "export_mode": ",".join(modes),
                "include_flagged_subjects": include_flagged_subjects,
                "zscore_model": zscore_model,
            },
        )

        thread = QThread(self)
        worker = ProjectSourceMapExportWorker(
            project_root=project_root,
            export_modes=modes,
            include_flagged_subjects=include_flagged_subjects,
            zscore_model=zscore_model,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_project_source_maps_progress)
        worker.exported.connect(self._on_project_source_maps_exported)
        worker.failed.connect(self._on_project_source_maps_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._project_source_export_finished)
        self._source_export_thread = thread
        self._source_export_worker = worker
        self._sync_project_source_button()
        thread.start()

    @Slot(str)
    def _on_project_source_maps_progress(self, message: str) -> None:
        self._set_source_export_status(message, variant="info")

    @Slot(object)
    def _on_project_source_maps_exported(self, result: object) -> None:
        export_results = result.results if isinstance(result, ProjectSourceMapExportBatchResult) else (result,)
        failures = result.failures if isinstance(result, ProjectSourceMapExportBatchResult) else ()
        valid_manifest_paths: list[Path] = []
        total_payload_count = 0
        last_output_dir: Path | None = None
        method_ids: list[str] = []
        for export_result in export_results:
            output_dir = getattr(export_result, "output_dir", None)
            manifest_path = getattr(export_result, "manifest_path", None)
            producer_result = getattr(export_result, "producer_result", None)
            payloads = tuple(getattr(producer_result, "payloads", ()) or ())
            if not isinstance(output_dir, Path) or not isinstance(manifest_path, Path):
                continue
            valid_manifest_paths.append(manifest_path)
            total_payload_count += len(payloads)
            last_output_dir = output_dir
            method_id = str(getattr(producer_result, "method_id", ""))
            if method_id:
                method_ids.append(method_id)
            project_inputs = getattr(export_result, "project_inputs", None)
            export_model = str(getattr(export_result, "export_model", PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST))
            flagged_subjects = tuple(getattr(project_inputs, "flagged_subjects", ()) or ())
            excluded_subjects = tuple(getattr(project_inputs, "excluded_subjects", ()) or ())
            logger.info(
                "loreta_project_source_maps_export_complete",
                extra={
                    "manifest_path": str(manifest_path),
                    "method_id": method_id,
                    "condition_count": len(payloads),
                    "include_flagged_subjects": self._include_flagged_subjects,
                    "zscore_model": export_model,
                    "flagged_subject_count": len(flagged_subjects),
                    "excluded_subject_count": len(excluded_subjects),
                },
            )
        if not valid_manifest_paths or last_output_dir is None:
            self._set_source_export_status(
                "Project source export failed: unexpected export result.",
                variant="warning",
            )
            return
        self._last_import_dir = last_output_dir
        if failures:
            failure_labels = ", ".join(_source_export_mode_label(failure.export_mode) for failure in failures)
            status_variant = "warning"
            status_text = (
                f"Prepared {total_payload_count} source-map condition summaries, but {failure_labels} failed. "
                "Loaded available regenerated maps."
            )
        else:
            status_variant = "success"
            status_text = (
                f"Prepared L2-MNE surface and eLORETA volume source-space z-score maps "
                f"for {total_payload_count} condition summaries. Loaded regenerated maps."
            )
        self._set_source_export_status(status_text, variant=status_variant)
        joined_methods = " ".join(method_ids).lower()
        joined_manifests = " ".join(str(path).lower() for path in valid_manifest_paths)
        preferred_method = self._selected_source_method_id
        if preferred_method not in {SOURCE_METHOD_L2_MNE_SURFACE, SOURCE_METHOD_ELORETA_VOLUME}:
            preferred_method = SOURCE_METHOD_L2_MNE_SURFACE
        if len(valid_manifest_paths) == 1:
            preferred_method = (
                SOURCE_METHOD_ELORETA_VOLUME
                if "eloreta" in joined_methods or "eloreta" in joined_manifests
                else SOURCE_METHOD_L2_MNE_SURFACE
            )
        self._selected_source_method_id = preferred_method
        project_root = self._refresh_project_root()
        default_paths = default_project_source_manifest_paths(project_root) if project_root is not None else ()
        if any(path in default_paths for path in valid_manifest_paths):
            self._import_prepared_source_manifests(default_paths, preferred_source_method_id=preferred_method)
        else:
            self._import_prepared_source_manifests(tuple(valid_manifest_paths), preferred_source_method_id=preferred_method)

    @Slot(str)
    def _on_project_source_maps_failed(self, message: str) -> None:
        logger.warning(
            "loreta_project_source_maps_export_failed",
            extra={
                "error": message,
                "include_flagged_subjects": self._include_flagged_subjects,
                "zscore_model": PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
            },
        )
        self._set_source_export_status(_project_source_export_failure_text(message), variant="warning")

    @Slot()
    def _project_source_export_finished(self) -> None:
        self._source_export_thread = None
        self._source_export_worker = None
        self._sync_project_source_button()

    def _set_source_export_status(self, message: str, *, variant: str) -> None:
        self.mesh_status.set_variant(variant)
        self.mesh_status.set_text(message)

    def _import_prepared_source_payload(self, path: Path) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            self._set_source_export_status(
                "Prepared source import failed: no mesh transform is available.",
                variant="warning",
            )
            return
        try:
            payload = load_prepared_source_payload_json(path, display_transform=display_transform)
        except PreparedSourcePayloadImportError as exc:
            logger.warning("loreta_prepared_source_payload_import_failed", extra={"path": str(path), "error": str(exc)})
            self._set_source_export_status(f"Prepared source import failed: {exc}", variant="warning")
            return
        self._last_import_dir = path.parent
        self._set_activation_payload(payload)
        self._set_payload_display_status(payload)

    def _import_prepared_source_manifest(self, path: Path) -> None:
        try:
            entries = load_prepared_source_manifest_json(path)
        except PreparedSourcePayloadImportError as exc:
            logger.warning("loreta_prepared_source_manifest_import_failed", extra={"path": str(path), "error": str(exc)})
            self._set_source_export_status(f"Prepared source manifest import failed: {exc}", variant="warning")
            return
        self._last_import_dir = path.parent
        self._replace_manifest_conditions(entries)
        self._select_first_condition_if_needed()
        self._refresh_current_activation()

    def _import_prepared_source_manifests(
        self,
        paths: tuple[Path, ...],
        *,
        preferred_source_method_id: str | None = None,
    ) -> None:
        entries: list[PreparedSourceManifestEntry] = []
        loaded_paths: list[Path] = []
        for path in paths:
            try:
                manifest_entries = load_prepared_source_manifest_json(path)
            except PreparedSourcePayloadImportError as exc:
                logger.warning(
                    "loreta_prepared_source_manifest_import_failed",
                    extra={"path": str(path), "error": str(exc)},
                )
                self._set_source_export_status(f"Prepared source manifest import failed: {exc}", variant="warning")
                continue
            entries.extend(manifest_entries)
            loaded_paths.append(path)
        if not entries:
            self._clear_activation_payload()
            return
        self._last_import_dir = loaded_paths[-1].parent
        if preferred_source_method_id:
            self._selected_source_method_id = preferred_source_method_id
        self._replace_manifest_conditions(tuple(entries))
        self._select_first_condition_if_needed()
        self._refresh_current_activation()

    def _replace_manifest_conditions(self, entries: tuple[PreparedSourceManifestEntry, ...]) -> None:
        previous_method_block_state = self.source_method_combo.blockSignals(True)
        previous_block_state = self.condition_combo.blockSignals(True)
        previous_summary_block_state = self.summary_combo.blockSignals(True)
        try:
            self.source_method_combo.clear()
            self.condition_combo.clear()
            self.summary_combo.clear()
            self._manifest_conditions = {entry.condition_id: entry for entry in entries}
            self._manifest_method_groups = _group_manifest_methods(entries)
            self._populate_method_combo_blocked()
            self._set_selected_source_method_from_loaded_groups()
            self._manifest_condition_groups = dict(
                self._manifest_method_groups.get(
                    self._selected_source_method_id,
                    _ManifestMethodGroup(
                        method_id=self._selected_source_method_id,
                        label=_source_method_label(self._selected_source_method_id),
                        condition_groups={},
                    ),
                ).condition_groups
            )
            for group in self._manifest_condition_groups.values():
                self.condition_combo.addItem(group.label, group.condition_id)
        finally:
            self.source_method_combo.blockSignals(previous_method_block_state)
            self.condition_combo.blockSignals(previous_block_state)
            self.summary_combo.blockSignals(previous_summary_block_state)
        self._sync_source_map_selectors_enabled()

    def _populate_method_combo_blocked(self) -> None:
        ordered_methods = [
            method_id
            for _label, method_id in SOURCE_METHOD_OPTIONS
            if method_id in self._manifest_method_groups
        ]
        ordered_methods.extend(
            method_id
            for method_id in self._manifest_method_groups
            if method_id not in ordered_methods
        )
        for method_id in ordered_methods:
            group = self._manifest_method_groups[method_id]
            self.source_method_combo.addItem(group.label, method_id)

    def _set_selected_source_method_from_loaded_groups(self) -> None:
        if self._selected_source_method_id not in self._manifest_method_groups:
            self._selected_source_method_id = next(iter(self._manifest_method_groups), SOURCE_METHOD_L2_MNE_SURFACE)
        for index in range(self.source_method_combo.count()):
            if self.source_method_combo.itemData(index) == self._selected_source_method_id:
                self.source_method_combo.setCurrentIndex(index)
                break

    def _populate_condition_combo_for_selected_method(self, *, preferred_condition: str | None = None) -> None:
        previous_block_state = self.condition_combo.blockSignals(True)
        previous_summary_block_state = self.summary_combo.blockSignals(True)
        try:
            self.condition_combo.clear()
            self.summary_combo.clear()
            method_group = self._manifest_method_groups.get(self._selected_source_method_id)
            self._manifest_condition_groups = dict(method_group.condition_groups) if method_group is not None else {}
            for group in self._manifest_condition_groups.values():
                self.condition_combo.addItem(group.label, group.condition_id)
        finally:
            self.condition_combo.blockSignals(previous_block_state)
            self.summary_combo.blockSignals(previous_summary_block_state)
        selected_condition = (
            preferred_condition if preferred_condition in self._manifest_condition_groups else None
        )
        if selected_condition is None:
            first_group = next(iter(self._manifest_condition_groups.values()), None)
            selected_condition = first_group.condition_id if first_group is not None else ""
        self._selected_condition_id = selected_condition or ""
        if selected_condition:
            self._set_condition_combo_data(selected_condition)
        self._sync_source_map_selectors_enabled()

    def _select_first_condition_if_needed(self) -> None:
        first_group = next(iter(self._manifest_condition_groups.values()), None)
        if first_group is None:
            self._clear_activation_payload()
            return
        if self._selected_condition_id not in self._manifest_condition_groups:
            self._selected_condition_id = first_group.condition_id
        self._set_condition_combo_data(self._selected_condition_id)
        self._sync_summary_combo_for_selected_condition(preferred_summary=self._selected_summary_id)

    def _set_condition_combo_data(self, condition_id: str) -> None:
        for index in range(self.condition_combo.count()):
            if self.condition_combo.itemData(index) == condition_id:
                self.condition_combo.setCurrentIndex(index)
                return

    def _sync_summary_combo_for_selected_condition(self, *, preferred_summary: str | None = None) -> None:
        previous_block_state = self.summary_combo.blockSignals(True)
        try:
            self.summary_combo.clear()
            group = self._manifest_condition_groups.get(self._selected_condition_id)
            if group is None:
                self.summary_combo.addItem("No source maps loaded", SOURCE_SUMMARY_DIRECT)
                self._selected_summary_id = SOURCE_SUMMARY_RAW_MEAN
            else:
                summary_ids = _ordered_source_summary_ids(group)
                for summary_id in summary_ids:
                    self.summary_combo.addItem(_source_summary_label(summary_id), summary_id)
                selected_summary = preferred_summary if preferred_summary in summary_ids else None
                if selected_summary is None and SOURCE_SUMMARY_RAW_MEAN in summary_ids:
                    selected_summary = SOURCE_SUMMARY_RAW_MEAN
                if selected_summary is None and summary_ids:
                    selected_summary = summary_ids[0]
                if selected_summary is not None:
                    self._selected_summary_id = selected_summary
                    for index in range(self.summary_combo.count()):
                        if self.summary_combo.itemData(index) == selected_summary:
                            self.summary_combo.setCurrentIndex(index)
                            break
        finally:
            self.summary_combo.blockSignals(previous_block_state)
        self._sync_source_map_selectors_enabled()

    def _start_fsaverage_load(self, *, allow_fetch: bool) -> None:
        if self._mesh_thread is not None:
            return
        self.mesh_status.set_variant("info")
        self.mesh_status.set_text(
            "Fetching/loading fsaverage through the FPVS Toolbox cache..."
            if allow_fetch
            else "Checking configured/root-local fsaverage cache..."
        )

        thread = QThread(self)
        worker = FsaverageLoadWorker(allow_fetch=allow_fetch)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_fsaverage_loaded)
        worker.failed.connect(self._on_fsaverage_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._mesh_load_finished)
        self._mesh_thread = thread
        self._mesh_worker = worker
        thread.start()

    @Slot(object)
    def _on_fsaverage_loaded(self, result: object) -> None:
        renderer = self.renderer
        if renderer is None or not isinstance(result, FsaverageMeshResult):
            return
        renderer.replace_brain_mesh(result.mesh, reset_camera=True)
        self._refresh_current_activation()
        self.mesh_status.set_variant("success")
        split_note = (
            f" Split view uses fsaverage {result.split_surface} hemispheres."
            if result.split_surface != result.surface
            else ""
        )
        shading_note = (
            f" Publication shading uses {result.split_shading_source}."
            if result.split_shading_source
            else ""
        )
        self.mesh_status.set_text(
            f"Using {result.source_label} mesh from cache ({result.triangle_count:,} triangles)."
            f"{split_note}{shading_note}"
        )
        self._ensure_default_project_zscore_maps()

    @Slot(str)
    def _on_fsaverage_failed(self, message: str) -> None:
        self.mesh_status.set_variant("warning")
        self.mesh_status.set_text(f"Using synthetic fallback mesh. {message}")

    @Slot()
    def _mesh_load_finished(self) -> None:
        self._mesh_thread = None
        self._mesh_worker = None
        self._sync_project_source_button()

    def _refresh_current_activation(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            return
        manifest_entry = self._selected_manifest_entry()
        if manifest_entry is not None:
            self._render_manifest_condition(manifest_entry)
            return
        self._clear_activation_payload()

    def _render_manifest_condition(self, entry: PreparedSourceManifestEntry) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            self._set_source_export_status(
                "Imported source condition failed: no mesh transform is available.",
                variant="warning",
            )
            return
        try:
            payload = load_prepared_source_payload_json(entry.payload_path, display_transform=display_transform)
        except PreparedSourcePayloadImportError as exc:
            logger.warning(
                "loreta_manifest_condition_payload_failed",
                extra={"path": str(entry.payload_path), "condition": entry.condition_id, "error": str(exc)},
            )
            self._set_source_export_status(f"Imported source condition failed: {exc}", variant="warning")
            return
        payload.metadata.update(
            {
                "manifest_condition_id": entry.condition_id,
                "manifest_condition_label": entry.label,
                "manifest_metadata": entry.metadata,
            }
        )
        self._set_activation_payload(payload)
        self._set_payload_display_status(payload)

    def _set_payload_display_status(self, payload: SourcePayload) -> None:
        underpowered_text = _underpowered_cluster_mask_status_text(payload)
        if underpowered_text is not None:
            self._set_source_export_status(underpowered_text, variant="warning")
            return
        if _source_payload_uses_zscores(payload):
            source_kind_text = "vertices" if uses_cortical_surface_paint(payload) else "source locations"
            if not getattr(self, "_use_cluster_mask", True) and payload_has_cluster_mask(payload):
                exploratory_text = (
                    f"z >= {format_scalar_value(self._zscore_display_threshold)}"
                    if uses_cortical_surface_paint(payload)
                    else "z > 0"
                )
                self._set_source_export_status(
                    (
                        "Cluster mask display is disabled. Showing exploratory "
                        f"{exploratory_text} instead."
                    ),
                    variant="info",
                )
                return
            if payload_cluster_mask_is_empty(payload):
                self._set_source_export_status(
                    f"No {source_kind_text} survived the Hauk et al. (2025) cluster-permutation mask.",
                    variant="warning",
                )
                return
            if payload_has_cluster_mask(payload):
                self._set_source_export_status(
                    "Loaded Hauk et al. (2025) source-estimation cluster mask.",
                    variant="info",
                )
                return
        if _source_payload_uses_zscores(payload) and not payload_has_cluster_mask(payload):
            self._set_source_export_status(
                "Loaded unmasked source map. Rebuild z-score maps to add cluster masks.",
                variant="warning",
            )

    def _clear_activation_payload(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        self._source_activation_payload = None
        self._current_activation_payload = None
        self._sync_activation_render_mode_controls()
        renderer.set_activation_payload(empty_source_payload("No source map loaded"))
        self.activation_scale_min_label.setText("")
        self.activation_scale_max_label.setText("")

    def _set_activation_payload(self, payload: SourcePayload) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        self._source_activation_payload = payload
        if not _display_mode_allowed_for_payload(payload, self._display_mode):
            self._display_mode = _preferred_display_mode_for_payload(payload)
            self._set_display_mode_combo_data(self._display_mode)
        display_payload = _activation_display_payload(
            payload,
            transparent_mesh_display=self._display_mode == DISPLAY_MODE_TRANSPARENT_MESH,
            use_cluster_mask=self._use_cluster_mask,
        )
        display_payload = renderer.display_payload_for_current_mesh(display_payload)
        self._current_activation_payload = display_payload
        self._sync_activation_render_mode_controls()
        renderer.set_display_mode(self._display_mode, refresh=False)
        renderer.set_cortical_paint_cluster_mask_enabled(self._use_cluster_mask)
        vmin, vmax = self._resolve_activation_scalar_range(display_payload)
        renderer.set_activation_scalar_range(vmin, vmax, refresh=False)
        self._update_activation_scale_readout(vmin, vmax)
        renderer.set_activation_payload(display_payload)
        renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
        renderer.set_activation_visible(self._activation_visible)

    def _resolve_activation_scalar_range(self, payload: SourcePayload) -> tuple[float, float]:
        scale_values = _activation_scale_values(
            payload,
            zscore_display_threshold=self._zscore_display_threshold,
            cortical_threshold_display=self._activation_uses_opaque_cortical_mode(),
            use_cluster_mask=self._use_cluster_mask,
        )
        if self._activation_uses_opaque_cortical_mode() and _source_payload_uses_zscores(payload):
            if self._use_cluster_mask and payload_has_cluster_mask(payload):
                vmin, vmax = resolve_scalar_limits(
                    scale_values,
                    auto_scale=self.activation_auto_scale_check.isChecked(),
                    manual_min=self.activation_min_spin.value(),
                    manual_max=self.activation_max_spin.value(),
                )
                return vmin, vmax
            lower_bound = self._zscore_display_threshold
            if self.activation_auto_scale_check.isChecked():
                finite = scale_values[np.isfinite(scale_values)]
                vmax = float(np.nanmax(finite)) if len(finite) else lower_bound + 1.0
                vmin, vmax = resolve_scalar_limits(
                    np.asarray([lower_bound, vmax], dtype=float),
                    auto_scale=False,
                    manual_min=lower_bound,
                    manual_max=vmax,
                )
            else:
                vmin, vmax = resolve_scalar_limits(
                    scale_values,
                    auto_scale=False,
                    manual_min=max(lower_bound, self.activation_min_spin.value()),
                    manual_max=self.activation_max_spin.value(),
                )
        else:
            vmin, vmax = resolve_scalar_limits(
                scale_values,
                auto_scale=self.activation_auto_scale_check.isChecked(),
                manual_min=self.activation_min_spin.value(),
                manual_max=self.activation_max_spin.value(),
            )
        return vmin, vmax

    def _apply_activation_scalar_range(self) -> None:
        renderer = self.renderer
        payload = self._current_activation_payload
        if renderer is None or payload is None:
            return
        vmin, vmax = self._resolve_activation_scalar_range(payload)
        renderer.set_activation_scalar_range(vmin, vmax)
        self._update_activation_scale_readout(vmin, vmax)

    def _update_activation_scale_readout(self, vmin: float, vmax: float) -> None:
        self.activation_scale_min_label.setText(format_scalar_value(vmin))
        self.activation_scale_max_label.setText(format_scalar_value(vmax))

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        renderer = self.renderer
        self.renderer = None
        if renderer is not None:
            renderer.shutdown()
        if self._mesh_thread is not None:
            self._mesh_thread.quit()
            self._mesh_thread.wait(1000)
        if self._source_export_thread is not None:
            self._source_export_thread.quit()
            self._source_export_thread.wait(1000)
        super().closeEvent(event)

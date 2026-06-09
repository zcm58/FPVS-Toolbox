"""Embedded PySide6 page for the LORETA 3D brain visualizer."""

from __future__ import annotations

import logging
import os
import re
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
    SubsectionHeaderLabel,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
)
from Tools.LORETA_Visualizer.conditions import DEMO_LORETA_CONDITIONS, condition_by_id, default_condition
from Tools.LORETA_Visualizer.cortical_paint import (
    DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    payload_cluster_mask,
    payload_has_cluster_mask,
    source_payload_uses_zscores,
    uses_cortical_surface_paint,
)
from Tools.LORETA_Visualizer.dummy_activation import make_demo_condition_activation
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
from Tools.LORETA_Visualizer.source_payloads import SourcePayload, filter_source_payload_values_above

logger = logging.getLogger(__name__)

DEFAULT_OPACITY_PERCENT = 48
DEFAULT_ACTIVATION_OPACITY_PERCENT = 72
DEFAULT_DISPLAY_MODE = DISPLAY_MODE_SPLIT_HEMISPHERE
PROJECT_SOURCE_EXPORT_AMPLITUDE = "amplitude"
PROJECT_SOURCE_EXPORT_HAUK_ZSCORE = "hauk_zscore"
PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST = "participant_first"
PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST = "deprecated_group_first"
SOURCE_OPTIONS_ACTION_LOAD_PAYLOAD = "load_payload"
SOURCE_OPTIONS_ACTION_LOAD_MANIFEST = "load_manifest"
SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE = "rebuild_zscore"
SOURCE_OPTIONS_ACTION_REBUILD_AMPLITUDE = "rebuild_amplitude"
ZSCORE_DISPLAY_THRESHOLD_CUSTOM_ID = "custom"
ZSCORE_DISPLAY_THRESHOLD_PRESETS: tuple[tuple[str, float], ...] = (
    ("z >= 1.64 (~one-tailed p < .05)", 1.64),
    ("z >= 1.96 (~two-tailed p < .05)", 1.96),
    ("z >= 2.58 (~two-tailed p < .01)", 2.58),
    ("z >= 3.29 (~two-tailed p < .001)", 3.29),
    ("z >= 3.89 (~two-tailed p < .0001)", 3.89),
)
DISPLAY_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Publication split hemispheres", DISPLAY_MODE_SPLIT_HEMISPHERE),
    ("Fsaverage cortical surface", DISPLAY_MODE_CORTICAL_SURFACE),
    ("Transparent brain mesh", DISPLAY_MODE_TRANSPARENT_MESH),
)


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
        export_mode: str,
        include_flagged_subjects: bool,
        zscore_model: str,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._export_mode = export_mode
        self._include_flagged_subjects = include_flagged_subjects
        self._zscore_model = zscore_model

    @Slot()
    def run(self) -> None:
        try:
            if self._export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
                from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
                    write_project_l2_mne_hauk_zscore_payloads,
                )

                if self._zscore_model == PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST:
                    self.progress.emit("Starting deprecated group-first source-space z-score rebuild...")
                else:
                    self.progress.emit("Starting participant-first source-space z-score rebuild...")
                result = write_project_l2_mne_hauk_zscore_payloads(
                    project_root=self._project_root,
                    include_flagged_subjects=self._include_flagged_subjects,
                    zscore_model=self._zscore_model,
                    progress_callback=self.progress.emit,
                )
            else:
                from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
                    write_project_l2_mne_cortical_surface_payloads,
                )

                self.progress.emit("Starting diagnostic L2-MNE amplitude source-map export...")
                result = write_project_l2_mne_cortical_surface_payloads(
                    project_root=self._project_root,
                    include_flagged_subjects=self._include_flagged_subjects,
                )
        except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError) as exc:
            self.failed.emit(str(exc))
        else:
            self.exported.emit(result)
        finally:
            self.finished.emit()


def resolve_loreta_import_start_dir(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
) -> str:
    """Return the preferred starting folder for LORETA JSON file dialogs."""
    if last_import_dir is not None and last_import_dir.is_dir():
        return str(last_import_dir)
    if project_root is not None and project_root.is_dir():
        from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
            default_project_l2_mne_hauk_zscore_output_dir,
        )
        from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
            default_project_l2_mne_output_dir,
        )

        for source_dir in (
            default_project_l2_mne_hauk_zscore_output_dir(project_root),
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


def default_split_svg_export_path(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
    condition_label: str,
) -> str:
    """Return a helpful default path for publication split SVG exports."""
    start_dir_text = resolve_loreta_import_start_dir(
        project_root=project_root,
        last_import_dir=last_import_dir,
    )
    stem = _safe_export_stem(f"loreta_split_hemispheres_{condition_label}")
    if start_dir_text:
        return str(Path(start_dir_text) / f"{stem}.svg")
    return f"{stem}.svg"


def default_stacked_split_svg_export_path(
    *,
    project_root: Path | None,
    last_import_dir: Path | None,
    top_condition_label: str,
    bottom_condition_label: str,
) -> str:
    """Return a helpful default path for stacked publication split SVG exports."""
    top_code = split_svg_condition_code(top_condition_label)
    bottom_code = split_svg_condition_code(bottom_condition_label)
    start_dir_text = resolve_loreta_import_start_dir(
        project_root=project_root,
        last_import_dir=last_import_dir,
    )
    stem = _safe_export_stem(f"loreta_split_hemispheres_{top_code}_{bottom_code}")
    if start_dir_text:
        return str(Path(start_dir_text) / f"{stem}.svg")
    return f"{stem}.svg"


def split_svg_condition_code(condition_label: str) -> str:
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


def _safe_export_stem(text: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text).strip())
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return stem or "loreta_split_hemispheres"


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
) -> str:
    if cortical_threshold_display and uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
        if payload_has_cluster_mask(payload):
            return "; display: source-space cluster mask"
        return f"; display: z >= {format_scalar_value(zscore_display_threshold)}"
    if payload.metadata.get("display_value_filter") != "values_above_threshold":
        return ""
    threshold = payload.metadata.get("display_value_filter_threshold")
    try:
        threshold_text = format_scalar_value(float(threshold))
    except (TypeError, ValueError):
        threshold_text = "threshold"
    return f"; display: > {threshold_text}"


def _source_payload_uses_zscores(payload: SourcePayload) -> bool:
    return source_payload_uses_zscores(payload)


def _activation_display_payload(payload: SourcePayload) -> SourcePayload:
    if _source_payload_uses_zscores(payload) and not uses_cortical_surface_paint(payload):
        return filter_source_payload_values_above(payload, threshold=0.0)
    return payload


def _activation_scale_values(
    payload: SourcePayload,
    *,
    zscore_display_threshold: float = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    cortical_threshold_display: bool = True,
) -> np.ndarray:
    values = np.asarray(payload.values, dtype=float)
    if cortical_threshold_display and uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
        cluster_mask = payload_cluster_mask(payload)
        if cluster_mask is not None:
            return values[cluster_mask & (values > 0.0)]
        return values[values >= float(zscore_display_threshold)]
    return values


def _source_export_status_text(
    export_mode: str,
    *,
    automatic: bool,
    include_flagged_subjects: bool,
    zscore_model: str = PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
) -> str:
    flag_text = "including flagged participants" if include_flagged_subjects else "excluding flagged participants"
    if automatic:
        return f"Preparing participant-first project source-space z-score maps ({flag_text})..."
    if export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
        if zscore_model == PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST:
            return f"Building deprecated group-first source-space z-score JSON from the active project ({flag_text})..."
        return f"Building participant-first source-space z-score JSON from the active project ({flag_text})..."
    return f"Building beta L2-MNE source JSON from the active project ({flag_text})..."


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
        zscore_model: str,
        zscore_display_threshold: float,
        project_available: bool,
        export_busy: bool,
    ) -> None:
        super().__init__("Source Map Options", parent, size=SurfaceSize(width=480, height=500, min_width=430))
        self.selected_action: str | None = None
        self._syncing_threshold_controls = False

        method_label = QLabel(
            "Default project maps use participant-first beta Hauk-style L2-MNE source-space z-scores. "
            "The method uses project FullFFT target/noise bins, Stats-selected oddball harmonics, "
            "and a BioSemi64/fsaverage cortical template.",
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
        threshold_spin_label = QLabel("z cutoff", display_tab)
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

        threshold_note = QLabel(
            "Values below this display cutoff render as gray cortex. "
            "Cluster-masked payloads use their producer-computed mask first.",
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

        zscore_model_label = QLabel("Z-score generation model", data_tab)
        zscore_model_label.setObjectName("loreta_zscore_model_label")
        data_layout.addWidget(zscore_model_label)

        self.zscore_model_combo = QComboBox(data_tab)
        self.zscore_model_combo.setObjectName("loreta_zscore_model_combo")
        self.zscore_model_combo.addItem(
            "Participant-first source z-scores (default)",
            PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
        )
        self.zscore_model_combo.addItem(
            "Deprecated group-first beta model",
            PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
        )
        for index in range(self.zscore_model_combo.count()):
            if self.zscore_model_combo.itemData(index) == zscore_model:
                self.zscore_model_combo.setCurrentIndex(index)
                break
        data_layout.addWidget(self.zscore_model_combo)

        deprecated_note = QLabel(
            "The deprecated group-first model is retained only for comparison and is planned for removal.",
            data_tab,
        )
        deprecated_note.setObjectName("loreta_zscore_model_deprecated_note")
        deprecated_note.setWordWrap(True)
        data_layout.addWidget(deprecated_note)

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

        self.rebuild_zscore_btn = make_action_button("Rebuild z-score maps", compact=True, parent=self)
        self.rebuild_zscore_btn.setObjectName("loreta_options_rebuild_zscore_btn")
        self.rebuild_zscore_btn.setToolTip("Write Hauk-style source-space z-score JSON and load it.")
        self.rebuild_zscore_btn.clicked.connect(lambda: self._select_action(SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE))
        data_layout.addWidget(self.rebuild_zscore_btn)

        self.rebuild_amplitude_btn = make_action_button("Build diagnostic amplitude maps", compact=True, parent=self)
        self.rebuild_amplitude_btn.setObjectName("loreta_options_rebuild_amplitude_btn")
        self.rebuild_amplitude_btn.setToolTip("Write diagnostic beta L2-MNE amplitude JSON and load it.")
        self.rebuild_amplitude_btn.clicked.connect(lambda: self._select_action(SOURCE_OPTIONS_ACTION_REBUILD_AMPLITUDE))
        data_layout.addWidget(self.rebuild_amplitude_btn)

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
        self.rebuild_amplitude_btn.setEnabled(rebuild_enabled)
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


class StackedSplitSvgExportDialog(AppDialog):
    """Modal for choosing the two conditions in a stacked split-hemisphere SVG."""

    def __init__(
        self,
        parent: QWidget,
        *,
        condition_options: tuple[tuple[str, str], ...],
        current_condition_id: str,
    ) -> None:
        super().__init__("Export Stacked Split SVG", parent, size=SurfaceSize(width=420, height=220, min_width=380))
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
        self._selected_condition_id = default_condition().condition_id
        self._current_activation_payload: SourcePayload | None = None
        self._last_import_dir: Path | None = None
        self._manifest_conditions: dict[str, PreparedSourceManifestEntry] = {}
        self._auto_project_zscore_attempted = False
        self._include_flagged_subjects = False
        self._zscore_model = PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST
        self._zscore_display_threshold = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD
        self._display_mode = DEFAULT_DISPLAY_MODE

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = SubsectionHeaderLabel("LORETA Visualizer", self)
        root.addWidget(header, 0)
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
        controls.setFixedWidth(240)

        condition_label = QLabel("Condition", controls)
        condition_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(condition_label)

        self.condition_combo = QComboBox(controls)
        self.condition_combo.setObjectName("loreta_condition_combo")
        for condition in DEMO_LORETA_CONDITIONS:
            self.condition_combo.addItem(condition.label, condition.condition_id)
        self.condition_combo.currentIndexChanged.connect(self._on_condition_changed)
        controls.content_layout.addWidget(self.condition_combo)

        self.condition_status_label = QLabel("", controls)
        self.condition_status_label.setObjectName("loreta_condition_status_label")
        self.condition_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.condition_status_label.setWordWrap(True)
        controls.content_layout.addWidget(self.condition_status_label)

        display_mode_label = QLabel("Display", controls)
        display_mode_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(display_mode_label)

        self.display_mode_combo = QComboBox(controls)
        self.display_mode_combo.setObjectName("loreta_display_mode_combo")
        for label, mode in DISPLAY_MODE_OPTIONS:
            self.display_mode_combo.addItem(label, mode)
        self.display_mode_combo.currentIndexChanged.connect(self._on_display_mode_changed)
        controls.content_layout.addWidget(self.display_mode_combo)
        self._set_display_mode_combo_data(self._display_mode)

        self.activation_auto_scale_check = QCheckBox("Auto scale intensity", controls)
        self.activation_auto_scale_check.setObjectName("loreta_activation_auto_scale_check")
        self.activation_auto_scale_check.setChecked(True)
        self.activation_auto_scale_check.toggled.connect(self._on_activation_auto_scale_changed)
        controls.content_layout.addWidget(self.activation_auto_scale_check)

        self.activation_scale_mode_label = QLabel("Auto color scale", controls)
        self.activation_scale_mode_label.setObjectName("loreta_activation_scale_mode_label")
        self.activation_scale_mode_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(self.activation_scale_mode_label)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(6)
        self.activation_scale_min_label = QLabel("", controls)
        self.activation_scale_min_label.setObjectName("loreta_activation_scale_min_label")
        self.activation_scale_min_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.activation_color_ramp = QLabel("", controls)
        self.activation_color_ramp.setObjectName("loreta_activation_color_ramp")
        self.activation_color_ramp.setFixedHeight(12)
        self.activation_color_ramp.setMinimumWidth(72)
        self.activation_color_ramp.setStyleSheet(_activation_color_ramp_stylesheet())
        self.activation_scale_max_label = QLabel("", controls)
        self.activation_scale_max_label.setObjectName("loreta_activation_scale_max_label")
        self.activation_scale_max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        scale_row.addWidget(self.activation_scale_min_label, 0)
        scale_row.addWidget(self.activation_color_ramp, 1)
        scale_row.addWidget(self.activation_scale_max_label, 0)
        controls.content_layout.addLayout(scale_row)

        range_label = QLabel("Manual range", controls)
        range_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(range_label)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 0, 0, 0)
        range_row.setSpacing(6)
        self.activation_min_spin = QDoubleSpinBox(controls)
        self.activation_min_spin.setObjectName("loreta_activation_min_spin")
        self.activation_min_spin.setDecimals(2)
        self.activation_min_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.activation_min_spin.setSingleStep(0.05)
        self.activation_min_spin.setValue(DEFAULT_SCALAR_MIN)
        self.activation_min_spin.valueChanged.connect(self._on_activation_range_changed)
        self.activation_max_spin = QDoubleSpinBox(controls)
        self.activation_max_spin.setObjectName("loreta_activation_max_spin")
        self.activation_max_spin.setDecimals(2)
        self.activation_max_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.activation_max_spin.setSingleStep(0.05)
        self.activation_max_spin.setValue(DEFAULT_SCALAR_MAX)
        self.activation_max_spin.valueChanged.connect(self._on_activation_range_changed)
        range_row.addWidget(self.activation_min_spin)
        range_row.addWidget(QLabel("to", controls), 0)
        range_row.addWidget(self.activation_max_spin)
        controls.content_layout.addLayout(range_row)

        self.activation_value_label = QLabel("", controls)
        self.activation_value_label.setObjectName("loreta_activation_value_label")
        self.activation_value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.activation_value_label.setWordWrap(True)
        controls.content_layout.addWidget(self.activation_value_label)

        self.opacity_label = QLabel("Brain opacity", controls)
        self.opacity_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(self.opacity_label)

        self.transparency_value_label = QLabel("", controls)
        self.transparency_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.transparency_slider = QSlider(Qt.Horizontal, controls)
        self.transparency_slider.setObjectName("loreta_transparency_slider")
        self.transparency_slider.setRange(5, 100)
        self.transparency_slider.setValue(DEFAULT_OPACITY_PERCENT)
        self.transparency_slider.valueChanged.connect(self._on_transparency_changed)
        controls.content_layout.addWidget(self.transparency_slider)
        controls.content_layout.addWidget(self.transparency_value_label)

        self.activation_opacity_label = QLabel("Source opacity", controls)
        self.activation_opacity_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(self.activation_opacity_label)

        self.activation_opacity_value_label = QLabel("", controls)
        self.activation_opacity_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.activation_opacity_slider = QSlider(Qt.Horizontal, controls)
        self.activation_opacity_slider.setObjectName("loreta_activation_opacity_slider")
        self.activation_opacity_slider.setRange(0, 100)
        self.activation_opacity_slider.setValue(DEFAULT_ACTIVATION_OPACITY_PERCENT)
        self.activation_opacity_slider.valueChanged.connect(self._on_activation_opacity_changed)
        controls.content_layout.addWidget(self.activation_opacity_slider)
        controls.content_layout.addWidget(self.activation_opacity_value_label)

        self.activation_visible_check = QCheckBox("Show source map", controls)
        self.activation_visible_check.setObjectName("loreta_activation_visible_check")
        self.activation_visible_check.setChecked(True)
        self.activation_visible_check.toggled.connect(self._on_activation_visibility_changed)
        controls.content_layout.addWidget(self.activation_visible_check)

        self.split_rotation_label = QLabel("Hemisphere rotation", controls)
        self.split_rotation_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(self.split_rotation_label)

        self.left_split_rotation_row = QWidget(controls)
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
        controls.content_layout.addWidget(self.left_split_rotation_row)

        self.right_split_rotation_row = QWidget(controls)
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
        controls.content_layout.addWidget(self.right_split_rotation_row)

        self.reset_camera_btn = make_action_button("Reset", compact=True, parent=controls)
        self.reset_camera_btn.setObjectName("loreta_reset_camera_btn")
        self.reset_camera_btn.setToolTip("Reset view")
        self.reset_camera_btn.clicked.connect(self._reset_camera)
        controls.content_layout.addWidget(self.reset_camera_btn)

        self.export_split_svg_btn = make_action_button("Export Split SVG...", compact=True, parent=controls)
        self.export_split_svg_btn.setObjectName("loreta_export_split_svg_btn")
        self.export_split_svg_btn.setToolTip(
            "Export the current publication split-hemisphere view as a transparent SVG."
        )
        self.export_split_svg_btn.clicked.connect(self._export_split_hemisphere_svg)
        controls.content_layout.addWidget(self.export_split_svg_btn)

        self.export_stacked_split_svg_btn = make_action_button("Export Stack SVG...", compact=True, parent=controls)
        self.export_stacked_split_svg_btn.setObjectName("loreta_export_stacked_split_svg_btn")
        self.export_stacked_split_svg_btn.setToolTip(
            "Export two split-hemisphere conditions as one transparent SVG."
        )
        self.export_stacked_split_svg_btn.clicked.connect(self._export_stacked_split_hemisphere_svg)
        controls.content_layout.addWidget(self.export_stacked_split_svg_btn)

        self.source_options_btn = make_action_button("Source Map Options...", compact=True, parent=controls)
        self.source_options_btn.setObjectName("loreta_source_options_btn")
        self.source_options_btn.setToolTip("Open source-map rebuild, import, and participant QC options.")
        self.source_options_btn.clicked.connect(self._open_source_map_options)
        controls.content_layout.addWidget(self.source_options_btn)
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
        self._set_controls_enabled(True)
        self._refresh_dummy_activation()

    def _set_controls_enabled(self, enabled: bool) -> None:
        opacity_enabled = enabled and not self._activation_uses_opaque_cortical_mode()
        self.transparency_slider.setEnabled(opacity_enabled)
        self.activation_opacity_slider.setEnabled(opacity_enabled)
        self.activation_auto_scale_check.setEnabled(enabled)
        self._sync_activation_range_enabled()
        self.condition_combo.setEnabled(enabled)
        self.display_mode_combo.setEnabled(enabled)
        self.activation_visible_check.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)
        self.export_split_svg_btn.setEnabled(enabled)
        self.export_stacked_split_svg_btn.setEnabled(enabled)
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
                self.source_options_btn.setToolTip("Open source-map rebuild, import, and participant QC options.")

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
        self._display_mode = mode
        renderer = self.renderer
        if renderer is not None:
            renderer.set_display_mode(mode)
            renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
            renderer.set_activation_visible(self.activation_visible_check.isChecked())
        self._sync_activation_render_mode_controls()
        self._apply_activation_scalar_range()

    def _rotate_split_hemisphere(self, side: str, degrees: float) -> None:
        renderer = self.renderer
        if renderer is not None:
            renderer.rotate_split_hemisphere(side, degrees)

    def _on_activation_visibility_changed(self, checked: bool) -> None:
        renderer = self.renderer
        if renderer is not None:
            renderer.set_activation_visible(checked)

    def _on_condition_changed(self, _index: int) -> None:
        condition_id = self.condition_combo.currentData()
        if isinstance(condition_id, str):
            self._selected_condition_id = condition_id
        self._update_condition_status()
        self._refresh_dummy_activation()

    def _update_condition_status(self) -> None:
        manifest_entry = self._manifest_conditions.get(self._selected_condition_id)
        if manifest_entry is not None:
            self.condition_status_label.setText("")
            return
        condition = condition_by_id(self._selected_condition_id)
        region_label = condition.activation_region.replace("_", " ")
        self.condition_status_label.setText(f"Showing synthetic {region_label} activation.")

    def _zoom_in(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_in()

    def _zoom_out(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_out()

    def _reset_camera(self) -> None:
        if self.renderer is not None:
            self.renderer.reset_camera()

    def _export_split_hemisphere_svg(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        if renderer.display_mode() != DISPLAY_MODE_SPLIT_HEMISPHERE or not renderer.can_export_split_hemisphere_svg():
            self._set_source_export_status(
                "Switch to Publication split hemispheres with a loaded source map before exporting SVG.",
                variant="warning",
            )
            return
        project_root = self._refresh_project_root()
        default_path = default_split_svg_export_path(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
            condition_label=self._selected_condition_label(),
        )
        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export publication split hemisphere SVG",
            default_path,
            "SVG files (*.svg)",
        )
        if not file_name:
            return
        output_path = Path(file_name)
        if output_path.suffix.lower() != ".svg":
            output_path = output_path.with_suffix(".svg")
        try:
            written_path = renderer.write_split_hemisphere_svg(output_path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_split_svg_export_failed", extra={"path": str(output_path), "error": str(exc)})
            self._set_source_export_status(f"Split hemisphere SVG export failed: {exc}", variant="warning")
            return
        self._last_import_dir = written_path.parent
        self._set_source_export_status(f"Exported split hemisphere SVG: {written_path}", variant="success")

    def _export_stacked_split_hemisphere_svg(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        condition_options = self._condition_options()
        if len(condition_options) < 2:
            self._set_source_export_status(
                "Load at least two source-map conditions before exporting a stacked SVG.",
                variant="warning",
            )
            return
        dialog = StackedSplitSvgExportDialog(
            self,
            condition_options=condition_options,
            current_condition_id=self._selected_condition_id,
        )
        if not dialog.exec():
            return
        (top_id, top_label), (bottom_id, bottom_label) = dialog.selected_conditions()
        if top_id == bottom_id:
            self._set_source_export_status("Choose two different conditions for the stacked SVG.", variant="warning")
            return
        try:
            top_payload = self._condition_payload_for_export(top_id)
            bottom_payload = self._condition_payload_for_export(bottom_id)
            scalar_range = self._stacked_split_scalar_range((top_payload, bottom_payload))
            panels = (
                renderer.split_hemisphere_svg_panel_for_payload(
                    top_payload,
                    label=split_svg_condition_code(top_label),
                    scalar_range=scalar_range,
                ),
                renderer.split_hemisphere_svg_panel_for_payload(
                    bottom_payload,
                    label=split_svg_condition_code(bottom_label),
                    scalar_range=scalar_range,
                ),
            )
        except (OSError, RuntimeError, TypeError, ValueError, PreparedSourcePayloadImportError) as exc:
            logger.warning("loreta_stacked_split_svg_prepare_failed", extra={"error": str(exc)})
            self._set_source_export_status(f"Stacked split SVG export failed: {exc}", variant="warning")
            return

        project_root = self._refresh_project_root()
        default_path = default_stacked_split_svg_export_path(
            project_root=project_root,
            last_import_dir=self._last_import_dir,
            top_condition_label=top_label,
            bottom_condition_label=bottom_label,
        )
        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export stacked split hemisphere SVG",
            default_path,
            "SVG files (*.svg)",
        )
        if not file_name:
            return
        output_path = Path(file_name)
        if output_path.suffix.lower() != ".svg":
            output_path = output_path.with_suffix(".svg")
        try:
            written_path = renderer.write_split_hemisphere_stack_svg(output_path, panels=panels)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_stacked_split_svg_export_failed", extra={"path": str(output_path), "error": str(exc)})
            self._set_source_export_status(f"Stacked split SVG export failed: {exc}", variant="warning")
            return
        self._last_import_dir = written_path.parent
        self._set_source_export_status(f"Exported stacked split SVG: {written_path}", variant="success")

    def _selected_condition_label(self) -> str:
        manifest_entry = self._manifest_conditions.get(self._selected_condition_id)
        if manifest_entry is not None:
            return manifest_entry.label
        return condition_by_id(self._selected_condition_id).label

    def _condition_options(self) -> tuple[tuple[str, str], ...]:
        options: list[tuple[str, str]] = []
        for index in range(self.condition_combo.count()):
            condition_id = self.condition_combo.itemData(index)
            if not isinstance(condition_id, str):
                continue
            manifest_entry = self._manifest_conditions.get(condition_id)
            if manifest_entry is not None:
                options.append((condition_id, manifest_entry.label))
            else:
                options.append((condition_id, condition_by_id(condition_id).label))
        return tuple(options)

    def _condition_payload_for_export(self, condition_id: str) -> SourcePayload:
        renderer = self.renderer
        if renderer is None:
            raise RuntimeError("3D renderer is not available.")
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            raise RuntimeError("No mesh transform is available.")
        manifest_entry = self._manifest_conditions.get(condition_id)
        if manifest_entry is not None:
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
            return _activation_display_payload(payload)
        mesh_points = renderer.mesh_points()
        if mesh_points is None:
            raise RuntimeError("No display mesh is available.")
        payload = make_demo_condition_activation(
            mesh_points,
            mesh_faces=renderer.mesh_faces(),
            condition=condition_by_id(condition_id),
            display_transform=display_transform,
        )
        return _activation_display_payload(payload)

    def _stacked_split_scalar_range(self, payloads: tuple[SourcePayload, SourcePayload]) -> tuple[float, float]:
        scale_chunks = [
            _activation_scale_values(
                payload,
                zscore_display_threshold=self._zscore_display_threshold,
                cortical_threshold_display=uses_cortical_surface_paint(payload),
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
            has_cluster_mask = any(payload_has_cluster_mask(payload) for payload in payloads)
            lower_bound = 0.0 if has_cluster_mask else self._zscore_display_threshold
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
            zscore_model=self._zscore_model,
            zscore_display_threshold=self._zscore_display_threshold,
            project_available=project_root is not None,
            export_busy=self._source_export_thread is not None,
        )
        dialog.exec()
        self._include_flagged_subjects = dialog.include_flagged_check.isChecked()
        self._zscore_model = str(dialog.zscore_model_combo.currentData() or PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST)
        self._set_zscore_display_threshold(dialog.zscore_threshold_spin.value())
        if dialog.selected_action == SOURCE_OPTIONS_ACTION_REBUILD_ZSCORE:
            self._build_project_zscore_source_maps()
        elif dialog.selected_action == SOURCE_OPTIONS_ACTION_REBUILD_AMPLITUDE:
            self._build_project_source_maps()
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

    def _build_project_source_maps(self) -> None:
        self._build_project_source_maps_for_mode(PROJECT_SOURCE_EXPORT_AMPLITUDE)

    def _build_project_zscore_source_maps(self) -> None:
        self._build_project_source_maps_for_mode(PROJECT_SOURCE_EXPORT_HAUK_ZSCORE)

    def _ensure_default_project_zscore_maps(self) -> None:
        project_root = self._refresh_project_root()
        if self._auto_project_zscore_attempted or project_root is None or self.renderer is None:
            return
        self._auto_project_zscore_attempted = True
        manifest_path = default_project_zscore_manifest_path(project_root)
        if manifest_path is not None:
            self.condition_status_label.setText("Loading project source-space z-score maps...")
            self._last_import_dir = manifest_path.parent
            self._import_prepared_source_manifest(manifest_path)
            return
        self._build_project_source_maps_for_mode(PROJECT_SOURCE_EXPORT_HAUK_ZSCORE, automatic=True)

    def _build_project_source_maps_for_mode(self, export_mode: str, *, automatic: bool = False) -> None:
        project_root = self._refresh_project_root()
        if project_root is None:
            self.condition_status_label.setText("Open a project before building beta source JSON.")
            return
        if self._source_export_thread is not None:
            self._set_source_export_status(
                "Source-map rebuild is already running. You can keep using the viewer while it finishes.",
                variant="info",
            )
            return
        include_flagged_subjects = self._include_flagged_subjects
        zscore_model = self._zscore_model
        status_text = _source_export_status_text(
            export_mode,
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
                "export_mode": export_mode,
                "include_flagged_subjects": include_flagged_subjects,
                "zscore_model": zscore_model,
            },
        )

        thread = QThread(self)
        worker = ProjectSourceMapExportWorker(
            project_root=project_root,
            export_mode=export_mode,
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
        output_dir = getattr(result, "output_dir", None)
        manifest_path = getattr(result, "manifest_path", None)
        producer_result = getattr(result, "producer_result", None)
        payloads = getattr(producer_result, "payloads", ())
        if not isinstance(output_dir, Path) or not isinstance(manifest_path, Path):
            self._set_source_export_status(
                "Project source export failed: unexpected export result.",
                variant="warning",
            )
            return
        self._last_import_dir = output_dir
        method_id = str(getattr(producer_result, "method_id", ""))
        source_label = "source-space z-score maps" if "zscore" in method_id or "z_score" in method_id else "source maps"
        project_inputs = getattr(result, "project_inputs", None)
        export_model = str(getattr(result, "export_model", self._zscore_model))
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
        self._set_source_export_status(
            f"Prepared project {source_label} for {len(payloads)} conditions. Loaded regenerated maps.",
            variant="success",
        )
        self._import_prepared_source_manifest(manifest_path)

    @Slot(str)
    def _on_project_source_maps_failed(self, message: str) -> None:
        logger.warning(
            "loreta_project_source_maps_export_failed",
            extra={
                "error": message,
                "include_flagged_subjects": self._include_flagged_subjects,
                "zscore_model": self._zscore_model,
            },
        )
        self._set_source_export_status(_project_source_export_failure_text(message), variant="warning")

    @Slot()
    def _project_source_export_finished(self) -> None:
        self._source_export_thread = None
        self._source_export_worker = None
        self._sync_project_source_button()

    def _set_source_export_status(self, message: str, *, variant: str) -> None:
        self.condition_status_label.setText(message)
        self.mesh_status.set_variant(variant)
        self.mesh_status.set_text(message)

    def _import_prepared_source_payload(self, path: Path) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            self.condition_status_label.setText("Prepared source import failed: no mesh transform is available.")
            return
        try:
            payload = load_prepared_source_payload_json(path, display_transform=display_transform)
        except PreparedSourcePayloadImportError as exc:
            logger.warning("loreta_prepared_source_payload_import_failed", extra={"path": str(path), "error": str(exc)})
            self.condition_status_label.setText(f"Prepared source import failed: {exc}")
            return
        self._last_import_dir = path.parent
        self._set_activation_payload(payload)
        self.condition_status_label.setText("")

    def _import_prepared_source_manifest(self, path: Path) -> None:
        try:
            entries = load_prepared_source_manifest_json(path)
        except PreparedSourcePayloadImportError as exc:
            logger.warning("loreta_prepared_source_manifest_import_failed", extra={"path": str(path), "error": str(exc)})
            self.condition_status_label.setText(f"Prepared source manifest import failed: {exc}")
            return
        self._last_import_dir = path.parent
        self._replace_manifest_conditions(entries)
        first_entry = entries[0]
        self._selected_condition_id = first_entry.condition_id
        self._set_condition_combo_data(first_entry.condition_id)
        self._refresh_dummy_activation()

    def _replace_manifest_conditions(self, entries: tuple[PreparedSourceManifestEntry, ...]) -> None:
        previous_block_state = self.condition_combo.blockSignals(True)
        try:
            for index in range(self.condition_combo.count() - 1, -1, -1):
                item_data = self.condition_combo.itemData(index)
                if isinstance(item_data, str) and item_data in self._manifest_conditions:
                    self.condition_combo.removeItem(index)
            self._manifest_conditions = {entry.condition_id: entry for entry in entries}
            for entry in entries:
                self.condition_combo.addItem(f"Imported: {entry.label}", entry.condition_id)
        finally:
            self.condition_combo.blockSignals(previous_block_state)

    def _set_condition_combo_data(self, condition_id: str) -> None:
        for index in range(self.condition_combo.count()):
            if self.condition_combo.itemData(index) == condition_id:
                self.condition_combo.setCurrentIndex(index)
                return

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
        self._refresh_dummy_activation()
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

    def _refresh_dummy_activation(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            return
        manifest_entry = self._manifest_conditions.get(self._selected_condition_id)
        if manifest_entry is not None:
            self._render_manifest_condition(manifest_entry)
            return
        mesh_points = renderer.mesh_points()
        if mesh_points is None:
            return
        mesh_faces = renderer.mesh_faces()
        condition = condition_by_id(self._selected_condition_id)
        payload = make_demo_condition_activation(
            mesh_points,
            mesh_faces=mesh_faces,
            condition=condition,
            display_transform=display_transform,
        )
        self._set_activation_payload(payload)

    def _render_manifest_condition(self, entry: PreparedSourceManifestEntry) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_transform = renderer.mesh_display_transform()
        if display_transform is None:
            self.condition_status_label.setText("Imported source condition failed: no mesh transform is available.")
            return
        try:
            payload = load_prepared_source_payload_json(entry.payload_path, display_transform=display_transform)
        except PreparedSourcePayloadImportError as exc:
            logger.warning(
                "loreta_manifest_condition_payload_failed",
                extra={"path": str(entry.payload_path), "condition": entry.condition_id, "error": str(exc)},
            )
            self.condition_status_label.setText(f"Imported source condition failed: {exc}")
            return
        payload.metadata.update(
            {
                "manifest_condition_id": entry.condition_id,
                "manifest_condition_label": entry.label,
                "manifest_metadata": entry.metadata,
            }
        )
        self._set_activation_payload(payload)
        if (
            uses_cortical_surface_paint(payload)
            and _source_payload_uses_zscores(payload)
            and not payload_has_cluster_mask(payload)
        ):
            self.condition_status_label.setText("Loaded unmasked source map. Rebuild z-score maps to add cluster masks.")
        else:
            self.condition_status_label.setText("")

    def _set_activation_payload(self, payload: SourcePayload) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_payload = _activation_display_payload(payload)
        self._current_activation_payload = display_payload
        self._sync_activation_render_mode_controls()
        renderer.set_display_mode(self._display_mode)
        renderer.set_activation_payload(display_payload)
        self._apply_activation_scalar_range()
        renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
        renderer.set_activation_visible(self.activation_visible_check.isChecked())

    def _apply_activation_scalar_range(self) -> None:
        renderer = self.renderer
        payload = self._current_activation_payload
        if renderer is None or payload is None:
            return
        scale_values = _activation_scale_values(
            payload,
            zscore_display_threshold=self._zscore_display_threshold,
            cortical_threshold_display=self._activation_uses_opaque_cortical_mode(),
        )
        manual_min = self.activation_min_spin.value()
        if self._activation_uses_opaque_cortical_mode() and _source_payload_uses_zscores(payload):
            lower_bound = 0.0 if payload_has_cluster_mask(payload) else self._zscore_display_threshold
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
                    manual_min=max(lower_bound, manual_min),
                    manual_max=self.activation_max_spin.value(),
                )
        else:
            vmin, vmax = resolve_scalar_limits(
                scale_values,
                auto_scale=self.activation_auto_scale_check.isChecked(),
                manual_min=manual_min,
                manual_max=self.activation_max_spin.value(),
            )
        renderer.set_activation_scalar_range(vmin, vmax)
        self._update_activation_scale_readout(vmin, vmax)

    def _update_activation_scale_readout(self, vmin: float, vmax: float) -> None:
        self.activation_scale_min_label.setText(format_scalar_value(vmin))
        self.activation_scale_max_label.setText(format_scalar_value(vmax))
        self.activation_value_label.setText(
            _activation_value_readout(
                self._current_activation_payload,
                zscore_display_threshold=self._zscore_display_threshold,
                cortical_threshold_display=self._activation_uses_opaque_cortical_mode(),
            )
        )

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

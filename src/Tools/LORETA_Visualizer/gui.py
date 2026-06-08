"""Embedded PySide6 page for the LORETA 3D brain visualizer."""

from __future__ import annotations

import logging
import os
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
from Tools.LORETA_Visualizer.renderer import BrainRendererWidget, RenderBackendError
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
PROJECT_SOURCE_EXPORT_AMPLITUDE = "amplitude"
PROJECT_SOURCE_EXPORT_HAUK_ZSCORE = "hauk_zscore"
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

    exported = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        project_root: Path,
        export_mode: str,
        include_flagged_subjects: bool,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._export_mode = export_mode
        self._include_flagged_subjects = include_flagged_subjects

    @Slot()
    def run(self) -> None:
        try:
            if self._export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
                from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
                    write_project_l2_mne_hauk_zscore_payloads,
                )

                result = write_project_l2_mne_hauk_zscore_payloads(
                    project_root=self._project_root,
                    include_flagged_subjects=self._include_flagged_subjects,
                )
            else:
                from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
                    write_project_l2_mne_cortical_surface_payloads,
                )

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
) -> str:
    if payload is None:
        return "Value: source activation"
    label = payload.value_label.strip() or "source activation"
    source_unit = str(payload.metadata.get("source_value_unit", "")).strip()
    sensor_unit = str(payload.metadata.get("sensor_value_unit", "")).strip()
    filter_text = _activation_display_filter_readout(payload, zscore_display_threshold=zscore_display_threshold)
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
) -> str:
    if uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
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
) -> np.ndarray:
    values = np.asarray(payload.values, dtype=float)
    if uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
        return values[values >= float(zscore_display_threshold)]
    return values


def _source_export_status_text(
    export_mode: str,
    *,
    automatic: bool,
    include_flagged_subjects: bool,
) -> str:
    flag_text = "including flagged participants" if include_flagged_subjects else "excluding flagged participants"
    if automatic:
        return f"Preparing project source-space z-score maps ({flag_text})..."
    if export_mode == PROJECT_SOURCE_EXPORT_HAUK_ZSCORE:
        return f"Building Hauk-style source-space z-score JSON from the active project ({flag_text})..."
    return f"Building beta L2-MNE source JSON from the active project ({flag_text})..."


class SourceMapOptionsDialog(AppDialog):
    """Small modal for source-map rebuild and import options."""

    def __init__(
        self,
        parent: QWidget,
        *,
        include_flagged_subjects: bool,
        zscore_display_threshold: float,
        project_available: bool,
        export_busy: bool,
    ) -> None:
        super().__init__("Source Map Options", parent, size=SurfaceSize(width=460, height=430, min_width=410))
        self.selected_action: str | None = None
        self._syncing_threshold_controls = False

        method_label = QLabel(
            "Default project maps use beta Hauk-style L2-MNE source-space z-scores. "
            "The method uses project FullFFT target/noise bins, the Stats-selected "
            "oddball harmonics, and a BioSemi64/fsaverage cortical template.",
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
            "This is not a cluster-permutation significance mask.",
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

        self.include_flagged_check = QCheckBox("Include Stats QC flagged participants in source-map calculations", self)
        self.include_flagged_check.setObjectName("loreta_include_flagged_subjects_check")
        self.include_flagged_check.setChecked(bool(include_flagged_subjects))
        self.include_flagged_check.setToolTip(
            "Leave unchecked to exclude participants listed in Flagged Participants.xlsx."
        )
        data_layout.addWidget(self.include_flagged_check)

        availability_label = QLabel(
            "Open a project to rebuild source maps." if not project_available else "Rebuilds write project-local JSON and load the resulting manifest.",
            self,
        )
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
        self._zscore_display_threshold = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD

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

    def _resolve_project_root(self, provided_root: str | None) -> Path | None:
        if provided_root:
            root = Path(provided_root)
            if root.exists():
                return root.resolve()
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
            if root.exists():
                return root.resolve()
        parent: QObject | None = self.parent()
        while parent is not None:
            project = getattr(parent, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                root = Path(project.project_root)
                if root.exists():
                    return root.resolve()
            parent = parent.parent()
        return None

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

        self.reset_camera_btn = make_action_button("Reset", compact=True, parent=controls)
        self.reset_camera_btn.setObjectName("loreta_reset_camera_btn")
        self.reset_camera_btn.setToolTip("Reset view")
        self.reset_camera_btn.clicked.connect(self._reset_camera)
        controls.content_layout.addWidget(self.reset_camera_btn)

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
        self._set_controls_enabled(True)
        self._refresh_dummy_activation()

    def _set_controls_enabled(self, enabled: bool) -> None:
        opacity_enabled = enabled and not self._activation_uses_cortical_paint()
        self.transparency_slider.setEnabled(opacity_enabled)
        self.activation_opacity_slider.setEnabled(opacity_enabled)
        self.activation_auto_scale_check.setEnabled(enabled)
        self._sync_activation_range_enabled()
        self.condition_combo.setEnabled(enabled)
        self.activation_visible_check.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)
        self.source_options_btn.setEnabled(enabled)
        self._sync_activation_render_mode_controls()
        self._sync_project_source_button()

    def _sync_project_source_button(self) -> None:
        if hasattr(self, "source_options_btn"):
            self.source_options_btn.setEnabled(self.renderer is not None)

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

    def _sync_activation_render_mode_controls(self) -> None:
        if not hasattr(self, "activation_opacity_slider"):
            return
        cortical_paint = self._activation_uses_cortical_paint()
        opacity_enabled = self.renderer is not None and not cortical_paint
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
            widget.setVisible(not cortical_paint)
        self.activation_color_ramp.setStyleSheet(_activation_color_ramp_stylesheet())

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

    def _open_source_map_options(self) -> None:
        if self.renderer is None:
            return
        dialog = SourceMapOptionsDialog(
            self,
            include_flagged_subjects=self._include_flagged_subjects,
            zscore_display_threshold=self._zscore_display_threshold,
            project_available=self._project_root is not None,
            export_busy=self._source_export_thread is not None,
        )
        dialog.exec()
        self._include_flagged_subjects = dialog.include_flagged_check.isChecked()
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
        initial_dir = resolve_loreta_import_start_dir(
            project_root=self._project_root,
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
        initial_dir = resolve_loreta_import_start_dir(
            project_root=self._project_root,
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
        if self._auto_project_zscore_attempted or self._project_root is None or self.renderer is None:
            return
        self._auto_project_zscore_attempted = True
        manifest_path = default_project_zscore_manifest_path(self._project_root)
        if manifest_path is not None:
            self.condition_status_label.setText("Loading project source-space z-score maps...")
            self._last_import_dir = manifest_path.parent
            self._import_prepared_source_manifest(manifest_path)
            return
        self._build_project_source_maps_for_mode(PROJECT_SOURCE_EXPORT_HAUK_ZSCORE, automatic=True)

    def _build_project_source_maps_for_mode(self, export_mode: str, *, automatic: bool = False) -> None:
        if self._project_root is None:
            self.condition_status_label.setText("Open a project before building beta source JSON.")
            return
        if self._source_export_thread is not None:
            return
        include_flagged_subjects = self._include_flagged_subjects
        status_text = _source_export_status_text(
            export_mode,
            automatic=automatic,
            include_flagged_subjects=include_flagged_subjects,
        )
        self.condition_status_label.setText(status_text)
        self.source_options_btn.setEnabled(False)
        logger.info(
            "loreta_project_source_maps_export_started",
            extra={
                "project_root": str(self._project_root),
                "export_mode": export_mode,
                "include_flagged_subjects": include_flagged_subjects,
            },
        )

        thread = QThread(self)
        worker = ProjectSourceMapExportWorker(
            project_root=self._project_root,
            export_mode=export_mode,
            include_flagged_subjects=include_flagged_subjects,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.exported.connect(self._on_project_source_maps_exported)
        worker.failed.connect(self._on_project_source_maps_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._project_source_export_finished)
        self._source_export_thread = thread
        self._source_export_worker = worker
        thread.start()

    @Slot(object)
    def _on_project_source_maps_exported(self, result: object) -> None:
        output_dir = getattr(result, "output_dir", None)
        manifest_path = getattr(result, "manifest_path", None)
        producer_result = getattr(result, "producer_result", None)
        payloads = getattr(producer_result, "payloads", ())
        if not isinstance(output_dir, Path) or not isinstance(manifest_path, Path):
            self.condition_status_label.setText("Project source export failed: unexpected export result.")
            return
        self._last_import_dir = output_dir
        method_id = str(getattr(producer_result, "method_id", ""))
        source_label = "source-space z-score maps" if "hauk_zscore" in method_id else "source maps"
        project_inputs = getattr(result, "project_inputs", None)
        flagged_subjects = tuple(getattr(project_inputs, "flagged_subjects", ()) or ())
        excluded_subjects = tuple(getattr(project_inputs, "excluded_subjects", ()) or ())
        logger.info(
            "loreta_project_source_maps_export_complete",
            extra={
                "manifest_path": str(manifest_path),
                "method_id": method_id,
                "condition_count": len(payloads),
                "include_flagged_subjects": self._include_flagged_subjects,
                "flagged_subject_count": len(flagged_subjects),
                "excluded_subject_count": len(excluded_subjects),
            },
        )
        self.condition_status_label.setText(
            f"Prepared project {source_label} for {len(payloads)} conditions."
        )
        self._import_prepared_source_manifest(manifest_path)

    @Slot(str)
    def _on_project_source_maps_failed(self, message: str) -> None:
        logger.warning(
            "loreta_project_source_maps_export_failed",
            extra={"error": message, "include_flagged_subjects": self._include_flagged_subjects},
        )
        self.condition_status_label.setText(f"Project source export failed: {message}")

    @Slot()
    def _project_source_export_finished(self) -> None:
        self._source_export_thread = None
        self._source_export_worker = None
        self._sync_project_source_button()

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
            "Fetching/loading fsaverage through MNE outside the repo..."
            if allow_fetch
            else "Checking external fsaverage cache..."
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
        self.mesh_status.set_text(
            f"Using {result.source_label} mesh from external cache ({result.triangle_count:,} triangles)."
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
        self.condition_status_label.setText("")

    def _set_activation_payload(self, payload: SourcePayload) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        display_payload = _activation_display_payload(payload)
        self._current_activation_payload = display_payload
        self._sync_activation_render_mode_controls()
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
        )
        manual_min = self.activation_min_spin.value()
        if uses_cortical_surface_paint(payload) and _source_payload_uses_zscores(payload):
            threshold = self._zscore_display_threshold
            if self.activation_auto_scale_check.isChecked():
                finite = scale_values[np.isfinite(scale_values)]
                vmax = float(np.nanmax(finite)) if len(finite) else threshold + 1.0
                vmin, vmax = resolve_scalar_limits(
                    np.asarray([threshold, vmax], dtype=float),
                    auto_scale=False,
                    manual_min=threshold,
                    manual_max=vmax,
                )
            else:
                vmin, vmax = resolve_scalar_limits(
                    scale_values,
                    auto_scale=False,
                    manual_min=max(threshold, manual_min),
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

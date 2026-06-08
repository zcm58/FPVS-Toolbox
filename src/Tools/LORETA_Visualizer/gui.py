"""Embedded PySide6 page for the LORETA 3D brain visualizer."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
)
from Tools.LORETA_Visualizer.conditions import DEMO_LORETA_CONDITIONS, condition_by_id, default_condition
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
from Tools.LORETA_Visualizer.source_payloads import SourcePayload

logger = logging.getLogger(__name__)

DEFAULT_OPACITY_PERCENT = 48
DEFAULT_ACTIVATION_OPACITY_PERCENT = 72


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

    def __init__(self, *, project_root: Path) -> None:
        super().__init__()
        self._project_root = project_root

    @Slot()
    def run(self) -> None:
        try:
            from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
                write_project_l2_mne_cortical_surface_payloads,
            )

            result = write_project_l2_mne_cortical_surface_payloads(project_root=self._project_root)
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
        from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
            default_project_l2_mne_output_dir,
        )

        source_dir = default_project_l2_mne_output_dir(project_root)
        if source_dir.is_dir():
            return str(source_dir)
        return str(project_root)
    return ""


def _activation_color_ramp_stylesheet() -> str:
    stops = []
    max_index = max(len(LORETA_SCALAR_COLORS) - 1, 1)
    for index, color in enumerate(LORETA_SCALAR_COLORS):
        stops.append(f"stop:{index / max_index:.3f} {color}")
    return (
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"{', '.join(stops)});"
        "border: 1px solid #d6dee8;"
        "border-radius: 2px;"
    )


def _activation_value_readout(payload: SourcePayload | None) -> str:
    if payload is None:
        return "Value: source activation"
    label = payload.value_label.strip() or "source activation"
    source_unit = str(payload.metadata.get("source_value_unit", "")).strip()
    sensor_unit = str(payload.metadata.get("sensor_value_unit", "")).strip()
    if source_unit and sensor_unit:
        return f"Value: {label}; unit: {source_unit}; input: {sensor_unit}"
    if source_unit:
        return f"Value: {label}; unit: {source_unit}"
    if sensor_unit:
        return f"Value: {label}; input: {sensor_unit}"
    return f"Value: {label}"


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

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = SubsectionHeaderLabel("LORETA Visualizer", self)
        root.addWidget(header, 0)
        self.mesh_status = StatusBanner(
            "Synthetic placeholder mesh shown. Looking for an external fsaverage cache...",
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
            self._start_fsaverage_load(allow_fetch=False)

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
        controls = SectionCard("View Controls", self, object_name="loreta_view_controls")
        controls.setFixedWidth(240)

        opacity_label = QLabel("Brain transparency", controls)
        opacity_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(opacity_label)

        self.transparency_value_label = QLabel("", controls)
        self.transparency_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.transparency_slider = QSlider(Qt.Horizontal, controls)
        self.transparency_slider.setObjectName("loreta_transparency_slider")
        self.transparency_slider.setRange(5, 100)
        self.transparency_slider.setValue(DEFAULT_OPACITY_PERCENT)
        self.transparency_slider.valueChanged.connect(self._on_transparency_changed)
        controls.content_layout.addWidget(self.transparency_slider)
        controls.content_layout.addWidget(self.transparency_value_label)

        activation_label = QLabel("Source map opacity", controls)
        activation_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        controls.content_layout.addWidget(activation_label)

        self.activation_opacity_value_label = QLabel("", controls)
        self.activation_opacity_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.activation_opacity_slider = QSlider(Qt.Horizontal, controls)
        self.activation_opacity_slider.setObjectName("loreta_activation_opacity_slider")
        self.activation_opacity_slider.setRange(0, 100)
        self.activation_opacity_slider.setValue(DEFAULT_ACTIVATION_OPACITY_PERCENT)
        self.activation_opacity_slider.valueChanged.connect(self._on_activation_opacity_changed)
        controls.content_layout.addWidget(self.activation_opacity_slider)
        controls.content_layout.addWidget(self.activation_opacity_value_label)

        self.activation_auto_scale_check = QCheckBox("Auto scale intensity", controls)
        self.activation_auto_scale_check.setObjectName("loreta_activation_auto_scale_check")
        self.activation_auto_scale_check.setChecked(True)
        self.activation_auto_scale_check.toggled.connect(self._on_activation_auto_scale_changed)
        controls.content_layout.addWidget(self.activation_auto_scale_check)

        range_label = QLabel("Intensity range", controls)
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

        self.activation_value_label = QLabel("", controls)
        self.activation_value_label.setObjectName("loreta_activation_value_label")
        self.activation_value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.activation_value_label.setWordWrap(True)
        controls.content_layout.addWidget(self.activation_value_label)

        condition_label = QLabel("Source condition", controls)
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

        self.activation_visible_check = QCheckBox("Show source map", controls)
        self.activation_visible_check.setObjectName("loreta_activation_visible_check")
        self.activation_visible_check.setChecked(True)
        self.activation_visible_check.toggled.connect(self._on_activation_visibility_changed)
        controls.content_layout.addWidget(self.activation_visible_check)

        self.smooth_surface_check = QCheckBox("Smooth visual brain surface", controls)
        self.smooth_surface_check.setObjectName("loreta_smooth_surface_check")
        self.smooth_surface_check.setChecked(False)
        self.smooth_surface_check.setToolTip("Display a smoothed visual duplicate; activation coordinates stay unchanged.")
        self.smooth_surface_check.toggled.connect(self._on_smooth_surface_toggled)
        controls.content_layout.addWidget(self.smooth_surface_check)

        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(6)
        self.zoom_out_btn = make_action_button("-", compact=True, parent=controls)
        self.zoom_out_btn.setObjectName("loreta_zoom_out_btn")
        self.zoom_out_btn.setToolTip("Zoom out")
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_in_btn = make_action_button("+", compact=True, parent=controls)
        self.zoom_in_btn.setObjectName("loreta_zoom_in_btn")
        self.zoom_in_btn.setToolTip("Zoom in")
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_in_btn)
        controls.content_layout.addLayout(zoom_row)

        self.reset_camera_btn = make_action_button("Reset", compact=True, parent=controls)
        self.reset_camera_btn.setObjectName("loreta_reset_camera_btn")
        self.reset_camera_btn.setToolTip("Reset view")
        self.reset_camera_btn.clicked.connect(self._reset_camera)
        controls.content_layout.addWidget(self.reset_camera_btn)

        self.load_source_payload_btn = make_action_button("Load source JSON", compact=True, parent=controls)
        self.load_source_payload_btn.setObjectName("loreta_load_source_payload_btn")
        self.load_source_payload_btn.setToolTip("Load a prepared source payload JSON file.")
        self.load_source_payload_btn.clicked.connect(self._load_prepared_source_payload)
        controls.content_layout.addWidget(self.load_source_payload_btn)

        self.build_project_source_btn = make_action_button("Build project source JSON", compact=True, parent=controls)
        self.build_project_source_btn.setObjectName("loreta_build_project_source_btn")
        self.build_project_source_btn.setToolTip("Write beta L2-MNE source JSON from the active project and load it.")
        self.build_project_source_btn.clicked.connect(self._build_project_source_maps)
        controls.content_layout.addWidget(self.build_project_source_btn)

        self.load_source_manifest_btn = make_action_button("Load manifest", compact=True, parent=controls)
        self.load_source_manifest_btn.setObjectName("loreta_load_source_manifest_btn")
        self.load_source_manifest_btn.setToolTip("Load a prepared source condition manifest.")
        self.load_source_manifest_btn.clicked.connect(self._load_prepared_source_manifest)
        controls.content_layout.addWidget(self.load_source_manifest_btn)

        self.load_fsaverage_btn = make_action_button("Fetch/load fsaverage", compact=True, parent=controls)
        self.load_fsaverage_btn.setObjectName("loreta_load_fsaverage_btn")
        self.load_fsaverage_btn.setToolTip("Load an external MNE fsaverage mesh.")
        self.load_fsaverage_btn.clicked.connect(self._load_fsaverage_with_fetch)
        controls.content_layout.addWidget(self.load_fsaverage_btn)
        controls.content_layout.addStretch(1)

        self._update_transparency_label(DEFAULT_OPACITY_PERCENT)
        self._update_activation_opacity_label(DEFAULT_ACTIVATION_OPACITY_PERCENT)
        self._sync_activation_range_enabled()
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
        self.transparency_slider.setEnabled(enabled)
        self.activation_opacity_slider.setEnabled(enabled)
        self.activation_auto_scale_check.setEnabled(enabled)
        self._sync_activation_range_enabled()
        self.condition_combo.setEnabled(enabled)
        self.activation_visible_check.setEnabled(enabled)
        self.smooth_surface_check.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.zoom_in_btn.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)
        self.load_source_payload_btn.setEnabled(enabled)
        self._sync_project_source_button()
        self.load_source_manifest_btn.setEnabled(enabled)
        self.load_fsaverage_btn.setEnabled(enabled)

    def _sync_project_source_button(self) -> None:
        enabled = (
            self.renderer is not None
            and self._project_root is not None
            and self._source_export_thread is None
        )
        self.build_project_source_btn.setEnabled(enabled)

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
            self.condition_status_label.setText(f"Showing imported source condition: {manifest_entry.label}")
            return
        condition = condition_by_id(self._selected_condition_id)
        region_label = condition.activation_region.replace("_", " ")
        self.condition_status_label.setText(f"Showing synthetic {region_label} activation.")

    def _on_smooth_surface_toggled(self, checked: bool) -> None:
        renderer = self.renderer
        if renderer is not None:
            renderer.set_smooth_visual_enabled(checked)

    def _zoom_in(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_in()

    def _zoom_out(self) -> None:
        if self.renderer is not None:
            self.renderer.zoom_out()

    def _reset_camera(self) -> None:
        if self.renderer is not None:
            self.renderer.reset_camera()

    def _load_fsaverage_with_fetch(self) -> None:
        self._start_fsaverage_load(allow_fetch=True)

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
        if self._project_root is None:
            self.condition_status_label.setText("Open a project before building beta source JSON.")
            return
        if self._source_export_thread is not None:
            return
        self.condition_status_label.setText("Building beta L2-MNE source JSON from the active project...")
        self.build_project_source_btn.setEnabled(False)

        thread = QThread(self)
        worker = ProjectSourceMapExportWorker(project_root=self._project_root)
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
        self.condition_status_label.setText(
            f"Built beta source JSON for {len(payloads)} conditions."
        )
        self._import_prepared_source_manifest(manifest_path)

    @Slot(str)
    def _on_project_source_maps_failed(self, message: str) -> None:
        logger.warning("loreta_project_source_maps_export_failed", extra={"error": message})
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
        self.condition_status_label.setText(f"Showing imported prepared source payload: {path.name}")

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
        self.load_fsaverage_btn.setEnabled(False)

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
        renderer.set_smooth_visual_enabled(self.smooth_surface_check.isChecked())
        self._refresh_dummy_activation()
        self.mesh_status.set_variant("success")
        self.mesh_status.set_text(
            f"Using {result.source_label} mesh from external cache ({result.triangle_count:,} triangles)."
        )

    @Slot(str)
    def _on_fsaverage_failed(self, message: str) -> None:
        self.mesh_status.set_variant("warning")
        self.mesh_status.set_text(f"Using synthetic fallback mesh. {message}")

    @Slot()
    def _mesh_load_finished(self) -> None:
        self._mesh_thread = None
        self._mesh_worker = None
        if self.renderer is not None:
            self.load_fsaverage_btn.setEnabled(True)
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
        self.condition_status_label.setText(f"Showing imported source condition: {entry.label}")

    def _set_activation_payload(self, payload: SourcePayload) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        self._current_activation_payload = payload
        renderer.set_activation_payload(payload)
        self._apply_activation_scalar_range()
        renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
        renderer.set_activation_visible(self.activation_visible_check.isChecked())

    def _apply_activation_scalar_range(self) -> None:
        renderer = self.renderer
        payload = self._current_activation_payload
        if renderer is None or payload is None:
            return
        vmin, vmax = resolve_scalar_limits(
            payload.values,
            auto_scale=self.activation_auto_scale_check.isChecked(),
            manual_min=self.activation_min_spin.value(),
            manual_max=self.activation_max_spin.value(),
        )
        renderer.set_activation_scalar_range(vmin, vmax)
        self._update_activation_scale_readout(vmin, vmax)

    def _update_activation_scale_readout(self, vmin: float, vmax: float) -> None:
        self.activation_scale_min_label.setText(format_scalar_value(vmin))
        self.activation_scale_max_label.setText(format_scalar_value(vmax))
        self.activation_value_label.setText(_activation_value_readout(self._current_activation_payload))

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

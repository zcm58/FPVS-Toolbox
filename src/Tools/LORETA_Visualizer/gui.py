"""Embedded PySide6 page for the LORETA 3D brain visualizer."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
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
from Tools.LORETA_Visualizer.dummy_activation import make_occipital_demo_activation
from Tools.LORETA_Visualizer.fsaverage_mesh import FsaverageMeshError, FsaverageMeshResult, load_fsaverage_brain_mesh
from Tools.LORETA_Visualizer.renderer import BrainRendererWidget, RenderBackendError

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


class LoretaVisualizerWindow(QWidget):
    """Embedded workspace page for Phase 1 real-time brain rendering."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        embedded: bool = True,
    ) -> None:
        super().__init__(parent)
        surface_size = SurfaceSize(width=1120, height=780)
        if not embedded:
            surface_size = SurfaceSize(width=1120, height=780, min_width=980)
        configure_window_surface(self, title="LORETA Visualizer", size=surface_size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.renderer: BrainRendererWidget | None = None
        self.status_banner: StatusBanner | None = None
        self._mesh_thread: QThread | None = None
        self._mesh_worker: FsaverageLoadWorker | None = None

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

        activation_label = QLabel("Dummy LORETA opacity", controls)
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

        self.activation_visible_check = QCheckBox("Show dummy occipital heatmap", controls)
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

        self.load_fsaverage_btn = make_action_button("Fetch/load fsaverage", compact=True, parent=controls)
        self.load_fsaverage_btn.setObjectName("loreta_load_fsaverage_btn")
        self.load_fsaverage_btn.setToolTip("Load an external MNE fsaverage mesh.")
        self.load_fsaverage_btn.clicked.connect(self._load_fsaverage_with_fetch)
        controls.content_layout.addWidget(self.load_fsaverage_btn)
        controls.content_layout.addStretch(1)

        self._update_transparency_label(DEFAULT_OPACITY_PERCENT)
        self._update_activation_opacity_label(DEFAULT_ACTIVATION_OPACITY_PERCENT)
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
        self.activation_visible_check.setEnabled(enabled)
        self.smooth_surface_check.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.zoom_in_btn.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)
        self.load_fsaverage_btn.setEnabled(enabled)

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

    def _on_activation_visibility_changed(self, checked: bool) -> None:
        renderer = self.renderer
        if renderer is not None:
            renderer.set_activation_visible(checked)

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

    def _refresh_dummy_activation(self) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        mesh_points = renderer.mesh_points()
        if mesh_points is None:
            return
        payload = make_occipital_demo_activation(mesh_points)
        renderer.set_activation_payload(payload)
        renderer.set_activation_opacity(self.activation_opacity_slider.value() / 100.0)
        renderer.set_activation_visible(self.activation_visible_check.isChecked())

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        renderer = self.renderer
        self.renderer = None
        if renderer is not None:
            renderer.shutdown()
        if self._mesh_thread is not None:
            self._mesh_thread.quit()
            self._mesh_thread.wait(1000)
        super().closeEvent(event)

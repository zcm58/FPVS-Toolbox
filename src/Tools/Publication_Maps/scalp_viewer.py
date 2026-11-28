"""Native trackball viewer for qualified electrode-space scalp maps."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from threading import Event

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)
from shiboken6 import isValid

from Main_App.exports.figure_style import FIGURE_EXPORT_DPI
from Tools.LORETA_Visualizer.graphics_support import require_desktop_opengl
from Tools.Publication_Maps.generation_outcome import PublicationMapGenerationCancelled
from Tools.Publication_Maps.rendering import sanitize_filename_stem
from Tools.Publication_Maps.scalp_surface import _camera, build_scalp_surface_scene
from Tools.Publication_Maps.scalp_view_export import (
    VIEW_IMAGE_WIDTH_IN, camera_view_paths, draw_view_scale, export_camera_view, prepare_camera_export_folder,
)

logger = logging.getLogger(__name__)


class _JobSignals(QObject):
    finished = Signal(object, object)


class _ViewerJob(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _JobSignals()

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            result, error = None, exc
        else:
            error = None
        # Application teardown can destroy the QObject while a cancelled
        # export is rolling back staged files in the pool.
        try:
            self.signals.finished.emit(result, error)
        except RuntimeError:
            if isValid(self.signals):
                raise


class ScalpSurfaceDialog(QDialog):
    """Inspect one prepared panel at a time, keeping the camera across panel changes."""

    def __init__(self, panels, parent=None):
        super().__init__(parent)
        self.panels = tuple(panels)
        if not self.panels:
            raise ValueError("Choose at least one available scalp map.")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("3D Scalp Maps")
        self.resize(820, 650)
        self.setMinimumSize(630, 440)
        self._plotter = None
        self._job = None
        self._closed = False
        self._graphics_ready = Event()
        self._cancel = Event()
        self._ready = False
        self._camera_initialized = False
        self._focal = np.zeros(3)
        layout = QVBoxLayout(self)
        selection = QHBoxLayout()
        self.map_combo = QComboBox()
        self.map_combo.setObjectName("scalp3dPanel")
        for panel in self.panels:
            self.map_combo.addItem(panel.label)
        self.map_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.map_combo.setAccessibleName("Scalp map")
        selection.addWidget(QLabel("Map"))
        selection.addWidget(self.map_combo, 1)
        layout.addLayout(selection)
        canvas_row = QHBoxLayout()
        canvas_row.setSpacing(0)
        layout.addLayout(canvas_row, 1)
        self.legend = FigureCanvasQTAgg(Figure(facecolor="white"))
        self.legend.setFixedWidth(125)
        canvas_row.addWidget(self.legend)
        controls = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.setAccessibleName("Camera view")
        self.camera_combo.addItems(["Back", "Front", "Left", "Right", "Top"])
        self.camera_combo.setPlaceholderText("Custom")
        self._preset_index = 0
        self._preset_orientation = None
        self._orientation_timer = QTimer(self)
        self._orientation_timer.setSingleShot(True)
        self._orientation_timer.timeout.connect(self._update_camera_label)
        self.camera_combo.activated.connect(self.reset_camera)
        controls.addWidget(QLabel("Camera"))
        controls.addWidget(self.camera_combo)
        for label, factor in (("Zoom in", 1.2), ("Zoom out", 1 / 1.2)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, f=factor: self.zoom(f))
            controls.addWidget(button)
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.reset_camera)
        controls.addWidget(reset)
        controls.addStretch()
        self.export_button = QPushButton("Export view…")
        self.export_button.clicked.connect(self._choose_export)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.map_combo.currentIndexChanged.connect(self._load_panel)
        try:
            self._load_panel()
            # Finish the initial CPU interpolation while Qt probes the display
            # and opens VTK. Results wait for both steps to finish.
            require_desktop_opengl(self)
            from pyvistaqt import QtInteractor

            self._plotter = QtInteractor(self, auto_update=False)
            self._plotter.setObjectName("scalp3dInteractor")
            self._plotter.enable_trackball_style()
            self._plotter.set_background("white")
            self._plotter.enable_parallel_projection()
            canvas_row.insertWidget(0, self._plotter, 1)
            self._camera_observer = self._plotter.camera.AddObserver("ModifiedEvent", self._camera_changed)
        except Exception:  # Construction failure must close native resources and prevent queued scene delivery.
            self._closed = True
            if self._plotter is not None:
                self._plotter.close()
            self.deleteLater()
            raise
        finally:
            self._graphics_ready.set()

    @property
    def current_panel(self):
        return self.panels[self.map_combo.currentIndex()]

    def _start_job(self, operation, finished):
        self._job = _ViewerJob(operation)
        self._job.signals.finished.connect(finished, Qt.ConnectionType.QueuedConnection)
        self.map_combo.setEnabled(False)
        self.export_button.setEnabled(False)
        QThreadPool.globalInstance().start(self._job)

    @Slot()
    def _load_panel(self):
        panel = self.current_panel
        self.status.setText("Preparing scalp surface…")
        self._ready = False
        graphics_ready = self._graphics_ready

        def prepare():
            try:
                return build_scalp_surface_scene(panel.data, panel.info, cmap=panel.cmap, norm=panel.norm)
            finally:
                # Prepare the first field while Qt opens the native graphics
                # context. Only deliver results once its widgets exist.
                graphics_ready.wait()

        self._start_job(prepare, self._panel_ready)

    @Slot(object, object)
    def _panel_ready(self, scene, error):
        self._job = None
        if self._closed:
            return
        try:
            if error is not None:
                raise error
            self._show_scene(scene)
            self.legend.figure.clear()
            draw_view_scale(self.legend.figure, self.legend.figure.add_axes((0.12, 0.13, 0.15, 0.74)), self.current_panel)
            self.legend.draw_idle()
            self._ready = True
            guidance = "Drag to rotate · Scroll to zoom · Shift-drag to pan"
            if self.current_panel.missing_count:
                guidance += f" · Missing montage values omitted: {self.current_panel.missing_count}"
            self.status.setText(guidance)
        except Exception as exc:
            logger.warning("scalp_surface_display_failed", exc_info=True)
            self._plotter.clear()
            self.legend.figure.clear()
            self.legend.draw_idle()
            self.status.setText(f"Could not display this scalp map. {exc}")
        self.map_combo.setEnabled(True)
        self.export_button.setEnabled(self._ready)

    def _show_scene(self, scene):
        import pyvista as pv

        plotter = self._plotter
        directions = scene.vertices - scene.origin
        radii = np.linalg.norm(directions, axis=1, keepdims=True)
        surface = pv.PolyData.from_regular_faces(scene.vertices + 0.00008 * directions / radii, scene.scalp_faces)
        surface.active_texture_coordinates = scene.texture_coordinates
        texture = pv.numpy_to_texture(np.ascontiguousarray(scene.texture_rgba[::-1]))
        texture.repeat = False
        texture.interpolate = False
        plotter.add_mesh(pv.PolyData.from_regular_faces(scene.vertices, scene.faces), name="scalp", color="#e5e5e5",
                         smooth_shading=True, ambient=0.55, diffuse=0.45, specular=0,
                         reset_camera=False, render=False)
        plotter.add_mesh(surface, name="values", texture=texture, lighting=False, show_scalar_bar=False,
                         reset_camera=False, render=False)
        dots = scene.sensor_locations - scene.origin
        locations = scene.sensor_locations + 0.00045 * dots / np.linalg.norm(dots, axis=1, keepdims=True)
        self._electrodes = plotter.add_points(locations, name="electrodes", color="#171717", point_size=6,
                                              render_points_as_spheres=True, lighting=False,
                                              reset_camera=False, render=False)
        if not self._camera_initialized:
            self._focal = (scene.vertices.min(axis=0) + scene.vertices.max(axis=0)) / 2
            self.reset_camera()
            self._camera_initialized = True
        else:
            plotter.render()

    @Slot()
    def reset_camera(self):
        if self.camera_combo.currentIndex() < 0:
            self.camera_combo.setCurrentIndex(self._preset_index)
        self._preset_index = self.camera_combo.currentIndex()
        view = self.camera_combo.currentText()
        if view in ("Front", "Back"):
            offset = _camera(view.lower())[2]
        else:
            offset = np.array({"Left": (-1, 0, 0.1), "Right": (1, 0, 0.1), "Top": (0, 0, 1)}[view])
        camera = self._plotter.camera
        camera.position = self._focal + 0.55 * offset / np.linalg.norm(offset)
        camera.focal_point = self._focal
        camera.up = (0, 1, 0) if view == "Top" else (0, 0, 1)
        camera.parallel_scale = 0.15
        self._preset_orientation = camera.GetOrientation()
        self._plotter.reset_camera_clipping_range()
        self._plotter.render()

    def _camera_changed(self, _camera, _event):
        # VTK updates position and focal point separately during a pan. Read
        # the final orientation after the interaction event has completed.
        if self.camera_combo.currentIndex() >= 0 and not self._orientation_timer.isActive():
            self._orientation_timer.start(0)

    @Slot()
    def _update_camera_label(self):
        if self._preset_orientation is not None and not self._closed:
            orientation = self._plotter.camera.GetOrientation()
            if not np.allclose(orientation, self._preset_orientation, atol=1e-6, rtol=0):
                self.camera_combo.setCurrentIndex(-1)

    def zoom(self, factor):
        self._plotter.camera.Zoom(factor)
        self._plotter.render()

    @Slot()
    def _choose_export(self):
        panel = self.current_panel
        try:
            folder = prepare_camera_export_folder(panel)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("scalp_camera_output_folder_unavailable", exc_info=True)
            self.status.setText(f"Could not open the export folder. {exc}")
            return
        default = folder / (sanitize_filename_stem(panel.label) + "_3d_view.png")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export current view as PNG and PDF", str(default), "PNG figure (*.png)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename:
            return
        target = Path(filename)
        existing = [path.name for path in camera_view_paths(target) if path.exists()]
        if existing and QMessageBox.question(
            self, "Replace figures?", "Replace " + " and ".join(existing) + "?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.export_view(target)

    def export_view(self, filename):
        """Capture the live camera on the GUI thread and publish both formats in a worker."""
        if not self._ready or self._job is not None:
            return
        panel = self.current_panel
        cancel = self._cancel

        def check_cancel():
            if cancel.is_set():
                raise PublicationMapGenerationCancelled("Export cancelled.")

        try:
            width = max(1, self._plotter.window_size[0])
            scale = max(1, math.ceil(VIEW_IMAGE_WIDTH_IN * FIGURE_EXPORT_DPI / width))
            # VTK scales its render target but keeps point sizes in device pixels.
            original_size = self._electrodes.prop.point_size
            try:
                self._electrodes.prop.point_size = original_size * scale
                image = self._plotter.screenshot(return_img=True, scale=scale)
            finally:
                self._electrodes.prop.point_size = original_size
        except Exception as exc:
            logger.warning("scalp_camera_capture_failed", exc_info=True)
            self.status.setText(f"Could not capture this view. {exc}")
        else:
            self.status.setText("Exporting PNG and PDF…")
            self._start_job(lambda: export_camera_view(image, panel, filename, check_cancel), self._export_finished)
        finally:
            # Restore the on-screen dots while the worker encodes the captured image.
            try:
                self._plotter.render()
            except (OSError, RuntimeError, ValueError):
                logger.warning("scalp_viewport_redraw_failed", exc_info=True)

    @Slot(object, object)
    def _export_finished(self, paths, error):
        self._job = None
        if self._closed:
            return
        if error is None:
            self.status.setText(f"Saved PNG and PDF in {paths[0].parent}")
        else:
            self.status.setText(f"Could not export this view. {error}")
        self.map_combo.setEnabled(True)
        self.export_button.setEnabled(self._ready)

    def done(self, result):
        # Both Escape/Reject and the window close button must release VTK.
        self._closed = True
        self._cancel.set()
        if self._plotter is not None:
            self._plotter.camera.RemoveObserver(self._camera_observer)
            self._orientation_timer.stop()
            self._plotter.close()
            self._plotter = None
        super().done(result)

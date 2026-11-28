"""Exercise the live scalp viewer without requiring a CI OpenGL display."""

import sys
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import matplotlib
from matplotlib.colors import Normalize
import numpy as np
import pyvista as pv
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget
from shiboken6 import delete

from Tools.Publication_Maps import scalp_viewer
from Tools.Publication_Maps.models import PublicationMetric
from Tools.Publication_Maps.scalp_io import biosemi64_info
from Tools.Publication_Maps.scalp_scene import ScalpSurfacePanel


class _Display(QWidget):
    """Real VTK camera and actors, with the OS graphics context replaced."""

    def __init__(self, parent, *, auto_update):
        super().__init__(parent)
        self.camera = pv.Camera()
        self.actors = {}
        self.window_size = (420, 300)
        self.capture = np.full((16, 24, 3), [14, 93, 121], dtype=np.uint8)
        self.captured_cameras = []
        self.capture_sizes = []

    def enable_trackball_style(self):
        pass

    def set_background(self, color):
        pass

    def enable_parallel_projection(self):
        self.camera.parallel_projection = True

    def add_mesh(self, mesh, *, name, **kwargs):
        self.actors[name] = pv.Actor()
        return self.actors[name]

    def add_points(self, points, *, name, point_size, **kwargs):
        actor = pv.Actor()
        actor.prop.point_size = point_size
        self.point_locations = np.asarray(points)
        self.actors[name] = actor
        return actor

    def clear(self):
        self.actors.clear()

    def render(self):
        pass

    def reset_camera_clipping_range(self):
        pass

    def screenshot(self, *, return_img, scale):
        assert return_img and scale > 1
        self.captured_cameras.append(_camera_state(self.camera))
        self.capture_sizes.append((self.actors["electrodes"].prop.point_size, scale))
        return self.capture.copy()


def _camera_state(camera):
    return np.array([*camera.position, *camera.focal_point, *camera.up, camera.parallel_scale])


@pytest.fixture
def panels(tmp_path):
    info = biosemi64_info()
    bca = ScalpSurfacePanel(
        "Words · BCA", PublicationMetric.BCA, "Baseline-corrected amplitude (µV)",
        np.linspace(0, 2, len(info.ch_names)), info, matplotlib.colormaps["viridis"], Normalize(0, 2),
        "neither", 0, "Words", tmp_path / "inputs", tmp_path, tmp_path, (), None, "",
    )
    snr = replace(bca, label="Words · SNR", metric=PublicationMetric.SNR, colorbar_label="Signal to Noise Ratio",
                  data=bca.data + 1, norm=Normalize(1, 3))
    return bca, snr


@pytest.fixture
def dialog(qtbot, panels, monkeypatch):
    monkeypatch.setattr(scalp_viewer, "require_desktop_opengl", lambda _: None)
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=_Display))
    viewer = scalp_viewer.ScalpSurfaceDialog(panels)
    # Escape and the window close button delete this dialog; close explicitly
    # rather than leaving pytest-qt with a wrapper to an already deleted object.
    viewer.show()
    qtbot.waitUntil(lambda: viewer.export_button.isEnabled())
    yield viewer
    if not viewer._closed:
        viewer.close()


def test_camera_presets_zoom_and_live_view_export_survive_switching_metric(dialog, qtbot, tmp_path, monkeypatch):
    assert set(dialog._plotter.actors) == {"scalp", "values", "electrodes"}
    assert len(dialog._plotter.point_locations) == len(dialog.current_panel.info.ch_names)
    assert dialog._plotter.actors["electrodes"].prop.point_size > 0
    for name, axis, sign in (("Front", 1, 1), ("Left", 0, -1), ("Right", 0, 1), ("Top", 2, 1), ("Back", 1, -1)):
        dialog.camera_combo.setCurrentText(name)
        dialog.camera_combo.activated.emit(dialog.camera_combo.currentIndex())
        camera = dialog._plotter.camera
        direction = np.asarray(camera.position) - camera.focal_point
        assert sign * direction[axis] / np.linalg.norm(direction) > 0.8
        if name in ("Front", "Back"):
            np.testing.assert_allclose(direction / np.linalg.norm(direction), scalp_viewer._camera(name.lower())[2])
    camera.Azimuth(29)
    offset = np.array([0.012, -0.006, 0.003])
    camera.position = np.asarray(camera.position) + offset
    camera.focal_point = np.asarray(camera.focal_point) + offset
    scale = camera.parallel_scale
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Zoom in").click()
    assert camera.parallel_scale < scale
    oblique = _camera_state(camera)
    dialog.map_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled())
    np.testing.assert_allclose(_camera_state(camera), oblique)
    legend, = dialog.legend.figure.axes
    assert legend.get_ylabel() == "Signal to Noise Ratio"
    np.testing.assert_allclose(legend.get_ylim(), (1, 3))

    received = []

    def publish(image, panel, filename, check_cancel):
        check_cancel()
        received.append((image.copy(), panel, filename))
        return (filename, filename.with_suffix(".pdf"))

    monkeypatch.setattr(scalp_viewer, "export_camera_view", publish)
    target = tmp_path / "chosen-view.png"
    dot_size = dialog._plotter.actors["electrodes"].prop.point_size
    dialog.export_view(target)
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled())
    image, panel, filename = received[0]
    np.testing.assert_array_equal(image, dialog._plotter.capture)
    np.testing.assert_allclose(dialog._plotter.captured_cameras[-1], oblique)
    captured_size, upscale = dialog._plotter.capture_sizes[-1]
    assert captured_size == pytest.approx(dot_size * upscale)
    assert dialog._plotter.actors["electrodes"].prop.point_size == dot_size
    assert filename == target and panel is dialog.current_panel


def test_failed_panel_clears_stale_scene_and_can_recover(dialog, qtbot, monkeypatch):
    original = scalp_viewer.build_scalp_surface_scene
    invalid_values = dialog.panels[1].data

    def build(values, *args, **kwargs):
        if values is invalid_values:
            raise ValueError("incomplete scalp geometry")
        return original(values, *args, **kwargs)

    monkeypatch.setattr(scalp_viewer, "build_scalp_surface_scene", build)
    dialog.map_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: "incomplete scalp geometry" in dialog.status.text())
    assert not dialog.export_button.isEnabled()
    assert not dialog._plotter.actors and not dialog.legend.figure.axes
    dialog.map_combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled())
    assert dialog._plotter.actors


def test_camera_label_tracks_free_rotation_and_reset_recalls_selected_preset(dialog, qtbot):
    dialog.camera_combo.setCurrentText("Left")
    dialog.camera_combo.activated.emit(dialog.camera_combo.currentIndex())
    camera = dialog._plotter.camera
    original = _camera_state(camera)
    delta = np.array([.015, -.004, .006])
    camera.position = np.asarray(camera.position) + delta
    camera.focal_point = np.asarray(camera.focal_point) + delta
    dialog.zoom(1.3)
    qtbot.waitUntil(lambda: not dialog._orientation_timer.isActive())
    assert dialog.camera_combo.currentText() == "Left"

    camera.Azimuth(33)
    qtbot.waitUntil(lambda: dialog.camera_combo.currentIndex() == -1)
    assert dialog.camera_combo.placeholderText() == "Custom"
    dialog.map_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled())
    assert dialog.camera_combo.currentIndex() == -1
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Reset view").click()
    qtbot.waitUntil(lambda: not dialog._orientation_timer.isActive())
    assert dialog.camera_combo.currentText() == "Left"
    np.testing.assert_allclose(_camera_state(camera), original)


def test_first_save_as_offers_existing_output_folder_and_cancel_creates_no_figures(dialog, tmp_path, monkeypatch):
    folder = tmp_path / "Figures" / "Control"
    dialog.panels = tuple(replace(p, output_root=folder, output_base_root=folder.parent) for p in dialog.panels)
    offered = []

    def cancel(_parent, _title, filename, _filters, **_options):
        offered.append(filename)
        assert folder.is_dir()
        return "", ""

    monkeypatch.setattr(scalp_viewer.QFileDialog, "getSaveFileName", cancel)
    dialog.export_button.click()
    assert offered == [str(folder / "Words_BCA_3d_view.png")]
    assert list(folder.iterdir()) == []


def test_invalid_default_export_folder_reports_error_without_opening_picker(dialog, monkeypatch):
    dialog.panels = tuple(replace(p, output_root=p.input_root) for p in dialog.panels)
    monkeypatch.setattr(scalp_viewer.QFileDialog, "getSaveFileName", lambda *_a, **_kw: pytest.fail("unexpected picker"))
    dialog.export_button.click()
    assert "processed Excel input folder" in dialog.status.text()
    assert dialog.export_button.isEnabled()


def test_close_during_export_cancels_publication(dialog, qtbot, tmp_path, monkeypatch):
    started, release, cancelled = Event(), Event(), Event()

    def publish(image, panel, filename, check_cancel):
        started.set()
        if not release.wait(5):
            raise AssertionError("Test failed to release the export worker")
        try:
            check_cancel()
        except scalp_viewer.PublicationMapGenerationCancelled:
            cancelled.set()
            raise
        raise AssertionError("A closed viewer attempted to publish its export")

    monkeypatch.setattr(scalp_viewer, "export_camera_view", publish)
    target = tmp_path / "cancelled.png"
    dialog.export_view(target)
    try:
        qtbot.waitUntil(started.is_set)
        assert not dialog.export_button.isEnabled()
        assert not dialog.map_combo.isEnabled()
        dialog.reject()
    finally:
        release.set()
    qtbot.waitUntil(cancelled.is_set)
    assert not target.exists() and not target.with_suffix(".pdf").exists()


def test_export_starts_before_restored_viewport_redraw(dialog, qtbot, tmp_path, monkeypatch):
    original_size = dialog._electrodes.prop.point_size
    redraws = []

    def render():
        redraws.append((dialog._job is not None, dialog._electrodes.prop.point_size))
        raise RuntimeError("Viewport unavailable after capture")

    monkeypatch.setattr(dialog._plotter, "render", render)
    monkeypatch.setattr(scalp_viewer, "export_camera_view", lambda _img, _panel, name, _check: (name,))
    dialog.export_view(tmp_path / "snapshot.png")
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled())
    assert redraws == [(True, original_size)]
    assert "Saved PNG and PDF" in dialog.status.text()


def test_capture_failure_restores_display_and_leaves_viewer_usable(dialog, tmp_path, monkeypatch):
    size = dialog._plotter.actors["electrodes"].prop.point_size

    def fail_capture(*, return_img, scale):
        assert dialog._plotter.actors["electrodes"].prop.point_size == pytest.approx(size * scale)
        raise RuntimeError("graphics memory unavailable")

    monkeypatch.setattr(dialog._plotter, "screenshot", fail_capture)
    dialog.export_view(tmp_path / "capture.png")
    assert "graphics memory unavailable" in dialog.status.text()
    assert dialog._plotter.actors["electrodes"].prop.point_size == size
    assert dialog.export_button.isEnabled() and dialog.map_combo.isEnabled()
    assert not (tmp_path / "capture.png").exists()


def test_missing_desktop_graphics_fails_before_vtk_context_creation(qtbot, panels, monkeypatch):
    def unavailable(_):
        raise RuntimeError("Desktop OpenGL 3.2 is unavailable")

    monkeypatch.setattr(scalp_viewer, "require_desktop_opengl", unavailable)
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=lambda *_a, **_k: pytest.fail("VTK started")))
    with pytest.raises(RuntimeError, match="OpenGL 3.2"):
        scalp_viewer.ScalpSurfaceDialog(panels)


@pytest.mark.parametrize("context_fails", [False, True])
def test_first_surface_waits_for_native_graphics_even_if_setup_processes_events(qtbot, panels, monkeypatch, context_fails):
    prepared = Event()
    original_build = scalp_viewer.build_scalp_surface_scene

    def build(*args, **kwargs):
        scene = original_build(*args, **kwargs)
        prepared.set()
        return scene

    def open_context(parent, *, auto_update):
        assert prepared.wait(5)
        QTest.qWait(20)
        assert parent._job is not None and not parent._ready
        if context_fails:
            raise RuntimeError("Cannot open native display")
        return _Display(parent, auto_update=auto_update)

    monkeypatch.setattr(scalp_viewer, "build_scalp_surface_scene", build)
    monkeypatch.setattr(scalp_viewer, "require_desktop_opengl", lambda _: None)
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=open_context))
    if context_fails:
        with pytest.raises(RuntimeError, match="Cannot open native display"):
            scalp_viewer.ScalpSurfaceDialog(panels)
        QTest.qWait(20)
    else:
        viewer = scalp_viewer.ScalpSurfaceDialog(panels)
        viewer.show()
        qtbot.waitUntil(lambda: viewer.export_button.isEnabled())
        viewer.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_worker_can_finish_after_qt_tears_down_its_signals(qtbot, cancelled):
    def operation():
        if cancelled:
            raise scalp_viewer.PublicationMapGenerationCancelled("Closed")
        return "export completed"

    worker = scalp_viewer._ViewerJob(operation)
    delete(worker.signals)
    worker.run()

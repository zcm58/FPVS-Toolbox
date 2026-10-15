"""CI-only MRI preview lifecycle smoke tests with bounded fake rendering."""

from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QPushButton, QWidget

from Tools.LORETA_Visualizer import gui


class _ControlledRenderWorker(QObject):
    rendered = Signal(object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, request, workers):
        super().__init__()
        self.request = request
        self.entered = Event()
        self.release = Event()
        self.fail = False
        workers.append(self)

    @Slot()
    def run(self):
        self.entered.set()
        try:
            if not self.release.wait(timeout=5):
                self.failed.emit(self.request["id"], "Fake rendering release timed out")
            elif self.fail:
                self.failed.emit(self.request["id"], "obsolete render failure")
            else:
                result = SimpleNamespace(peak_voxel=(1, 2, 3), request_id=self.request["id"])
                self.rendered.emit((self.request, result, object()))
        finally:
            self.finished.emit()


class _PreviewHarness(gui.LoretaVisualizerWindow):
    """Use the real controller/Qt lifecycle without building the full 3D page."""

    def __init__(self, tmp_path):
        QWidget.__init__(self)
        self.applied = []
        self.errors = []
        self.shutdown_count = 0
        self._display_mode = gui.DISPLAY_MODE_MRI_SLICES
        self._closing_requested = False
        self._mesh_thread = None
        self._source_export_thread = None
        self._source_export_worker = None
        self._stats_ready_export_thread = None
        self._pending_source_map_rebuild = None
        self._mri_render_thread = None
        self._mri_render_worker = None
        self._mri_render_pending = None
        self._mri_render_request_id = 0
        self._mri_anatomy_error = None
        self._mri_anatomy_cache = None
        self._mri_anatomy_cache_dir = None
        self._mri_slice_indices_cache = None
        self._mri_slice_indices_cache_key = None
        self._fsaverage_dir = tmp_path
        self._manifest_condition_groups = {}
        self._selected_summary_id = "mean"
        self._use_cluster_mask = True
        self._activation_visible = True
        self._source_activation_payload = SimpleNamespace(kind="volume_points")
        self._current_activation_payload = self._source_activation_payload
        self.renderer = SimpleNamespace(mesh_display_transform=lambda: object(), shutdown=self._shutdown)
        self.mri_slice_view = SimpleNamespace(
            set_render_result=self.applied.append, clear_slice_image=self.errors.append
        )
        self.export_figures_btn = QPushButton("Export", self)

    def _shutdown(self):
        self.shutdown_count += 1

    def _mri_slice_reference_cache_key(self):
        return ("fixed-test-reference",)

    def _mri_slice_preview_figure_settings(self):
        return ((3.0, 2.0), 20)

    def _selected_condition_label(self):
        return "Test condition"

    def _set_source_export_status(self, message, *, variant):
        self.errors.append((message, variant))

    def request_preview(self):
        self._render_mri_slice_payload(self._current_activation_payload, scalar_range=(0.0, 5.0))


@pytest.fixture
def preview_harness(qtbot, monkeypatch, tmp_path):
    workers = []
    monkeypatch.setattr(gui, "MriSliceRenderWorker", lambda request: _ControlledRenderWorker(request, workers))
    host = _PreviewHarness(tmp_path)
    qtbot.addWidget(host)
    try:
        yield host, workers
    finally:
        host._mri_render_pending = None
        for worker in workers:
            worker.release.set()
        qtbot.waitUntil(lambda: host._mri_render_thread is None, timeout=7000)
        host.close()


@pytest.mark.parametrize("first_fails", [False, True])
def test_mri_preview_coalesces_latest_request_and_suppresses_obsolete_result(
    qtbot, preview_harness, first_fails
):
    host, workers = preview_harness
    host.request_preview()
    qtbot.waitUntil(lambda: workers[0].entered.is_set())
    assert not host.export_figures_btn.isEnabled()
    workers[0].fail = first_fails
    host.request_preview()
    host.request_preview()
    assert len(workers) == 1
    assert host._mri_render_pending["id"] == 3

    workers[0].release.set()
    qtbot.waitUntil(lambda: len(workers) == 2)
    assert workers[1].request["id"] == 3
    assert host.applied == []
    assert host.errors == []
    workers[1].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)

    assert [result.request_id for result in host.applied] == [3]
    assert host.export_figures_btn.isEnabled()
    assert host._mri_slice_indices_cache == (1, 2, 3)


def test_closing_waits_for_preview_worker_and_discards_queued_work(qtbot, preview_harness):
    host, workers = preview_harness
    host.show()
    qtbot.waitUntil(host.isVisible)
    host.request_preview()
    qtbot.waitUntil(lambda: workers[0].entered.is_set())
    host.request_preview()

    assert not host.close()
    assert host._closing_requested
    assert host.isVisible()
    assert host._mri_render_pending is None
    assert host.shutdown_count == 0
    workers[0].release.set()
    qtbot.waitUntil(lambda: not host.isVisible())

    assert len(workers) == 1
    assert host.applied == []
    assert host.shutdown_count == 1
    assert host.renderer is None

"""CI-only MRI preview lifecycle smoke tests with bounded fake rendering."""

from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Signal, Slot
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
        self.anatomy = object()
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
                result = SimpleNamespace(
                    peak_voxel=self.request["render_kwargs"].get("slice_indices") or (1, 2, 3),
                    request_id=self.request["id"],
                )
                self.rendered.emit((self.request, result, self.anatomy))
        finally:
            self.finished.emit()


class _PreviewHarness(gui.LoretaVisualizerWindow):
    """Use the real controller/Qt lifecycle without building the full 3D page."""

    def __init__(self, tmp_path):
        QWidget.__init__(self)
        self.applied = []
        self.preserved = []
        self.errors = []
        self.shutdown_count = 0
        self._display_mode = gui.DISPLAY_MODE_MRI_SLICES
        self._closing_requested = False
        self._mesh_thread = None
        self._source_export_thread = None
        self._source_export_worker = None
        self._stats_ready_export_thread = None
        self._source_discovery_thread = None
        self._source_discovery_pending = None
        self._pending_source_map_rebuild = None
        self._mri_render_thread = None
        self._mri_render_worker = None
        self._mri_render_pending = None
        self._mri_render_request_id = 0
        self._mri_render_context_id = 0
        self._mri_render_context_payload = None
        self._mri_render_reference_key = None
        self._mri_render_last_applied_id = 0
        self._mri_drag_active = False
        self._mri_drag_first_request_id = 0
        self._mri_preview_cache = None
        self._group_comparison_thread = None
        self._comparison_renderer = None
        self._mri_preview_requested_settings = None
        self._mri_preview_scalar_range = None
        self._test_preview_settings = ((3.0, 2.0), 20)
        self._mri_preview_resize_timer = QTimer(self)
        self._mri_preview_resize_timer.setSingleShot(True)
        self._mri_preview_resize_timer.setInterval(gui.MRI_SLICE_RESIZE_DEBOUNCE_MS)
        self._mri_preview_resize_timer.timeout.connect(self._render_mri_preview_after_resize)
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
            set_render_result=self._apply_preview, clear_slice_image=self.errors.append, isVisible=self.isVisible,
            cancel_drag=lambda: self._on_mri_drag_active_changed(False),
        )
        self.export_figures_btn = QPushButton("Export", self)

    def _shutdown(self):
        self.shutdown_count += 1

    def _apply_preview(self, result, *, preserve_cursor=False):
        self.applied.append(result)
        self.preserved.append(preserve_cursor)

    def _mri_slice_reference_cache_key(self):
        return ("fixed-test-reference",)

    def _mri_slice_preview_figure_settings(self):
        return self._test_preview_settings

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
    assert workers[1].request["render_kwargs"]["anatomy"] is (None if first_fails else workers[0].anatomy)
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
    assert host._mri_preview_cache is None
    assert not host._mri_drag_active
    assert host.shutdown_count == 0
    workers[0].release.set()
    qtbot.waitUntil(lambda: not host.isVisible())

    assert len(workers) == 1
    assert host.applied == []
    assert host.shutdown_count == 1
    assert host._mri_anatomy_cache is None
    assert host.renderer is None


def test_preview_resize_debounces_preserves_cursor_and_ignores_same_size_or_hidden(qtbot, preview_harness):
    host, workers = preview_harness
    host.show()
    qtbot.waitUntil(host.isVisible)
    host.request_preview()
    qtbot.waitUntil(lambda: workers[0].entered.is_set())
    workers[0].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)
    host._mri_slice_indices_cache = (7, 8, 9)
    host._test_preview_settings = ((8.0, 6.0), 100)

    for _ in range(3):
        host._schedule_mri_preview_resize()
    assert len(workers) == 1
    qtbot.waitUntil(lambda: len(workers) == 2, timeout=1500)
    kwargs = workers[1].request["render_kwargs"]
    assert kwargs["slice_indices"] == (7, 8, 9)
    assert kwargs["scalar_range"] == (0.0, 5.0)
    assert kwargs["payload"] is host._current_activation_payload
    assert kwargs["anatomy"] is workers[0].anatomy
    workers[1].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)

    host._schedule_mri_preview_resize()
    qtbot.wait(gui.MRI_SLICE_RESIZE_DEBOUNCE_MS + 80)
    assert len(workers) == 2
    host._test_preview_settings = ((12.0, 6.0), 100)
    host._schedule_mri_preview_resize()
    host.hide()
    qtbot.wait(gui.MRI_SLICE_RESIZE_DEBOUNCE_MS + 80)
    assert len(workers) == 2


def test_drag_keeps_completed_frames_visible_and_finishes_at_latest_cursor(qtbot, preview_harness):
    host, workers = preview_harness
    host.show()
    host.request_preview()
    qtbot.waitUntil(lambda: workers[0].entered.is_set())
    workers[0].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)

    host._on_mri_drag_active_changed(True)
    host._on_mri_slice_indices_requested((4, 5, 6))
    qtbot.waitUntil(lambda: len(workers) == 2 and workers[1].entered.is_set())
    for indices in ((5, 6, 7), (6, 7, 8), (7, 8, 9)):
        host._on_mri_slice_indices_requested(indices)
    assert len(workers) == 2
    assert host._mri_render_pending["render_kwargs"]["slice_indices"] == (7, 8, 9)

    workers[1].release.set()
    qtbot.waitUntil(lambda: len(workers) == 3)
    assert [result.request_id for result in host.applied] == [1, 2]
    assert host.preserved == [False, True]
    assert host._mri_slice_indices_cache == (7, 8, 9)
    assert workers[2].request["render_kwargs"]["slice_indices"] == (7, 8, 9)
    assert workers[2].request["render_kwargs"]["preview_cache"] is workers[1].request["render_kwargs"]["preview_cache"]

    host._on_mri_drag_active_changed(False)
    workers[2].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)
    assert [result.request_id for result in host.applied] == [1, 2, 5]
    assert host.applied[-1].peak_voxel == (7, 8, 9)
    assert host.preserved[-1] is False
    assert host.export_figures_btn.isEnabled()


def test_drag_frame_is_rejected_after_scale_context_changes(qtbot, preview_harness):
    host, workers = preview_harness
    host.request_preview()
    qtbot.waitUntil(lambda: workers[0].entered.is_set())
    workers[0].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)
    host._on_mri_drag_active_changed(True)
    host._on_mri_slice_indices_requested((4, 5, 6))
    qtbot.waitUntil(lambda: len(workers) == 2 and workers[1].entered.is_set())
    host._render_mri_slice_payload(host._current_activation_payload, scalar_range=(0.0, 20.0))
    assert not host._mri_drag_active
    workers[1].release.set()
    qtbot.waitUntil(lambda: len(workers) == 3)
    assert [result.request_id for result in host.applied] == [1]
    assert workers[2].request["render_kwargs"]["scalar_range"] == (0.0, 20.0)
    assert workers[2].request["render_kwargs"]["preview_cache"] is not workers[1].request["render_kwargs"]["preview_cache"]
    workers[2].release.set()
    qtbot.waitUntil(lambda: host._mri_render_thread is None)
    assert [result.request_id for result in host.applied] == [1, 3]

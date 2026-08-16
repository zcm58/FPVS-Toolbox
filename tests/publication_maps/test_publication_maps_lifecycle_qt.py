from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMainWindow, QWidget

from Main_App.gui import main_window as main_window_module
from Main_App.projects import GroupInfo, ProjectDatasetIndex, WorkbookRecord
from Tools.Publication_Maps import gui as publication_maps_gui
from Tools.Publication_Maps.generation_outcome import (
    PublicationMapsWorkerOutcome,
)


def _managed_multigroup_index(tmp_path) -> ProjectDatasetIndex:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    excel_root.mkdir(parents=True)
    groups = {
        "control": GroupInfo(
            group_id="control",
            label="Control",
            folder_name="Control",
            raw_input_folder=project_root / "raw-control",
        ),
        "clinical": GroupInfo(
            group_id="clinical",
            label="Clinical",
            folder_name="Clinical",
            raw_input_folder=project_root / "raw-clinical",
        ),
    }
    workbooks = tuple(
        WorkbookRecord(
            participant_id=participant_id,
            condition=condition,
            path=excel_root / condition / group.folder_name / f"{participant_id}.xlsx",
            group_id=group.group_id,
            group_label=group.label,
            observed_layout="condition_group",
            observed_group_folder=group.folder_name,
        )
        for participant_id, group in (("P01", groups["control"]), ("P02", groups["clinical"]))
        for condition in ("Faces", "Objects")
    )
    return ProjectDatasetIndex(
        project_root=project_root,
        excel_root=excel_root,
        scan_root=excel_root,
        manifest={"name": "Lifecycle smoke"},
        groups=groups,
        participants={},
        workbooks=workbooks,
        excluded_workbooks=(),
        diagnostics=(),
    )


def _build_page(qtbot, monkeypatch, tmp_path):
    dataset_index = _managed_multigroup_index(tmp_path)
    monkeypatch.setattr(
        publication_maps_gui,
        "load_project_dataset_index",
        lambda _path: dataset_index,
    )
    host = QMainWindow()
    host.sidebar = QWidget(host)
    host.currentProject = SimpleNamespace(
        project_root=dataset_index.project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        results_folder=dataset_index.project_root,
    )
    page = publication_maps_gui.PublicationMapsWindow(
        parent=host,
        project_root=str(dataset_index.project_root),
        embedded=True,
    )
    host.setCentralWidget(page)
    qtbot.addWidget(host)
    host.show()
    return host, page


@pytest.mark.qt
def test_all_groups_builds_separate_canonical_requests(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    _host, page = _build_page(qtbot, monkeypatch, tmp_path)

    assert page.group_combo.currentData() == publication_maps_gui.ALL_GROUPS_VALUE
    requests = page._collect_requests()

    assert [request.group_id for request in requests] == ["clinical", "control"]
    assert [request.group_label for request in requests] == ["Clinical", "Control"]
    assert [request.group_folder for request in requests] == ["Clinical", "Control"]
    assert len({request.output_root for request in requests}) == 1
    assert page.status_label.isVisible()


@pytest.mark.qt
def test_active_project_rejects_unmanaged_input_before_run(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    dataset_index = _managed_multigroup_index(tmp_path)
    unmanaged_index = ProjectDatasetIndex(
        project_root=dataset_index.project_root,
        excel_root=dataset_index.excel_root,
        scan_root=dataset_index.scan_root,
        manifest=None,
        groups={},
        participants={},
        workbooks=dataset_index.workbooks,
        excluded_workbooks=(),
        diagnostics=(),
    )
    monkeypatch.setattr(
        publication_maps_gui,
        "load_project_dataset_index",
        lambda _path: unmanaged_index,
    )
    host = QMainWindow()
    host.currentProject = SimpleNamespace(
        project_root=dataset_index.project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        results_folder=dataset_index.project_root,
    )
    page = publication_maps_gui.PublicationMapsWindow(
        parent=host,
        project_root=str(dataset_index.project_root),
        embedded=True,
    )
    host.setCentralWidget(page)
    qtbot.addWidget(host)

    assert page._dataset_index is None
    assert page.run_btn.isEnabled() is False
    assert "active project's configured Excel folder" in page.status_label.text()


@pytest.mark.qt
def test_active_project_requires_the_exact_configured_excel_root(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    _host, page = _build_page(qtbot, monkeypatch, tmp_path)
    assert page._dataset_index is not None
    assert page.input_root_edit.isReadOnly() is True
    assert page.input_root_btn.isEnabled() is False

    page.input_root_edit.setText(str(page._dataset_index.excel_root / "Faces"))
    page._refresh_conditions()

    assert page._dataset_index is None
    assert page.run_btn.isEnabled() is False
    assert "active project's configured Excel folder" in page.status_label.text()


@pytest.mark.qt
def test_output_inside_excel_root_is_rejected_before_worker_start(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    _host, page = _build_page(qtbot, monkeypatch, tmp_path)
    assert page._dataset_index is not None
    invalid_output = page._dataset_index.excel_root / "Generated Maps"

    page.output_root_edit.setText(str(invalid_output))

    assert page.run_btn.isEnabled() is False
    assert "output cannot be the processed Excel input folder" in page.status_label.text()

    page._start_run()

    assert page.has_active_generation() is False
    assert "output cannot be the processed Excel input folder" in page.status_label.text()


@pytest.mark.qt
def test_cancel_keeps_busy_and_navigation_locked_until_worker_exit(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    class ControlledWorker(QObject):
        progress = Signal(int)
        message = Signal(str)
        finished = Signal(object)
        instances: list[ControlledWorker] = []

        def __init__(self, requests) -> None:
            super().__init__()
            self.requests = tuple(requests)
            self.started = threading.Event()
            self.cancel_requested = threading.Event()
            self.allow_finish = threading.Event()
            self.outcome = None
            self.instances.append(self)

        def run(self) -> None:
            self.started.set()
            self.cancel_requested.wait(timeout=5.0)
            self.allow_finish.wait(timeout=5.0)
            self.outcome = PublicationMapsWorkerOutcome.cancelled()
            self.finished.emit(self.outcome)

        def cancel(self) -> None:
            self.cancel_requested.set()

    monkeypatch.setattr(
        publication_maps_gui,
        "PublicationMapsWorker",
        ControlledWorker,
    )
    confirmations: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(
        publication_maps_gui,
        "confirm",
        lambda _parent, title, _message: confirmations.append(title) or False,
    )
    monkeypatch.setattr(
        publication_maps_gui,
        "show_error",
        lambda _parent, _title, message: errors.append(message),
    )
    host, page = _build_page(qtbot, monkeypatch, tmp_path)

    page._start_run()
    qtbot.waitUntil(lambda: bool(ControlledWorker.instances), timeout=2000)
    worker = ControlledWorker.instances[0]
    qtbot.waitUntil(worker.started.is_set, timeout=2000)

    try:
        assert page.has_active_generation()
        assert page.run_btn.isEnabled() is False
        assert page.cancel_btn.isEnabled() is True
        assert host.menuBar().isEnabled() is False

        page._cancel_run()

        assert worker.cancel_requested.is_set()
        assert page.cancel_btn.isEnabled() is False
        assert page.has_active_generation()
        assert host.menuBar().isEnabled() is False
        assert "waiting for the active worker" in page.status_label.text()

        page._start_run()
        assert len(ControlledWorker.instances) == 1

        worker.allow_finish.set()
        qtbot.waitUntil(lambda: not page.has_active_generation(), timeout=3000)

        assert page.run_btn.isEnabled() is True
        assert page.cancel_btn.isEnabled() is False
        assert host.menuBar().isEnabled() is True
        assert "No new output was published" in page.status_label.text()
        assert confirmations == []
        assert errors == []
    finally:
        worker.allow_finish.set()
        if page.has_active_generation():
            qtbot.waitUntil(lambda: not page.has_active_generation(), timeout=6000)


@pytest.mark.qt
def test_post_processing_outcome_emits_shared_recovery_request(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    _host, page = _build_page(qtbot, monkeypatch, tmp_path)
    requests: list[tuple[str, str, str]] = []
    confirmations: list[str] = []
    page.post_processing_required.connect(
        lambda tool, reason, root: requests.append((tool, reason, root))
    )
    monkeypatch.setattr(
        publication_maps_gui,
        "confirm",
        lambda _parent, title, _message: confirmations.append(title) or False,
    )

    page._handle_worker_outcome(
        PublicationMapsWorkerOutcome.post_processing_required(
            reason="Saved harmonic selection is missing.",
            project_root=page._project_root,
        )
    )

    assert requests == [
        (
            "Scalp Maps",
            "Saved harmonic selection is missing.",
            str(page._project_root.resolve(strict=False)),
        )
    ]
    assert confirmations == []
    assert page.status_label.property("statusVariant") == "warning"


@pytest.mark.qt
def test_error_outcome_never_opens_completion_prompt(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    _host, page = _build_page(qtbot, monkeypatch, tmp_path)
    confirmations: list[str] = []
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        publication_maps_gui,
        "confirm",
        lambda _parent, title, _message: confirmations.append(title) or False,
    )
    monkeypatch.setattr(
        publication_maps_gui,
        "show_error",
        lambda _parent, title, message: errors.append((title, message)),
    )

    page._handle_worker_outcome(
        PublicationMapsWorkerOutcome.error("One active workbook is unreadable.")
    )

    assert confirmations == []
    assert errors == [
        ("Scalp Maps error", "One active workbook is unreadable.")
    ]
    assert page.status_label.property("statusVariant") == "error"


@pytest.mark.qt
def test_main_window_defers_close_while_scalp_maps_generation_stops(
    monkeypatch,
) -> None:
    class PublicationMapsPage:
        shutdown_calls = 0

        @staticmethod
        def has_active_generation() -> bool:
            return True

        def shutdown(self) -> bool:
            self.shutdown_calls += 1
            return True

    page = PublicationMapsPage()
    ignored: list[bool] = []
    notices: list[tuple[str, str]] = []
    host = SimpleNamespace(
        _plot_generator_page=None,
        _publication_maps_page=page,
    )
    event = SimpleNamespace(ignore=lambda: ignored.append(True))
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        lambda _parent, title, message: notices.append((title, message)),
    )

    main_window_module.MainWindow.closeEvent(host, event)

    assert ignored == [True]
    assert page.shutdown_calls == 1
    assert notices == [
        (
            "Scalp Map Generation Is Stopping",
            "Cancellation was requested. Wait for the active Scalp Maps worker "
            "to stop before closing FPVS Toolbox.",
        )
    ]

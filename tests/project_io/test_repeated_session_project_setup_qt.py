from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest


if (
    importlib.util.find_spec("PySide6") is None
    or importlib.util.find_spec("pytestqt") is None
):
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from Main_App.projects import project_manager  # noqa: E402
from Main_App.projects.recording_preflight import (  # noqa: E402
    RecordingPreflightCancelled,
)


class _ProjectHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.loaded = []

    def loadProject(self, project) -> None:  # noqa: N802 - app compatibility API
        self.loaded.append(project)


def _manifest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    raw_root = tmp_path / "raw"
    groups = {
        "birth_control": {
            "label": "Birth Control",
            "folder_name": "Birth Control",
            "raw_input_folder": raw_root / "Birth Control",
        },
        "control": {
            "label": "Control Group",
            "folder_name": "Control Group",
            "raw_input_folder": raw_root / "Control Group",
        },
    }
    sessions = {
        "luteal": {"label": "Luteal", "visit_index": 1},
        "follicular": {"label": "Follicular", "visit_index": 2},
    }
    sources = {
        (group_id, session_id): Path(info["raw_input_folder"]) / session_id
        for group_id, info in groups.items()
        for session_id in sessions
    }
    for (group_id, session_id), folder in sources.items():
        folder.mkdir(parents=True)
        participant = "P01" if group_id == "birth_control" else "P02"
        group_token = "BC" if group_id == "birth_control" else "CG"
        session_token = "L" if session_id == "luteal" else "F"
        (folder / f"{participant}_{group_token}_{session_token}.bdf").write_text(
            "fixture",
            encoding="utf-8",
        )
    project_dir = tmp_path / "Repeated Project"
    manifest = project_manager.build_repeated_session_project_manifest(
        project_root=project_dir,
        project_name="Repeated Project",
        groups=groups,
        sessions=sessions,
        source_folders=sources,
    )
    return project_dir, manifest


def test_repeated_project_preflight_runs_off_gui_thread_and_continues(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    host = _ProjectHost()
    qtbot.addWidget(host)
    project_dir, manifest = _manifest(tmp_path)
    worker_threads: list[QThread] = []
    continuation_threads: list[QThread] = []
    real_preflight = project_manager.preflight_repeated_recording_sources
    real_create = project_manager._create_repeated_session_project

    def observed_preflight(*args, **kwargs):
        worker_threads.append(QThread.currentThread())
        return real_preflight(*args, **kwargs)

    def observed_create(*args, **kwargs):
        continuation_threads.append(QThread.currentThread())
        return real_create(*args, **kwargs)

    monkeypatch.setattr(
        project_manager,
        "preflight_repeated_recording_sources",
        observed_preflight,
    )
    monkeypatch.setattr(
        project_manager,
        "_create_repeated_session_project",
        observed_create,
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "critical",
        lambda *args, **kwargs: pytest.fail("unexpected preflight failure"),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "information",
        lambda *args, **kwargs: pytest.fail("unexpected information message"),
    )

    started = project_manager._start_repeated_session_preflight(
        host,
        project_dir=project_dir,
        project_name="Repeated Project",
        manifest=manifest,
        use_existing_project_folder=False,
    )

    assert started is True
    qtbot.waitUntil(lambda: len(host.loaded) == 1, timeout=5_000)
    assert worker_threads
    assert worker_threads[0] != app.thread()
    assert continuation_threads == [app.thread()]
    assert (project_dir / "project.json").is_file()
    assert host._active_repeated_preflight_job is None


def test_repeated_project_preflight_cancel_stops_before_project_creation(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    QApplication.instance() or QApplication([])
    host = _ProjectHost()
    qtbot.addWidget(host)
    project_dir, manifest = _manifest(tmp_path)
    entered_worker = threading.Event()
    information_messages: list[tuple[str, str]] = []

    def cancellable_preflight(*args, cancel_requested, **kwargs):  # noqa: ARG001
        entered_worker.set()
        while not cancel_requested():
            time.sleep(0.001)
        raise RecordingPreflightCancelled("cancelled")

    monkeypatch.setattr(
        project_manager,
        "preflight_repeated_recording_sources",
        cancellable_preflight,
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "information",
        lambda _parent, title, text: information_messages.append((title, text)),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "critical",
        lambda *args, **kwargs: pytest.fail("unexpected preflight failure"),
    )

    project_manager._start_repeated_session_preflight(
        host,
        project_dir=project_dir,
        project_name="Repeated Project",
        manifest=manifest,
        use_existing_project_folder=False,
    )
    qtbot.waitUntil(entered_worker.is_set, timeout=5_000)
    host._active_repeated_preflight_progress.cancel()

    qtbot.waitUntil(
        lambda: host._active_repeated_preflight_job is None,
        timeout=5_000,
    )
    assert not project_dir.exists()
    assert host.loaded == []
    assert any("No project was created" in text for _title, text in information_messages)

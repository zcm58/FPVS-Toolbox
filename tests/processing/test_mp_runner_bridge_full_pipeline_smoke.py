import sys
import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import Main_App.workers.mp_runner_bridge as mp_runner_bridge
from Main_App.workers.mp_runner_bridge import MpRunnerBridge


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeQueue:
    def __init__(self) -> None:
        self._items = []

    def put(self, item) -> None:
        self._items.append(item)

    def get_nowait(self):
        if not self._items:
            raise mp_runner_bridge.Empty
        return self._items.pop(0)


def test_mp_runner_bridge_error_and_finished(app, qtbot):
    bridge = MpRunnerBridge()
    errors = []
    file_statuses = []
    finished_payloads = []
    progresses = []

    bridge.error.connect(errors.append)
    bridge.file_status.connect(file_statuses.append)
    bridge.finished.connect(lambda payload: finished_payloads.append(payload))
    bridge.progress.connect(lambda pct: progresses.append(pct))

    q = _FakeQueue()
    # Inject the queue and a total count so _poll() can run without starting real workers.
    bridge._q = q  # type: ignore[assignment]
    bridge._total = 2

    # Simulate one error result and one ok result, then completion.
    q.put(
        {
            "type": "progress",
            "completed": 1,
            "total": 2,
            "result": {
                "status": "error",
                "file": r"C:\Projects\FPVS\Semantic Categories\SC_P13.bdf",
                "stage": "events",
                "error": "Missing event codes [5] in SC_P13.bdf (stim='Status')",
            },
        }
    )
    q.put(
        {
            "type": "progress",
            "completed": 2,
            "total": 2,
            "result": {
                "status": "ok",
                "file": r"C:\Projects\FPVS\Semantic Categories\SC_P14.bdf",
                "stage": "done",
                "audit": {},
                "problems": [],
            },
        }
    )
    q.put({"type": "done", "count": 2})

    # Call the internal poll slot directly; pytest-qt keeps the event loop alive.
    bridge._poll()

    # Ordinary failures update the file row without invoking fatal error UI.
    assert errors == []
    assert [result["status"] for result in file_statuses] == ["error", "ok"]

    # Finished emitted once, with the ok result preserved.
    assert len(finished_payloads) == 1
    payload = finished_payloads[0]
    assert payload["files"] == 2
    assert len(payload["results"]) == 1
    assert payload["results"][0]["file"].endswith("SC_P14.bdf")
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["stage"] == "events"
    assert "Missing event codes [5]" in payload["errors"][0]["error"]

    # Progress signal should have been emitted at least once.
    assert any(p > 0 for p in progresses)


def test_mp_runner_bridge_excluded_result_is_not_error(app, qtbot):
    bridge = MpRunnerBridge()
    errors = []
    file_statuses = []
    finished_payloads = []

    bridge.error.connect(errors.append)
    bridge.file_status.connect(file_statuses.append)
    bridge.finished.connect(lambda payload: finished_payloads.append(payload))

    q = _FakeQueue()
    bridge._q = q  # type: ignore[assignment]
    bridge._total = 1

    q.put(
        {
            "type": "progress",
            "completed": 1,
            "total": 1,
            "result": {
                "status": "excluded",
                "file": r"C:\Projects\FPVS\MCCTR\p16.bdf",
                "stage": "preflight",
                "reason": "recording_not_started",
                "message": "File p16.bdf was created, but the user did not click Record in BioSemi.",
            },
        }
    )
    q.put({"type": "done", "count": 1})

    bridge._poll()

    assert errors == []
    assert file_statuses[0]["status"] == "excluded"
    assert len(finished_payloads) == 1
    payload = finished_payloads[0]
    assert payload["results"] == []
    assert payload["excluded"][0]["file"].endswith("p16.bdf")


def test_mp_runner_bridge_logs_single_settings_snapshot(app, caplog, monkeypatch):
    bridge = MpRunnerBridge()

    monkeypatch.setattr(mp_runner_bridge, "set_blas_threads_single_process", lambda: None)
    monkeypatch.setattr(mp_runner_bridge.Thread, "start", lambda self: None)
    monkeypatch.setattr(mp_runner_bridge, "Queue", _FakeQueue)

    project_root = Path(r"C:\Projects\FPVS\Semantic Categories")
    data_files = [
        project_root / "SC_P13.bdf",
        project_root / "SC_P14.bdf",
        project_root / "SC_P15.bdf",
    ]
    settings = {
        "high_pass": 0.1,
        "low_pass": 50.0,
        "downsample_rate": 256,
        "reject_thresh": 5.0,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "stim_channel": "Status",
    }

    with caplog.at_level(logging.DEBUG):
        bridge.start(
            project_root=project_root,
            data_files=data_files,
            settings=settings,
            event_map={"CondA": 1},
            save_folder=project_root / "1 - Excel Data Files",
            max_workers=4,
        )

    snapshot_records = [
        record for record in caplog.records if "BRIDGE_SETTINGS_SNAPSHOT" in record.getMessage()
    ]
    assert len(snapshot_records) == 1
    assert "SC_P13.bdf" in snapshot_records[0].getMessage()
    assert "SC_P15.bdf" in snapshot_records[0].getMessage()
    bridge._timer.stop()


def test_dead_controller_drains_results_and_allows_restart(app, qtbot, monkeypatch, tmp_path):
    bridge = MpRunnerBridge()
    finished = []
    statuses = []
    bridge.finished.connect(finished.append)
    bridge.file_status.connect(statuses.append)
    first, second = tmp_path / "first.bdf", tmp_path / "second.bdf"

    def abnormal_exit(params, queue, cancel_event):
        queue.put({"type": "progress", "completed": 1, "result": {"status": "ok", "file": str(first)}})
        # Return without a terminal message to model an unexpected controller exit.

    monkeypatch.setattr(mp_runner_bridge, "run_project_parallel", abnormal_exit)
    bridge.start(tmp_path, [first, second], {}, {}, tmp_path, 1)
    qtbot.waitUntil(lambda: len(finished) == 1)
    assert not bridge._running
    assert finished[0]["status"] == "error"
    assert finished[0]["results"] == statuses
    assert finished[0]["interrupted_files"] == [str(second)]

    def succeed(params, queue, cancel_event):
        queue.put({"type": "done", "status": "success", "results": [{"status": "ok", "file": str(second)}]})

    monkeypatch.setattr(mp_runner_bridge, "run_project_parallel", succeed)
    bridge.start(tmp_path, [second], {}, {}, tmp_path, 1)
    qtbot.waitUntil(lambda: len(finished) == 2)
    assert finished[1]["status"] == "success"
    assert finished[1]["errors"] == []
    assert not bridge._timer.isActive()


def test_bridge_start_failure_emits_one_deferred_terminal(app, qtbot, monkeypatch, tmp_path):
    bridge = MpRunnerBridge()
    finished = []
    bridge.finished.connect(finished.append)

    def failed_start(self):
        raise RuntimeError("Thread creation failed")

    monkeypatch.setattr(mp_runner_bridge.Thread, "start", failed_start)
    bridge.start(tmp_path, [tmp_path / "a.bdf"], {}, {}, tmp_path, 1)
    assert finished == []
    qtbot.waitUntil(lambda: len(finished) == 1)
    assert not bridge._running
    assert finished[0]["status"] == "error"
    assert "Thread creation failed" in finished[0]["controller_error"]
    bridge._poll()
    assert len(finished) == 1

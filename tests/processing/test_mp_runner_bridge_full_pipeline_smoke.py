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


class _FakeContext:
    def Queue(self):
        return _FakeQueue()


def test_mp_runner_bridge_error_and_finished(app, qtbot):
    bridge = MpRunnerBridge()
    errors = []
    finished_payloads = []
    progresses = []

    bridge.error.connect(errors.append)
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

    # One error emitted, with file + stage included in the message.
    assert len(errors) == 1
    err_msg = errors[0]
    assert "SC_P13.bdf" in err_msg
    assert "[events]" in err_msg
    assert "Missing event codes [5]" in err_msg

    # Finished emitted once, with the ok result preserved.
    assert len(finished_payloads) == 1
    payload = finished_payloads[0]
    assert payload["files"] == 2
    assert len(payload["results"]) == 1
    assert payload["results"][0]["file"].endswith("SC_P14.bdf")

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
    monkeypatch.setattr(mp_runner_bridge, "get_context", lambda name: _FakeContext())

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

import sys
from multiprocessing import get_context

import pytest
from PySide6.QtWidgets import QApplication

from Main_App.PySide6_App.workers.mp_runner_bridge import MpRunnerBridge


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_mp_runner_bridge_error_and_finished(app, qtbot):
    bridge = MpRunnerBridge()
    errors = []
    finished_payloads = []
    progresses = []

    bridge.error.connect(errors.append)
    bridge.finished.connect(lambda payload: finished_payloads.append(payload))
    bridge.progress.connect(lambda pct: progresses.append(pct))

    ctx = get_context("spawn")
    q = ctx.Queue()
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

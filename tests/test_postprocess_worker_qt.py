import time
import importlib.util
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from Main_App.PySide6_App.GUI.main_window import MainWindow
from Main_App.PySide6_App.adapters import post_export_adapter


def test_postprocess_worker_qt(qtbot, monkeypatch):
    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)

    monkeypatch.setattr(post_export_adapter, "run_post_export", lambda ctx, labels: time.sleep(0.01))

    win.gui_queue.put({
        "type": "post",
        "file": "demo.bdf",
        "epochs_dict": {"A": []},
        "labels": ["A"],
    })

    win._periodic_queue_check()
    qtbot.mouseClick(win.btn_add_event, Qt.LeftButton)
    assert win.btn_add_event.isEnabled()
    qtbot.waitUntil(lambda: getattr(win, "_post_worker", None) is None, timeout=1000)

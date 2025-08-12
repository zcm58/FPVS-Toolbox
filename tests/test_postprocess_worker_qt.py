import sys, pytest
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Qt, QThread


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_post_worker_keeps_ui_responsive(app, qtbot, monkeypatch):
    from Main_App.PySide6_App.GUI.main_window import MainWindow
    import Main_App.PySide6_App.adapters.post_export_adapter as adapter
    # Stub heavy legacy call
    monkeypatch.setattr(adapter, "run_post_export", lambda ctx, labels: QThread.msleep(50))

    win = MainWindow()
    qtbot.addWidget(win)
    win._run_active = True

    win.gui_queue.put({"type": "post", "file": "demo.bdf", "epochs_dict": {"X": 1}, "labels": ["A"]})
    win._periodic_queue_check()

    btn = QPushButton("click", win)
    qtbot.addWidget(btn)
    qtbot.mouseClick(btn, Qt.LeftButton)
    assert btn.isEnabled()

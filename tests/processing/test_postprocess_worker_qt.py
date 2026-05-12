import sys

import pytest
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_post_worker_keeps_ui_responsive(app, qtbot, monkeypatch):
    from Main_App.gui.main_window import MainWindow
    import Main_App.gui.post_export_workflows as post_export_workflows

    class FastPostWorker(QObject):
        error = Signal(str)
        finished = Signal(dict)

        def __init__(self, *args, **kwargs):
            super().__init__()

        def stop(self):
            pass

        @Slot()
        def run(self):
            self.finished.emit(
                {
                    "file": "demo.bdf",
                    "generated_excel_paths": ["demo.xlsx"],
                    "existing_excel_paths": [],
                }
            )

    monkeypatch.setattr(post_export_workflows, "PostProcessWorker", FastPostWorker)

    win = MainWindow()
    qtbot.addWidget(win)
    win._run_active = True

    win.gui_queue.put({"type": "post", "file": "demo.bdf", "epochs_dict": {"X": 1}, "labels": ["A"]})
    win._periodic_queue_check()

    btn = QPushButton("click", win)
    qtbot.addWidget(btn)
    qtbot.mouseClick(btn, Qt.LeftButton)
    assert btn.isEnabled()
    qtbot.waitUntil(lambda: win._post_thread is None, timeout=2000)
    if win._post_thread is not None:
        win._post_thread.quit()
        win._post_thread.wait(2000)
        win._post_thread = None
        win._post_worker = None

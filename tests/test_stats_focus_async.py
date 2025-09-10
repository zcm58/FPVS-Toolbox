from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
from Tools.Stats.PySide6.stats_worker import StatsWorker


def test_stats_focus_async(qtbot, monkeypatch):
    win = StatsWindow(project_dir=str(Path.cwd()))
    qtbot.addWidget(win)
    win.show()
    win.subject_data = {"s1": {"c1": {"roi": 1.0}}}
    win.subjects = ["s1"]
    win.conditions = ["c1"]

    def fake_run(self):
        self.signals.message.emit("start")
        self.signals.progress.emit(55)
        time.sleep(0.01)
        self.signals.finished.emit({})

    monkeypatch.setattr(StatsWorker, "run", fake_run, raising=False)

    qtbot.mouseClick(win.run_rm_anova_btn, Qt.LeftButton)
    assert not win.run_rm_anova_btn.isEnabled()
    qtbot.waitUntil(lambda: win.run_rm_anova_btn.isEnabled(), timeout=1000)
    assert win._progress_updates
    assert win._focus_calls >= 2

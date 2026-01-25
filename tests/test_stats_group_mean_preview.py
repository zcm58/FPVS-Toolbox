from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402

from Tools.Stats.PySide6.dv_policies import (  # noqa: E402
    EMPTY_LIST_FALLBACK_FIXED_K,
    GROUP_MEAN_Z_POLICY_NAME,
)
from Tools.Stats.PySide6.stats_workers import StatsWorker  # noqa: E402
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


@pytest.mark.qt
def test_group_mean_preview_updates_table(qtbot, tmp_path, monkeypatch):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    window.subjects = ["S1"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {"S1": {"CondA": "a.xlsx", "CondB": "b.xlsx"}}
    window.rois = {"ROI1": ["Fz"]}

    monkeypatch.setattr(window, "refresh_rois", lambda: None)
    monkeypatch.setattr(window, "_get_analysis_settings", lambda: (6.0, 0.05))

    window.dv_policy_combo.setCurrentText(GROUP_MEAN_Z_POLICY_NAME)
    window.group_mean_empty_policy_combo.setCurrentText(EMPTY_LIST_FALLBACK_FIXED_K)

    def fast_run(self):  # pragma: no cover - executed in Qt thread pool
        payload = {
            "union_harmonics_by_roi": {"ROI1": [1.2, 2.4]},
            "fallback_info_by_roi": {"ROI1": {"policy": EMPTY_LIST_FALLBACK_FIXED_K, "fallback_used": False}},
        }
        self.signals.finished.emit(payload)

    monkeypatch.setattr(StatsWorker, "run", fast_run, raising=False)

    qtbot.mouseClick(window.group_mean_preview_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.group_mean_preview_table.rowCount() == 1, timeout=2000)

    assert window.group_mean_preview_table.item(0, 0).text() == "ROI1"
    assert "1.2" in window.group_mean_preview_table.item(0, 1).text()

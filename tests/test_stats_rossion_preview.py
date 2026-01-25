from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openpyxl")
from PySide6.QtCore import Qt  # noqa: E402

from Tools.Stats.PySide6.dv_policies import (  # noqa: E402
    ROSSION_POLICY_NAME,
)
from Tools.Stats.PySide6.stats_workers import StatsWorker  # noqa: E402
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


def _write_z_sheet(path, values):
    df = pd.DataFrame(values, index=["Fz"])
    df.to_excel(path, sheet_name="Z Score")


@pytest.mark.qt
def test_rossion_preview_excludes_harmonic1_and_reports_stop(qtbot, tmp_path, monkeypatch):
    file_a = tmp_path / "cond_a.xlsx"
    file_b = tmp_path / "cond_b.xlsx"
    values = {
        "1.2_Hz": [0.5],
        "2.4_Hz": [2.0],
        "3.6_Hz": [1.0],
        "4.8_Hz": [0.5],
    }
    _write_z_sheet(file_a, values)
    _write_z_sheet(file_b, values)

    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    window.subjects = ["S1"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {
        "S1": {"CondA": str(file_a), "CondB": str(file_b)},
    }
    window.rois = {"ROI1": ["Fz"]}

    monkeypatch.setattr(window, "refresh_rois", lambda: None)
    monkeypatch.setattr(window, "_get_analysis_settings", lambda: (6.0, 0.05))

    window.fixed_k_exclude_h1.setChecked(True)
    window.dv_policy_combo.setCurrentText(ROSSION_POLICY_NAME)

    def fast_run(self):  # pragma: no cover - executed in Qt thread pool
        result = self._fn(
            self.signals.progress.emit, self.signals.message.emit, *self._args, **self._kwargs
        )
        payload = result if isinstance(result, dict) else {"result": result}
        self.signals.finished.emit(payload)

    monkeypatch.setattr(StatsWorker, "run", fast_run, raising=False)

    qtbot.mouseClick(window.group_mean_preview_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.group_mean_preview_table.rowCount() == 1, timeout=2000)

    harmonics_text = window.group_mean_preview_table.item(0, 1).text()
    assert "1.2" not in harmonics_text
    assert "2.4" in harmonics_text

    stop_reason = window.group_mean_preview_table.item(0, 4).text()
    stop_fail = window.group_mean_preview_table.item(0, 5).text()
    assert stop_reason == "two_consecutive_nonsignificant"
    assert "3.6" in stop_fail
    assert "4.8" in stop_fail

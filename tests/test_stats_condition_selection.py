from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QCheckBox  # noqa: E402

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


@pytest.mark.qt
def test_stats_condition_selection_snapshot_and_block(qtbot, tmp_path, monkeypatch):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    conditions = ["CondA", "CondB", "CondC"]
    window._populate_conditions_panel(conditions)

    assert window.conditions_group.title() == "Included Conditions"
    assert window._get_selected_conditions() == conditions

    checkboxes = {box.text(): box for box in window.findChildren(QCheckBox)}
    for condition in conditions:
        assert condition in checkboxes

    checkboxes["CondC"].setChecked(False)

    window.rois = {"ROI1": ["Fz"]}
    monkeypatch.setattr(window, "refresh_rois", lambda: None)
    monkeypatch.setattr(window, "_get_analysis_settings", lambda: (6.0, 0.05))

    base_freq, alpha, roi_map, selected_conditions = window.get_analysis_settings_snapshot()
    assert base_freq == 6.0
    assert alpha == 0.05
    assert roi_map == {"ROI1": ["Fz"]}
    assert selected_conditions == ["CondA", "CondB"]

    checkboxes["CondB"].setChecked(False)
    window.subject_data = {"S1": {"CondA": "fake.xlsx"}}
    window.subjects = ["S1"]
    window.conditions = conditions
    window.le_folder.setText(str(tmp_path))

    monkeypatch.setattr(window, "_get_harmonic_settings", lambda: window._harmonic_config)
    worker_called = {"value": False}

    def _record_worker(*_args, **_kwargs):
        worker_called["value"] = True

    monkeypatch.setattr(window, "start_step_worker", _record_worker)
    window.on_analyze_single_group_clicked()

    assert worker_called["value"] is False
    assert "Select at least two conditions" in window.lbl_status.text()

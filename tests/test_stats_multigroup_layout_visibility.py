from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QAbstractScrollArea, QGroupBox, QPlainTextEdit

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.mark.qt
def test_multigroup_scan_summary_controls_visible_at_startup(qtbot, tmp_path):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(100)

    summary_group = next(
        box for box in window.findChildren(QGroupBox) if box.title() == "Multi-Group Scan Summary"
    )
    assert summary_group.isVisible()
    assert summary_group.height() > 0

    assert window.compute_shared_harmonics_btn.isVisible()
    assert window.compute_shared_harmonics_btn.height() > 20
    assert window.compute_fixed_harmonic_dv_btn.isVisible()
    assert window.compute_fixed_harmonic_dv_btn.height() > 20
    assert window.multi_group_issue_toggle_btn.isVisible()

    issues = window.multi_group_issue_text
    assert isinstance(issues, QPlainTextEdit)
    assert isinstance(issues, QAbstractScrollArea)
    assert issues.isVisible()
    assert issues.minimumHeight() >= 70
    assert issues.maximumHeight() <= 140

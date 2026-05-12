from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QAbstractScrollArea, QPlainTextEdit

from Main_App.gui.widgets import SectionCard
from Tools.Stats.ui.stats_window import StatsWindow


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
        card
        for card in window.findChildren(SectionCard)
        if card.header.title_label.text() == "Multi-Group Scan Summary"
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

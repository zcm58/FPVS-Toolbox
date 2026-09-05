from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from Main_App.gui.signal_review_model import SignalReviewItem  # noqa: E402
from Main_App.gui.signal_review_panel import SignalReviewPanel  # noqa: E402
from Main_App.gui.theme import apply_fpvs_theme  # noqa: E402


@pytest.fixture
def review_items() -> tuple[SignalReviewItem, ...]:
    first = SignalReviewItem(
        (
            "P13", "recording-1", "Baseline", "1", "Patient group", "p13.bdf",
            "Oz was flagged in Positive, occurrence 1. Category: low_variance. "
            "Analyzed samples: [718565, 964325].",
        ),
        "Channel signal", "Low variance", "Positive", "1", "Oz",
    )
    second = SignalReviewItem(
        (
            *first.export_row[:-1],
            "T7 had a transient high amplitude flag in Negative, occurrence 2, "
            "across 9 overlapping diagnostic windows. Reported coverage is the "
            "union of flagged windows, not measured artifact duration.",
        ),
        "Transient signal", "High amplitude", "Negative", "2", "T7",
    )
    third = SignalReviewItem(
        (
            "P13", "recording-2", "Follow-up", "2", "Patient group", "p13.bdf",
            "Removed-electrode assessment disabled; no automatic assessment.",
        ),
        "Assessment status", "Not assessed",
    )
    return first, second, third


@pytest.fixture
def review_panel(qtbot, review_items):
    panel = SignalReviewPanel(review_items)
    qtbot.addWidget(panel)
    panel.resize(1000, 650)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def test_grouped_recordings_keep_concise_rows_and_full_details(review_panel, review_items):
    panel = review_panel
    assert panel.tree.topLevelItemCount() == 2
    first_root = panel.tree.topLevelItem(0)
    second_root = panel.tree.topLevelItem(1)
    assert first_root.childCount() == 2
    assert second_root.childCount() == 1
    assert "recording-1" in first_root.text(0)
    assert "recording-2" in second_root.text(0)
    assert first_root.isExpanded()
    assert panel.tree.currentItem() is first_root.child(0)
    assert [first_root.child(0).text(column) for column in range(4)] == [
        "Low variance", "Positive", "1", "Oz"
    ]
    assert panel.details_view.toPlainText() == review_items[0].details
    assert panel.details_view.isReadOnly()
    assert "3 review items" in panel.count_label.text()
    assert "2 recordings" in panel.count_label.text()

    panel.tree.setCurrentItem(second_root.child(0))
    assert panel.details_view.toPlainText() == review_items[2].details
    for value in ("recording-2", "Follow-up", "visit 2", "Patient group"):
        assert value in panel.details_context_label.text()


def test_filters_search_complete_evidence_and_clear_stale_selection(
    review_panel, review_items
):
    panel = review_panel
    panel.search_edit.setText("P13 718565")
    assert panel.tree.topLevelItemCount() == 1
    assert panel.tree.topLevelItem(0).childCount() == 1
    assert panel.details_view.toPlainText() == review_items[0].details
    assert "1 of 3 review items" in panel.count_label.text()

    panel.kind_combo.setCurrentIndex(panel.kind_combo.findData("Assessment status"))
    assert panel.tree.topLevelItemCount() == 0
    assert panel.tree.currentItem() is None
    assert panel.details_view.toPlainText() == ""
    assert "No matching findings" in panel.details_context_label.text()

    panel.search_edit.clear()
    assert panel.tree.topLevelItemCount() == 1
    assert panel.details_view.toPlainText() == review_items[2].details
    panel.kind_combo.setCurrentIndex(0)
    assert panel.tree.topLevelItemCount() == 2
    assert panel.details_view.toPlainText() == review_items[0].details


def test_keyboard_selection_updates_complete_evidence(qtbot, review_panel, review_items):
    panel = review_panel
    panel.tree.setFocus()
    qtbot.keyClick(panel.tree, Qt.Key.Key_Down)
    assert panel.tree.currentItem() is panel.tree.topLevelItem(0).child(1)
    assert panel.details_view.toPlainText() == review_items[1].details
    assert "Condition: Negative" in panel.details_context_label.text()
    assert "Occurrence: 2" in panel.details_context_label.text()
    assert "Channel(s): T7" in panel.details_context_label.text()

    # Recording groups must be reachable and expandable without a mouse.
    second_root = panel.tree.topLevelItem(1)
    panel.tree.setCurrentItem(second_root)
    qtbot.keyClick(panel.tree, Qt.Key.Key_Right)
    assert second_root.isExpanded()
    qtbot.keyClick(panel.tree, Qt.Key.Key_Down)
    assert panel.tree.currentItem() is second_root.child(0)
    assert panel.details_view.toPlainText() == review_items[2].details


def test_duplicate_findings_are_kept(qtbot, review_items):
    panel = SignalReviewPanel((review_items[0], review_items[0]))
    qtbot.addWidget(panel)
    assert panel.tree.topLevelItemCount() == 1
    assert panel.tree.topLevelItem(0).childCount() == 2


def test_long_evidence_fits_bounded_themed_workspace(qtbot, review_items):
    app = QApplication.instance()
    previous_stylesheet = app.styleSheet()
    previous_font = app.font()
    previous_palette = app.palette()
    previous_style = app.style().objectName()
    host = QWidget()
    qtbot.addWidget(host)
    try:
        apply_fpvs_theme(app)
        # The panel shares the supported 1280 x 900 shell with QC header/actions.
        host.setFixedSize(1000, 650)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        long_item = replace(
            review_items[0],
            export_row=(
                "P13", "recording-1", "Baseline before intervention", "1",
                "Patient group with a descriptive study label", "p13.bdf",
                review_items[0].details * 500,
            ),
        )
        panel = SignalReviewPanel((long_item, *review_items[1:]), host)
        layout.addWidget(panel)
        host.show()
        qtbot.waitExposed(host)
        QApplication.processEvents()

        for control in (
            panel.count_label, panel.search_edit, panel.kind_combo,
            panel.tree, panel.details_context_label, panel.details_view,
        ):
            assert control.isVisibleTo(host)
            bounds = QRect(control.mapTo(host, QPoint(0, 0)), control.size())
            assert host.rect().contains(bounds), type(control).__name__
            assert control.height() >= control.minimumHeight()
        context = panel.details_context_label
        assert context.height() >= context.heightForWidth(context.width())
        assert panel.details_view.toPlainText() == long_item.details
        assert panel.details_view.verticalScrollBar().maximum() > 0
        assert panel.tree.visualItemRect(panel.tree.currentItem()).height() < 50
        assert panel.tree.columnWidth(0) >= 200
    finally:
        host.close()
        app.setStyle(previous_style)
        app.setFont(previous_font)
        app.setPalette(previous_palette)
        app.setStyleSheet(previous_stylesheet)


@pytest.mark.parametrize("choice", ("continue", "cancel"))
@pytest.mark.parametrize("save_fails", (False, True))
def test_review_choice_restores_shared_processing_widgets(
    qtbot, monkeypatch, tmp_path, choice, save_fails
):
    from Main_App.gui import preprocessing_qc_workflow as workflow

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1000, 700)
    layout = QVBoxLayout(host)
    host.processing_status_card = QWidget(host)
    layout.addWidget(host.processing_status_card)
    host.processing_files_card = QWidget(host)
    layout.addWidget(host.processing_files_card, 1)
    files_layout = QVBoxLayout(host.processing_files_card)
    host.processing_files_title_label = QLabel("Files", host.processing_files_card)
    files_layout.addWidget(host.processing_files_title_label)
    host.processing_files_table = QTableWidget(host.processing_files_card)
    files_layout.addWidget(host.processing_files_table)
    host.show()
    qtbot.waitExposed(host)
    # Retain a previously hidden table as well as the usual visible state.
    host.processing_files_table.setVisible(choice == "continue")
    shared_widgets = (
        host.processing_status_card,
        host.processing_files_title_label,
        host.processing_files_table,
    )
    previous_visibility = [not widget.isHidden() for widget in shared_widgets]
    scan = workflow.PreflightQcScan(results=(workflow.PreflightQcFileResult(
        path=Path("p13.bdf"),
        participant_id="P13",
        group_id="patient",
        load_error=None,
        raw_channel_qc={
            "high_amplitude_channels": ["C5", "T7"],
            "experimental_removed_electrode_detector": {"evaluation_status": "evaluated"},
        },
        raw_spectral_qc=None,
    ),))
    expected_rows = [("P13", "Patient group", "p13.bdf", "High-amplitude channel review: C5, T7")]
    report_path = tmp_path / "Data_Quality_Check_Review_Flags.xlsx"
    written_rows = []
    panels = []

    def write_report(_host, rows):
        written_rows.extend(rows)
        if save_fails:
            raise OSError("Synthetic workbook failure")
        return report_path

    def choose(_host, actions):
        assert [action[1] for action in actions] == ["continue", "cancel"]
        panel = host.processing_files_card.findChild(SignalReviewPanel)
        assert panel is not None
        panels.append(panel)
        assert panel.isVisibleTo(host)
        assert all(widget.isHidden() for widget in shared_widgets)
        assert panel.details_view.toPlainText() == expected_rows[0][-1]
        assert panel.tree.topLevelItem(0).child(0).text(3) == "C5, T7"
        report_status = panel.findChild(QLabel, "signal_review_report_status")
        open_report = panel.findChild(QPushButton, "signal_review_open_report")
        assert open_report.isEnabled() is not save_fails
        if save_fails:
            assert "could not be saved" in report_status.text()
            assert "Synthetic workbook failure" in report_status.toolTip()
        else:
            assert str(report_path) in open_report.toolTip()
        return choice

    monkeypatch.setattr(workflow, "_show_data_quality_notice", lambda *args, **kwargs: None)
    monkeypatch.setattr(workflow, "_write_preflight_review_flags", write_report)
    monkeypatch.setattr(workflow, "_await_preflight_choice", choose)

    assert workflow._show_suspicious_remainder(
        host, scan, set(), {"patient": "Patient group"}
    ) is (choice == "continue")
    assert written_rows == expected_rows
    assert [not widget.isHidden() for widget in shared_widgets] == previous_visibility
    assert len(panels) == 1
    assert panels[0].isHidden()
    assert files_layout.indexOf(panels[0]) == -1
    assert files_layout.count() == 2

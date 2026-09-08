from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QWidget,
)

from Main_App.gui.components import AppDialog  # noqa: E402
from Main_App.gui.marker_occurrence_panel import MarkerOccurrenceReviewPanel  # noqa: E402
from Main_App.gui.marker_occurrence_review import (  # noqa: E402
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MarkerOccurrenceReviewItem,
    marker_occurrence_review_rows,
)
from Main_App.gui.theme import apply_fpvs_theme  # noqa: E402


@pytest.fixture
def marker_item(tmp_path: Path) -> MarkerOccurrenceReviewItem:
    return MarkerOccurrenceReviewItem(
        path=tmp_path / "Control" / "Follow-up" / "P01_followup.bdf",
        participant_id="P01", recording_id="P01_followup", session_id="followup",
        session_label="Follow-up visit", condition_label="Faces", condition_code=1,
        repetition_index=1, occurrence_key="1:1", marker_plan_fingerprint="a" * 64,
        occurrence_fingerprint="b" * 64, sampling_rate_hz=Fraction(12), first_samp=0,
        oddball_marker_code=55, expected_analyzed_cycles=4, oddball_rate_hz=Fraction(2),
        raw_marker_samples=(10, 10, 12, 18, 30, 36), retained_marker_samples=(10, 12, 18, 30, 36),
        exact_duplicate_count=1, missing_gap_count=1, estimated_missing_markers=1,
        early_or_extra_count=1, maximum_phase_residual_cycles=Fraction(1, 3),
        interval_evidence=("Gap between samples 18 and 30",),
        proposed_start_sample=10, proposed_stop_sample=34,
        contiguous_candidate_spans=((12, 36),),
        review_reasons=("early_or_extra_marker", "missing_marker_gap"),
    )


def _show_panel(qtbot, item):
    panel = MarkerOccurrenceReviewPanel(item, index=2, total=5, group_label="Control")
    qtbot.addWidget(panel)
    panel.resize(1000, 650)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def test_marker_panel_prioritizes_identity_and_choices_without_timing_dump(qtbot, marker_item):
    panel = _show_panel(qtbot, marker_item)

    assert panel.count_label.text() == "Decision 2 of 5"
    visible_text = "\n".join(label.text() for label in panel.findChildren(QLabel))
    for identity in ("P01", "P01_followup", "Follow-up visit", "Faces", "Control"):
        assert identity in visible_text
    assert marker_item.path.name in panel.source_label.text()
    assert panel.source_label.toolTip() == str(marker_item.path)
    assert "Raw marker samples" not in visible_text
    assert "10, 10, 12, 18, 30, 36" not in visible_text
    assert not panel.findChildren(QPlainTextEdit)
    assert not panel.findChildren(QTableWidget)
    assert not panel.findChildren(QScrollArea)
    assert len(panel.choice_buttons) == 3
    assert [button.text() for button in panel.choice_buttons.values()] == [
        "Use verified window…", "Keep planned window…", "Exclude this repetition…",
    ]
    assert all(button.isEnabled() for button in panel.choice_buttons.values())
    assert all(label.isVisible() and label.text() for label in panel.choice_descriptions.values())
    assert "Technical details" in panel.details_button.text()


@pytest.mark.parametrize("available_span, full_crop, enabled_count", [(True, True, 3), (False, True, 2), (False, False, 1)])
def test_unavailable_marker_choices_keep_their_explanation_visible(
    qtbot, marker_item, available_span, full_crop, enabled_count,
):
    item = replace(
        marker_item,
        contiguous_candidate_spans=marker_item.contiguous_candidate_spans if available_span else (),
        proposed_start_sample=10 if full_crop else None,
        proposed_stop_sample=34 if full_crop else None,
    )
    panel = _show_panel(qtbot, item)
    emitted = []
    panel.choice_requested.connect(emitted.append)

    assert sum(button.isEnabled() for button in panel.choice_buttons.values()) == enabled_count
    assert panel.choice_buttons[MARKER_DECISION_USE_CONTIGUOUS].isEnabled() == available_span
    assert panel.choice_buttons[MARKER_DECISION_RETAIN_FULL].isEnabled() == full_crop
    assert panel.choice_buttons[MARKER_DECISION_EXCLUDE].isEnabled()
    for decision, button in panel.choice_buttons.items():
        if not button.isEnabled():
            description = panel.choice_descriptions[decision]
            assert description.isVisible() and description.text()
            assert description.text().startswith("Unavailable:")
            assert button.accessibleDescription() == description.text()
            qtbot.mouseClick(button, Qt.LeftButton)
    assert emitted == []


@pytest.mark.parametrize("choice", [MARKER_DECISION_USE_CONTIGUOUS, MARKER_DECISION_RETAIN_FULL, MARKER_DECISION_EXCLUDE, "cancel"])
def test_marker_panel_emits_only_the_explicit_choice(qtbot, marker_item, choice):
    panel = _show_panel(qtbot, marker_item)
    emitted = []
    panel.choice_requested.connect(emitted.append)
    button = panel.cancel_button if choice == "cancel" else panel.choice_buttons[choice]
    qtbot.mouseClick(button, Qt.LeftButton)
    assert emitted == [choice]


def test_marker_details_preserve_complete_evidence_without_a_decision(qtbot, marker_item):
    panel = _show_panel(qtbot, marker_item)
    emitted = []
    panel.choice_requested.connect(emitted.append)
    observed = {}

    def inspect_and_close():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, AppDialog):
            observed["wrong_dialog"] = True
            if dialog is not None:
                dialog.close()
            return
        try:
            viewer = dialog.findChild(QPlainTextEdit, "marker_occurrence_details_viewer")
            observed["text"] = viewer.toPlainText()
            observed["read_only"] = viewer.isReadOnly()
            observed["buttons"] = [button.text() for button in dialog.findChildren(QPushButton)]
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect_and_close)
    qtbot.mouseClick(panel.details_button, Qt.LeftButton)

    assert "wrong_dialog" not in observed
    assert observed["read_only"]
    for label, value in marker_occurrence_review_rows(marker_item):
        assert f"{label}\n{value}" in observed["text"]
    assert str(marker_item.path) in observed["text"]
    assert observed["buttons"] == ["Close"]
    assert emitted == []
    assert panel.count_label.text() == "Decision 2 of 5"
    assert not marker_item.path.exists()


def test_marker_panel_fits_available_workspace_with_all_actions_reachable(qtbot, qapp, marker_item):
    apply_fpvs_theme(qapp)
    screen = QWidget()
    screen.resize(1280, 900)
    qtbot.addWidget(screen)
    panel = MarkerOccurrenceReviewPanel(marker_item, screen, index=1, total=8, group_label="Control")
    panel.setGeometry(140, 125, 1000, 650)
    screen.show()
    qtbot.waitExposed(screen)

    assert panel.width() == 1000 and panel.height() == 650
    assert panel.minimumSizeHint().width() <= panel.width()
    assert panel.minimumSizeHint().height() <= panel.height()
    assert screen.rect().contains(panel.geometry())
    for widget in (
        panel.count_label, panel.context_label, panel.source_label, panel.finding_banner,
        panel.required_label, *panel.choice_buttons.values(), *panel.choice_descriptions.values(),
        panel.details_button, panel.cancel_button,
    ):
        assert widget.isVisible()
        bounds = QRect(widget.mapTo(panel, QPoint(0, 0)), widget.size())
        assert panel.rect().contains(bounds), widget.objectName()
    assert not panel.findChildren(QScrollArea)

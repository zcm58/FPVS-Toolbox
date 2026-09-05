from __future__ import annotations

import pytest

from Main_App.gui.signal_review_model import SignalReviewItem


def test_complete_evidence_and_export_row_are_preserved() -> None:
    evidence = (
        "T7 had a transient high amplitude flag in Positive, occurrence 2, "
        "across 9 overlapping diagnostic window(s). Reported coverage is the "
        "union of flagged windows, not measured artifact duration.\n"
        "Analyzed samples: [718565, 964325]. Category: low_variance."
    )
    row = ("P13", "Patient group", "p13.bdf", evidence)
    item = SignalReviewItem(
        row, "Transient signal", "High amplitude", "Positive", "2", "T7"
    )

    assert item.export_row == row
    assert item.details == evidence
    assert item.participant == "P13"
    assert item.group == "Patient group"
    assert item.source_file == "p13.bdf"
    assert (item.recording, item.session, item.visit) == ("", "", "")
    for term in ("patient group", "718565", "positive", "transient signal", "t7"):
        assert term in item.search_text


def test_recording_identity_keeps_session_visit_and_missing_labels() -> None:
    row = (
        "P13",
        "Not registered",
        "Missing session",
        "Missing visit",
        "Patient group",
        "p13.bdf",
        "Assessment unavailable.",
    )
    item = SignalReviewItem(row, "Assessment status", "Not assessed")

    assert item.export_row == row
    assert item.recording == "Not registered"
    assert item.session == "Missing session"
    assert item.visit == "Missing visit"
    assert item.group == "Patient group"
    assert item.source_file == "p13.bdf"
    for value in row[:-1]:
        assert value in item.recording_label
        assert value.casefold() in item.search_text


def test_same_participant_and_filename_do_not_merge_distinct_recordings() -> None:
    first = SignalReviewItem(
        ("P13", "recording-1", "Baseline", "1", "Patient", "p13.bdf", "Finding A"),
        "Channel signal",
        "Low variance",
    )
    second = SignalReviewItem(
        ("P13", "recording-2", "Follow-up", "2", "Patient", "p13.bdf", "Finding A"),
        "Channel signal",
        "Low variance",
    )
    same_recording = SignalReviewItem(
        (*first.export_row[:-1], "Finding B"), "Channel signal", "High amplitude"
    )

    assert first.recording_key != second.recording_key
    assert first.recording_label != second.recording_label
    assert first.recording_key == same_recording.recording_key


@pytest.mark.parametrize("column_count", (0, 3, 5, 6, 8))
def test_invalid_export_shape_is_rejected(column_count: int) -> None:
    with pytest.raises(ValueError, match="four or seven"):
        SignalReviewItem(("value",) * column_count, "Review item", "Finding")

from datetime import UTC, datetime, timedelta, timezone

import pytest

from Main_App.gui.processing_history_model import format_processing_history
from Main_App.processing.processing_history import CompletedProcessingRun, ProcessingHistoryStatus


def completed(count=17):
    return ProcessingHistoryStatus(
        state="completed",
        latest_completed_run=CompletedProcessingRun(
            timestamp=datetime(2026, 11, 4, 14, 30, tzinfo=UTC),
            participant_count=count,
            successful_recording_count=20,
        ),
    )


def test_completion_shows_local_time_zone_and_participants_not_recordings():
    local_zone = timezone(timedelta(hours=-6), name="CST")
    text = format_processing_history(completed(), tz=local_zone)
    assert text == "Last completed processing: 04 Nov 2026, 08:30 CST · 17 participants"
    assert "20" not in text.split("·")[1]


def test_completion_date_changes_with_local_time_zone():
    status = ProcessingHistoryStatus(
        state="completed",
        latest_completed_run=CompletedProcessingRun(
            datetime(2026, 1, 1, 0, 15, tzinfo=UTC), 1, 2,
        ),
    )
    text = format_processing_history(status, tz=timezone(timedelta(hours=-6), "CST"))
    assert text == "Last completed processing: 31 Dec 2025, 18:15 CST · 1 participant"


@pytest.mark.parametrize(("timestamp", "local_zone", "expected"), [
    (datetime(1, 1, 1, tzinfo=UTC), timezone(timedelta(hours=-6)), "01 Jan 0001, 00:00 UTC"),
    (datetime(9999, 12, 31, 23, 59, tzinfo=UTC), timezone(timedelta(hours=14)), "31 Dec 9999, 23:59 UTC"),
])
def test_unrepresentable_local_time_keeps_saved_time_zone(timestamp, local_zone, expected):
    status = ProcessingHistoryStatus(
        state="completed", latest_completed_run=CompletedProcessingRun(timestamp, 1, 1),
    )
    assert format_processing_history(status, tz=local_zone) == f"Last completed processing: {expected} · 1 participant"


def test_unknown_participant_count_is_not_inferred_from_recordings():
    text = format_processing_history(completed(None), tz=UTC)
    assert "participant count unavailable" in text
    assert "20 participants" not in text


@pytest.mark.parametrize(("state", "text"), [
    ("missing", "No completed processing run recorded"),
    ("unavailable", "Processing history unavailable"),
])
def test_history_states_do_not_claim_the_project_was_never_processed(state, text):
    assert format_processing_history(ProcessingHistoryStatus(state=state)) == text


def test_incomplete_history_qualifies_the_latest_known_completion():
    status = completed()
    status = ProcessingHistoryStatus(
        state="completed", latest_completed_run=status.latest_completed_run,
        history_incomplete=True,
    )
    text = format_processing_history(status, tz=UTC)
    assert text.startswith("Last recorded completion:")
    assert "17 participants" in text
    assert text.endswith("(history incomplete)")

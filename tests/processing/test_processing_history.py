from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from Main_App.processing.processing_history import (
    latest_completed_processing_run,
    load_processing_history,
)
from Main_App.processing.processing_ledger import runs_path


def _run(timestamp="2026-11-04T14:30:24Z", **changes):
    return {
        "timestamp": timestamp, "cancelled": False, "run_files": 3,
        "successful_files": 2, "excluded_files": 1, "failed_files": 0,
        "condition_warning_files": 0, "successful_participant_ids": ["P01", "P02"],
        "successful_participant_count": 2, **changes,
    }


def _write(root, rows):
    path = runs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize("changes", [
    {"cancelled": True}, {"cancelled": "false"},
    {"failed_files": 1}, {"condition_warning_files": 1},
    {"successful_files": 1}, {"failed_files": False},
    {"run_files": 0, "successful_files": 0, "excluded_files": 0},
    {"run_files": 3, "successful_files": 0, "excluded_files": 3},
    {"recording_condition_outcomes": {"reconciliation_status": "blocked", "is_pre_review_ready": False}},
    {"recording_condition_outcomes": {"reconciliation_status": "complete", "is_pre_review_ready": False}},
])
def test_incomplete_or_no_work_attempt_does_not_replace_completed_run(changes):
    summary = latest_completed_processing_run([
        _run("2026-11-03T10:00:00Z"), _run(**changes),
    ])
    assert summary.timestamp == datetime(2026, 11, 3, 10, tzinfo=UTC)
    assert summary.participant_count == 2
    assert summary.successful_recording_count == 2


@pytest.mark.parametrize("timestamp", [None, "bad-date", "2026-11-04", "2026-11-04T08:30:00"])
def test_ambiguous_or_invalid_date_is_not_a_completed_timestamp(timestamp):
    assert latest_completed_processing_run([_run(timestamp)]) is None


def test_latest_timestamp_is_compared_in_utc_not_record_order():
    summary = latest_completed_processing_run([
        _run("2026-11-04T10:00:00-06:00"), _run("2026-11-04T14:30:24Z"),
    ])
    assert summary.timestamp == datetime(2026, 11, 4, 16, tzinfo=UTC)


def test_unknown_legacy_count_keeps_latest_completion_instead_of_older_known_count():
    legacy = _run()
    del legacy["successful_participant_ids"]
    del legacy["successful_participant_count"]
    summary = latest_completed_processing_run([_run("2026-11-03T10:00:00Z"), legacy])
    assert summary.timestamp.day == 4
    assert summary.participant_count is None
    assert summary.successful_recording_count == 2


def test_legacy_outcomes_deduplicate_visits_and_conditions_without_excluded_participants():
    record = _run(successful_participant_ids=None)
    del record["successful_participant_ids"]
    del record["successful_participant_count"]
    record["recording_condition_outcomes"] = {
        "reconciliation_status": "complete", "is_pre_review_ready": True,
        "cells": [
            {"processing_id": visit, "participant_id": "P01", "status": "ready", "contributor_count": 1}
            for visit in ("P01-v1", "P01-v2") for _condition in range(3)
        ] + [{"processing_id": "P02-v1", "participant_id": "P02", "status": "excluded", "contributor_count": 0}],
    }
    assert latest_completed_processing_run([record]).participant_count == 1


def test_full_expected_cohort_does_not_become_incremental_processed_count():
    record = _run(run_files=1, successful_files=1, excluded_files=0)
    del record["successful_participant_ids"]
    del record["successful_participant_count"]
    record["recording_condition_outcomes"] = {
        "reconciliation_status": "complete", "is_pre_review_ready": True,
        "cells": [{"processing_id": pid, "participant_id": pid, "status": "ready", "contributor_count": 1}
                  for pid in ("P01", "P02")],
    }
    assert latest_completed_processing_run([record]).participant_count is None


@pytest.mark.parametrize("invalid_status", [[], {}])
def test_malformed_legacy_cell_status_keeps_completion_with_unknown_count(tmp_path, invalid_status):
    record = _run(run_files=1, successful_files=1, excluded_files=0)
    del record["successful_participant_ids"]
    del record["successful_participant_count"]
    record["recording_condition_outcomes"] = {
        "reconciliation_status": "complete", "is_pre_review_ready": True,
        "cells": [{"processing_id": "P01", "participant_id": "P01",
                   "status": invalid_status, "contributor_count": 1}],
    }
    _write(tmp_path, [record])

    summary = load_processing_history(tmp_path)

    assert summary.state == "completed"
    assert summary.latest_completed_run.timestamp == datetime(2026, 11, 4, 14, 30, 24, tzinfo=UTC)
    assert summary.latest_completed_run.participant_count is None


def test_explicit_count_rejects_invalid_identity_count_but_preserves_date():
    assert latest_completed_processing_run([_run(successful_participant_count=3)]).participant_count is None


def test_missing_history_does_not_create_files(tmp_path):
    assert load_processing_history(tmp_path).state == "missing"
    assert not list(tmp_path.iterdir())


def test_reader_finds_completed_history_and_is_read_only(tmp_path):
    path = _write(tmp_path, [_run(), _run("2026-11-05T14:30:24Z", cancelled=True)])
    before = path.read_bytes()
    summary = load_processing_history(tmp_path)
    assert summary.state == "completed"
    assert summary.latest_completed_run.participant_count == 2
    assert path.read_bytes() == before


def test_corrupt_tail_retains_valid_completion_with_explicit_incomplete_flag(tmp_path):
    path = _write(tmp_path, [_run()])
    with path.open("ab") as stream:
        stream.write(b'{"timestamp":"torn append')
    summary = load_processing_history(tmp_path)
    assert summary.state == "completed"
    assert summary.history_incomplete is True


@pytest.mark.parametrize("corrupt_line", [
    b'[' * 2000 + b']' * 2000,
    b'{"oversized_integer":' + b'9' * 10000 + b'}',
], ids=["excessive-nesting", "oversized-integer"])
def test_json_decoder_limits_preserve_an_older_readable_completion(tmp_path, corrupt_line):
    path = _write(tmp_path, [_run()])
    with path.open("ab") as stream:
        stream.write(corrupt_line + b'\n')

    summary = load_processing_history(tmp_path)

    assert summary.state == "completed"
    assert summary.latest_completed_run.participant_count == 2
    assert summary.history_incomplete is True


@pytest.mark.parametrize("field", ["excluded_files", "condition_warning_files"])
@pytest.mark.parametrize("invalid_value", ["invalid", None, True, -1])
def test_invalid_optional_counter_marks_older_completion_as_incomplete(
    tmp_path, field, invalid_value,
):
    _write(tmp_path, [_run("2026-11-03T10:00:00Z"), _run(**{field: invalid_value})])
    summary = load_processing_history(tmp_path)
    assert summary.state == "completed"
    assert summary.latest_completed_run.timestamp.day == 3
    assert summary.history_incomplete is True


def test_absent_legacy_optional_counters_keep_complete_history(tmp_path):
    record = _run(run_files=2)
    del record["excluded_files"]
    del record["condition_warning_files"]
    _write(tmp_path, [record])
    summary = load_processing_history(tmp_path)
    assert summary.state == "completed"
    assert summary.history_incomplete is False


def test_only_corrupt_or_non_object_history_is_unavailable(tmp_path):
    path = _write(tmp_path, [3, []])
    path.write_bytes(path.read_bytes() + b'not-json\n')
    assert load_processing_history(tmp_path).state == "unavailable"


def test_completed_record_with_unreadable_time_is_unavailable_not_unprocessed(tmp_path):
    _write(tmp_path, [_run("not-a-timestamp")])
    assert load_processing_history(tmp_path).state == "unavailable"


def test_tail_budget_skips_partial_old_line_and_keeps_exactly_fitting_new_line(tmp_path):
    path = _write(tmp_path, [{"old": "x" * 2000}, _run()])
    newest_size = len(path.read_bytes().splitlines(keepends=True)[-1])
    summary = load_processing_history(tmp_path, max_bytes=newest_size)
    assert summary.state == "completed"
    assert summary.history_incomplete is True


def test_history_outside_budget_is_unavailable_not_never_processed(tmp_path):
    _write(tmp_path, [_run()])
    assert load_processing_history(tmp_path, max_bytes=10).state == "unavailable"


def test_run_limit_skips_older_completion_without_claiming_never_processed(tmp_path):
    _write(tmp_path, [_run(), _run("2026-11-05T14:30:24Z", cancelled=True)])
    assert load_processing_history(tmp_path, max_records=1).state == "unavailable"


def test_unreadable_history_is_unavailable(tmp_path, monkeypatch):
    from Main_App.processing import processing_history

    def denied(*_args):
        raise PermissionError("locked")

    monkeypatch.setattr(processing_history, "_read_tail", denied)
    assert load_processing_history(tmp_path).state == "unavailable"


def test_linked_history_file_is_not_followed(tmp_path):
    path = _write(tmp_path, [_run()])
    linked = tmp_path / "history-hardlink"
    try:
        linked.hardlink_to(path)
    except OSError:
        pytest.skip("Host does not support hardlinks")
    assert load_processing_history(tmp_path).state == "unavailable"


@pytest.mark.parametrize("kwargs", [{"max_bytes": 0}, {"max_records": -1}, {"max_bytes": True}])
def test_invalid_limits_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError, match="positive integers"):
        load_processing_history(tmp_path, **kwargs)

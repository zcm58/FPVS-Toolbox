"""Expected QC metadata recovery must not hide unrelated implementation errors."""

from __future__ import annotations

import json
import logging

import pytest

from Main_App import io
from Main_App.processing import frequency_domain_qc, harmonic_selection_qc
from Main_App.processing.processing_ledger import ledger_path


@pytest.mark.parametrize("payload", [None, b"{broken", b"[]", b'{"entries": []}', b"\xff"])
def test_ledger_filter_preserves_legacy_missing_or_unreadable_recovery(tmp_path, payload):
    path = ledger_path(tmp_path)
    if payload is not None:
        path.parent.mkdir()
        path.write_bytes(payload)
    subjects = ["P1", "P2"]
    data = {subject: {"Faces": f"{subject}.xlsx"} for subject in subjects}

    actual_subjects, actual_data = harmonic_selection_qc._filter_to_completed_subjects(
        project_root=tmp_path, subjects=subjects, subject_data=data,
    )

    assert actual_subjects is subjects
    assert actual_data is data


def test_ledger_filter_retains_only_completed_subjects_in_original_order(tmp_path):
    path = ledger_path(tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps({"entries": {
        "p2": {"status": "completed"}, "P1": {"status": "failed"},
        "P3": {"status": "completed"},
    }}), encoding="utf-8")
    data = {subject: {"Faces": f"{subject}.xlsx"} for subject in ("P3", "P1", "P2")}

    subjects, filtered = harmonic_selection_qc._filter_to_completed_subjects(
        project_root=tmp_path, subjects=list(data), subject_data=data,
    )

    assert subjects == ["P3", "P2"]
    assert list(filtered) == subjects
    assert filtered == {subject: data[subject] for subject in subjects}


def test_ledger_io_recovery_logs_project_context(tmp_path, monkeypatch, caplog):
    error = PermissionError("ledger unavailable")

    def fail(_root):
        raise error

    monkeypatch.setattr(harmonic_selection_qc, "load_ledger", fail)
    with caplog.at_level(logging.WARNING):
        assert harmonic_selection_qc._filter_to_completed_subjects(
            project_root=tmp_path, subjects=["P1"], subject_data={},
        ) == (["P1"], {})

    record = next(row for row in caplog.records if row.msg == "harmonic_selection_processing_ledger_unreadable")
    assert record.project_root == str(tmp_path)
    assert record.exc_info[1] is error


@pytest.mark.parametrize("error", [RuntimeError("implementation failure"), TypeError("invalid call")])
def test_ledger_filter_does_not_silently_remove_completion_guard(monkeypatch, tmp_path, error):
    def fail(_root):
        raise error

    monkeypatch.setattr(harmonic_selection_qc, "load_ledger", fail)
    with pytest.raises(type(error)) as caught:
        harmonic_selection_qc._filter_to_completed_subjects(
            project_root=tmp_path, subjects=["P1"], subject_data={},
        )
    assert caught.value is error


@pytest.mark.parametrize("error", [OSError("missing workbook"), ValueError("invalid header"), RuntimeError("reader failure")])
def test_representative_header_probe_recovers_with_source_context(monkeypatch, caplog, error):
    calls = []

    def read(path, *, sheet_name):
        calls.append((path, sheet_name))
        if path == "first.xlsx":
            raise error
        return ["Electrode", "1.200_Hz", "2.400_Hz"]

    monkeypatch.setattr(io, "read_xlsx_sheet_header", read)
    with caplog.at_level(logging.DEBUG, logger=frequency_domain_qc.__name__):
        columns = frequency_domain_qc._find_first_bca_columns(
            ["P1", "P2"], ["Faces"],
            {"P1": {"Faces": "first.xlsx"}, "P2": {"Faces": "second.xlsx"}},
        )

    assert columns == ["1.200_Hz", "2.400_Hz"]
    assert calls == [("first.xlsx", "BCA (uV)"), ("second.xlsx", "BCA (uV)")]
    record = next(row for row in caplog.records if row.msg == "frequency_domain_qc_bca_header_read_failed")
    assert (record.path, record.subject, record.condition) == ("first.xlsx", "P1", "Faces")
    assert record.exc_info[1] is error

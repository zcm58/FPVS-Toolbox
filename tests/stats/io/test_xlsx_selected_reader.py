from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import Tools.Stats.io.xlsx_selected_reader as selected_reader
from Tools.Stats.io.xlsx_selected_reader import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
    xlsx_read_cache_scope,
)


def test_selected_reader_matches_pandas_for_requested_columns(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)
    columns = ["Electrode", "1.2000_Hz", "3.6000_Hz"]

    fast = read_xlsx_sheet_selected_columns(
        workbook,
        sheet_name="BCA (uV)",
        required_columns=columns,
    )
    expected = pd.read_excel(workbook, sheet_name="BCA (uV)", usecols=columns)

    pd.testing.assert_frame_equal(fast, expected, check_dtype=False)


def test_selected_reader_filters_electrodes_before_frame_build(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)

    fast = read_xlsx_sheet_selected_columns(
        workbook,
        sheet_name="FullFFT Amplitude (uV)",
        required_columns=["Electrode", "1.2000_Hz", "2.4000_Hz"],
        included_electrodes_upper={"O1", "PO8"},
    )

    assert fast["Electrode"].tolist() == ["O1", "PO8"]
    assert fast["1.2000_Hz"].tolist() == [0.22, 0.33]
    assert fast["2.4000_Hz"].tolist() == [2.0, 3.0]


def test_selected_reader_reports_missing_required_columns(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)

    with pytest.raises(MissingXlsxColumnsError) as exc_info:
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "7.2000_Hz"],
        )

    assert exc_info.value.sheet_name == "BCA (uV)"
    assert exc_info.value.missing_columns == ["7.2000_Hz"]


def test_selected_reader_can_omit_missing_optional_columns(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)

    fast = read_xlsx_sheet_selected_columns(
        workbook,
        sheet_name="BCA (uV)",
        required_columns=["Electrode", "7.2000_Hz"],
        require_all=False,
    )

    assert list(fast.columns) == ["Electrode"]
    assert fast["Electrode"].tolist() == ["Fp1", "O1", "PO8"]


def test_selected_reader_header_read_avoids_full_dataframe_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)

    def fail_read_excel(*_args, **_kwargs):
        raise AssertionError("XML reader should not call pd.read_excel")

    monkeypatch.setattr(pd, "read_excel", fail_read_excel)

    header = read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")
    fast = read_xlsx_sheet_selected_columns(
        workbook,
        sheet_name="BCA (uV)",
        required_columns=["Electrode", "1.2000_Hz"],
    )

    assert header == ["Electrode", "1.2000_Hz", "2.4000_Hz", "3.6000_Hz"]
    assert list(fast.columns) == ["Electrode", "1.2000_Hz"]


def test_run_scoped_cache_reuses_headers_and_selected_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    load_count = 0
    original_load_shared_strings = selected_reader._load_shared_strings

    def counted_load_shared_strings(archive):  # noqa: ANN001
        nonlocal load_count
        load_count += 1
        return original_load_shared_strings(archive)

    monkeypatch.setattr(
        selected_reader,
        "_load_shared_strings",
        counted_load_shared_strings,
    )
    timing_details: dict[str, float] = {}

    with xlsx_read_cache_scope():
        first_header = read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")
        second_header = read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")
        first_frame = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
            timing_details=timing_details,
        )
        second_frame = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
            timing_details=timing_details,
        )

    assert load_count == 2
    assert second_header == first_header
    pd.testing.assert_frame_equal(second_frame, first_frame)
    assert timing_details["cache_hit"] >= 0.0


def test_run_scoped_cache_returns_defensive_copies(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)

    with xlsx_read_cache_scope():
        first_header = read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")
        first_header[0] = "Mutated"
        second_header = read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")

        first_frame = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
        )
        first_frame.loc[0, "1.2000_Hz"] = 999.0
        first_frame["Injected"] = "changed"
        second_frame = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
        )

    assert second_header[0] == "Electrode"
    assert second_frame.loc[0, "1.2000_Hz"] == 0.11
    assert "Injected" not in second_frame.columns


def test_run_scoped_cache_misses_when_read_arguments_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    read_count = 0
    original_read = selected_reader._read_selected_columns_from_stream

    def counted_read(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal read_count
        read_count += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(
        selected_reader,
        "_read_selected_columns_from_stream",
        counted_read,
    )

    with xlsx_read_cache_scope():
        for _ in range(2):
            read_xlsx_sheet_selected_columns(
                workbook,
                sheet_name="BCA (uV)",
                required_columns=["Electrode", "1.2000_Hz"],
            )
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "2.4000_Hz"],
        )
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
            require_all=False,
        )
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
            included_electrodes_upper={"O1"},
        )
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="FullFFT Amplitude (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
        )

    assert read_count == 5


def test_xlsx_read_cache_is_disabled_outside_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    load_count = 0
    original_load_shared_strings = selected_reader._load_shared_strings

    def counted_load_shared_strings(archive):  # noqa: ANN001
        nonlocal load_count
        load_count += 1
        return original_load_shared_strings(archive)

    monkeypatch.setattr(
        selected_reader,
        "_load_shared_strings",
        counted_load_shared_strings,
    )
    timing_details: dict[str, float] = {}

    for _ in range(2):
        read_xlsx_sheet_header(workbook, sheet_name="BCA (uV)")
        read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
            timing_details=timing_details,
        )

    assert load_count == 4
    assert "cache_hit" not in timing_details


def test_run_scoped_cache_invalidates_changed_file_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    read_count = 0
    original_read = selected_reader._read_selected_columns_from_stream

    def counted_read(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal read_count
        read_count += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(
        selected_reader,
        "_read_selected_columns_from_stream",
        counted_read,
    )

    with xlsx_read_cache_scope():
        first = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
        )
        previous_mtime_ns = workbook.stat().st_mtime_ns
        _write_metric_workbook(tmp_path, first_bca_value=9.11)
        rewritten_stat = workbook.stat()
        os.utime(
            workbook,
            ns=(
                rewritten_stat.st_atime_ns,
                max(rewritten_stat.st_mtime_ns, previous_mtime_ns + 1_000_000_000),
            ),
        )
        second = read_xlsx_sheet_selected_columns(
            workbook,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", "1.2000_Hz"],
        )

    assert read_count == 2
    assert first.loc[0, "1.2000_Hz"] == 0.11
    assert second.loc[0, "1.2000_Hz"] == 9.11


def test_workbook_signature_detects_same_size_mtime_replacement(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "identity.xlsx"
    replacement = tmp_path / "replacement.xlsx"
    workbook.write_bytes(b"original")
    original_stat = workbook.stat()
    original_signature = selected_reader._workbook_signature_or_none(workbook)

    replacement.write_bytes(b"replaced")
    os.utime(
        replacement,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    os.replace(replacement, workbook)
    os.utime(
        workbook,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    replacement_stat = workbook.stat()
    replacement_signature = selected_reader._workbook_signature_or_none(workbook)

    assert replacement_stat.st_size == original_stat.st_size
    assert replacement_stat.st_mtime_ns == original_stat.st_mtime_ns
    assert replacement_signature != original_signature


def test_run_scoped_cache_does_not_store_a_read_changed_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    original_signature = selected_reader._workbook_signature_or_none(workbook)
    assert original_signature is not None
    changed_signature = replace(
        original_signature,
        mtime_ns=original_signature.mtime_ns + 1,
    )
    signature_calls = 0

    def changing_signature(_excel_path):  # noqa: ANN001
        nonlocal signature_calls
        signature_calls += 1
        return original_signature if signature_calls == 1 else changed_signature

    monkeypatch.setattr(
        selected_reader,
        "_workbook_signature_or_none",
        changing_signature,
    )
    read_count = 0
    original_read = selected_reader._read_selected_columns_from_stream

    def counted_read(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal read_count
        read_count += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(
        selected_reader,
        "_read_selected_columns_from_stream",
        counted_read,
    )

    with xlsx_read_cache_scope():
        for _ in range(3):
            read_xlsx_sheet_selected_columns(
                workbook,
                sheet_name="BCA (uV)",
                required_columns=["Electrode", "1.2000_Hz"],
            )

    assert read_count == 2


def _write_metric_workbook(
    tmp_path: Path,
    *,
    first_bca_value: float = 0.11,
) -> Path:
    workbook = tmp_path / "subject_results.xlsx"
    bca = pd.DataFrame(
        {
            "Electrode": ["Fp1", "O1", "PO8"],
            "1.2000_Hz": [first_bca_value, 0.22, 0.33],
            "2.4000_Hz": [1.0, 2.0, 3.0],
            "3.6000_Hz": [1.5, 2.5, 3.5],
        }
    )
    full_fft = bca.copy()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)
    return workbook

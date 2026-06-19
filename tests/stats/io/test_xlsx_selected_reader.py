from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Tools.Stats.io.xlsx_selected_reader import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
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


def _write_metric_workbook(tmp_path: Path) -> Path:
    workbook = tmp_path / "subject_results.xlsx"
    bca = pd.DataFrame(
        {
            "Electrode": ["Fp1", "O1", "PO8"],
            "1.2000_Hz": [0.11, 0.22, 0.33],
            "2.4000_Hz": [1.0, 2.0, 3.0],
            "3.6000_Hz": [1.5, 2.5, 3.5],
        }
    )
    full_fft = bca.copy()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)
    return workbook

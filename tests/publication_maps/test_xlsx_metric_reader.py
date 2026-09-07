from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np
import pytest

from Tools.Publication_Maps.xlsx_metric_reader import read_metric_sheet_selected_columns


@pytest.mark.parametrize("damage", ["spectral", "condition"])
def test_native_metric_values_and_source_companions_are_preserved_and_verified(
    tmp_path: Path, damage: str,
) -> None:
    from Main_App.Shared.post_process_excel import write_results_workbook
    from Tools.Publication_Maps.metrics import (
        _capture_workbook_identity, verify_publication_workbooks_unchanged,
    )
    from Tools.Publication_Maps.models import PublicationMapInputError, WorkbookEntry

    native = tmp_path / "P01.fpvs"
    values = np.array([-0.0, np.nextafter(1.0, 2.0)], dtype=np.float64)
    frames = {
        name: pd.DataFrame({"Electrode": ["Cz", "Pz"], "1.2000_Hz": values})
        for name in ("BCA (uV)", "SNR", "Z Score", "FullFFT Amplitude (uV)")
    }
    write_results_workbook(str(native), frames)
    entry = _capture_workbook_identity(
        WorkbookEntry(condition="Faces", subject_id="P01", path=native),
        cancel_check=None,
    )
    assert entry.spectral_companion is not None
    assert entry.condition_companion is not None
    for sheet in ("BCA (uV)", "SNR", "Z Score"):
        actual = read_metric_sheet_selected_columns(
            native, sheet_name=sheet, required_columns=["Electrode", "1.2000_Hz"],
        )
        assert actual["Electrode"].tolist() == ["Cz", "Pz"]
        np.testing.assert_array_equal(actual["1.2000_Hz"].to_numpy().view(np.uint64), values.view(np.uint64))
    verify_publication_workbooks_unchanged((entry,))
    descriptor = entry.spectral_companion if damage == "spectral" else entry.condition_companion
    companion = native.with_name(descriptor["path"])
    content = bytearray(companion.read_bytes())
    content[-1] ^= 1
    companion.write_bytes(content)
    with pytest.raises(PublicationMapInputError, match="[Cc]ompanion"):
        verify_publication_workbooks_unchanged((entry,))


def test_scalp_identity_rejects_malformed_native_source(tmp_path: Path) -> None:
    from Tools.Publication_Maps.metrics import _capture_workbook_identity
    from Tools.Publication_Maps.models import PublicationMapInputError, WorkbookEntry

    native = tmp_path / "bad.fpvs"
    native.write_text("{}", encoding="utf-8")
    with pytest.raises(PublicationMapInputError, match="FPVS result"):
        _capture_workbook_identity(
            WorkbookEntry(condition="Faces", subject_id="P01", path=native),
            cancel_check=None,
        )


def test_selected_metric_reader_matches_pandas_for_scalp_metric_sheets(
    tmp_path: Path,
) -> None:
    workbook = _write_metric_workbook(tmp_path)
    columns = ["Electrode", "1.2000_Hz", "3.6000_Hz"]

    for sheet_name in ("BCA (uV)", "SNR", "Z Score"):
        fast = read_metric_sheet_selected_columns(
            workbook,
            sheet_name=sheet_name,
            required_columns=columns,
        )
        expected = pd.read_excel(workbook, sheet_name=sheet_name, usecols=columns)

        pd.testing.assert_frame_equal(fast, expected, check_dtype=False)


def test_selected_metric_reader_omits_missing_harmonic_columns(
    tmp_path: Path,
) -> None:
    workbook = _write_metric_workbook(tmp_path)

    fast = read_metric_sheet_selected_columns(
        workbook,
        sheet_name="SNR",
        required_columns=["Electrode", "1.2000_Hz", "7.2000_Hz"],
    )

    assert list(fast.columns) == ["Electrode", "1.2000_Hz"]
    assert fast["Electrode"].tolist() == ["Fp1", "O1", "PO8"]


def test_selected_metric_reader_omits_missing_electrode_column(
    tmp_path: Path,
) -> None:
    workbook = _write_metric_workbook(tmp_path, include_electrode=False)

    fast = read_metric_sheet_selected_columns(
        workbook,
        sheet_name="BCA (uV)",
        required_columns=["Electrode", "1.2000_Hz"],
    )

    assert list(fast.columns) == ["1.2000_Hz"]
    assert fast["1.2000_Hz"].tolist() == [0.11, 0.22, 0.33]


def test_selected_metric_reader_reports_missing_sheet(tmp_path: Path) -> None:
    workbook = _write_metric_workbook(tmp_path)

    with pytest.raises(ValueError, match="Worksheet named 'Missing Sheet' not found"):
        read_metric_sheet_selected_columns(
            workbook,
            sheet_name="Missing Sheet",
            required_columns=["Electrode", "1.2000_Hz"],
        )


def test_selected_metric_reader_does_not_use_pandas_excel_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _write_metric_workbook(tmp_path)

    def fail_read_excel(*_args, **_kwargs):
        raise AssertionError("selected metric reader should not call pd.read_excel")

    monkeypatch.setattr(pd, "read_excel", fail_read_excel)

    fast = read_metric_sheet_selected_columns(
        workbook,
        sheet_name="Z Score",
        required_columns=["Electrode", "1.2000_Hz"],
    )

    assert list(fast.columns) == ["Electrode", "1.2000_Hz"]
    assert fast["Electrode"].tolist() == ["Fp1", "O1", "PO8"]


def _write_metric_workbook(
    tmp_path: Path,
    *,
    include_electrode: bool = True,
) -> Path:
    workbook = tmp_path / "subject_results.xlsx"
    base_columns: dict[str, list[object]] = {
        "Electrode": ["Fp1", "O1", "PO8"],
        "1.2000_Hz": [0.11, 0.22, 0.33],
        "2.4000_Hz": [9.0, 9.0, 9.0],
        "3.6000_Hz": [1.5, 2.5, 3.5],
        "Notes": ["ignore", "ignore", "ignore"],
    }
    if not include_electrode:
        base_columns.pop("Electrode")
    base = pd.DataFrame(base_columns)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        base.to_excel(writer, sheet_name="BCA (uV)", index=False)
        (base.copy()).to_excel(writer, sheet_name="SNR", index=False)
        (base.copy()).to_excel(writer, sheet_name="Z Score", index=False)
    return workbook

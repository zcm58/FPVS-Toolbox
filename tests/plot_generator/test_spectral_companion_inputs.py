"""Companion-backed plot reads preserve values and immutable input identity."""

from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from Main_App.io.spectral_data import (
    spectral_manifest_frame,
    write_spectral_companion,
)
from Tools.Plot_Generator.full_snr_reader import (
    XlsxWorkbookReadSession,
    _read_full_snr_sheet_read_only,
)
from Tools.Plot_Generator.source_identity import (
    SNRPublicationError,
    capture_stable_source_snapshot,
    verify_source_snapshot_after_read,
)
from Tools.Plot_Generator.spectral_qc import read_full_fft_sheet_read_only


def _spectral_workbook(path: Path) -> tuple[dict, dict[str, pd.DataFrame]]:
    frames = {
        "FullFFT Amplitude (uV)": pd.DataFrame({
            "Electrode": ["Cz", "Pz"],
            "0.0000_Hz": [0.0, 0.0],
            "1.0000_Hz": [0.125, 0.25],
            "1.2000_Hz": [0.5, 1.0],
            "2.0000_Hz": [2.0, 4.0],
        }),
        "FullSNR": pd.DataFrame({
            "Electrode": ["Cz", "Pz"],
            "1.0000_Hz": [2.125, np.nan],
            "1.2000_Hz": [4.567890123456789, 9.125],
            "2.0000_Hz": [8.25, 16.5],
        }),
    }
    descriptor = write_spectral_companion(path, frames)
    with pd.ExcelWriter(path) as writer:
        spectral_manifest_frame(descriptor).to_excel(
            writer, sheet_name="Spectral Data", index=False
        )
        for sheet in frames:
            pd.DataFrame({"Notice": ["Stored in the NumPy companion"]}).to_excel(
                writer, sheet_name=sheet, index=False
            )
        pd.DataFrame({"Electrode": ["Cz", "Pz"], "1.2000_Hz": [0.4, 0.8]}).to_excel(
            writer, sheet_name="BCA (uV)", index=False
        )
    return descriptor, frames


@pytest.mark.parametrize("sheet,reader", [
    ("FullSNR", _read_full_snr_sheet_read_only),
    ("FullFFT Amplitude (uV)", read_full_fft_sheet_read_only),
])
def test_plot_readers_select_saved_companion_values_exactly(tmp_path, sheet, reader):
    workbook = tmp_path / "P01.xlsx"
    _descriptor, frames = _spectral_workbook(workbook)
    actual, frequencies, columns = reader(
        workbook, x_min=1.0, x_max=1.2, included_electrodes_upper={"CZ"}
    )
    assert frequencies == [1.0, 1.2]
    assert columns == ["1.0000_Hz", "1.2000_Hz"]
    expected = frames[sheet].iloc[:1].loc[:, ["Electrode", *columns]]
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_captured_plot_inputs_do_not_reread_live_companion(tmp_path):
    workbook = tmp_path / "P01.xlsx"
    descriptor, frames = _spectral_workbook(workbook)
    snapshot = capture_stable_source_snapshot(workbook)
    companion = workbook.with_name(descriptor["path"])
    companion.unlink()
    with XlsxWorkbookReadSession(
        snapshot.content, spectral_sheets=snapshot.spectral_sheets
    ) as session:
        actual, _, _ = _read_full_snr_sheet_read_only(
            workbook, x_min=1, x_max=2, workbook_session=session
        )
    pd.testing.assert_frame_equal(actual, frames["FullSNR"], check_exact=True)
    with pytest.raises(SNRPublicationError, match="companion"):
        verify_source_snapshot_after_read(workbook, snapshot=snapshot)


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_declared_companion_failure_never_reads_excel_notice(tmp_path, damage):
    workbook = tmp_path / "P01.xlsx"
    descriptor, _frames = _spectral_workbook(workbook)
    companion = workbook.with_name(descriptor["path"])
    if damage == "missing":
        companion.unlink()
    else:
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        companion.write_bytes(data)
    for reader in (_read_full_snr_sheet_read_only, read_full_fft_sheet_read_only):
        with pytest.raises(ValueError, match="[Cc]ompanion"):
            reader(workbook, x_min=1, x_max=2)


def test_workbook_and_companion_remain_readable_when_project_moves(tmp_path):
    original = tmp_path / "Original"
    original.mkdir()
    descriptor, frames = _spectral_workbook(original / "P01.xlsx")
    moved = tmp_path / "Moved"
    moved.mkdir()
    for name in ("P01.xlsx", descriptor["path"]):
        shutil.move(str(original / name), str(moved / name))
    actual, _, _ = _read_full_snr_sheet_read_only(
        moved / "P01.xlsx", x_min=1, x_max=2
    )
    pd.testing.assert_frame_equal(actual, frames["FullSNR"], check_exact=True)


def test_legacy_source_adapter_reads_fullfft_companion_columns(tmp_path):
    from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
        _read_fullfft_columns,
        _read_fullfft_header,
    )

    workbook = tmp_path / "P01.xlsx"
    _descriptor, frames = _spectral_workbook(workbook)
    assert _read_fullfft_header(workbook) == list(frames["FullFFT Amplitude (uV)"].columns)
    columns = ["Electrode", "1.2000_Hz"]
    actual = _read_fullfft_columns(workbook, columns=columns)
    pd.testing.assert_frame_equal(
        actual, frames["FullFFT Amplitude (uV)"].loc[:, columns], check_exact=True
    )


def test_scalp_workbook_identity_detects_companion_tampering(tmp_path):
    from Tools.Publication_Maps.metrics import (
        _capture_workbook_identity,
        verify_publication_workbooks_unchanged,
    )
    from Tools.Publication_Maps.models import PublicationMapInputError, WorkbookEntry

    workbook = tmp_path / "P01.xlsx"
    descriptor, _frames = _spectral_workbook(workbook)
    entry = _capture_workbook_identity(
        WorkbookEntry(condition="Faces", subject_id="P01", path=workbook),
        cancel_check=None,
    )
    assert entry.spectral_companion == descriptor
    companion = workbook.with_name(descriptor["path"])
    data = bytearray(companion.read_bytes())
    data[-1] ^= 1
    companion.write_bytes(data)
    with pytest.raises(PublicationMapInputError, match="[Cc]ompanion"):
        verify_publication_workbooks_unchanged((entry,))

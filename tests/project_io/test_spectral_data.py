from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd
import pytest

from Main_App.io import (
    MissingXlsxColumnsError,
    SPECTRAL_MANIFEST_SHEET,
    SpectralDataError,
    read_spectral_sheet,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
    spectral_companion_identity,
    spectral_manifest_frame,
    validate_spectral_companion,
    write_spectral_companion,
    xlsx_read_cache_scope,
)

FFT = "FullFFT Amplitude (uV)"
SNR = "FullSNR"


def _frames() -> dict[str, pd.DataFrame]:
    bits = np.array([0x0000000000000001, 0x8000000000000000, 0x3FF0000000000001], dtype=np.uint64)
    fft = pd.DataFrame(np.tile(bits.view(np.float64), (3, 1)), columns=["0.0000_Hz", "0.5000_Hz", "1.0000_Hz"])
    fft.insert(0, "Electrode", ["Fp1", "O1", "PO8"])
    snr = pd.DataFrame({"Electrode": ["Fp1", "O1", "PO8"], "0.00": [np.nan, 1.25, np.nan], "0.01": [2.25, np.nan, 3.5]})
    return {FFT: fft, SNR: snr}


def _write(path: Path, frames=None, metadata=None) -> dict:
    descriptor = write_spectral_companion(path, frames or _frames(), metadata=metadata)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        spectral_manifest_frame(descriptor).to_excel(writer, sheet_name=SPECTRAL_MANIFEST_SHEET, index=False)
        # A physical placeholder must never be mistaken for the spectral data.
        pd.DataFrame({"Spectral data": ["Stored in companion"]}).to_excel(writer, sheet_name=FFT, index=False)
    return descriptor


def test_lossless_uncompressed_roundtrip_preserves_snr_and_exact_grid(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    frames = _frames()
    grid = np.array([0.0, np.nextafter(0.5, 1), 1.0])
    descriptor = _write(path, frames, {"frequencies_hz": grid, "sampling_frequency_hz": 2.0, "fft_sample_count": 4})

    assert spectral_companion_identity(path) == descriptor
    assert validate_spectral_companion(tmp_path / "not-yet-written.xlsx", descriptor) == descriptor
    for sheet, original in frames.items():
        actual = read_spectral_sheet(path, sheet_name=sheet)
        assert actual.columns.tolist() == original.columns.tolist()
        assert actual["Electrode"].tolist() == original["Electrode"].tolist()
        np.testing.assert_array_equal(actual.iloc[:, 1:].to_numpy().view(np.uint64), original.iloc[:, 1:].to_numpy().view(np.uint64))
    np.testing.assert_array_equal(np.asarray(read_spectral_sheet(path).attrs["spectral_metadata"]["frequencies_hz"]).view(np.uint64), grid.view(np.uint64))
    with zipfile.ZipFile(path.parent / descriptor["path"]) as archive:
        assert all(member.compress_type == zipfile.ZIP_STORED for member in archive.infolist())
    with np.load(path.parent / descriptor["path"], allow_pickle=False) as archive:
        assert all(archive[key].dtype.kind != "O" for key in archive.files)


def test_shared_reader_routes_exact_columns_and_electrode_filter(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    _write(path)
    assert read_xlsx_sheet_header(path, sheet_name=FFT) == _frames()[FFT].columns.tolist()
    result = read_xlsx_sheet_selected_columns(
        path, sheet_name=FFT, required_columns=["1.0000_Hz", "Electrode", "1.0000_Hz"],
        included_electrodes_upper={"O1"},
    )
    assert result.columns.tolist() == ["1.0000_Hz", "Electrode"]
    assert result["Electrode"].tolist() == ["O1"]
    with pytest.raises(MissingXlsxColumnsError):
        read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=["missing"])
    empty = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=["missing"], require_all=False)
    assert empty.empty and empty.columns.tolist() == []


def test_legacy_workbook_without_manifest_uses_physical_sheet(tmp_path: Path) -> None:
    path = tmp_path / "legacy.xlsx"
    original = pd.DataFrame({"Electrode": ["O1"], "1.2000_Hz": [1.25]})
    original.to_excel(path, sheet_name=FFT, index=False)
    assert spectral_companion_identity(path) is None
    assert read_xlsx_sheet_header(path, sheet_name=FFT) == original.columns.tolist()
    pd.testing.assert_frame_equal(read_spectral_sheet(path), original)


@pytest.mark.parametrize("failure", ["missing", "tampered"])
def test_declared_missing_or_changed_companion_never_falls_back(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    companion = tmp_path / descriptor["path"]
    if failure == "missing":
        companion.unlink()
    else:
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        companion.write_bytes(data)
    with pytest.raises(SpectralDataError):
        read_xlsx_sheet_header(path, sheet_name=FFT)
    with pytest.raises(SpectralDataError):
        spectral_companion_identity(path)


@pytest.mark.parametrize("unsafe", ["../escape.npz", "folder/escape.npz", "folder\\escape.npz", "/escape.npz", "C:\\escape.npz", "stream:escape.npz"])
def test_manifest_rejects_paths_outside_workbook_folder(tmp_path: Path, unsafe: str) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    descriptor["path"] = unsafe
    with pytest.raises(SpectralDataError, match="basename"):
        spectral_manifest_frame(descriptor)
    # Check the reader boundary independently of the writer's validation.
    pd.DataFrame({"Field": list(descriptor), "Value": [json.dumps(value) for value in descriptor.values()]}).to_excel(path, sheet_name=SPECTRAL_MANIFEST_SHEET, index=False)
    with pytest.raises(SpectralDataError, match="basename"):
        spectral_companion_identity(path)


def test_moving_workbook_directory_preserves_companion_resolution(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    path = original / "recording.xlsx"
    descriptor = _write(path)
    moved = tmp_path / "moved"
    shutil.move(str(original), str(moved))
    assert spectral_companion_identity(moved / path.name) == descriptor
    assert read_spectral_sheet(moved / path.name)["Electrode"].tolist() == ["Fp1", "O1", "PO8"]


def test_cache_hashes_once_and_invalidates_companion_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    calls = 0
    original_digest = hashlib.file_digest

    def counted_digest(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_digest(*args, **kwargs)

    monkeypatch.setattr(hashlib, "file_digest", counted_digest)
    with xlsx_read_cache_scope():
        spectral_companion_identity(path)
        header = read_xlsx_sheet_header(path, sheet_name=FFT)
        first = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=header)
        first.iloc[0, 1] = 99
        second = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=header)
        assert second.iloc[0, 1] != 99
        assert calls == 1
        companion = path.parent / descriptor["path"]
        replacement = tmp_path / "replacement.npz"
        previous_stat = companion.stat()
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        replacement.write_bytes(data)
        os.utime(replacement, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
        os.replace(replacement, companion)
        with pytest.raises(SpectralDataError, match="checksum"):
            spectral_companion_identity(path)
        assert calls == 2


def test_same_inputs_reuse_immutable_companion_and_changed_values_create_new_one(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    first = write_spectral_companion(path, _frames())
    repeated = write_spectral_companion(path, _frames())
    changed_frames = _frames()
    changed_frames[FFT].iloc[0, 1] = 123.0
    changed = write_spectral_companion(path, changed_frames)
    assert repeated == first
    assert changed["path"] != first["path"]
    assert (tmp_path / first["path"]).exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_512_hz_120_second_fft_exceeds_excel_width_without_losing_bins(tmp_path: Path) -> None:
    fs, samples = 512.0, 61_440
    grid = np.fft.rfftfreq(samples, 1.0 / fs)
    assert len(grid) > 16_384
    columns = [f"{frequency:.4f}_Hz" for frequency in grid]
    values = np.arange(len(grid), dtype=np.float64)[None, :]
    frame = pd.DataFrame(values, columns=columns)
    frame.insert(0, "Electrode", ["O1"])
    path = tmp_path / "wide.xlsx"
    _write(path, {FFT: frame}, {"sampling_frequency_hz": fs, "fft_sample_count": samples})
    assert len(read_xlsx_sheet_header(path, sheet_name=FFT)) == len(grid) + 1
    selected = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=["Electrode", columns[-1]])
    assert selected.iloc[0, 1] == values[0, -1]
    np.testing.assert_array_equal(selected.attrs["spectral_metadata"]["frequencies_hz"], grid)


def test_workbook_manifest_replacement_invalidates_cached_identity(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    first = _write(path)
    with xlsx_read_cache_scope():
        assert spectral_companion_identity(path) == first
        frames = _frames()
        frames[FFT].iloc[0, 1] = 9.0
        second = _write(path, frames)
        assert spectral_companion_identity(path) == second
        assert read_spectral_sheet(path).iloc[0, 1] == 9.0

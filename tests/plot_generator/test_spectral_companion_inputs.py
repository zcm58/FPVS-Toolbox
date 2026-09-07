"""Companion-backed plot reads preserve values and immutable input identity."""

from pathlib import Path
from collections import Counter
import hashlib
import os
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


def _spectral_workbook(
    path: Path, *, metadata: dict | None = None, special_values: bool = False,
) -> tuple[dict, dict[str, pd.DataFrame]]:
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
    if special_values:
        frames["FullFFT Amplitude (uV)"].iloc[0, 1] = -0.0
        frames["FullSNR"].iloc[0, 1] = np.nextafter(0.0, 1.0)
        frames["FullSNR"].iloc[1, 1] = np.asarray(
            [0x7FF8000000000042], dtype=np.uint64,
        ).view(np.float64)[0]
    descriptor = write_spectral_companion(path, frames, metadata=metadata)
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


def _add_condition_companion(workbook: Path) -> dict:
    from Main_App.io.condition_data import condition_manifest_frame, write_condition_companion

    descriptor = write_condition_companion(
        workbook, {"BCA (uV)": pd.DataFrame({"Electrode": ["Cz"], "1.2000_Hz": [0.125]})},
    )
    with pd.ExcelWriter(workbook, engine="openpyxl", mode="a") as writer:
        condition_manifest_frame(descriptor).to_excel(
            writer, sheet_name="Condition Data", index=False,
        )
    return descriptor


def test_snapshot_reuses_payload_but_keeps_two_fresh_integrity_boundaries(
    tmp_path, monkeypatch,
):
    from Main_App.io import xlsx_read_cache_scope, xlsx_selected_reader
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    workbook = tmp_path / "P01.xlsx"
    spectral, _frames = _spectral_workbook(workbook)
    condition = _add_condition_companion(workbook)
    hashes, loads = Counter(), Counter()
    original_digest, original_load = hashlib.file_digest, np.load

    def digest(stream, *args, **kwargs):
        hashes[Path(stream.name).name] += 1
        return original_digest(stream, *args, **kwargs)

    def load(stream, *args, **kwargs):
        loads[Path(stream.name).name] += 1
        return original_load(stream, *args, **kwargs)

    with xlsx_read_cache_scope():
        spectral_companion_identity(workbook)
        condition_companion_identity(workbook)
        ambient = xlsx_selected_reader._ACTIVE_XLSX_READ_CACHE.get()
        monkeypatch.setattr(hashlib, "file_digest", digest)
        monkeypatch.setattr(np, "load", load)
        snapshot = capture_stable_source_snapshot(workbook)
        assert xlsx_selected_reader._ACTIVE_XLSX_READ_CACHE.get() is ambient
        expected = Counter({spectral["path"]: 2, condition["path"]: 2})
        assert hashes == loads == expected
        assert snapshot.identity.spectral_companion == spectral
        assert snapshot.identity.condition_companion == condition
        hashes.clear()
        loads.clear()
        assert verify_source_snapshot_after_read(workbook, snapshot=snapshot) == snapshot.identity
        assert hashes == loads == Counter({spectral["path"]: 1, condition["path"]: 1})
        assert xlsx_selected_reader._ACTIVE_XLSX_READ_CACHE.get() is ambient


def test_snapshot_preserves_numeric_bits_metadata_and_detached_frames(tmp_path):
    from Main_App.io.spectral_data import read_spectral_sheet

    workbook = tmp_path / "P01.xlsx"
    metadata = {"frequencies_hz": [0.0, 1.0, 1.2, 2.0], "nested": {"labels": ["original"]}}
    _descriptor, frames = _spectral_workbook(
        workbook, metadata=metadata, special_values=True,
    )
    snapshot = capture_stable_source_snapshot(workbook)
    assert snapshot.content == workbook.read_bytes()
    assert snapshot.identity.sha256 == hashlib.sha256(snapshot.content).hexdigest()
    for name, expected in frames.items():
        actual = snapshot.spectral_sheets[name]
        assert actual.columns.tolist() == expected.columns.tolist()
        assert actual["Electrode"].tolist() == expected["Electrode"].tolist()
        np.testing.assert_array_equal(
            actual.iloc[:, 1:].to_numpy().view(np.uint64),
            expected.iloc[:, 1:].to_numpy().view(np.uint64),
        )
        assert actual.attrs == read_spectral_sheet(workbook, sheet_name=name).attrs

    snapshot.spectral_sheets["FullSNR"].iloc[0, 1] = 999.0
    snapshot.spectral_sheets["FullSNR"].attrs["spectral_metadata"]["nested"]["labels"].append("changed")
    again = capture_stable_source_snapshot(workbook)
    assert again.spectral_sheets["FullSNR"].iloc[0, 1] == np.nextafter(0.0, 1.0)
    assert again.spectral_sheets["FullSNR"].attrs["spectral_metadata"]["nested"]["labels"] == ["original"]


@pytest.mark.parametrize("companion_kind", ["spectral", "condition"])
@pytest.mark.parametrize("boundary", ["capture", "after_read"])
def test_fresh_snapshot_boundaries_reject_same_signature_corruption_with_warm_caller(
    tmp_path, monkeypatch, companion_kind, boundary,
):
    from Main_App.io import xlsx_read_cache_scope, xlsx_selected_reader
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    workbook = tmp_path / "P01.xlsx"
    spectral, _frames = _spectral_workbook(workbook)
    condition = _add_condition_companion(workbook)
    damaged = workbook.with_name((spectral if companion_kind == "spectral" else condition)["path"])
    with xlsx_read_cache_scope():
        spectral_companion_identity(workbook)
        condition_companion_identity(workbook)
        snapshot = capture_stable_source_snapshot(workbook)
        original_signature = xlsx_selected_reader._workbook_signature_or_none
        frozen_signature = original_signature(damaged)
        before = damaged.stat()
        content = bytearray(damaged.read_bytes())
        content[-1] ^= 1
        damaged.write_bytes(content)
        os.utime(damaged, ns=(before.st_atime_ns, before.st_mtime_ns))

        # Model a writer/filesystem preserving every signature field. The
        # independent boundary must use bytes, not trust the caller's cache.
        def signature(path):
            return frozen_signature if Path(path) == damaged else original_signature(path)

        monkeypatch.setattr(xlsx_selected_reader, "_workbook_signature_or_none", signature)
        with pytest.raises(SNRPublicationError, match="[Cc]ompanion"):
            if boundary == "capture":
                capture_stable_source_snapshot(workbook)
            else:
                verify_source_snapshot_after_read(workbook, snapshot=snapshot)


@pytest.mark.parametrize("companion_kind", ["spectral", "condition"])
def test_snapshot_rejects_companion_corruption_after_last_sheet_read(
    tmp_path, monkeypatch, companion_kind,
):
    from Main_App.io import spectral_data, xlsx_selected_reader

    workbook = tmp_path / "P01.xlsx"
    spectral, _frames = _spectral_workbook(workbook)
    condition = _add_condition_companion(workbook)
    damaged = workbook.with_name((spectral if companion_kind == "spectral" else condition)["path"])
    original_read = spectral_data.read_spectral_sheet
    original_signature = xlsx_selected_reader._workbook_signature_or_none
    frozen_signature = original_signature(damaged)

    def read_and_corrupt(path, *, sheet_name):
        frame = original_read(path, sheet_name=sheet_name)
        if sheet_name == "FullSNR":
            content = bytearray(damaged.read_bytes())
            content[-1] ^= 1
            damaged.write_bytes(content)
        return frame

    monkeypatch.setattr(spectral_data, "read_spectral_sheet", read_and_corrupt)
    monkeypatch.setattr(
        xlsx_selected_reader, "_workbook_signature_or_none",
        lambda path: frozen_signature if Path(path) == damaged else original_signature(path),
    )
    with pytest.raises(SNRPublicationError, match="[Cc]ompanion"):
        capture_stable_source_snapshot(workbook)


def test_native_result_snapshot_reads_captured_sheets_without_excel_archive(
    tmp_path, monkeypatch,
):
    from Main_App.Shared.post_process_excel import write_results_workbook

    _descriptor, frames = _spectral_workbook(tmp_path / "legacy.xlsx")
    native = tmp_path / "P01.fpvs"
    write_results_workbook(str(native), {
        **frames,
        "BCA (uV)": pd.DataFrame({"Electrode": ["Cz", "Pz"], "1.2000_Hz": [0.4, 0.8]}),
    })
    snapshot = capture_stable_source_snapshot(native)
    assert snapshot.identity.spectral_companion is not None
    assert snapshot.identity.condition_companion is not None
    assert snapshot.content == native.read_bytes()

    def no_archive(_session):
        raise AssertionError("Native or captured spectra must not open an Excel archive")

    monkeypatch.setattr(XlsxWorkbookReadSession, "archive", property(no_archive))
    for source, sheets in (
        (native, None), (snapshot.content, snapshot.spectral_sheets),
    ):
        with XlsxWorkbookReadSession(source, spectral_sheets=sheets) as session:
            for name, reader in (
                ("FullSNR", _read_full_snr_sheet_read_only),
                ("FullFFT Amplitude (uV)", read_full_fft_sheet_read_only),
            ):
                actual, _frequencies, columns = reader(
                    native, x_min=1.0, x_max=2.0, workbook_session=session,
                )
                pd.testing.assert_frame_equal(
                    actual, frames[name].loc[:, ["Electrode", *columns]], check_exact=True,
                )
    assert verify_source_snapshot_after_read(native, snapshot=snapshot) == snapshot.identity


def test_malformed_native_manifest_is_not_treated_as_legacy_placeholder(tmp_path):
    native = tmp_path / "broken.fpvs"
    native.write_text('{"unsupported": true}', encoding="utf-8")
    with pytest.raises(SNRPublicationError, match="missing or invalid"):
        capture_stable_source_snapshot(native)


def test_snapshot_cancellation_restores_callers_read_scope(tmp_path):
    from Main_App.io import xlsx_read_cache_scope, xlsx_selected_reader
    from Tools.Plot_Generator.source_identity import SNRPublicationCancelled

    workbook = tmp_path / "P01.xlsx"
    _spectral_workbook(workbook)
    with xlsx_read_cache_scope():
        ambient = xlsx_selected_reader._ACTIVE_XLSX_READ_CACHE.get()
        with pytest.raises(SNRPublicationCancelled):
            capture_stable_source_snapshot(workbook, cancellation_checkpoint=lambda: True)
        assert xlsx_selected_reader._ACTIVE_XLSX_READ_CACHE.get() is ambient


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

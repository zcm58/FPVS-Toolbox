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
from Main_App.io.result_manifest import write_result_manifest

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


@pytest.mark.parametrize("order", ["C", "F"])
def test_native_full_sheet_preserves_bits_column_layout_and_cache_isolation(tmp_path, order):
    bits = np.array([
        [0x0000000000000001, 0x8000000000000000, 0x7FF80000000000AB],
        [0x7FF0000000000000, 0xFFF0000000000000, 0x0000000000000000],
    ], dtype=np.uint64, order=order)
    labels = ["B", "A", "C"]
    electrodes = ["PO8", "Fp1"]
    values = bits.view(np.float64)
    source = pd.DataFrame(values, columns=labels, copy=False)
    source.insert(0, "Electrode", electrodes)
    metadata = {"details": {"units": ["uV"]}}
    path = tmp_path / "recording.fpvs"
    descriptor = write_spectral_companion(path, {FFT: source}, metadata=metadata)
    write_result_manifest(path, sheet_names=[FFT], spectral_companion=descriptor, condition_companion=None)

    # The original reader assembled contiguous columns from the verified array.
    expected = pd.DataFrame({"Electrode": electrodes, **{
        name: values[:, index].copy() for index, name in enumerate(labels)
    }})
    with xlsx_read_cache_scope():
        first = read_spectral_sheet(path)
        first.iloc[0, 0] = "mutated label"
        first.iloc[0, 1] = 99.0
        first.attrs["spectral_metadata"]["details"]["units"].append("mutated metadata")
        reread = read_spectral_sheet(path)
    pd.testing.assert_frame_equal(reread, expected, check_exact=True)
    assert reread.attrs["spectral_metadata"] == metadata
    for index, column in enumerate(labels):
        actual = reread[column].to_numpy()
        np.testing.assert_array_equal(actual.view(np.uint64), bits[:, index])
        assert actual.strides == expected[column].to_numpy().strides


@pytest.mark.parametrize("electrodes", [None, {"PO8", "FP1"}, set()])
@pytest.mark.parametrize("requested", [["C", "absent", "Electrode", "B", "C"], ["B"], ["Electrode"]])
def test_native_spectral_subset_preserves_bits_order_and_isolation(tmp_path, electrodes, requested):
    labels = ["Fp1", "O1", "PO8"]
    bits = np.array([
        [0x8000000000000000, 0x7FF80000000000AB],
        [0x7FF0000000000000, 0x0000000000000001],
        [0x7FF8000000000012, 0xFFF0000000000000],
    ], dtype=np.uint64)
    original = pd.DataFrame(bits.view(np.float64), columns=["B", "C"])
    original.insert(0, "Electrode", labels)
    path = tmp_path / "recording.fpvs"
    descriptor = write_spectral_companion(path, {FFT: original}, metadata={"units": ["uV"]})
    write_result_manifest(path, sheet_names=[FFT], spectral_companion=descriptor, condition_companion=None)
    selected = [name for name in dict.fromkeys(requested) if name in original]
    indices = [i for i, label in enumerate(labels) if electrodes is None or label.upper() in electrodes]
    expected = original.loc[indices, selected].reset_index(drop=True)

    def read():
        return read_xlsx_sheet_selected_columns(
            path, sheet_name=FFT, required_columns=requested, require_all=False,
            included_electrodes_upper=electrodes,
        )

    with xlsx_read_cache_scope():
        first = read()
        if len(first):
            for name in selected:
                first.loc[0, name] = "changed" if name == "Electrode" else 123.0
        first.attrs["spectral_metadata"]["units"].append("changed")
        actual = read()
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.attrs["spectral_metadata"]["units"] == ["uV"]
    for name in selected:
        if name != "Electrode":
            values = actual[name].to_numpy()
            np.testing.assert_array_equal(values.view(np.uint64), expected[name].to_numpy().view(np.uint64))
            assert values.flags.c_contiguous


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


@pytest.mark.parametrize("layout", ["C", "F", "strided", "mixed"])
@pytest.mark.parametrize("sheets", [[FFT], [FFT, SNR]])
def test_spectral_publication_matches_numpy_savez_byte_for_byte(tmp_path, layout, sheets):
    from io import BytesIO
    from Main_App.io.spectral_data import SPECTRAL_COMPANION_VERSION

    bits = np.resize(np.array([0x8000000000000000, 1, 0x7FF800000000003D, 0xFFF0000000000000],
                              dtype=np.uint64), (6, 10))
    values = bits.view(np.float64)
    values = values[::-2, ::2] if layout == "strided" else values[:3, :5].copy(order="F" if layout == "F" else "C")
    frames, expected = {}, {}
    for index, sheet in enumerate(sheets):
        frame = pd.DataFrame(values, columns=list("ABCDE"), copy=False)
        if layout == "mixed":
            frame["B"] = pd.array([1, None, -4], dtype="Int64")
        frame.insert(0, "Electrode", ["O1", "Fp1", "PO8"])
        frames[sheet] = frame
        expected[f"sheet{index}_columns"] = np.asarray(frame.columns.tolist(), dtype=np.str_)
        expected[f"sheet{index}_electrodes"] = np.asarray(frame["Electrode"].tolist(), dtype=np.str_)
        expected[f"sheet{index}_values"] = frame.iloc[:, 1:].to_numpy(dtype=np.float64, copy=True)
    grid = np.arange(10, dtype=np.float64)[::2]
    expected["fullfft_frequencies_hz"] = grid
    expected["metadata_json"] = np.asarray(json.dumps({
        "version": SPECTRAL_COMPANION_VERSION, "sheets": sheets, "metadata": {"units": "µV"},
        "has_exact_fullfft_frequencies": True,
    }, sort_keys=True, separators=(",", ":")), dtype=np.str_)
    reference = BytesIO()
    np.savez(reference, **expected)

    descriptor = write_spectral_companion(tmp_path / "recording.fpvs", frames, metadata={"units": "µV", "frequencies_hz": grid})
    assert (tmp_path / descriptor["path"]).read_bytes() == reference.getvalue()
    assert descriptor["sha256"] == hashlib.sha256(reference.getvalue()).hexdigest()


@pytest.mark.parametrize("failure", ["new_temp", "write_member", "close_archive", "invalid_path"])
@pytest.mark.parametrize("invalid", [None, "second_sheet", "grid"])
def test_spectral_write_failure_cleans_up_and_preserves_input_error_priority(tmp_path, monkeypatch, failure, invalid):
    from Main_App.io import spectral_data

    target = tmp_path / "recording.fpvs"
    frames = _frames()
    first = write_spectral_companion(target, frames)
    prior = tmp_path / first["path"]
    if invalid == "second_sheet":
        frames[SNR].iloc[0, 0] = ""
    metadata = {"frequencies_hz": [1]} if invalid == "grid" else {}

    def fail(*args, **kwargs):
        raise OSError("spectral publication interrupted")

    if failure == "new_temp":
        monkeypatch.setattr(spectral_data.tempfile, "NamedTemporaryFile", fail)
    elif failure == "write_member":
        monkeypatch.setattr(np.lib.format, "write_array", fail)
    elif failure == "close_archive":
        monkeypatch.setattr(zipfile.ZipFile, "_write_end_record", fail)
    else:
        target = tmp_path / "invalid\x00name.fpvs"
    error, message = {
        None: (ValueError, "null") if failure == "invalid_path" else (OSError, "spectral publication interrupted"),
        "second_sheet": (SpectralDataError, "FullSNR electrode labels must be nonempty and unique"),
        "grid": (SpectralDataError, "Exact FullFFT frequencies do not match its spectral columns"),
    }[invalid]
    with pytest.raises(error, match=message) as caught:
        write_spectral_companion(target, frames, metadata=metadata)
    if invalid:
        assert caught.value.__context__ is None

    assert list(tmp_path.iterdir()) == [prior]
    assert hashlib.sha256(prior.read_bytes()).hexdigest() == first["sha256"]


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


def test_verified_headers_survive_dense_eviction_without_reloading_arrays(tmp_path, monkeypatch):
    from Main_App.io import spectral_data, xlsx_selected_reader as xlsx

    paths = [tmp_path / f"recording{index}.xlsx" for index in range(6)]
    descriptors = [_write(path) for path in paths]
    original_load = np.load
    with xlsx_read_cache_scope():
        for path, descriptor in zip(paths, descriptors, strict=True):
            assert spectral_companion_identity(path) == descriptor
        cache = xlsx._ACTIVE_XLSX_READ_CACHE.get()
        assert len(cache.spectral_payloads) == 4
        headers = list(cache.spectral_verified_headers.values())
        assert headers[0][FFT] is headers[-1][FFT]

        def unexpected_load(*args, **kwargs):
            pytest.fail("Verified identity/header reloaded dense arrays after eviction")

        monkeypatch.setattr(spectral_data.np, "load", unexpected_load)
        for path, descriptor in zip(paths, descriptors, strict=True):
            assert spectral_companion_identity(path) == descriptor
            header = read_xlsx_sheet_header(path, sheet_name=FFT)
            assert header == _frames()[FFT].columns.tolist()
            header[0] = "caller mutation"
        monkeypatch.setattr(spectral_data.np, "load", original_load)
        actual = read_spectral_sheet(paths[0])
        np.testing.assert_array_equal(
            actual.iloc[:, 1:].to_numpy().view(np.uint64),
            _frames()[FFT].iloc[:, 1:].to_numpy().view(np.uint64),
        )


@pytest.mark.parametrize("mode", ["buffered", "above_limit", "memory_pressure", "buffer_view_failure"])
def test_npz_validation_reads_small_archive_once_with_streaming_fallbacks(tmp_path, monkeypatch, mode):
    from Main_App.io import numpy_companion

    path = tmp_path / "result.npz"
    bits = np.array([0x8000000000000000, 0x7FF8000000000001], dtype=np.uint64)
    np.savez(path, values=bits.view(np.float64))
    size = path.stat().st_size
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(numpy_companion, "_MAX_BUFFER_BYTES", size - 1 if mode == "above_limit" else size)
    if mode == "memory_pressure":
        def allocation_failed(*_args):
            raise MemoryError

        monkeypatch.setattr(numpy_companion, "BytesIO", allocation_failed)
    elif mode == "buffer_view_failure":
        class FailingView(numpy_companion.BytesIO):
            def getbuffer(self):
                raise MemoryError

        monkeypatch.setattr(numpy_companion, "BytesIO", FailingView)

    class ObservedFile:
        def __init__(self, stream):
            self.stream = stream
            self.bytes_read = 0

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, *args):
            chunk = self.stream.read(*args)
            self.bytes_read += len(chunk)
            return chunk

        def readinto(self, target):
            count = self.stream.readinto(target)
            self.bytes_read += count
            return count

    with path.open("rb") as stream:
        observed = ObservedFile(stream)
        with numpy_companion.open_verified_npz(observed, size, expected, ValueError("checksum")) as archive:
            np.testing.assert_array_equal(archive["values"].view(np.uint64), bits)
        if mode == "buffered":
            assert observed.bytes_read == size
        else:
            assert observed.bytes_read > size
        stream.seek(0)
        with pytest.raises(ValueError, match="checksum"), numpy_companion.open_verified_npz(
            stream, size, "0" * 64, ValueError("checksum"),
        ):
            pytest.fail("An archive with a wrong checksum reached a consumer")


def test_evicted_numeric_read_rehashes_valid_inplace_archive_with_identical_signature(tmp_path, monkeypatch):
    """Windows creation-time stats cannot certify new body reads after eviction."""
    from Main_App.io import xlsx_selected_reader as xlsx

    paths = [tmp_path / f"recording{index}.xlsx" for index in range(6)]
    descriptors = [_write(path) for path in paths]
    companion = tmp_path / descriptors[0]["path"]
    before = companion.stat()
    frozen_signature = xlsx._workbook_signature_or_none(companion)
    original_signature = xlsx._workbook_signature_or_none
    digest_calls = []
    original_digest = hashlib.file_digest

    def counted_digest(stream, *args, **kwargs):
        digest = original_digest(stream, *args, **kwargs)
        digest_calls.append(digest.hexdigest())
        return digest

    monkeypatch.setattr(hashlib, "file_digest", counted_digest)
    with xlsx_read_cache_scope():
        for path in paths:
            spectral_companion_identity(path)
        cache = xlsx._ACTIVE_XLSX_READ_CACHE.get()
        assert len(cache.spectral_payloads) == 4
        assert len(cache.spectral_verified_headers) == 6
        assert len(digest_calls) == 6

        with np.load(companion, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
        arrays["sheet0_values"].view(np.uint64)[0, 0] ^= np.uint64(1)
        replacement = tmp_path / "changed.npz"
        np.savez(replacement, **arrays)
        changed_bytes = replacement.read_bytes()
        assert len(changed_bytes) == before.st_size
        with companion.open("r+b") as stream:
            stream.write(changed_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.utime(companion, ns=(before.st_atime_ns, before.st_mtime_ns))
        with zipfile.ZipFile(companion) as archive:
            assert archive.testzip() is None  # Valid CRC/schema cannot replace SHA validation.

        # Model Windows st_ctime-as-creation-time on every test platform. The
        # real NTFS signature also stayed identical in local characterization.
        monkeypatch.setattr(
            xlsx, "_workbook_signature_or_none",
            lambda path: frozen_signature if Path(path).resolve() == companion.resolve()
            else original_signature(path),
        )
        assert spectral_companion_identity(paths[0]) == descriptors[0]
        with pytest.raises(SpectralDataError, match="checksum"):
            read_xlsx_sheet_selected_columns(
                paths[0], sheet_name=FFT, required_columns=["Electrode", "0.0000_Hz"],
            )
        assert len(digest_calls) == 7
        assert digest_calls[-1] == hashlib.sha256(changed_bytes).hexdigest()


def test_evicted_spectral_verification_rejects_changed_companion_and_is_bounded(tmp_path, monkeypatch):
    from Main_App.io import spectral_data, xlsx_selected_reader as xlsx

    monkeypatch.setattr(spectral_data, "_MAX_CACHED_VERIFICATIONS", 5)
    paths = [tmp_path / f"recording{index}.xlsx" for index in range(6)]
    descriptors = [_write(path) for path in paths]
    with xlsx_read_cache_scope():
        for path in paths:
            spectral_companion_identity(path)
        cache = xlsx._ACTIVE_XLSX_READ_CACHE.get()
        assert len(cache.spectral_verified_headers) == 5
        # The second workbook retains metadata but has no dense payload.
        companion = tmp_path / descriptors[1]["path"]
        previous = companion.stat()
        replacement = tmp_path / "changed.npz"
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        replacement.write_bytes(data)
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        os.replace(replacement, companion)
        with pytest.raises(SpectralDataError, match="checksum"):
            read_xlsx_sheet_header(paths[1], sheet_name=FFT)


def test_cohort_header_pass_reuses_checks_after_dense_payload_eviction(tmp_path, monkeypatch):
    first = tmp_path / "first.fpvs"
    frames = _frames()
    descriptor = write_spectral_companion(first, frames)
    write_result_manifest(first, sheet_names=list(frames), spectral_companion=descriptor, condition_companion=None)
    paths = [first, *(tmp_path / f"recording-{index}.fpvs" for index in range(399))]
    declaration = first.read_bytes()
    for path in paths[1:]:
        path.write_bytes(declaration)

    digest_count = 0
    file_digest = hashlib.file_digest

    def counted_digest(stream, *args, **kwargs):
        nonlocal digest_count
        digest_count += 1
        return file_digest(stream, *args, **kwargs)

    monkeypatch.setattr(hashlib, "file_digest", counted_digest)
    with xlsx_read_cache_scope():
        for path in paths:
            assert spectral_companion_identity(path) == descriptor
        for path in paths:
            assert read_xlsx_sheet_header(path, sheet_name=FFT) == frames[FFT].columns.tolist()
    assert digest_count == len(paths)


def test_verified_header_budget_counts_shared_grids_once_and_limits_distinct_grids(tmp_path, monkeypatch):
    from Main_App.io import spectral_data, xlsx_selected_reader as xlsx

    monkeypatch.setattr(spectral_data, "_MAX_CACHED_HEADER_LABELS", 8)
    shared_paths = [tmp_path / f"shared{index}.xlsx" for index in range(3)]
    for path in shared_paths:
        _write(path)
    with xlsx_read_cache_scope():
        for path in shared_paths:
            spectral_companion_identity(path)
        cache = xlsx._ACTIVE_XLSX_READ_CACHE.get()
        assert len(cache.spectral_verified_headers) == 3  # 4 FFT + 3 SNR labels
        changed = _frames()
        changed[FFT] = changed[FFT].rename(columns={"1.0000_Hz": "1.1000_Hz"})
        different = tmp_path / "different.xlsx"
        descriptor = _write(different, changed)
        assert spectral_companion_identity(different) == descriptor
        assert len(cache.spectral_verified_headers) == 1
        monkeypatch.setattr(spectral_data, "_MAX_CACHED_HEADER_LABELS", 1)
        oversized = tmp_path / "oversized.xlsx"
        descriptor = _write(oversized)
        assert spectral_companion_identity(oversized) == descriptor
        assert not cache.spectral_verified_headers
        assert read_xlsx_sheet_header(oversized, sheet_name=FFT) == _frames()[FFT].columns.tolist()


def test_metadata_and_selected_reads_load_only_requested_dense_sheet(tmp_path, monkeypatch):
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path, metadata={"frequencies_hz": [0.0, 0.5, 1.0]})
    loaded = []
    archive_type = np.lib.npyio.NpzFile
    original = archive_type.__getitem__

    def track_values(archive, key):
        if key.endswith("_values"):
            loaded.append(key)
        return original(archive, key)

    monkeypatch.setattr(archive_type, "__getitem__", track_values)
    with xlsx_read_cache_scope():
        assert spectral_companion_identity(path) == descriptor
        assert validate_spectral_companion(path, descriptor) == descriptor
        assert read_xlsx_sheet_header(path, sheet_name=FFT) == _frames()[FFT].columns.tolist()
        electrodes = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=["Electrode"])
        assert electrodes["Electrode"].tolist() == ["Fp1", "O1", "PO8"]
        assert loaded == []
        selected = read_xlsx_sheet_selected_columns(path, sheet_name=FFT, required_columns=["1.0000_Hz"])
        np.testing.assert_array_equal(
            selected.to_numpy().view(np.uint64),
            _frames()[FFT][["1.0000_Hz"]].to_numpy().view(np.uint64),
        )
        assert loaded == ["sheet0_values"]
        read_spectral_sheet(path, sheet_name=FFT)
        assert loaded == ["sheet0_values"]
        read_spectral_sheet(path, sheet_name=SNR)
        assert loaded == ["sheet0_values", "sheet1_values"]


@pytest.mark.parametrize(
    "failure", ["wrong_shape", "wrong_dtype", "truncated", "duplicate_column", "duplicate_electrode"],
)
def test_header_read_rejects_invalid_unrequested_spectral_sheet(tmp_path, failure):
    import io

    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    companion = path.parent / descriptor["path"]
    with zipfile.ZipFile(companion) as source:
        members = {name: source.read(name) for name in source.namelist()}
    key = "sheet1_values.npy"
    if failure == "truncated":
        members[key] = members[key][:-8]
    else:
        if failure == "duplicate_column":
            key, array = "sheet1_columns.npy", np.asarray(["Electrode", "Aµ", "Aµ"])
        elif failure == "duplicate_electrode":
            key, array = "sheet1_electrodes.npy", np.asarray(["Fp1", "Ó1", "Ó1"])
        else:
            array = np.zeros(
                (1, 2) if failure == "wrong_shape" else (3, 2),
                dtype=np.float32 if failure == "wrong_dtype" else np.float64,
            )
        buffer = io.BytesIO()
        np.save(buffer, array)
        members[key] = buffer.getvalue()
    with zipfile.ZipFile(companion, "w", compression=zipfile.ZIP_STORED) as target:
        for name, data in members.items():
            target.writestr(name, data)
    descriptor["size_bytes"] = companion.stat().st_size
    descriptor["sha256"] = hashlib.sha256(companion.read_bytes()).hexdigest()
    spectral_manifest_frame(descriptor).to_excel(path, sheet_name=SPECTRAL_MANIFEST_SHEET, index=False)
    with pytest.raises(SpectralDataError):
        read_xlsx_sheet_header(path, sheet_name=FFT)

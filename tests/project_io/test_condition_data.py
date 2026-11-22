from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import zipfile

import numpy as np
import pandas as pd
import pytest

from Main_App.io import (
    CONDITION_MANIFEST_SHEET,
    ConditionDataError,
    MissingXlsxColumnsError,
    condition_companion_identity,
    condition_manifest_frame,
    declared_condition_companion,
    read_condition_sheet,
    read_condition_sheet_header,
    read_condition_sheet_selected_columns,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
    validate_condition_companion,
    write_condition_companion,
    xlsx_read_cache_scope,
)
from Main_App.io.result_manifest import write_result_manifest

BCA = "BCA (uV)"
ELIGIBILITY = "Spectral Eligibility"


def _frames() -> dict[str, pd.DataFrame]:
    bits = np.array([0x0000000000000001, 0x8000000000000000, 0x7FF8000000000001], dtype=np.uint64)
    values = pd.DataFrame(np.tile(bits.view(np.float64), (3, 1)), columns=["1.2000_Hz", "2.4000_Hz", "3.6000_Hz"])
    values.insert(0, "Electrode", ["Fp1", "O1", "PO8"])
    eligibility = pd.DataFrame({
        "frequency_hz": [1.2, 2.4, 3.6],
        "eligible": [True, False, True],
        "exact_samples": np.array([2**53 + 1, 2**53 + 3, 2**53 + 5], dtype=np.int64),
        "reason": pd.Series(["NA", "001", None], dtype=object),
        "mixed": pd.Series([True, 1.25, "1.25"], dtype=object),
        "missing": pd.Series([pd.NA, np.nan, None], dtype=object),
        "nullable": pd.Series([1, pd.NA, 3], dtype="Int64"),
    })
    return {BCA: values, ELIGIBILITY: eligibility}


def _write(path: Path, frames=None) -> dict:
    descriptor = write_condition_companion(path, _frames() if frames is None else frames)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        condition_manifest_frame(descriptor).to_excel(writer, sheet_name=CONDITION_MANIFEST_SHEET, index=False)
        pd.DataFrame({"Condition data": ["Stored in companion"]}).to_excel(writer, sheet_name=BCA, index=False)
        pd.DataFrame({"Note": ["legacy report"]}).to_excel(writer, sheet_name="Report", index=False)
    return descriptor


def test_lossless_uncompressed_metrics_and_mixed_metadata(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    frames = _frames()
    descriptor = _write(path, frames)
    assert condition_companion_identity(path) == descriptor
    assert validate_condition_companion(tmp_path / "not-yet-written.xlsx", descriptor) == descriptor
    for sheet, original in frames.items():
        actual = read_condition_sheet(path, sheet_name=sheet)
        pd.testing.assert_frame_equal(actual, original)
    actual = read_condition_sheet(path, sheet_name=BCA)
    np.testing.assert_array_equal(actual.iloc[:, 1:].to_numpy().view(np.uint64), frames[BCA].iloc[:, 1:].to_numpy().view(np.uint64))
    mixed = read_condition_sheet(path, sheet_name=ELIGIBILITY)
    assert mixed.loc[0, "missing"] is pd.NA
    assert np.isnan(mixed.loc[1, "missing"])
    assert mixed.loc[2, "missing"] is None
    with zipfile.ZipFile(tmp_path / descriptor["path"]) as archive:
        assert all(member.compress_type == zipfile.ZIP_STORED for member in archive.infolist())
    with np.load(tmp_path / descriptor["path"], allow_pickle=False) as archive:
        assert all(archive[key].dtype.kind != "O" for key in archive.files)
        # All harmonic columns are one native array, avoiding per-column ZIP I/O.
        assert archive["sheet0_block1"].shape == (3, 3)


def test_shared_reader_routes_selection_and_preserves_column_order(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    _write(path)
    assert read_xlsx_sheet_header(path, sheet_name=BCA) == _frames()[BCA].columns.tolist()
    selected = read_xlsx_sheet_selected_columns(
        path, sheet_name=BCA, required_columns=["3.6000_Hz", "Electrode", "3.6000_Hz"],
        included_electrodes_upper={"O1"},
    )
    assert selected.columns.tolist() == ["3.6000_Hz", "Electrode"]
    assert selected["Electrode"].tolist() == ["O1"]
    with pytest.raises(MissingXlsxColumnsError):
        read_condition_sheet_selected_columns(path, sheet_name=BCA, required_columns=["missing"])
    omitted = read_condition_sheet_selected_columns(path, sheet_name=BCA, required_columns=["missing"], require_all=False)
    assert omitted.empty and omitted.columns.tolist() == []
    with pytest.raises(MissingXlsxColumnsError):
        read_condition_sheet_selected_columns(path, sheet_name=ELIGIBILITY, required_columns=["eligible"], included_electrodes_upper={"O1"})


@pytest.mark.parametrize("included", [None, {"FP1", "PO8"}, set()])
def test_native_selected_columns_are_exact_and_detached(tmp_path: Path, included) -> None:
    path = tmp_path / "recording.fpvs"
    source = _frames()[BCA].assign(
        Electrode=pd.Series([" Fp1 ", "O1", "PO8"], dtype="string"),
        nullable=pd.Series([1, pd.NA, 3], dtype="Int64"),
    )
    descriptor = write_condition_companion(path, {BCA: source})
    write_result_manifest(path, sheet_names=[BCA], spectral_companion=None, condition_companion=descriptor)
    columns = ["3.6000_Hz", "nullable", "2.4000_Hz"]
    expected = source[columns] if included is None else source.loc[
        source["Electrode"].str.upper().str.strip().isin(included), columns
    ].reset_index(drop=True)

    with xlsx_read_cache_scope():
        for _ in range(2):
            result = read_xlsx_sheet_selected_columns(
                path, sheet_name=BCA, required_columns=columns, included_electrodes_upper=included,
            )
            pd.testing.assert_frame_equal(result, expected, check_exact=True)
            for column in ("3.6000_Hz", "2.4000_Hz"):
                np.testing.assert_array_equal(
                    result[column].to_numpy().view(np.uint64), expected[column].to_numpy().view(np.uint64),
                )
            if len(result):
                result.loc[0, "nullable"] = 99
                result.loc[0, "3.6000_Hz"] = 99

        pd.testing.assert_frame_equal(read_condition_sheet(path, sheet_name=BCA), source, check_exact=True)


def test_legacy_and_undeclared_sheets_retain_excel_fallback(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.xlsx"
    frame = pd.DataFrame({"Electrode": ["O1"], "1.2000_Hz": [1.25]})
    frame.to_excel(legacy, sheet_name=BCA, index=False)
    assert condition_companion_identity(legacy) is None
    pd.testing.assert_frame_equal(read_condition_sheet(legacy, sheet_name=BCA), frame)
    pd.testing.assert_frame_equal(read_condition_sheet_selected_columns(legacy, sheet_name=BCA, required_columns=list(frame)), frame)
    assert read_condition_sheet_header(legacy, sheet_name=BCA) == list(frame)
    path = tmp_path / "current.xlsx"
    _write(path)
    assert read_condition_sheet(path, sheet_name="Report")["Note"].tolist() == ["legacy report"]


@pytest.mark.parametrize("failure", ["missing", "tampered"])
def test_declared_invalid_companion_never_reads_placeholder(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    companion = tmp_path / descriptor["path"]
    if failure == "missing":
        companion.unlink()
    else:
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        companion.write_bytes(data)
    assert declared_condition_companion(path) == descriptor
    for reader in (read_condition_sheet, read_condition_sheet_header):
        with pytest.raises(ConditionDataError):
            reader(path, sheet_name=BCA)
    with pytest.raises(ConditionDataError):
        condition_companion_identity(path)


@pytest.mark.parametrize("unsafe", ["../escape.npz", "folder/escape.npz", "folder\\escape.npz", "/escape.npz", "C:\\escape.npz", "stream:escape.npz"])
def test_manifest_rejects_unsafe_companion_paths(tmp_path: Path, unsafe: str) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    descriptor["path"] = unsafe
    with pytest.raises(ConditionDataError, match="basename"):
        condition_manifest_frame(descriptor)
    pd.DataFrame({"Field": list(descriptor), "Value": [json.dumps(value) for value in descriptor.values()]}).to_excel(path, sheet_name=CONDITION_MANIFEST_SHEET, index=False)
    with pytest.raises(ConditionDataError, match="basename"):
        declared_condition_companion(path)


def test_project_move_preserves_resolution(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    path = original / "recording.xlsx"
    descriptor = _write(path)
    moved = tmp_path / "moved"
    shutil.move(str(original), str(moved))
    assert condition_companion_identity(moved / path.name) == descriptor
    pd.testing.assert_frame_equal(read_condition_sheet(moved / path.name, sheet_name=BCA), _frames()[BCA])


def test_cache_hashes_once_and_detects_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        condition_companion_identity(path)
        first = read_condition_sheet(path, sheet_name=BCA)
        first.iloc[0, 1] = 99
        assert read_condition_sheet(path, sheet_name=BCA).iloc[0, 1] != 99
        read_condition_sheet_selected_columns(path, sheet_name=ELIGIBILITY, required_columns=["reason"])
        assert calls == 1
        companion = tmp_path / descriptor["path"]
        replacement = tmp_path / "replacement.npz"
        previous_stat = companion.stat()
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        replacement.write_bytes(data)
        os.utime(replacement, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
        os.replace(replacement, companion)
        with pytest.raises(ConditionDataError, match="checksum"):
            condition_companion_identity(path)
        assert calls == 2


def test_cache_is_bounded_and_workbook_replacement_invalidates_identity(tmp_path: Path) -> None:
    from Main_App.io import xlsx_selected_reader as xlsx

    path = tmp_path / "recording.xlsx"
    first = _write(path)
    with xlsx_read_cache_scope():
        assert condition_companion_identity(path) == first
        changed = _frames()
        changed[BCA].iloc[0, 1] = 9.0
        second = _write(path, changed)
        assert condition_companion_identity(path) == second
        assert read_condition_sheet(path, sheet_name=BCA).iloc[0, 1] == 9.0
        for index in range(6):
            other = tmp_path / f"recording{index}.xlsx"
            _write(other)
            condition_companion_identity(other)
        assert len(xlsx._ACTIVE_XLSX_READ_CACHE.get().condition_payloads) == 4


def test_verified_condition_schema_survives_payload_eviction_and_preserves_values(tmp_path, monkeypatch):
    from Main_App.io import condition_data, xlsx_selected_reader as xlsx

    paths = [tmp_path / f"recording{index}.xlsx" for index in range(6)]
    descriptors = [_write(path) for path in paths]
    with xlsx_read_cache_scope():
        for path, descriptor in zip(paths, descriptors, strict=True):
            assert condition_companion_identity(path) == descriptor
        assert len(xlsx._ACTIVE_XLSX_READ_CACHE.get().condition_payloads) == 4

        def unexpected_schema(*args, **kwargs):
            pytest.fail("Unchanged verified condition schema was revalidated after eviction")

        monkeypatch.setattr(condition_data, "_archive_schema", unexpected_schema)
        for path, descriptor in zip(paths, descriptors, strict=True):
            assert condition_companion_identity(path) == descriptor
            assert read_condition_sheet_header(path, sheet_name=BCA) == _frames()[BCA].columns.tolist()
            actual = read_condition_sheet(path, sheet_name=BCA)
            np.testing.assert_array_equal(
                actual.iloc[:, 1:].to_numpy().view(np.uint64),
                _frames()[BCA].iloc[:, 1:].to_numpy().view(np.uint64),
            )
            pd.testing.assert_frame_equal(read_condition_sheet(path, sheet_name=ELIGIBILITY), _frames()[ELIGIBILITY])


def test_evicted_condition_verification_rejects_changed_companion_and_is_bounded(tmp_path, monkeypatch):
    from Main_App.io import condition_data, xlsx_selected_reader as xlsx

    monkeypatch.setattr(condition_data, "_MAX_CACHED_VERIFICATIONS", 5)
    paths = [tmp_path / f"recording{index}.xlsx" for index in range(6)]
    descriptors = [_write(path) for path in paths]
    with xlsx_read_cache_scope():
        for path in paths:
            condition_companion_identity(path)
        assert len(xlsx._ACTIVE_XLSX_READ_CACHE.get().condition_verified_schemas) == 5
        companion = tmp_path / descriptors[1]["path"]
        previous = companion.stat()
        replacement = tmp_path / "changed.npz"
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        replacement.write_bytes(data)
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        os.replace(replacement, companion)
        with pytest.raises(ConditionDataError, match="checksum"):
            condition_companion_identity(paths[1])


def test_immutable_companions_reused_and_failed_write_cleans_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "recording.xlsx"
    first = write_condition_companion(path, _frames())
    assert write_condition_companion(path, _frames()) == first
    changed = _frames()
    changed[BCA].iloc[0, 1] = 2.5
    second = write_condition_companion(path, changed)
    assert first["path"] != second["path"]
    assert (tmp_path / first["path"]).exists()

    def denied(*args, **kwargs):
        raise PermissionError("simulated write denied")

    monkeypatch.setattr(np, "savez", denied)
    with pytest.raises(PermissionError, match="denied"):
        write_condition_companion(path, changed)
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_sheet_keeps_headers_and_dtypes(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    frame = _frames()[ELIGIBILITY].iloc[:0]
    _write(path, {ELIGIBILITY: frame})
    pd.testing.assert_frame_equal(read_condition_sheet(path, sheet_name=ELIGIBILITY), frame)
    assert read_condition_sheet_header(path, sheet_name=ELIGIBILITY) == list(frame)


@pytest.mark.parametrize("damage", ["shape", "dtype", "missing_array", "extra_array", "sheet_identity", "duplicate_mapping"])
def test_valid_checksum_cannot_hide_invalid_archive_schema(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    companion = tmp_path / descriptor["path"]
    with np.load(companion, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    if damage == "shape":
        arrays["sheet0_block1"] = arrays["sheet0_block1"][:-1]
    elif damage == "dtype":
        arrays["sheet0_block1"] = np.ones((3, 3), dtype=np.int64)
    elif damage == "missing_array":
        del arrays["sheet0_block1"]
    elif damage == "extra_array":
        arrays["surprise"] = np.array([1])
    else:
        metadata = json.loads(arrays["metadata_json"].item())
        if damage == "sheet_identity":
            metadata["sheets"][0]["name"] = "SNR"
        else:
            metadata["sheets"][0]["encodings"][2]["column"] = 0
        arrays["metadata_json"] = np.asarray(json.dumps(metadata))
    np.savez(companion, **arrays)
    descriptor["size_bytes"] = companion.stat().st_size
    descriptor["sha256"] = hashlib.sha256(companion.read_bytes()).hexdigest()
    condition_manifest_frame(descriptor).to_excel(path, sheet_name=CONDITION_MANIFEST_SHEET, index=False)
    with pytest.raises(ConditionDataError):
        condition_companion_identity(path)


def test_numerical_reads_never_open_dense_spectral_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from Main_App.io import spectral_data

    path = tmp_path / "recording.xlsx"
    _write(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("compact reads must not load FullFFT")

    monkeypatch.setattr(spectral_data, "_companion_payload", forbidden)
    pd.testing.assert_frame_equal(read_condition_sheet(path, sheet_name=BCA), _frames()[BCA])


def test_identity_and_selected_metrics_do_not_decode_unrelated_audit_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "recording.xlsx"
    _write(path)
    opened = []
    original_getitem = np.lib.npyio.NpzFile.__getitem__

    def tracked(archive, key):
        opened.append(key)
        return original_getitem(archive, key)

    monkeypatch.setattr(np.lib.npyio.NpzFile, "__getitem__", tracked)
    with xlsx_read_cache_scope():
        condition_companion_identity(path)
        read_condition_sheet_header(path, sheet_name=ELIGIBILITY)
        assert opened == ["metadata_json"]
        read_condition_sheet_selected_columns(path, sheet_name=BCA, required_columns=["1.2000_Hz"])
        assert opened == ["metadata_json", "sheet0_block1"]
        read_condition_sheet_selected_columns(path, sheet_name=BCA, required_columns=["1.2000_Hz"])
        assert opened == ["metadata_json", "sheet0_block1"]


def test_unsupported_objects_and_duplicate_columns_fail_before_publish(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    with pytest.raises(ConditionDataError, match="Unsupported"):
        write_condition_companion(path, {ELIGIBILITY: pd.DataFrame({"value": [[1, 2]]})})
    with pytest.raises(ConditionDataError, match="unique"):
        write_condition_companion(path, {BCA: pd.DataFrame([[1, 2]], columns=["same", "same"])})
    assert not list(tmp_path.iterdir())


def test_typed_mixed_cells_reject_invalid_serialization_at_read_and_full_validation(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    descriptor = _write(path)
    companion = tmp_path / descriptor["path"]
    with np.load(companion, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    arrays["sheet0_dictionary0"] = np.asarray(["untyped text", "untyped text", "untyped text"])
    np.savez(companion, **arrays)
    descriptor["size_bytes"] = companion.stat().st_size
    descriptor["sha256"] = hashlib.sha256(companion.read_bytes()).hexdigest()
    condition_manifest_frame(descriptor).to_excel(path, sheet_name=CONDITION_MANIFEST_SHEET, index=False)
    # Identity inspects typed schemas without interpreting every audit cell.
    assert condition_companion_identity(path) == descriptor
    with pytest.raises(ConditionDataError):
        read_condition_sheet(path, sheet_name=BCA)
    with pytest.raises(ConditionDataError):
        validate_condition_companion(path, descriptor)


def test_repeated_mixed_cells_use_uncompressed_dictionary_without_type_coalescing(tmp_path: Path) -> None:
    path = tmp_path / "recording.xlsx"
    frame = pd.DataFrame({"Value": pd.Series([True, 1, "1", 1.0, None, np.nan, pd.NA] * 1000, dtype=object)})
    descriptor = _write(path, {ELIGIBILITY: frame})
    actual = read_condition_sheet(path, sheet_name=ELIGIBILITY)
    pd.testing.assert_frame_equal(actual, frame)
    assert [type(value) for value in actual["Value"].iloc[:4]] == [bool, int, str, float]
    with np.load(tmp_path / descriptor["path"], allow_pickle=False) as archive:
        assert archive["sheet0_dictionary0"].shape == (7,)
        assert archive["sheet0_block0"].shape == (7000, 1)
    assert descriptor["size_bytes"] < 40000


@pytest.mark.parametrize("buffering", ["small", "oversized", "allocation_failure"])
def test_full_validation_has_bounded_archives_and_skips_discarded_frames(tmp_path, monkeypatch, buffering):
    from Main_App.io import condition_data, numpy_companion

    workbook = tmp_path / "recording.xlsx"
    frames = _frames()
    descriptor = _write(workbook, frames)
    companion = tmp_path / descriptor["path"]
    if buffering == "oversized":
        monkeypatch.setattr(numpy_companion, "_MAX_BUFFER_BYTES", 1)
    elif buffering == "allocation_failure":
        def refuse_buffer(*_args):
            raise MemoryError
        monkeypatch.setattr(numpy_companion, "_read_buffer", refuse_buffer)

    opens = []
    loads = []
    original_open, original_load = Path.open, np.load
    original_shared = condition_data.open_replaceable_companion

    def count_open(path, *args, **kwargs):
        if path == companion:
            opens.append(path)
        return original_open(path, *args, **kwargs)

    def count_load(*args, **kwargs):
        loads.append(None)
        return original_load(*args, **kwargs)

    def count_shared_open(path):
        if os.name == "nt":
            opens.append(path)  # Windows uses a delete-sharing native opener.
        return original_shared(path)

    monkeypatch.setattr(Path, "open", count_open)
    monkeypatch.setattr(np, "load", count_load)
    monkeypatch.setattr(condition_data, "open_replaceable_companion", count_shared_open)
    with monkeypatch.context() as validation:
        validation.setattr(condition_data.pd, "DataFrame", lambda *a, **kw: pytest.fail("Discarded DataFrame"))
        assert validate_condition_companion(workbook, descriptor, for_publication=True) == descriptor
    assert len(opens) == 2
    assert len(loads) == 1 + len(frames)


def test_scoped_full_validation_retains_exact_detached_columns_after_same_stat_edit(tmp_path, monkeypatch):
    from Main_App.io import condition_data, xlsx_selected_reader as xlsx

    workbook = tmp_path / "recording.xlsx"
    frames = _frames()
    descriptor = _write(workbook, frames)
    companion = tmp_path / descriptor["path"]
    with xlsx_read_cache_scope():
        assert validate_condition_companion(workbook, descriptor, for_publication=True) == descriptor
        payload, = xlsx._ACTIVE_XLSX_READ_CACHE.get().condition_payloads.values()
        for name, frame in frames.items():
            assert list(payload.columns[name]) == list(frame.columns)
        existing_signature = xlsx._workbook_signature_or_none
        monkeypatch.setattr(xlsx, "_workbook_signature_or_none", lambda path: (
            payload.companion_signature if path == companion else existing_signature(path)
        ))
        with companion.open("r+b") as stream:
            stream.write(b"bad!")
        monkeypatch.setattr(condition_data, "open_replaceable_companion", lambda *a: pytest.fail("Unexpected reopen"))
        assert validate_condition_companion(workbook, descriptor, for_publication=True) == descriptor
        detached = read_condition_sheet(workbook, sheet_name=BCA)
        detached.iloc[0, 1] = 12
        for name, expected in frames.items():
            pd.testing.assert_frame_equal(read_condition_sheet(workbook, sheet_name=name), expected)
    with pytest.raises(ConditionDataError, match="checksum"):
        validate_condition_companion(workbook, descriptor, for_publication=True)


@pytest.mark.parametrize("damage", ["data", "directory"])
def test_full_validation_rechecks_restored_stat_corruption_with_live_column_error(tmp_path, monkeypatch, damage):
    from Main_App.io import condition_data, xlsx_selected_reader as xlsx

    workbook = tmp_path / "recording.fpvs"
    descriptor = write_condition_companion(workbook, _frames())
    companion = tmp_path / descriptor["path"]
    signature = xlsx._workbook_signature_or_none(companion)
    existing_signature = xlsx._workbook_signature_or_none
    monkeypatch.setattr(xlsx, "_workbook_signature_or_none", lambda path: (
        signature if path == companion else existing_signature(path)
    ))
    data = bytearray(companion.read_bytes())
    with zipfile.ZipFile(companion) as archive:
        info = archive.getinfo("sheet1_block1.npy")
        central_directory = archive.start_dir
    if damage == "data":
        filename_length, extra_length = struct.unpack_from("<HH", data, info.header_offset + 26)
        last_byte = info.header_offset + 30 + filename_length + extra_length + info.file_size - 1
        data[last_byte] ^= 1
        error = "Bad CRC-32.*sheet1_block1"
    else:
        data[central_directory] ^= 1
        error = "Bad magic number for central directory"
    original_decode = condition_data.decode_column

    def change_after_snapshot(*args, **kwargs):
        monkeypatch.setattr(condition_data, "decode_column", original_decode)
        companion.write_bytes(data)
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(condition_data, "decode_column", change_after_snapshot)
    with pytest.raises(ConditionDataError, match=f"Cannot read condition columns .*{error}"):
        validate_condition_companion(workbook, descriptor, for_publication=True)


@pytest.mark.parametrize("target", ["workbook", "companion"])
def test_full_validation_allows_and_detects_replacement_during_decode(tmp_path, monkeypatch, target):
    from Main_App.io import condition_data

    workbook = tmp_path / "recording.xlsx"
    descriptor = _write(workbook)
    path = workbook if target == "workbook" else tmp_path / descriptor["path"]
    replacement = tmp_path / "replacement"
    replacement.write_bytes(path.read_bytes())
    original_decode = condition_data.decode_column

    def replace_during_decode(*args, **kwargs):
        monkeypatch.setattr(condition_data, "decode_column", original_decode)
        if os.name == "nt" and target == "companion":
            # MoveFileEx cannot overwrite an open destination. Delete sharing
            # lets another process rename that destination and replace its path.
            path.rename(tmp_path / "previous.npz")
        os.replace(replacement, path)
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(condition_data, "decode_column", replace_during_decode)
    with pytest.raises(ConditionDataError, match="Condition data changed while its columns were read"):
        validate_condition_companion(workbook, descriptor, for_publication=True)
    assert validate_condition_companion(workbook, descriptor, for_publication=True) == descriptor


@pytest.mark.parametrize("denied", [False, True])
def test_unavailable_shared_handle_uses_ordinary_access_diagnostics(tmp_path, monkeypatch, denied):
    from Main_App.io import condition_data

    workbook = tmp_path / "recording.fpvs"
    descriptor = write_condition_companion(workbook, _frames())
    companion = tmp_path / descriptor["path"]
    original_open = Path.open
    shared_failed = False

    def unsupported(_path):
        nonlocal shared_failed
        shared_failed = True
        raise OSError("unavailable shared opener")

    def ordinary_open(path, *args, **kwargs):
        if shared_failed and path == companion and denied:
            raise PermissionError("column read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(condition_data, "open_replaceable_companion", unsupported)
    monkeypatch.setattr(Path, "open", ordinary_open)
    if denied:
        with pytest.raises(ConditionDataError, match=r"Cannot read condition columns .*column read denied"):
            validate_condition_companion(workbook, descriptor, for_publication=True)
    else:
        assert validate_condition_companion(workbook, descriptor, for_publication=True) == descriptor
    assert shared_failed


def test_independent_validation_reopens_and_observes_denial_on_the_second_sheet(tmp_path, monkeypatch):
    from Main_App.io import condition_data

    workbook = tmp_path / "independent.fpvs"
    descriptor = write_condition_companion(workbook, _frames())
    companion = tmp_path / descriptor["path"]
    opens = 0
    original_open = Path.open

    def revoke_for_second_sheet(path, *args, **kwargs):
        nonlocal opens
        if path == companion:
            opens += 1
            if opens == 3:  # The checksum and the first sheet each opened successfully.
                raise PermissionError("second sheet denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(condition_data, "open_replaceable_companion", lambda *a: pytest.fail("Unexpected handle reuse"))
    monkeypatch.setattr(Path, "open", revoke_for_second_sheet)
    with pytest.raises(ConditionDataError, match=r"Cannot read condition columns .*second sheet denied"):
        validate_condition_companion(workbook, descriptor)
    assert opens == 3


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_only_producer_publication_shares_the_live_companion(tmp_path, monkeypatch, suffix):
    from Main_App.exports.post_process_excel import write_results_workbook
    from Main_App.io import condition_data
    from Main_App.io.result_manifest import write_result_manifest

    workbook = tmp_path / f"result{suffix}"
    frame = _frames()[BCA]
    opens = []
    original = condition_data.open_replaceable_companion

    def record(path):
        opens.append(path)
        return original(path)

    monkeypatch.setattr(condition_data, "open_replaceable_companion", record)
    receipt = write_results_workbook(str(workbook), {BCA: frame})
    descriptor = receipt["condition_companion"]
    assert opens == [tmp_path / descriptor["path"]]
    pd.testing.assert_frame_equal(read_condition_sheet(workbook, sheet_name=BCA), frame)
    opens.clear()
    if suffix == ".fpvs":
        write_result_manifest(workbook, sheet_names=[BCA], spectral_companion=None, condition_companion=descriptor)
    assert validate_condition_companion(workbook, descriptor) == descriptor
    assert not opens

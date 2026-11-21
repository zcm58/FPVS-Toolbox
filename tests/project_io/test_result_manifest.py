from pathlib import Path
import os
import shutil

import numpy as np
import pandas as pd
import pytest

from Main_App.io import read_condition_sheet, read_spectral_sheet, read_xlsx_sheet_header, read_xlsx_sheet_selected_columns
from Main_App.io.result_manifest import ResultManifestError, read_result_manifest, resolve_result_path
from Main_App.Shared.post_process_excel import write_results_workbook


def _frames():
    values = np.array([0x8000000000000000, 0x3FF0000000000001, 0x7FF8000000000001], dtype=np.uint64).view(np.float64)
    frame = pd.DataFrame({"Electrode": ["Fp1", "O1", "PO8"], "1.2000_Hz": values})
    return {"BCA (uV)": frame, "FullFFT Amplitude (uV)": frame.copy(), "FullSNR": frame.copy()}


def _write(path, frames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_results_workbook(str(path), _frames() if frames is None else frames)


def test_native_and_excel_anchor_preserve_identical_companion_bits(tmp_path):
    legacy = tmp_path / "old" / "P1_A_Results.xlsx"
    native = tmp_path / "new" / "P1_A_Results.fpvs"
    old, new = _write(legacy), _write(native)
    assert new["path"] == str(native.resolve())
    assert new["schema_validation"]["status"] == "passed"
    assert not native.with_suffix(".xlsx").exists()
    for key in ("spectral_companion", "condition_companion"):
        assert new[key] == old[key]
        assert (native.parent / new[key]["path"]).read_bytes() == (legacy.parent / old[key]["path"]).read_bytes()
    for sheet, original in _frames().items():
        reader = read_condition_sheet if sheet == "BCA (uV)" else read_spectral_sheet
        before, after = reader(legacy, sheet_name=sheet), reader(native, sheet_name=sheet)
        pd.testing.assert_frame_equal(before, after, check_exact=True)
        np.testing.assert_array_equal(after.iloc[:, 1:].to_numpy().view(np.uint64), original.iloc[:, 1:].to_numpy().view(np.uint64))
    actual = read_xlsx_sheet_selected_columns(native, sheet_name="BCA (uV)", required_columns=["1.2000_Hz", "Electrode"], included_electrodes_upper={"O1"})
    assert actual["Electrode"].tolist() == ["O1"]
    assert actual["1.2000_Hz"].to_numpy().view(np.uint64)[0] == 0x3FF0000000000001


def test_native_writer_does_not_open_excel(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Native results must not assemble Excel")
    monkeypatch.setattr(pd, "ExcelWriter", forbidden)
    _write(tmp_path / "P1_A_Results.fpvs")


def test_optional_absent_native_sheet_uses_existing_missing_sheet_contract(tmp_path):
    path = tmp_path / "P1_A_Results.fpvs"
    _write(path)
    for reader, kwargs in (
        (read_condition_sheet, {}),
        (read_xlsx_sheet_header, {}),
        (read_xlsx_sheet_selected_columns, {"required_columns": ["Electrode"]}),
    ):
        with pytest.raises(ValueError, match="Worksheet named 'Spectral Metric QC' not found"):
            reader(path, sheet_name="Spectral Metric QC", **kwargs)


def test_native_results_are_portable_and_companion_damage_is_not_hidden(tmp_path):
    original = tmp_path / "original" / "P1_A_Results.fpvs"
    _write(original)
    shutil.copytree(original.parent, tmp_path / "moved")
    moved = tmp_path / "moved" / original.name
    pd.testing.assert_frame_equal(read_condition_sheet(moved, sheet_name="BCA (uV)"), _frames()["BCA (uV)"])
    descriptor = read_result_manifest(moved)["condition_companion"]
    (moved.parent / descriptor["path"]).write_bytes(b"damaged")
    with pytest.raises(ValueError, match="missing or has changed"):
        read_condition_sheet(moved, sheet_name="BCA (uV)")


def test_native_precedence_does_not_fall_back_when_invalid(tmp_path):
    old = tmp_path / "P1_A_Results.xlsx"
    _write(old)
    native = old.with_suffix(".fpvs")
    native.write_text("invalid", encoding="utf-8")
    assert resolve_result_path(old) == native
    with pytest.raises(ResultManifestError):
        read_condition_sheet(native, sheet_name="BCA (uV)")


def test_failed_native_publication_preserves_previous_result(tmp_path, monkeypatch):
    from Main_App.io import result_manifest
    path = tmp_path / "P1_A_Results.fpvs"
    _write(path)
    before = path.read_bytes()
    frames = _frames()
    frames["BCA (uV)"].loc[1, "1.2000_Hz"] = 4.0
    replace = result_manifest.os.replace
    def fail_publish(source, destination):
        if Path(destination) == path:
            raise OSError("simulated publication failure")
        return replace(source, destination)
    monkeypatch.setattr(result_manifest.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publication failure"):
        _write(path, frames)
    assert path.read_bytes() == before
    pd.testing.assert_frame_equal(read_condition_sheet(path, sheet_name="BCA (uV)"), _frames()["BCA (uV)"])


@pytest.mark.parametrize("data", [b"\xff", b"\xef\xbb\xbf{}", b"{\r\n!}", b"{}"])
def test_already_read_manifest_bytes_keep_original_diagnostics(tmp_path, data):
    path = tmp_path / "P1_A_Results.fpvs"
    path.write_bytes(data)
    with pytest.raises(ResultManifestError) as on_disk:
        read_result_manifest(path)
    with pytest.raises(ResultManifestError) as from_bytes:
        read_result_manifest(path, contents=data)
    assert str(from_bytes.value) == str(on_disk.value)


def test_legacy_path_case_is_retained(tmp_path):
    path = tmp_path / "P1_A_Results.XLSX"
    path.touch()
    assert resolve_result_path(path) == path


def test_native_identity_pair_validates_stable_declaration_once(tmp_path, monkeypatch):
    from Main_App.io import condition_data, result_manifest, spectral_data

    path = tmp_path / "stable.fpvs"
    _write(path)
    expected = spectral_data.spectral_companion_identity(path), condition_data.condition_companion_identity(path)
    validate = result_manifest._validate_manifest
    calls = []

    def counted(value):
        calls.append(value)
        return validate(value)

    monkeypatch.setattr(result_manifest, "_validate_manifest", counted)
    assert result_manifest.result_companion_identities(path) == expected
    assert len(calls) == 1
    monkeypatch.setattr(result_manifest, "_MAX_REUSED_MANIFEST_CHARS", 1)
    assert result_manifest.result_companion_identities(path) == expected
    assert len(calls) == 3


@pytest.mark.parametrize("read_mode", ["buffered", "streamed", "memory_pressure"])
def test_fresh_identity_passes_rehash_both_companions_and_reuse_only_verified_schemas(tmp_path, monkeypatch, read_mode):
    from collections import Counter
    import hashlib

    from Main_App.io import condition_data, numpy_companion, result_manifest, spectral_data
    from Main_App.processing.post_processing_context import post_processing_validation_scope

    path = tmp_path / "result.fpvs"
    written = _write(path)
    expected = written["spectral_companion"], written["condition_companion"]
    counts = Counter()

    def count(owner, name):
        original = getattr(owner, name)

        def tracked(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, tracked)

    count(hashlib, "file_digest")
    count(spectral_data, "_dense_shape")
    count(condition_data, "_array_header")
    if read_mode == "streamed":
        monkeypatch.setattr(numpy_companion, "_MAX_BUFFER_BYTES", 0)

    with post_processing_validation_scope():
        assert result_manifest.result_companion_identities(path) == expected
        first = counts.copy()
        assert first["file_digest"] == 2 and first["_dense_shape"] > 0 and first["_array_header"] > 0
        if read_mode == "memory_pressure":
            def no_buffer(*args):
                raise MemoryError

            monkeypatch.setattr(numpy_companion, "_read_buffer", no_buffer)
        with post_processing_validation_scope(fresh=True):
            assert result_manifest.result_companion_identities(path) == expected
        assert counts["file_digest"] == 4
        for name in ("_dense_shape", "_array_header"):
            assert counts[name] == first[name] * (1 if read_mode == "buffered" else 2)
    counts.clear()
    with post_processing_validation_scope():
        assert result_manifest.result_companion_identities(path) == expected
        assert counts == first


@pytest.mark.parametrize("kind", ["spectral", "condition"])
@pytest.mark.parametrize("damage", ["same_size_and_mtime", "missing", "new_sheet_declaration"])
def test_schema_receipt_checks_live_companion_and_exact_declaration(tmp_path, kind, damage):
    from Main_App.io import condition_data, spectral_data
    from Main_App.processing.post_processing_context import post_processing_validation_scope

    path = tmp_path / "result.fpvs"
    descriptor = _write(path)[f"{kind}_companion"]
    module = spectral_data if kind == "spectral" else condition_data
    validate = module._identity_from_descriptor
    error = module.SpectralDataError if kind == "spectral" else module.ConditionDataError
    with post_processing_validation_scope():
        assert validate(path, descriptor) == descriptor
        companion = path.parent / descriptor["path"]
        if damage == "same_size_and_mtime":
            before = companion.stat()
            data = bytearray(companion.read_bytes())
            data[-1] ^= 1
            companion.write_bytes(data)
            os.utime(companion, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif damage == "missing":
            companion.unlink()
        elif kind == "condition":
            descriptor = dict(descriptor, sheets=["SNR"])
        else:
            descriptor = dict(descriptor, sheets=descriptor["sheets"][:1])
        with pytest.raises(error) as scoped:
            validate(path, descriptor)
    with pytest.raises(error) as independent:
        validate(path, descriptor)
    assert str(scoped.value) == str(independent.value)


def test_schema_receipts_evict_and_skip_failed_validations(tmp_path, monkeypatch):
    from Main_App.io import companion_schema, result_manifest, spectral_data
    from Main_App.processing.post_processing_context import post_processing_validation_scope

    path = tmp_path / "result.fpvs"
    written = _write(path)
    descriptor = written["spectral_companion"]
    monkeypatch.setattr(companion_schema, "_MAX_SCHEMA_RECEIPTS", 1)
    original = spectral_data._dense_shape
    reads = []

    def fail_first(container, key):
        reads.append(key)
        if len(reads) == 1:
            raise OSError("interrupted spectral schema read")
        return original(container, key)

    monkeypatch.setattr(spectral_data, "_dense_shape", fail_first)
    with post_processing_validation_scope():
        with pytest.raises(spectral_data.SpectralDataError, match="interrupted spectral schema read"):
            result_manifest.result_companion_identities(path)
        expected = descriptor, written["condition_companion"]
        assert result_manifest.result_companion_identities(path) == expected
        assert len(reads) == 1 + len(descriptor["sheets"])
        # The condition companion took the only slot. Spectra validate again.
        assert result_manifest.result_companion_identities(path) == expected
        assert len(reads) == 1 + 2 * len(descriptor["sheets"])


@pytest.mark.parametrize("edit", ["replace", "same_size_and_mtime", "malformed", "missing"])
def test_native_identity_pair_observes_current_condition_after_spectral_check(tmp_path, monkeypatch, edit):
    from Main_App.io import condition_data, result_manifest, spectral_data

    path = tmp_path / "first" / "result.fpvs"
    other = tmp_path / "second" / path.name
    old = _write(path)
    changed_frames = _frames()
    changed_frames["BCA (uV)"].iloc[0, 1] = 6.0
    new = _write(other, changed_frames)
    changed_companion = new["condition_companion"]["path"]
    shutil.copyfile(other.parent / changed_companion, path.parent / changed_companion)
    assert old["condition_companion"] != new["condition_companion"]
    updated = other.read_bytes()
    assert len(updated) == path.stat().st_size
    verify_spectral = spectral_data._identity_from_descriptor

    def edit_after_spectral(workbook, descriptor):
        spectral = verify_spectral(workbook, descriptor)
        if edit == "replace":
            os.replace(other, path)
        elif edit == "same_size_and_mtime":
            before = path.stat()
            path.write_bytes(updated)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif edit == "malformed":
            path.write_bytes(b"\xff")
        else:
            path.unlink()
        return spectral

    monkeypatch.setattr(spectral_data, "_identity_from_descriptor", edit_after_spectral)
    if edit in {"replace", "same_size_and_mtime"}:
        assert result_manifest.result_companion_identities(path) == (
            old["spectral_companion"], new["condition_companion"],
        )
    else:
        with pytest.raises(ResultManifestError) as actual:
            result_manifest.result_companion_identities(path)
        with pytest.raises(ResultManifestError) as expected:
            condition_data.condition_companion_identity(path)
        assert str(actual.value) == str(expected.value)

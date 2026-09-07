from pathlib import Path
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


def test_legacy_path_case_is_retained(tmp_path):
    path = tmp_path / "P1_A_Results.XLSX"
    path.touch()
    assert resolve_result_path(path) == path

from __future__ import annotations

import importlib
import json
import pickle
import subprocess
import sys

from tests import repo_root


def test_path_helpers_and_package_discovery_need_no_scientific_stack():
    script = """
import sys
from pathlib import Path
from Main_App import io
from Main_App.Shared.paths import bundle_path
from Main_App.io.file_filters import is_eeg_recording_file
from Main_App.io.result_manifest import result_manifest_path

assert is_eeg_recording_file("trial.bdf") and not is_eeg_recording_file("trial.eeg")
assert result_manifest_path("trial.xlsx") == Path("trial.fpvs")
assert bundle_path("icon.svg") == Path(io.__file__).resolve().parents[1] / "Shared" / "icon.svg"
assert {"load_eeg_file", "read_spectral_sheet", "numpy_companion", "recording_inspection"} <= set(dir(io))
assert not {"mne", "numpy", "pandas", "PySide6"}.intersection(sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], cwd=repo_root() / "src", check=True, timeout=30)


def test_io_exports_resolve_to_canonical_owners_and_preserve_pickle_names():
    from Main_App import io

    owners = [importlib.import_module(f"Main_App.io.{name}") for name in (
        "load_utils", "eeg_geometry", "xlsx_selected_reader", "spectral_data", "condition_data",
    )]
    assert set(io.__all__) <= set(dir(io))
    for name in io.__all__:
        value = getattr(io, name)
        assert any(value is getattr(module, name, None) for module in owners), name
    for name in ("BdfPreflightInfo", "BioSemi64AcquisitionGeometry", "SpectralDataError", "ConditionDataError", "read_condition_sheet"):
        value = getattr(io, name)
        assert pickle.loads(f"cMain_App.io\n{name}\n.".encode("ascii")) is value
        assert pickle.loads(pickle.dumps(value)) is value
    assert io.load_utils is importlib.import_module("Main_App.Shared.load_utils")
    assert io.xlsx_xml is importlib.import_module("Main_App.io.xlsx_xml")
    assert not hasattr(io, "unknown_io_member")


def test_metadata_only_manifest_read_preserves_declarations_and_lightweight_errors(tmp_path):
    path = tmp_path / "result.fpvs"
    fields = {"path": "input.npz", "size_bytes": 1, "sha256": "a" * 64}
    spectral = {**fields, "version": "numpy_spectral_companion_v1", "sheets": ["FullFFT Amplitude (uV)"]}
    condition = {**fields, "version": "numpy_condition_companion_v1", "sheets": ["BCA (uV)"]}
    path.write_text(json.dumps({
        "version": "fpvs_result_manifest_v1", "sheet_names": ["BCA (uV)", "FullFFT Amplitude (uV)"],
        "spectral_companion": {**spectral, "optional_field": 1}, "condition_companion": condition,
    }), encoding="utf-8")
    script = """
from pathlib import Path
import importlib, json, pickle, sys
from Main_App.io.result_manifest import ResultManifestError, read_result_manifest

path = Path(sys.argv[1])
document = json.loads(path.read_bytes())
result = read_result_manifest(path)
assert result["condition_companion"] == document["condition_companion"]
assert result["sheet_names"] == document["sheet_names"]
assert result["spectral_companion"] == {k: v for k, v in document["spectral_companion"].items() if k != "optional_field"}
causes = []
for kind, field, message in (
    ("spectral", {"path": "../input.npz"}, "Spectral companion path must be a local .npz basename."),
    ("condition", {"optional_field": 1}, "Condition companion declaration has invalid fields."),
):
    key = kind + "_companion"
    invalid = {**document, key: {**document[key], **field}}
    try:
        read_result_manifest(path, contents=json.dumps(invalid).encode())
    except ResultManifestError as exc:
        assert str(exc) == f"Cannot read FPVS results {path.name}: {message}"
        cause = exc.__cause__
        assert type(cause).__module__ == "Main_App.io." + kind + "_data"
        assert str(cause) == message
        causes.append(cause)
    else:
        raise AssertionError("Invalid declaration accepted")
assert not {"numpy", "pandas", "mne", "PySide6", "Main_App.io.condition_data", "Main_App.io.spectral_data"}.intersection(sys.modules)
for cause in causes:
    cls = type(cause)
    assert cls is getattr(importlib.import_module(cls.__module__), cls.__name__)
    assert pickle.loads(f"c{cls.__module__}\\n{cls.__name__}\\n.".encode("ascii")) is cls
    assert type(pickle.loads(pickle.dumps(cause))) is cls
"""
    subprocess.run([sys.executable, "-c", script, str(path)], cwd=repo_root() / "src", check=True, timeout=30)

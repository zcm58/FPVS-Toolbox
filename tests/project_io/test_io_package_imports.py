from __future__ import annotations

import importlib
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
    for name in ("BdfPreflightInfo", "BioSemi64AcquisitionGeometry", "SpectralDataError", "read_condition_sheet"):
        value = getattr(io, name)
        assert pickle.loads(f"cMain_App.io\n{name}\n.".encode("ascii")) is value
        assert pickle.loads(pickle.dumps(value)) is value
    assert io.load_utils is importlib.import_module("Main_App.Shared.load_utils")
    assert io.xlsx_xml is importlib.import_module("Main_App.io.xlsx_xml")
    assert not hasattr(io, "unknown_io_member")

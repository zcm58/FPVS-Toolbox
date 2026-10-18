"""Compatibility contracts for purpose-based Main App implementation owners."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import pickle
import subprocess
import sys

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"


OWNER_PAIRS = (
    ("Shared.eeg_geometry", "io.eeg_geometry"),
    ("Shared.fft_crop_utils", "processing.fft_crop_utils"),
    ("Shared.file_filters", "io.file_filters"),
    ("Shared.load_utils", "io.load_utils"),
    ("Shared.paths", "io.resource_paths"),
    ("Shared.post_process", "exports.post_process"),
    ("Shared.post_process_excel", "exports.post_process_excel"),
    ("Shared.processing_mixin", "workers.processing_mixin"),
    ("Shared.roi_presets", "processing.roi_presets"),
    ("Shared.settings_manager", "settings.settings_manager"),
    ("Shared.settings_paths", "settings.settings_paths"),
    ("Shared.user_messages", "gui.user_messages"),
    ("Performance.mp_env", "workers.mp_env"),
    ("Performance.process_runner", "workers.process_runner"),
)


@pytest.mark.parametrize("historical,canonical", OWNER_PAIRS)
def test_compatibility_import_is_the_canonical_module(historical, canonical, monkeypatch):
    old = importlib.import_module(f"Main_App.{historical}")
    owner = importlib.import_module(f"Main_App.{canonical}")
    assert old is owner
    assert owner.__name__ == f"Main_App.{canonical}"
    marker = object()
    monkeypatch.setattr(old, "_compatibility_probe", marker, raising=False)
    assert owner._compatibility_probe is marker


@pytest.mark.parametrize("historical_first", [True, False])
def test_aliases_preserve_identity_in_a_fresh_interpreter(historical_first):
    script = """
import importlib, json, sys
for historical, canonical in json.loads(sys.argv[1]):
    names = (historical, canonical) if sys.argv[2] == 'True' else (canonical, historical)
    first, second = (importlib.import_module('Main_App.' + name) for name in names)
    assert first is second, names
    assert first.__name__ == 'Main_App.' + canonical, names
"""
    subprocess.run(
        [sys.executable, "-c", script, json.dumps(OWNER_PAIRS), str(historical_first)],
        cwd=SOURCE_ROOT,
        check=True,
        timeout=45,
    )


@pytest.mark.parametrize(
    "historical,canonical,name",
    [
        ("Shared.load_utils", "io.load_utils", "BdfPreflightInfo"),
        ("Shared.eeg_geometry", "io.eeg_geometry", "BioSemi64AcquisitionGeometry"),
        ("Shared.fft_crop_utils", "processing.fft_crop_utils", "CropResult"),
        ("Shared.roi_presets", "processing.roi_presets", "ROIPreset"),
        ("Performance.process_runner", "workers.process_runner", "RunParams"),
        ("Performance.process_runner", "workers.process_runner", "_process_one_file"),
        ("Performance.mp_env", "workers.mp_env", "set_worker_thread_limits"),
    ],
)
def test_old_pickle_globals_resolve_and_new_pickles_use_the_owner(historical, canonical, name):
    owner = getattr(importlib.import_module(f"Main_App.{canonical}"), name)
    historical_global = f"cMain_App.{historical}\n{name}\n.".encode("ascii")
    assert pickle.loads(historical_global) is owner
    assert owner.__module__ == f"Main_App.{canonical}"
    assert pickle.loads(pickle.dumps(owner)) is owner


def test_runner_dataclass_survives_pickle_roundtrip(tmp_path):
    from Main_App.workers.process_runner import RunParams

    params = RunParams(tmp_path, [tmp_path / "recording.bdf"], {}, {"condition": 1}, tmp_path)
    assert pickle.loads(pickle.dumps(params)) == params


def test_canonical_worker_helpers_resolve_in_spawned_process():
    script = """
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from Main_App.processing.fft_crop_utils import compute_onbin_N
if __name__ == '__main__':
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn')) as pool:
        assert pool.submit(compute_onbin_N, 100, 16).result(timeout=30) == 96
"""
    subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT, check=True, timeout=45)


def test_resource_path_keeps_source_and_frozen_roots(monkeypatch, tmp_path):
    from Main_App.io import resource_paths

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    source_root = Path(resource_paths.__file__).resolve().parents[1] / "Shared"
    assert resource_paths.bundle_path("icons", "tool.ico") == source_root / "icons" / "tool.ico"
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_paths.bundle_path("icons", "tool.ico") == tmp_path / "icons" / "tool.ico"


def test_boot_logging_and_settings_paths_do_not_import_scientific_or_gui_stack():
    script = """
import sys
import Main_App
from Main_App.settings import settings_paths
for prefix in ('Main_App.projects', 'Main_App.processing', 'Main_App.io', 'mne', 'numpy', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
assert settings_paths.__name__ == 'Main_App.settings.settings_paths'
"""
    subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT, check=True, timeout=15)

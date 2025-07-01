import importlib
import os
import sys
import types
import pytest


def _import_visualization():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "Tools",
        "SourceLocalization",
        "visualization.py",
    )
    spec = importlib.util.spec_from_file_location("visualization", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_deps():
    for mod in ("numpy", "mne"):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not available", allow_module_level=True)


def test_view_respects_show_brain_mesh_setting(tmp_path, monkeypatch):
    _check_deps()
    module = _import_visualization()

    SettingsManager = importlib.import_module("Main_App.settings_manager").SettingsManager
    settings = SettingsManager()
    settings.set("visualization", "show_brain_mesh", "False")

    monkeypatch.setitem(
        sys.modules,
        "Main_App.settings_manager",
        types.SimpleNamespace(SettingsManager=lambda: settings),
    )

    captured = {}

    def dummy_pyvista(stc, subjects_dir, time_idx, cortex_alpha, atlas_alpha, show_cortex):
        captured["show_cortex"] = show_cortex
        return types.SimpleNamespace()

    monkeypatch.setattr(module, "view_source_estimate_pyvista", dummy_pyvista)
    monkeypatch.setattr(module, "fetch_fsaverage", lambda verbose=False: types.SimpleNamespace(parent=tmp_path))
    dummy_data = [[0.0], [0.0]]
    monkeypatch.setattr(
        module.mne,
        "read_source_estimate",
        lambda p: types.SimpleNamespace(
            data=dummy_data,
            vertices=[[0], [0]],
            tmin=0.0,
            tstep=1.0,
            subject="fsaverage",
        ),
    )

    module.view_source_estimate(str(tmp_path / "dummy"), log_func=lambda x: None)

    assert captured["show_cortex"] is False

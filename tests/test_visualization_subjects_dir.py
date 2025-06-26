import importlib.util
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


def test_view_source_estimate_normalizes_subjects_dir(tmp_path, monkeypatch):
    _check_deps()
    module = _import_visualization()

    SettingsManager = importlib.import_module("Main_App.settings_manager").SettingsManager
    settings = SettingsManager()
    nested = tmp_path / "fsaverage" / "fsaverage"
    nested.mkdir(parents=True)
    settings.set("loreta", "mri_path", str(nested))

    monkeypatch.setitem(
        sys.modules,
        "Main_App.settings_manager",
        types.SimpleNamespace(SettingsManager=lambda: settings),
    )

    captured = {}

    class DummyBrain:
        def add_label(self, *a, **k):
            pass

    def dummy_plot(stc, hemi, subjects_dir, subject, alpha):
        captured["subjects_dir"] = subjects_dir
        return DummyBrain()

    monkeypatch.setattr(module, "_plot_with_alpha", dummy_plot)
    monkeypatch.setattr(module, "_ensure_pyvista_backend", lambda: None)
    monkeypatch.setattr(module, "_set_brain_alpha", lambda *a, **k: None)
    monkeypatch.setattr(module, "_set_brain_title", lambda *a, **k: None)
    monkeypatch.setattr(module, "_set_colorbar_label", lambda *a, **k: None)
    monkeypatch.setattr(module.mne, "read_source_estimate", lambda p: types.SimpleNamespace(data=[], subject="fsaverage"))
    monkeypatch.setattr(module.mne, "read_labels_from_annot", lambda *a, **k: [])

    module.view_source_estimate(str(tmp_path / "dummy"), log_func=lambda x: None)

    assert captured["subjects_dir"] == str(tmp_path / "fsaverage")


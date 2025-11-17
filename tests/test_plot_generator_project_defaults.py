import importlib.util
import json
import os

import pytest

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)


def _import_module():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "Tools",
        "Plot_Generator",
        "plot_generator.py",
    )
    spec = importlib.util.spec_from_file_location("plot_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_defaults_loaded_from_project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    excel = proj / "1 - Excel Data Files"
    snr = proj / "2 - SNR Plots"
    excel.mkdir()
    snr.mkdir()
    data = {
        "name": "Test",
        "subfolders": {"excel": "1 - Excel Data Files", "snr": "2 - SNR Plots"},
    }
    (proj / "project.json").write_text(json.dumps(data))

    monkeypatch.chdir(proj)
    module = _import_module()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    win = module.PlotGeneratorWindow()
    assert win.folder_edit.text() == str(excel)
    assert win.out_edit.text() == str(snr)
    app.quit()


def test_defaults_loaded_from_env(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    excel = proj / "1 - Excel Data Files"
    snr = proj / "2 - SNR Plots"
    excel.mkdir()
    snr.mkdir()
    data = {
        "name": "EnvTest",
        "subfolders": {"excel": "1 - Excel Data Files", "snr": "2 - SNR Plots"},
    }
    (proj / "project.json").write_text(json.dumps(data))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FPVS_PROJECT_ROOT", str(proj))
    module = _import_module()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    win = module.PlotGeneratorWindow()
    assert win.folder_edit.text() == str(excel)
    assert win.out_edit.text() == str(snr)
    app.quit()


def test_legacy_results_folder_detected(tmp_path, monkeypatch):
    proj = tmp_path / "legacy"
    results = proj / "Results"
    excel = results / "1 - Excel Data Files"
    snr = results / "2 - SNR Plots"
    results.mkdir(parents=True)
    excel.mkdir()
    snr.mkdir()
    data = {
        "name": "Legacy",
        "results_folder": "Results",
        "subfolders": {"excel": "1 - Excel Data Files", "snr": "2 - SNR Plots"},
    }
    (proj / "project.json").write_text(json.dumps(data))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FPVS_PROJECT_ROOT", str(proj))
    module = _import_module()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    win = module.PlotGeneratorWindow()
    assert win.folder_edit.text() == str(excel)
    assert win.out_edit.text() == str(snr)
    app.quit()

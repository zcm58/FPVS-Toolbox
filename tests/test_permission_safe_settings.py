from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QMessageBox

from Main_App.Shared import settings_paths
from Main_App.Shared.settings_manager import SettingsManager
from Tools.Plot_Generator.gui import PlotGeneratorWindow


def test_app_settings_use_fpvs_config_home(tmp_path, monkeypatch) -> None:
    config_home = tmp_path / "fpvs-config"
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(config_home))

    path = settings_paths.app_settings_file()

    assert path == config_home / "settings" / "settings.ini"
    assert path.parent.is_dir()


def test_settings_path_error_when_config_home_is_not_directory(tmp_path, monkeypatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(blocked))

    with pytest.raises(settings_paths.SettingsPathError, match="not writable"):
        settings_paths.app_settings_file()


def test_shared_settings_manager_migrates_roaming_appdata_ini(tmp_path, monkeypatch) -> None:
    config_home = tmp_path / "local-config"
    roaming = tmp_path / "roaming"
    old_root = roaming / "FPVS_Toolbox"
    old_root.mkdir(parents=True)
    (old_root / "settings.ini").write_text(
        "[analysis]\nbase_freq = 7.5\nalpha = 0.01\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(config_home))
    monkeypatch.setenv("APPDATA", str(roaming))

    manager = SettingsManager()

    assert manager.get("analysis", "base_freq") == "7.5"
    assert manager.get("analysis", "alpha") == "0.01"
    assert (config_home / "settings" / "settings.ini").is_file()
    assert (old_root / "settings.ini").is_file()


def test_settings_manager_uses_config_home_ini(tmp_path, monkeypatch, qtbot) -> None:
    config_home = tmp_path / "qt-config"
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(config_home))

    settings = SettingsManager()
    settings.set("updates", "last_checked_utc", "2026-05-01T00:00:00+00:00")
    settings.save()

    assert settings.ini_path == str(config_home / "settings" / "settings.ini")
    assert (config_home / "settings" / "settings.ini").is_file()


def test_settings_manager_project_root_roundtrip(tmp_path, monkeypatch) -> None:
    config_home = tmp_path / "qt-config"
    new_root = tmp_path / "new-projects"
    new_root.mkdir()
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(config_home))

    manager = SettingsManager()
    manager.set_project_root(str(new_root))
    manager.save()

    restored = SettingsManager()
    assert restored.get_project_root() == str(new_root)


def test_plot_generator_project_settings_roundtrip(tmp_path, monkeypatch, qtbot) -> None:
    monkeypatch.setenv(settings_paths.ENV_CONFIG_HOME, str(tmp_path / "config"))
    project_root = tmp_path / "Project"
    excel_dir = project_root / "1 - Excel Data Files"
    snr_dir = project_root / "2 - SNR Plots"
    excel_dir.mkdir(parents=True)
    snr_dir.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {
                    "excel": "1 - Excel Data Files",
                    "snr": "2 - SNR Plots",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window = PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(window)
    window.folder_edit.setText(str(excel_dir))
    window.out_edit.setText(str(snr_dir))
    window.scalp_check.setChecked(True)
    window.scalp_min_spin.setValue(-3.0)
    window.scalp_max_spin.setValue(3.0)
    window.scalp_title_a_edit.setText("A {condition}")
    window.scalp_title_b_edit.setText("B {condition}")

    window._save_defaults()

    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    plot_settings = saved["tools"]["snr_plot"]["plot_settings"]
    assert plot_settings["input_folder"] == str(excel_dir)
    assert plot_settings["output_folder"] == str(snr_dir)
    assert plot_settings["include_scalp_maps"] is True
    assert plot_settings["scalp_min"] == -3.0
    assert plot_settings["scalp_max"] == 3.0
    assert plot_settings["title_a_template"] == "A {condition}"
    assert plot_settings["title_b_template"] == "B {condition}"

    restored = PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(restored)
    assert restored.folder_edit.text() == str(excel_dir)
    assert restored.out_edit.text() == str(snr_dir)
    assert restored.scalp_check.isChecked() is True
    assert restored.scalp_min_spin.value() == pytest.approx(-3.0)
    assert restored.scalp_max_spin.value() == pytest.approx(3.0)
    assert restored.scalp_title_a_edit.text() == "A {condition}"
    assert restored.scalp_title_b_edit.text() == "B {condition}"

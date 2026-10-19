"""CI GUI coverage for project-owned Plot Generator settings."""

from __future__ import annotations

import json

from Main_App.settings import settings_paths
from Tools.Plot_Generator.gui import PlotGeneratorWindow


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
    window = PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(window)
    window.folder_edit.setText(str(excel_dir))
    window.out_edit.setText(str(snr_dir))

    assert window._persist_project_plot_settings(include_paths=True)

    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    plot_settings = saved["tools"]["snr_plot"]["plot_settings"]
    assert plot_settings["input_folder"] == str(excel_dir)
    assert plot_settings["output_folder"] == str(snr_dir)

    restored = PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(restored)
    assert restored.folder_edit.text() == str(excel_dir)
    assert restored.out_edit.text() == str(snr_dir)

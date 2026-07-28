from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from Tools.Plot_Generator.worker import _Worker


def _write_full_snr(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "Electrode": ["Cz"],
            "1.0_Hz": [values[0]],
            "2.0_Hz": [values[1]],
        }
    )
    with pd.ExcelWriter(path) as writer:
        df.to_excel(writer, sheet_name="FullSNR", index=False)


def test_group_overlay_matches_project_participant_ids_from_excel_names(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    after_raw = project_root / "Raw" / "After"
    before_raw = project_root / "Raw" / "Before"
    after_raw.mkdir(parents=True)
    before_raw.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "after": {
                        "label": "After Creatine",
                        "folder_name": "After Creatine",
                        "raw_input_folder": str(after_raw),
                    },
                    "before": {
                        "label": "Before Creatine",
                        "folder_name": "Before Creatine",
                        "raw_input_folder": str(before_raw),
                    },
                },
                "participants": {
                    "e2p2final": {"group_id": "after"},
                    "E2P1INITIAL": {"group_id": "before"},
                },
            }
        ),
        encoding="utf-8",
    )
    excel_root = project_root / "1 - Excel Data Files"
    condition = "Angry"
    _write_full_snr(
        excel_root
        / condition
        / "After Creatine"
        / "E2P2final_Angry_Results.xlsx",
        [2.0, 4.0],
    )
    _write_full_snr(
        excel_root
        / condition
        / "Before Creatine"
        / "E2P1initial_Angry_Results.xlsx",
        [1.0, 3.0],
    )

    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        "Angry",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        5.0,
        str(tmp_path / "plots"),
        subject_groups={
            "E2P2FINAL": "Before Creatine",
            "E2P1INITIAL": "After Creatine",
        },
        selected_groups=["After Creatine", "Before Creatine"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    captured: dict[str, object] = {}

    def fake_plot(freqs, roi_data, group_curves=None):
        captured["roi_data"] = roi_data
        captured["group_curves"] = group_curves or {}

    monkeypatch.setattr(worker, "_plot", fake_plot)

    worker.run()

    assert captured["roi_data"] == {"Central": [1.5, 3.5]}
    assert captured["group_curves"] == {
        "After Creatine": {"Central": [2.0, 4.0]},
        "Before Creatine": {"Central": [1.0, 3.0]},
    }
    assert worker.failed_items == []


def test_worker_uses_shared_index_preference_for_grouped_workbook(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    raw_root = project_root / "Raw" / "Control"
    raw_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "control": {
                        "label": "Control",
                        "folder_name": "Control",
                        "raw_input_folder": str(raw_root),
                    }
                },
                "participants": {"P01": {"group_id": "control"}},
            }
        ),
        encoding="utf-8",
    )
    excel_root = project_root / "1 - Excel Data Files"
    condition = "Faces"
    _write_full_snr(
        excel_root / condition / "P01_Faces_Results.xlsx",
        [90.0, 90.0],
    )
    _write_full_snr(
        excel_root / condition / "Control" / "P01_Faces_Results.xlsx",
        [2.0, 4.0],
    )
    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        condition,
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        100.0,
        str(tmp_path / "plots"),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        worker,
        "_plot",
        lambda freqs, roi_data, group_curves=None: captured.update(
            {"freqs": freqs, "roi_data": roi_data}
        ),
    )

    worker.run()

    assert captured == {
        "freqs": [1.0, 2.0],
        "roi_data": {"Central": [2.0, 4.0]},
    }
    assert worker.failed_items == []


def test_worker_rejects_stale_selected_group_label(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    control_raw = project_root / "Raw" / "Control"
    patient_raw = project_root / "Raw" / "Patient"
    control_raw.mkdir(parents=True)
    patient_raw.mkdir(parents=True)
    manifest_path = project_root / "project.json"
    manifest = {
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": str(control_raw),
            },
            "patient": {
                "label": "Patient",
                "folder_name": "Patient",
                "raw_input_folder": str(patient_raw),
            },
        },
        "participants": {
            "P01": {"group_id": "control"},
            "P02": {"group_id": "patient"},
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    excel_root = project_root / "1 - Excel Data Files"
    condition = "Faces"
    _write_full_snr(
        excel_root / condition / "Control" / "P01_Faces_Results.xlsx",
        [2.0, 4.0],
    )
    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        condition,
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        10.0,
        str(tmp_path / "plots"),
        subject_groups={"P01": "Control", "P02": "Patient"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
        project_root=str(project_root),
    )
    manifest["groups"]["control"]["label"] = "Comparison"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plotted = False

    def _capture_plot(*args, **kwargs) -> None:
        nonlocal plotted
        plotted = True

    monkeypatch.setattr(worker, "_plot", _capture_plot)

    worker.run()

    assert plotted is False
    assert len(worker.failed_items) == 1
    assert "Selected project group label(s) changed" in worker.failed_items[0]["error"]


def test_group_overlay_renderer_writes_overlay_plot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    out_dir = tmp_path / "plots"
    out_dir.mkdir()
    worker = _Worker(
        str(tmp_path),
        "Angry",
        {"Central": ["Cz"]},
        "Central",
        "Angry",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        5.0,
        str(out_dir),
        stem_color="#005500",
        stem_color_b="#ff00ff",
        selected_groups=["After Creatine", "Before Creatine"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )

    worker._plot(
        [1.0, 2.0],
        {"Central": [1.5, 2.5]},
        {
            "After Creatine": {"Central": [2.0, 3.0]},
            "Before Creatine": {"Central": [1.0, 2.0]},
        },
    )

    assert (out_dir / "Angry - Central.png").is_file()
    assert (out_dir / "Angry - Central.pdf").is_file()

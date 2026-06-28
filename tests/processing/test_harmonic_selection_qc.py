from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import load_workbook

from Main_App.processing import harmonic_selection_qc
from Tools.Stats.io.stats_ready_export import HARMONIC_SELECTION_COLUMNS


def test_processing_harmonic_selection_qc_writes_quality_check_workbook_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition_root = excel_root / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": excel_root},
        event_map={"Faces": 1},
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_base_frequency_hz", lambda: 6.0)
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_bca_upper_limit_hz", lambda: 8.4)

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.workbook_path == project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    assert report.workbook_path.exists()
    assert report.selection_metadata["detected_significant_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )
    assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    workbook = load_workbook(report.workbook_path)
    assert workbook.sheetnames == ["Selection_Summary", "Harmonic_Selection"]
    harmonic_headers = [
        cell.value for cell in next(workbook["Harmonic_Selection"].iter_rows(max_row=1))
    ]
    assert harmonic_headers == HARMONIC_SELECTION_COLUMNS
    summary_values = {
        row[0].value: row[1].value
        for row in workbook["Selection_Summary"].iter_rows(min_row=2, max_col=2)
    }
    assert summary_values["Included harmonic frequencies (Hz)"] == "1.2; 2.4; 3.6; 4.8; 7.2"

    manifest = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    entries = manifest["tools"]["stats"]["group_significant_harmonics_cache"]["entries"]
    assert len(entries) == 1


def test_processing_harmonic_selection_qc_uses_project_summation_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition_root = excel_root / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {
                    "group_significant_summation_method": "significant_only",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": excel_root},
        event_map={"Faces": 1},
        preprocessing={"group_significant_summation_method": "significant_only"},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_base_frequency_hz", lambda: 6.0)
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_bca_upper_limit_hz", lambda: 8.4)

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.selection_metadata["summation_method"] == "significant_only"
    assert report.selection_metadata["detected_significant_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )
    assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )


def test_processing_harmonic_selection_qc_resolves_relative_excel_subfolder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        event_map={"Faces": 1},
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_base_frequency_hz", lambda: 6.0)
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_bca_upper_limit_hz", lambda: 8.4)

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.workbook_path == project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    assert report.workbook_path.exists()


def _write_group_policy_workbook(path: Path, *, scale: int) -> None:
    frequency_values = [round(0.3 * idx, 4) for idx in range(0, int(round(10.2 / 0.3)) + 1)]
    fft_values = []
    for idx, freq in enumerate(frequency_values):
        value = 20.0 if freq in {1.2, 3.6, 7.2} else (1.2 if idx % 2 == 0 else 0.8)
        fft_values.append(value)
    full_fft = pd.DataFrame(
        {
            f"{freq:.4f}_Hz": [value, value, value]
            for freq, value in zip(frequency_values, fft_values)
        },
        index=["O1", "O2", "FZ"],
    )
    full_fft.index.name = "Electrode"
    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale],
            "2.4000_Hz": [100.0, 100.0, 100.0],
            "3.6000_Hz": [0.5, 0.5, 0.1],
            "4.8000_Hz": [100.0, 100.0, 100.0],
            "6.0000_Hz": [100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.1],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    SOURCE_TOPOGRAPHY_METRIC_BCA,
    SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
    _read_selected_harmonics,
    build_l2_mne_conditions_from_project,
)


def test_project_input_assembler_builds_bca_condition_topographies(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(project_root)

    assert result.metric == SOURCE_TOPOGRAPHY_METRIC_BCA
    assert result.selected_harmonics_hz == (2.4, 4.8)
    assert [condition.label for condition in result.conditions] == ["Condition A", "Condition B"]
    assert result.excluded_subjects == ("P2",)
    assert result.flagged_subjects == ("P2",)
    assert result.diagnostics == ()

    condition_a = result.conditions[0]
    expected_2_4 = np.asarray([10.0 + index for index in range(64)], dtype=float)
    expected_4_8 = np.asarray([20.0 + index for index in range(64)], dtype=float)
    assert np.allclose(condition_a.harmonic_topographies[2.4], expected_2_4)
    assert np.allclose(condition_a.harmonic_topographies[4.8], expected_4_8)
    assert condition_a.metadata["source_sheet"] == "BCA (uV)"
    assert condition_a.metadata["included_subject_count"] == 1
    assert condition_a.metadata["include_flagged_subjects"] is False
    assert condition_a.metadata["flagged_subjects_included"] == []


def test_project_input_assembler_can_include_flagged_subjects(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    condition_a = result.conditions[0]
    expected_2_4 = np.asarray([10.0 + index for index in range(64)], dtype=float) + 0.5
    assert np.allclose(condition_a.harmonic_topographies[2.4], expected_2_4)
    assert condition_a.metadata["included_subject_count"] == 2
    assert condition_a.metadata["include_flagged_subjects"] is True
    assert condition_a.metadata["flagged_subjects_included"] == ["P2"]


def test_project_input_assembler_can_use_fft_amplitude_metric(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(
        project_root,
        metric=SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
        conditions=["Condition B"],
    )

    assert result.sheet_name == "FFT Amplitude (uV)"
    assert [condition.label for condition in result.conditions] == ["Condition B"]
    condition_b = result.conditions[0]
    expected = np.asarray([300.0 + index for index in range(64)], dtype=float)
    assert np.allclose(condition_b.harmonic_topographies[2.4], expected)
    assert condition_b.sensor_value_unit == "summed FFT amplitude uV"


def test_project_input_assembler_reads_group_subfolder_workbooks(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, group_subfolders=True)

    result = build_l2_mne_conditions_from_project(project_root)

    assert [condition.label for condition in result.conditions] == ["Condition A", "Condition B"]
    assert result.summaries[0].workbook_count == 2
    assert result.conditions[0].metadata["included_subject_count"] == 1


def test_project_input_assembler_splits_canonical_groups_before_aggregation(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    _convert_fixture_to_multi_group(project_root, keep_stale_flat_copy=True)

    result = build_l2_mne_conditions_from_project(
        project_root,
        include_flagged_subjects=True,
    )

    assert [condition.label for condition in result.conditions] == [
        "Control Group - Condition A",
        "Patient Group - Condition A",
        "Control Group - Condition B",
        "Patient Group - Condition B",
    ]
    assert [
        condition.metadata["group_id"] for condition in result.conditions
    ] == ["control", "patient", "control", "patient"]
    assert all(
        condition.metadata["group_split_applied"]
        for condition in result.conditions
    )
    assert result.conditions[0].metadata["included_subject_count"] == 1
    assert result.conditions[1].metadata["included_subject_count"] == 1
    assert np.isclose(result.conditions[0].harmonic_topographies[2.4][0], 10.0)
    assert np.isclose(result.conditions[1].harmonic_topographies[2.4][0], 11.0)


def test_project_input_assembler_keeps_one_group_condition_identity(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path, group_subfolders=True)
    _write_single_group_manifest(project_root)

    result = build_l2_mne_conditions_from_project(
        project_root,
        include_flagged_subjects=True,
    )

    assert [condition.condition_id for condition in result.conditions] == [
        "condition_a",
        "condition_b",
    ]
    assert [condition.label for condition in result.conditions] == [
        "Condition A",
        "Condition B",
    ]
    assert all(
        not condition.metadata["group_split_applied"]
        for condition in result.conditions
    )
    assert all(
        condition.metadata["group_id"] == "default"
        for condition in result.conditions
    )


def test_project_input_assembler_rejects_unregistered_group_workbook(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    _convert_fixture_to_multi_group(project_root, keep_stale_flat_copy=False)
    source = (
        project_root
        / "1 - Excel Data Files"
        / "Condition A"
        / "Control Group"
        / "SCP1_Condition A_Results.xlsx"
    )
    shutil.copy2(
        source,
        source.with_name("SCP3_Condition A_Results.xlsx"),
    )

    with pytest.raises(
        ValueError,
        match="workbook identity is incomplete in project.json",
    ):
        build_l2_mne_conditions_from_project(project_root)


def test_project_input_assembler_rejects_missing_selected_column(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, omit_condition_b_4_8=True)

    with pytest.raises(ValueError, match="missing columns"):
        build_l2_mne_conditions_from_project(project_root)


def test_selected_harmonic_reader_accepts_current_stats_ready_schema(tmp_path) -> None:
    stats_ready = tmp_path / "Stats_Ready_Summed_BCA.xlsx"
    with pd.ExcelWriter(stats_ready) as writer:
        pd.DataFrame(
            {
                "requested_harmonic_hz": [1.2, 2.4, 3.6, 4.8],
                "selected": [False, True, False, True],
                "included_in_summation": [False, True, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)

    assert _read_selected_harmonics(stats_ready) == (2.4, 3.6, 4.8)


def _build_project_fixture(
    tmp_path: Path,
    *,
    omit_condition_b_4_8: bool = False,
    group_subfolders: bool = False,
) -> Path:
    project_root = tmp_path / "Project"
    stats_dir = project_root / "3 - Statistical Analysis Results"
    excel_root = project_root / "1 - Excel Data Files"
    stats_dir.mkdir(parents=True)
    excel_root.mkdir(parents=True)
    _write_stats_ready(stats_dir / "Stats_Ready_Summed_BCA.xlsx")
    _write_flagged(stats_dir / "Flagged Participants.xlsx")
    _write_empty_excluded(stats_dir / "Excluded Participants.xlsx")
    for condition in ("Condition A", "Condition B"):
        condition_dir = excel_root / condition
        condition_dir.mkdir()
        workbook_dir = condition_dir / "Default" if group_subfolders else condition_dir
        workbook_dir.mkdir(exist_ok=True)
        for subject_offset, subject in enumerate(("SCP1", "SCP2")):
            _write_participant_workbook(
                workbook_dir / f"{subject}_{condition}_Results.xlsx",
                condition=condition,
                subject_offset=subject_offset,
                omit_4_8=omit_condition_b_4_8 and condition == "Condition B",
            )
    return project_root


def _write_stats_ready(path: Path) -> None:
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            {
                "condition": ["Condition A", "Condition A", "Condition B", "Condition B"],
                "subject_id": ["P1", "P2", "P1", "P2"],
                "roi": ["ROI"] * 4,
                "summed_bca_uv": [1.0, 2.0, 3.0, 4.0],
            }
        ).to_excel(writer, sheet_name="Long_Format", index=False)
        pd.DataFrame(
            {
                "harmonic_hz": [1.2, 2.4, 4.8],
                "selected": [False, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)


def _write_flagged(path: Path) -> None:
    pd.DataFrame({"participant_id": ["P2"], "flag_types": ["QC_SUMABS"]}).to_excel(
        path,
        sheet_name="Flag Summary",
        index=False,
    )


def _write_empty_excluded(path: Path) -> None:
    pd.DataFrame({"participant_id": [], "exclusion_reason": []}).to_excel(
        path,
        sheet_name="Excluded Participants",
        index=False,
    )


def _write_participant_workbook(
    path: Path,
    *,
    condition: str,
    subject_offset: int,
    omit_4_8: bool,
) -> None:
    electrodes = DEFAULT_ELECTRODE_NAMES_64
    condition_base = 10.0 if condition == "Condition A" else 100.0
    fft_base = 200.0 if condition == "Condition A" else 300.0
    bca = pd.DataFrame(
        {
            "Electrode": electrodes,
            "2.4000_Hz": [condition_base + index + subject_offset for index in range(64)],
            "4.8000_Hz": [condition_base + 10.0 + index + subject_offset for index in range(64)],
        }
    )
    fft = pd.DataFrame(
        {
            "Electrode": electrodes,
            "2.4000_Hz": [fft_base + index + subject_offset for index in range(64)],
            "4.8000_Hz": [fft_base + 10.0 + index + subject_offset for index in range(64)],
        }
    )
    if omit_4_8:
        bca = bca.drop(columns=["4.8000_Hz"])
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        fft.to_excel(writer, sheet_name="FFT Amplitude (uV)", index=False)


def _convert_fixture_to_multi_group(
    project_root: Path,
    *,
    keep_stale_flat_copy: bool,
) -> None:
    excel_root = project_root / "1 - Excel Data Files"
    for condition in ("Condition A", "Condition B"):
        condition_dir = excel_root / condition
        control_dir = condition_dir / "Control Group"
        patient_dir = condition_dir / "Patient Group"
        control_dir.mkdir()
        patient_dir.mkdir()
        control_source = condition_dir / f"SCP1_{condition}_Results.xlsx"
        patient_source = condition_dir / f"SCP2_{condition}_Results.xlsx"
        control_target = control_dir / control_source.name
        patient_target = patient_dir / patient_source.name
        shutil.move(control_source, control_target)
        shutil.move(patient_source, patient_target)
        if keep_stale_flat_copy:
            shutil.copy2(control_target, control_source)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Multi-group source input fixture",
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "control": {
                        "label": "Control Group",
                        "folder_name": "Control Group",
                        "raw_input_folder": "Raw/Control",
                    },
                    "patient": {
                        "label": "Patient Group",
                        "folder_name": "Patient Group",
                        "raw_input_folder": "Raw/Patient",
                    },
                },
                "participants": {
                    "SCP1": {"group_id": "control"},
                    "SCP2": {"group_id": "patient"},
                },
            }
        ),
        encoding="utf-8",
    )


def _write_single_group_manifest(project_root: Path) -> None:
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Single-group source input fixture",
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "default": {
                        "label": "Default",
                        "folder_name": "Default",
                        "raw_input_folder": "Raw/Default",
                    }
                },
                "participants": {
                    "SCP1": {"group_id": "default"},
                    "SCP2": {"group_id": "default"},
                },
            }
        ),
        encoding="utf-8",
    )

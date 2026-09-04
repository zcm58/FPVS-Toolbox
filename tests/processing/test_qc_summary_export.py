from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from Main_App.io.eeg_geometry import biosemi64_geometry_identity
from openpyxl import load_workbook
from openpyxl import Workbook

from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    classify_processing_inputs,
    record_processing_results,
)
from Main_App.processing.qc_summary_export import (
    QC_SUMMARY_FILENAME,
    QC_SUMMARY_HEADERS,
    RECORDING_QC_IDENTITY_HEADERS,
    DATA_QUALITY_REVIEW_FLAGS_FILENAME,
    INTERPOLATION_BURDEN_SUMMARY_SHEET,
    QUALITY_CHECK_FOLDER,
    build_processing_qc_rows,
    export_processing_qc_summary,
)
from Main_App.projects.project import Project


def _project_with_raws(tmp_path: Path):
    project = Project.load(tmp_path / "project")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_p01 = raw_dir / "P01.bdf"
    raw_p02 = raw_dir / "P02.bdf"
    raw_p01.write_bytes(b"raw p01")
    raw_p02.write_bytes(b"raw p02")
    project.input_folder = raw_dir
    project.event_map = {"Condition A": 1}
    project.save()
    return project, [
        RawFileInfo(raw_p01.resolve(), "P01"),
        RawFileInfo(raw_p02.resolve(), "P02"),
    ]


def _settings() -> dict[str, object]:
    return {
        "high_pass": 0.1,
        "low_pass": 50.0,
        "downsample": 256,
        "base_freq": 6.0,
        "oddball_freq": 1.2,
        "bca_upper_limit": 14.4,
    }


def _write_expected_output_for_first_participant(plan) -> None:
    for output_path in plan.states[0].expected_outputs:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("ok", encoding="utf-8")


def test_processing_qc_summary_rows_and_formatting(tmp_path: Path) -> None:
    project, infos = _project_with_raws(tmp_path)
    plan = classify_processing_inputs(project, infos, _settings(), project.event_map)
    _write_expected_output_for_first_participant(plan)
    results = [
        {
            "status": "ok",
            "geometry": biosemi64_geometry_identity(),
            "file": str(infos[0].path),
            "audit": {
                "n_rejected": 4,
                "raw_qc_bad_channels": ["P9"],
                "raw_qc_manual_removed_channels": ["FT7"],
                "raw_qc_low_variance_channels": ["P9"],
                "raw_qc_high_amplitude_channels": ["FT8"],
                "raw_qc_rare_burst_channels": ["P10"],
                "raw_qc_spatial_outlier_channels": ["FT7"],
                "raw_qc_warning_rules": ["possible_bad_channel_cluster"],
                "raw_qc_baseline_median_std_uv": 520.4,
                "raw_qc_baseline_median_p2p_99_uv": 1671.6,
                "raw_qc_baseline_warning": False,
                "raw_qc_baseline_excluded": False,
                "removed_electrode_original_auto_flagged": ["FT7", "P9"],
                "removed_electrode_accepted_auto_flagged": ["FT7"],
                "removed_electrode_rejected_auto_flagged": ["P9"],
                "removed_electrode_manual_additions": ["P10"],
                "removed_electrode_final_confirmed_removed": ["FT7", "P10"],
                "removed_electrode_manual_only_missed_by_auto": ["P10"],
                "removed_electrode_auto_manual_overlap": ["FT7"],
                "removed_electrode_agreement_status": "partial",
                "kurtosis_bad_channels": ["P1", "P3"],
                "kurtosis_candidate_channels": ["P1", "P3"],
                "kurtosis_review_required_channels": [],
                "kurtosis_corroborated_channels": [],
                "kurtosis_user_approved_channels": ["P3"],
                "kurtosis_user_rejected_channels": ["P1"],
                "kurtosis_qc_evidence": {
                    "status": "valid",
                    "method_label": "EEGLAB-inspired trimmed kurtosis",
                    "fingerprint": "a" * 64,
                },
                "interpolation_status": "succeeded",
                "interpolation_requested_channels": ["FT7", "P9", "P1", "P3"],
                "interpolated_channels": ["FT7", "P9", "P1", "P3"],
            },
        },
        {
            "status": "excluded",
            "file": str(infos[1].path),
            "reason": "recording_not_started",
            "message": "Header-only BDF.",
            "raw_channel_qc": {
                "bad_channels": [],
                "n_bad_channels": 0,
            },
        },
    ]

    record_processing_results(
        project,
        plan,
        results,
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    rows = build_processing_qc_rows(project, plan, results)
    assert rows == [
        {
            "PID": "P01",
            "Manually Removed Electrodes": "FT7",
            "Auto-Detected Removed Electrodes (Low SD)": "P9",
            "Preflight Auto-Flagged Removed Electrodes": "FT7, P9",
            "Accepted FPVS Auto-Flagged Electrodes": "FT7",
            "Rejected FPVS Auto-Flagged Electrodes": "P9",
            "Manual Additions": "P10",
            "Final Confirmed Removed Electrodes": "FT7, P10",
            "Manually Confirmed Only (Auto Missed)": "P10",
            "Auto and Manual Removed Electrodes": "FT7",
            "Auto/Manual Removed-Electrode Agreement": "partial",
            "Flagged Removed-Electrode Candidates (High Amplitude)": "FT8",
            "Flagged Removed-Electrode Candidates (Rare Burst)": "P10",
                "Flagged Removed-Electrode Candidates (Spatial Consistency)": "FT7",
                "Kurtosis QC Status": "valid",
                "Kurtosis Method": "EEGLAB-inspired trimmed kurtosis",
                "Kurtosis Candidate Electrodes": "P1, P3",
                "Kurtosis Review-Required Electrodes": "None",
                "Kurtosis Corroborated Automatic Electrodes": "None",
                "Kurtosis User-Approved Electrodes": "P3",
                "Kurtosis User-Rejected Electrodes": "P1",
                "Kurtosis Evidence Fingerprint": "a" * 64,
                "Interpolation Requested Electrodes": "FT7, P9, P1, P3",
                "Successfully Interpolated Electrodes": "FT7, P9, P1, P3",
                "Successfully Interpolated Count": 4,
                "Eligible Scalp Electrode Count": 64,
                "Interpolation Burden (%)": 6.25,
                "Interpolation Review (>5%)": "Review required",
                "Interpolation Outcome": "Succeeded",
                "Interpolation Detail": "None",
                "Preprocessing Status": "Completed",
                "Total Number of Electrodes removed/rejected": 4,
            "Raw QC Warnings": "possible_bad_channel_cluster",
            "Raw Baseline Median STD (uV)": "520.4",
            "Raw Baseline Median P2P99 (uV)": "1671.6",
                "Raw Baseline QC": "OK",
                "Missing Conditions": "None",
                "Exclusion Reason": "",
        },
        {
            "PID": "P02",
            "Manually Removed Electrodes": "None",
            "Auto-Detected Removed Electrodes (Low SD)": "None",
            "Preflight Auto-Flagged Removed Electrodes": "None",
            "Accepted FPVS Auto-Flagged Electrodes": "None",
            "Rejected FPVS Auto-Flagged Electrodes": "None",
            "Manual Additions": "None",
            "Final Confirmed Removed Electrodes": "None",
            "Manually Confirmed Only (Auto Missed)": "None",
            "Auto and Manual Removed Electrodes": "None",
            "Auto/Manual Removed-Electrode Agreement": "None",
            "Flagged Removed-Electrode Candidates (High Amplitude)": "None",
            "Flagged Removed-Electrode Candidates (Rare Burst)": "None",
                "Flagged Removed-Electrode Candidates (Spatial Consistency)": "None",
                "Kurtosis QC Status": "not evaluated",
                "Kurtosis Method": "Not recorded",
                "Kurtosis Candidate Electrodes": "None",
                "Kurtosis Review-Required Electrodes": "None",
                "Kurtosis Corroborated Automatic Electrodes": "None",
                "Kurtosis User-Approved Electrodes": "None",
                "Kurtosis User-Rejected Electrodes": "None",
                "Kurtosis Evidence Fingerprint": "Not recorded",
                "Interpolation Requested Electrodes": "None",
                "Successfully Interpolated Electrodes": "None",
                "Successfully Interpolated Count": "Unavailable",
                "Eligible Scalp Electrode Count": "Unavailable",
                "Interpolation Burden (%)": "Unavailable",
                "Interpolation Review (>5%)": "Unavailable",
                "Interpolation Outcome": "Skipped",
                "Interpolation Detail": "Recording was excluded before interpolation.",
                "Preprocessing Status": "Excluded before preprocessing",
                "Total Number of Electrodes removed/rejected": 0,
            "Raw QC Warnings": "None",
            "Raw Baseline Median STD (uV)": "None",
            "Raw Baseline Median P2P99 (uV)": "None",
                "Raw Baseline QC": "None",
                "Missing Conditions": "None",
                "Exclusion Reason": "Header-only BDF.",
        },
    ]

    output = export_processing_qc_summary(project, plan, results)
    assert output == (project.project_root / QUALITY_CHECK_FOLDER / QC_SUMMARY_FILENAME)
    assert output.exists()

    workbook = load_workbook(output)
    worksheet = workbook.active
    assert [cell.value for cell in worksheet[1]] == list(QC_SUMMARY_HEADERS)
    assert worksheet.auto_filter.ref == worksheet.dimensions
    assert worksheet.freeze_panes == "A2"
    assert all(cell.font.bold for cell in worksheet[1])
    for row in worksheet.iter_rows(min_row=1, max_row=3, max_col=len(QC_SUMMARY_HEADERS)):
        for cell in row:
            assert cell.alignment.horizontal == "center"
            assert cell.alignment.vertical == "center"
    assert worksheet.column_dimensions["C"].width >= len(
        "Auto-Detected Removed Electrodes (Low SD)"
    )
    burden_sheet = workbook[INTERPOLATION_BURDEN_SUMMARY_SHEET]
    burden_metrics = {
        row[0].value: row[1].value
        for row in burden_sheet.iter_rows(min_row=2, max_col=2)
    }
    assert burden_metrics["Recordings in preprocessing cohort"] == 2
    assert burden_metrics["Recordings contributing to burden summary"] == 1
    assert burden_metrics["Recordings with unavailable burden"] == 1
    assert burden_metrics["Mean interpolation burden (%)"] == pytest.approx(6.25)
    assert burden_metrics["Recordings above 5%"] == 1


def test_repeated_session_qc_is_recording_keyed_and_exports_session_identity(
    tmp_path: Path,
) -> None:
    project, legacy_infos = _project_with_raws(tmp_path)
    legacy = legacy_infos[0]
    info = RawFileInfo(
        path=legacy.path,
        subject_id="P01",
        recording_id="P01__luteal",
        session_id="luteal",
        session_label="Luteal (Visit 1)",
        visit_index=1,
        source_id="control_luteal",
    )
    plan = classify_processing_inputs(
        project,
        [info],
        _settings(),
        project.event_map,
    )
    _write_expected_output_for_first_participant(plan)
    results = [
        {
            "status": "ok",
            "geometry": biosemi64_geometry_identity(),
            "file": str(info.path),
            "audit": {
                "n_rejected": 1,
                "raw_qc_bad_channels": ["P9"],
                "interpolation_status": "succeeded",
                "interpolation_requested_channels": ["P9"],
                "interpolated_channels": ["P9"],
            },
        }
    ]
    record_processing_results(
        project,
        plan,
        results,
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    rows = build_processing_qc_rows(project, plan, results)
    assert rows[0]["PID"] == "P01"
    assert rows[0]["Recording ID"] == "P01__luteal"
    assert rows[0]["Session ID"] == "luteal"
    assert rows[0]["Visit Index"] == 1
    assert rows[0]["Successfully Interpolated Electrodes"] == "P9"
    assert rows[0]["Interpolation Burden (%)"] == pytest.approx(1.5625)

    output_path = export_processing_qc_summary(project, plan, results)
    workbook = load_workbook(output_path, read_only=True)
    worksheet = workbook.active
    expected_headers = RECORDING_QC_IDENTITY_HEADERS + QC_SUMMARY_HEADERS[1:]
    assert worksheet.title == "Preprocessing QC"
    assert [cell.value for cell in worksheet[1]] == list(expected_headers)


def test_repeated_review_flags_are_joined_by_recording_without_visit_leak(
    tmp_path: Path,
) -> None:
    project, legacy_infos = _project_with_raws(tmp_path)
    infos = [
        RawFileInfo(
            path=legacy_infos[0].path,
            subject_id="P01",
            recording_id="P01__luteal",
            session_id="luteal",
            session_label="Luteal (Visit 1)",
            visit_index=1,
            source_id="control_luteal",
        ),
        RawFileInfo(
            path=legacy_infos[1].path,
            subject_id="P01",
            recording_id="P01__follicular",
            session_id="follicular",
            session_label="Follicular (Visit 2)",
            visit_index=2,
            source_id="control_follicular",
        ),
    ]
    plan = classify_processing_inputs(
        project,
        infos,
        _settings(),
        project.event_map,
    )
    qc_dir = project.project_root / QUALITY_CHECK_FOLDER
    qc_dir.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Review Flags"
    worksheet.append(
        (
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Group",
            "Source File",
            "Flagged Item",
        )
    )
    worksheet.append(
        (
            "P01",
            "P01__luteal",
            "Luteal (Visit 1)",
            "1",
            "Control",
            legacy_infos[0].path.name,
            "high-amplitude channel(s): F8, FC6",
        )
    )
    workbook.save(qc_dir / DATA_QUALITY_REVIEW_FLAGS_FILENAME)

    rows = build_processing_qc_rows(project, plan, [])
    by_recording = {str(row["Recording ID"]): row for row in rows}

    assert by_recording["P01__luteal"][
        "Flagged Removed-Electrode Candidates (High Amplitude)"
    ] == "F8, FC6"
    assert by_recording["P01__follicular"][
        "Flagged Removed-Electrode Candidates (High Amplitude)"
    ] == "None"


def test_processing_qc_summary_uses_ledger_for_skipped_completed_participant(tmp_path: Path) -> None:
    project, infos = _project_with_raws(tmp_path)
    plan = classify_processing_inputs(project, infos[:1], _settings(), project.event_map)
    _write_expected_output_for_first_participant(plan)
    record_processing_results(
        project,
        plan,
        [
            {
                "status": "ok",
                "geometry": biosemi64_geometry_identity(),
                "file": str(infos[0].path),
                "audit": {
                    "n_rejected": 3,
                    "raw_qc_bad_channels": ["P9"],
                    "raw_qc_manual_removed_channels": ["FT7"],
                    "removed_electrode_original_auto_flagged": ["FT7"],
                    "removed_electrode_accepted_auto_flagged": ["FT7"],
                    "removed_electrode_rejected_auto_flagged": [],
                    "removed_electrode_manual_additions": ["P9"],
                    "removed_electrode_final_confirmed_removed": ["FT7", "P9"],
                    "removed_electrode_manual_only_missed_by_auto": ["P9"],
                    "removed_electrode_auto_manual_overlap": ["FT7"],
                    "removed_electrode_agreement_status": "partial",
                    "kurtosis_bad_channels": ["Oz"],
                    "interpolation_status": "succeeded",
                    "interpolation_requested_channels": ["FT7", "P9", "Oz"],
                    "interpolated_channels": ["FT7", "P9", "Oz"],
                },
            }
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    # Simulate a later incremental run where P01 was already completed and skipped.
    rows = build_processing_qc_rows(project, plan, [])
    assert rows[0]["Preprocessing Status"] == "Completed"
    assert rows[0]["Exclusion Reason"] == ""
    assert rows[0]["Missing Conditions"] == "None"
    assert rows[0]["Manually Removed Electrodes"] == "FT7"
    assert rows[0]["Auto-Detected Removed Electrodes (Low SD)"] == "P9"
    assert rows[0]["Preflight Auto-Flagged Removed Electrodes"] == "FT7"
    assert rows[0]["Accepted FPVS Auto-Flagged Electrodes"] == "FT7"
    assert rows[0]["Rejected FPVS Auto-Flagged Electrodes"] == "None"
    assert rows[0]["Manual Additions"] == "P9"
    assert rows[0]["Final Confirmed Removed Electrodes"] == "FT7, P9"
    assert rows[0]["Manually Confirmed Only (Auto Missed)"] == "P9"
    assert rows[0]["Auto and Manual Removed Electrodes"] == "FT7"
    assert rows[0]["Auto/Manual Removed-Electrode Agreement"] == "partial"
    assert rows[0]["Flagged Removed-Electrode Candidates (High Amplitude)"] == "None"
    assert rows[0]["Flagged Removed-Electrode Candidates (Spatial Consistency)"] == "None"
    assert rows[0]["Kurtosis Candidate Electrodes"] == "Oz"
    assert rows[0]["Successfully Interpolated Electrodes"] == "FT7, P9, Oz"
    assert rows[0]["Total Number of Electrodes removed/rejected"] == 3

    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert ledger["entries"]["P01"]["raw_qc_bad_channels"] == ["P9"]
    assert ledger["entries"]["P01"]["raw_qc_manual_removed_channels"] == ["FT7"]
    assert ledger["entries"]["P01"]["removed_electrode_manual_additions"] == ["P9"]
    assert (
        ledger["entries"]["P01"]["removed_electrode_agreement_status"] == "partial"
    )
    assert ledger["entries"]["P01"]["interpolated_channels"] == ["FT7", "P9", "Oz"]


def test_processing_qc_summary_merges_saved_preflight_review_flags(
    tmp_path: Path,
) -> None:
    project, infos = _project_with_raws(tmp_path)
    plan = classify_processing_inputs(project, infos[:1], _settings(), project.event_map)
    _write_expected_output_for_first_participant(plan)
    record_processing_results(
        project,
        plan,
        [
            {
                "status": "ok",
                "geometry": biosemi64_geometry_identity(),
                "file": str(infos[0].path),
                "audit": {
                    "n_rejected": 1,
                    "kurtosis_bad_channels": ["Oz"],
                    "interpolation_status": "succeeded",
                    "interpolation_requested_channels": ["Oz"],
                    "interpolated_channels": ["Oz"],
                },
            }
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    qc_dir = project.project_root / QUALITY_CHECK_FOLDER
    qc_dir.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Review Flags"
    worksheet.append(("PID", "Group", "Source File", "Flagged Item"))
    worksheet.append(
        (
            "P01",
            "Single group",
            "P01.bdf",
            "high-amplitude channel(s): F8, FC6; spatially inconsistent channel(s): AF7, C6",
        )
    )
    worksheet.append(
        (
            "P01",
            "Single group",
            "P01.bdf",
            "raw data warning rule(s): possible_bad_channel_cluster",
        )
    )
    workbook.save(qc_dir / DATA_QUALITY_REVIEW_FLAGS_FILENAME)

    rows = build_processing_qc_rows(project, plan, [])

    assert rows[0]["Flagged Removed-Electrode Candidates (High Amplitude)"] == "F8, FC6"
    assert rows[0]["Flagged Removed-Electrode Candidates (Spatial Consistency)"] == "AF7, C6"
    assert rows[0]["Raw QC Warnings"] == "possible_bad_channel_cluster"
    assert rows[0]["Kurtosis Candidate Electrodes"] == "Oz"
    assert rows[0]["Successfully Interpolated Electrodes"] == "Oz"


def test_processing_qc_summary_flags_partial_condition_participant(tmp_path: Path) -> None:
    project, infos = _project_with_raws(tmp_path)
    project.event_map = {"Condition A": 1, "Condition B": 2}
    project.save()
    plan = classify_processing_inputs(project, infos[:1], _settings(), project.event_map)
    present_output = plan.states[0].expected_outputs[0]
    present_output.parent.mkdir(parents=True, exist_ok=True)
    present_output.write_text("ok", encoding="utf-8")
    results = [
        {
            "status": "ok",
            "geometry": biosemi64_geometry_identity(),
            "file": str(infos[0].path),
            "audit": {
                "n_rejected": 3,
                "raw_qc_bad_channels": ["P9"],
                "raw_qc_manual_removed_channels": ["FT7"],
                "kurtosis_bad_channels": ["P8"],
                "interpolation_status": "succeeded",
                "interpolation_requested_channels": ["FT7", "P9", "P8"],
                "interpolated_channels": ["FT7", "P9", "P8"],
            },
        }
    ]

    record_processing_results(
        project,
        plan,
        results,
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    rows = build_processing_qc_rows(project, plan, results)

    assert rows[0]["Missing Conditions"] == "Condition B"
    assert rows[0]["Preprocessing Status"] == "Completed with missing conditions"
    assert rows[0]["Exclusion Reason"] == ""
    assert rows[0]["Manually Removed Electrodes"] == "FT7"
    assert rows[0]["Auto-Detected Removed Electrodes (Low SD)"] == "P9"
    assert rows[0]["Flagged Removed-Electrode Candidates (High Amplitude)"] == "None"
    assert rows[0]["Flagged Removed-Electrode Candidates (Spatial Consistency)"] == "None"
    assert rows[0]["Kurtosis Candidate Electrodes"] == "P8"


def test_processing_qc_summary_uses_matching_cache_for_legacy_failed_entry(tmp_path: Path) -> None:
    project, infos = _project_with_raws(tmp_path)
    plan = classify_processing_inputs(project, infos[:1], _settings(), project.event_map)
    raw_stat = infos[0].path.stat()
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "P01": {
                        "participant_id": "P01",
                        "raw_file": str(infos[0].path),
                        "raw_size": raw_stat.st_size,
                        "raw_mtime_ns": raw_stat.st_mtime_ns,
                        "status": "failed",
                        "raw_qc_bad_channels": [],
                        "kurtosis_bad_channels": [],
                        "interpolated_channels": [],
                        "n_rejected": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cache_dir = project.project_root / ".fpvs_cache" / "preprocessed"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "P01_fake.json").write_text(
        json.dumps(
            {
                "payload": {
                    "source_path": str(infos[0].path),
                    "source_size": raw_stat.st_size,
                    "source_mtime_ns": raw_stat.st_mtime_ns,
                },
                    "raw_qc_bad_channels": ["P9"],
                    "raw_qc_manual_removed_channels": ["FT7"],
                    "kurtosis_bad_channels": ["P8"],
                    "interpolated_channels": ["FT7", "P9", "P8"],
                    "n_rejected": 3,
            }
        ),
        encoding="utf-8",
    )

    rows = build_processing_qc_rows(project, plan, [])

    assert rows[0]["Preprocessing Status"] == "Not recorded (legacy result)"
    assert rows[0]["Exclusion Reason"] == ""
    assert rows[0]["Missing Conditions"] == "None"
    assert rows[0]["Manually Removed Electrodes"] == "FT7"
    assert rows[0]["Auto-Detected Removed Electrodes (Low SD)"] == "P9"
    assert rows[0]["Flagged Removed-Electrode Candidates (High Amplitude)"] == "None"
    assert rows[0]["Flagged Removed-Electrode Candidates (Spatial Consistency)"] == "None"
    assert rows[0]["Kurtosis Candidate Electrodes"] == "P8"
    assert rows[0]["Successfully Interpolated Electrodes"] == "Not recorded"
    assert rows[0]["Interpolation Burden (%)"] == "Unavailable"
    assert rows[0]["Total Number of Electrodes removed/rejected"] == 3


def test_processing_qc_summary_indexes_cache_once_and_uses_newest_matching_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project, infos = _project_with_raws(tmp_path)
    plan = classify_processing_inputs(project, infos, _settings(), project.event_map)
    raw_stats = [info.path.stat() for info in infos]
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    info.subject_id: {
                        "participant_id": info.subject_id,
                        "raw_file": str(info.path),
                        "raw_size": raw_stat.st_size,
                        "raw_mtime_ns": raw_stat.st_mtime_ns,
                        "status": "failed",
                        "n_rejected": 0,
                    }
                    for info, raw_stat in zip(infos, raw_stats)
                },
            }
        ),
        encoding="utf-8",
    )
    cache_dir = project.project_root / ".fpvs_cache" / "preprocessed"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def write_metadata(
        name: str,
        *,
        source_path: Path,
        source_size: int,
        source_mtime_ns: int,
        manual_channels: list[str],
        metadata_mtime_ns: int,
    ) -> Path:
        meta_path = cache_dir / name
        meta_path.write_text(
            json.dumps(
                {
                    "payload": {
                        "source_path": str(source_path),
                        "source_size": source_size,
                        "source_mtime_ns": source_mtime_ns,
                    },
                    "raw_qc_manual_removed_channels": manual_channels,
                }
            ),
            encoding="utf-8",
        )
        os.utime(
            meta_path,
            ns=(metadata_mtime_ns, metadata_mtime_ns),
        )
        return meta_path

    p01_old = write_metadata(
        "P01_old.json",
        source_path=infos[0].path,
        source_size=raw_stats[0].st_size,
        source_mtime_ns=raw_stats[0].st_mtime_ns,
        manual_channels=["FT7"],
        metadata_mtime_ns=1_700_000_000_000_000_000,
    )
    p01_new = write_metadata(
        "P01_new.json",
        source_path=infos[0].path,
        source_size=raw_stats[0].st_size,
        source_mtime_ns=raw_stats[0].st_mtime_ns,
        manual_channels=["P9"],
        metadata_mtime_ns=1_700_000_001_000_000_000,
    )
    p02 = write_metadata(
        "P02.json",
        source_path=infos[1].path,
        source_size=raw_stats[1].st_size,
        source_mtime_ns=raw_stats[1].st_mtime_ns,
        manual_channels=["P10"],
        metadata_mtime_ns=1_700_000_002_000_000_000,
    )
    wrong_identity = write_metadata(
        "P01_wrong_size.json",
        source_path=infos[0].path,
        source_size=raw_stats[0].st_size + 1,
        source_mtime_ns=raw_stats[0].st_mtime_ns,
        manual_channels=["Cz"],
        metadata_mtime_ns=1_700_000_003_000_000_000,
    )
    malformed = cache_dir / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    metadata_paths = {
        p01_old,
        p01_new,
        p02,
        wrong_identity,
        malformed,
    }
    read_counts = {path: 0 for path in metadata_paths}
    original_read_text = Path.read_text

    def counted_read_text(self: Path, *args, **kwargs) -> str:
        if self in read_counts:
            read_counts[self] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    rows = build_processing_qc_rows(project, plan, [])

    assert rows[0]["Manually Removed Electrodes"] == "P9"
    assert rows[1]["Manually Removed Electrodes"] == "P10"
    assert set(read_counts.values()) == {1}


def test_processing_qc_summary_treats_legacy_missing_condition_as_included(
    tmp_path: Path,
) -> None:
    project, infos = _project_with_raws(tmp_path)
    project.event_map = {"Condition A": 1, "Condition B": 2}
    project.save()
    plan = classify_processing_inputs(project, infos[:1], _settings(), project.event_map)
    present_output = plan.states[0].expected_outputs[0]
    present_output.parent.mkdir(parents=True, exist_ok=True)
    present_output.write_text("ok", encoding="utf-8")
    raw_stat = infos[0].path.stat()
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "P01": {
                        "participant_id": "P01",
                        "raw_file": str(infos[0].path),
                        "raw_size": raw_stat.st_size,
                        "raw_mtime_ns": raw_stat.st_mtime_ns,
                        "status": "failed",
                        "raw_qc_bad_channels": ["P9"],
                        "kurtosis_bad_channels": ["P8"],
                        "interpolated_channels": ["P9", "P8"],
                        "n_rejected": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    rows = build_processing_qc_rows(project, plan, [])

    assert rows[0]["Missing Conditions"] == "Condition B"
    assert rows[0]["Preprocessing Status"] == "Not recorded (legacy result)"

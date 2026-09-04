from __future__ import annotations

from pathlib import Path
import threading
import time

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import attach_raw_biosemi64_geometry
from Main_App.io.load_utils import BdfPreflightInfo
from Main_App.processing.processing_controller import RawFileInfo
import Main_App.processing.preflight_qc as preflight_qc
from Main_App.processing.preflight_qc import (
    PreflightConditionCropObservation,
    PreflightQcFileResult,
    PreflightQcScan,
    build_preflight_condition_crop_grid_audit,
    scan_preprocessing_qc,
    scan_recording_not_started_files,
)
from Main_App.projects import FrequencyProtocol


def _raw_with_removed_channel(channel: str) -> mne.io.RawArray:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = list(montage.ch_names)
    rng = np.random.default_rng(99)
    data = rng.normal(scale=500e-6, size=(len(names), 4096))
    data[names.index(channel)] = rng.normal(scale=2e-6, size=data.shape[1])
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=256.0, ch_types=["eeg"] * len(names)),
        verbose=False,
    )
    raw.set_montage(montage)
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=names,
    )
    return raw


def test_scan_recording_not_started_files_uses_bdf_header(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "P01.bdf"
    raw_path.write_bytes(b"header")

    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.inspect_bdf_header",
        lambda _path: BdfPreflightInfo(
            file_size=19_000,
            header_bytes=19_000,
            data_records=0,
            record_duration=1.0,
            channel_count=72,
        ),
    )

    flagged = scan_recording_not_started_files(
        [RawFileInfo(raw_path, "P01", "control")]
    )

    assert len(flagged) == 1
    assert flagged[0].participant_id == "P01"
    assert flagged[0].path == raw_path
    assert flagged[0].group_id == "control"


def test_scan_carries_canonical_project_frequency_protocol() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        10,
        5,
        expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source="manual",
    )

    scan = scan_preprocessing_qc([], {"frequency_protocol": protocol})

    assert scan.oddball_frequency_hz == 2.0
    assert scan.frequency_protocol_fingerprint == protocol.fingerprint


def test_unscoped_preflight_reports_not_evaluated_without_loading_signal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P03.bdf"
    raw_path.write_bytes(b"not a real bdf for this unit test")

    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.inspect_bdf_header",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.load_eeg_file",
        lambda *_args, **_kwargs: pytest.fail("unscoped preflight must not load EEG"),
    )

    scan = scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P03", "patient")],
        {"stim_channel": "Status", "max_bad_chans": 20},
    )

    assert scan.cancelled is False
    assert scan.suggested_removed_electrodes == {}
    assert scan.hard_exclusion_candidates == ()
    assert scan.results[0].group_id == "patient"
    assert scan.results[0].raw_channel_qc is None
    assert scan.results[0].raw_spectral_qc is None
    assert scan.results[0].condition_qc == {
        "method_name": "condition_aware_preflight_qc",
        "method_version": "v7_analyzed_condition_scope",
        "evaluation_status": "not_evaluated",
        "cache_status": "not_evaluated",
        "reason": "missing_analyzed_interval_context",
        "message": (
            "Signal-based preflight QC was not evaluated because an active project "
            "root and condition event map are required to define the analyzed intervals."
        ),
    }


def test_unscoped_preflight_preserves_group_id_without_reporting_load_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P04.bdf"
    raw_path.write_bytes(b"not a real bdf for this unit test")
    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)

    monkeypatch.setattr(
        preflight_qc.load_utils,
        "load_eeg_file",
        lambda *_args, **_kwargs: pytest.fail("unscoped preflight must not load EEG"),
    )

    scan = scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P04", "patient")],
        {"stim_channel": "Status", "max_bad_chans": 20},
    )

    assert scan.results[0].group_id == "patient"
    assert scan.results[0].load_error is None
    assert scan.results[0].condition_qc["evaluation_status"] == "not_evaluated"


def test_legacy_preflight_loader_forwards_project_geometry_and_stim(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def _fake_load(_app, path, **kwargs):
        observed["path"] = path
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(preflight_qc.load_utils, "load_eeg_file", _fake_load)
    raw_path = tmp_path / "ab_labels.bdf"

    loaded = preflight_qc._load_raw_for_preflight(
        raw_path,
        {
            "ref_channel1": "EXG3",
            "ref_channel2": "EXG4",
            "stim_channel": "Trigger",
            "electrode_montage": "biosemi64",
            "electrode_mapping_profile": "biosemi64_1020_ab_v1",
        },
    )

    assert loaded is not None
    assert observed == {
        "path": str(raw_path),
        "ref_pair": ("EXG3", "EXG4"),
        "first_n_channels": 64,
        "stim_channel": "Trigger",
        "electrode_montage": "biosemi64",
        "electrode_mapping_profile": "biosemi64_1020_ab_v1",
    }


def test_preflight_suggestions_exclude_unselected_review_only_signal_classes(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        results=(
            PreflightQcFileResult(
                path=tmp_path / "P37.bdf",
                participant_id="P37",
                load_error=None,
                raw_channel_qc={
                    "channels_to_interpolate": ["FT7"],
                    "high_amplitude_channels": ["P9"],
                    "rare_burst_channels": ["P10"],
                },
                raw_spectral_qc=None,
            ),
        )
    )

    assert scan.suggested_removed_electrodes == {"P37": ["FT7"]}
    assert scan.suspicious_results == scan.results


def test_review_only_amplitude_and_burden_findings_reach_decision_review(
    tmp_path: Path,
) -> None:
    severe = PreflightQcFileResult(
        path=tmp_path / "P38.bdf",
        participant_id="P38",
        load_error=None,
        raw_channel_qc={
            "excluded": False,
            "raw_amplitude_review_findings": [
                {"severity": "severe_review", "authority": "review_only"}
            ],
        },
        raw_spectral_qc=None,
    )
    burden = PreflightQcFileResult(
        path=tmp_path / "P39.bdf",
        participant_id="P39",
        load_error=None,
        raw_channel_qc={
            "excluded": False,
            "candidate_burden_findings": [
                {"rule": "candidate_count_review", "authority": "review_only"}
            ],
        },
        raw_spectral_qc=None,
    )
    warning_only = PreflightQcFileResult(
        path=tmp_path / "P40.bdf",
        participant_id="P40",
        load_error=None,
        raw_channel_qc={
            "excluded": False,
            "raw_amplitude_review_findings": [
                {"severity": "warning_review", "authority": "review_only"}
            ],
        },
        raw_spectral_qc=None,
    )
    scan = PreflightQcScan(results=(severe, burden, warning_only))

    assert scan.hard_exclusion_candidates == (severe, burden)
    assert scan.suspicious_results == (severe, burden, warning_only)


def test_scan_preprocessing_qc_uses_parallel_workers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paths = []
    for index in range(6):
        raw_path = tmp_path / f"P{index + 1:02d}.bdf"
        raw_path.write_bytes(b"not a real bdf for this unit test")
        paths.append(raw_path)

    lock = threading.Lock()
    active = 0
    max_active = 0

    def _fake_scan(info, *_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return PreflightQcFileResult(
                path=Path(info.path),
                participant_id=str(info.subject_id),
                group_id=str(info.group),
                load_error=None,
                raw_channel_qc=None,
                raw_spectral_qc=None,
                condition_qc={"evaluation_status": "not_evaluated"},
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(preflight_qc, "_scan_one_preflight_file", _fake_scan)

    scan = scan_preprocessing_qc(
        [
            RawFileInfo(
                path,
                f"P{index + 1:02d}",
                "control" if index % 2 == 0 else "patient",
            )
            for index, path in enumerate(paths)
        ],
        {"stim_channel": "Status", "max_bad_chans": 20},
        max_workers=3,
    )

    assert scan.cancelled is False
    assert max_active > 1
    assert [result.participant_id for result in scan.results] == [
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
    ]
    assert [result.group_id for result in scan.results] == [
        "control",
        "patient",
        "control",
        "patient",
        "control",
        "patient",
    ]


def _condition_crop_result(
    tmp_path: Path,
    participant_id: str,
    condition: str,
    *,
    oddball_cycles: int,
    repetitions: int = 1,
    oddball_frequency_hz: float = 1.2,
) -> PreflightQcFileResult:
    sfreq = 256.0
    sample_count = int(round((oddball_cycles / oddball_frequency_hz) * sfreq))
    return PreflightQcFileResult(
        path=tmp_path / f"{participant_id}.bdf",
        participant_id=participant_id,
        group_id="control",
        load_error=None,
        raw_channel_qc={},
        raw_spectral_qc={},
        condition_qc={
            "event_plan": {
                "sfreq": sfreq,
                "spans": [
                    {
                        "condition_id": 22,
                        "condition_label": condition,
                        "repetition_index": repetition,
                        "spectral_start_sample": repetition * 100_000,
                        "spectral_stop_sample": repetition * 100_000
                        + sample_count,
                        "spectral_fallback_reason": None,
                    }
                    for repetition in range(repetitions)
                ],
            }
        },
    )


def test_preflight_crop_grid_audit_flags_condition_against_project_majority(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _condition_crop_result(tmp_path, "P1", "Faces", oddball_cycles=144),
            _condition_crop_result(tmp_path, "P2", "Faces", oddball_cycles=144),
            _condition_crop_result(
                tmp_path,
                "P3",
                "Negative Valence",
                oddball_cycles=144,
                repetitions=3,
            ),
            _condition_crop_result(
                tmp_path,
                "P4",
                "Negative Valence",
                oddball_cycles=21,
                repetitions=3,
            ),
        )
    )

    audit = build_preflight_condition_crop_grid_audit(scan)

    assert audit.reference_oddball_cycles == 144
    assert audit.reference_duration_s == 120.0
    assert audit.reference_support == 3
    assert audit.reference_total == 4
    assert [
        (
            candidate.participant_id,
            candidate.condition_label,
            candidate.oddball_cycles,
            candidate.repetition_count,
        )
        for candidate in audit.review_candidates
    ] == [("P4", "Negative Valence", 21, 3)]


def test_preflight_crop_grid_audit_uses_project_oddball_rate_and_fingerprint(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=2.0,
        frequency_protocol_fingerprint="project-protocol-fingerprint",
        results=(
            _condition_crop_result(
                tmp_path,
                "P1",
                "Faces",
                oddball_cycles=100,
                oddball_frequency_hz=2.0,
            ),
            _condition_crop_result(
                tmp_path,
                "P2",
                "Faces",
                oddball_cycles=100,
                oddball_frequency_hz=2.0,
            ),
        ),
    )

    audit = build_preflight_condition_crop_grid_audit(scan)

    assert audit.reference_oddball_cycles == 100
    assert audit.reference_duration_s == 50.0
    assert audit.oddball_frequency_hz == 2.0
    assert audit.frequency_protocol_fingerprint == "project-protocol-fingerprint"


def test_preflight_crop_grid_audit_excludes_saved_pairs_from_reference(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _condition_crop_result(tmp_path, "P1", "Faces", oddball_cycles=144),
            _condition_crop_result(tmp_path, "P2", "Faces", oddball_cycles=144),
            _condition_crop_result(
                tmp_path,
                "P4",
                "Negative Valence",
                oddball_cycles=21,
            ),
        )
    )

    audit = build_preflight_condition_crop_grid_audit(
        scan,
        excluded_participant_conditions={"p4": ["negative valence"]},
    )

    assert audit.reference_oddball_cycles == 144
    assert audit.review_candidates == ()
    observation = next(
        row for row in audit.observations if row.participant_id == "P4"
    )
    assert observation.already_excluded is True


def test_preflight_crop_grid_audit_does_not_guess_from_tied_grids(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _condition_crop_result(tmp_path, "P1", "Faces", oddball_cycles=144),
            _condition_crop_result(tmp_path, "P2", "Faces", oddball_cycles=21),
        )
    )

    audit = build_preflight_condition_crop_grid_audit(scan)

    assert audit.reference_oddball_cycles is None
    assert audit.has_unresolved_grid_conflict is True
    assert [row.participant_id for row in audit.review_candidates] == [
        "P1",
        "P2",
    ]
    assert audit.recommended_exclusions == ()
    assert audit.is_compatible_with_exclusions({}) is False
    assert audit.is_compatible_with_exclusions({"P2": ["Faces"]}) is True


def test_preflight_crop_grid_audit_uses_existing_project_grids_as_reference(
    tmp_path: Path,
) -> None:
    project_observations = tuple(
        PreflightConditionCropObservation(
            path=tmp_path / f"P{index}_Faces_Results.xlsx",
            participant_id=f"P{index}",
            group_id="control",
            condition_label="Faces",
            condition_id=1,
            repetition_count=0,
            oddball_cycles=144,
            duration_s=120.0,
            issue=None,
        )
        for index in (1, 2)
    )
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _condition_crop_result(
                tmp_path,
                "P4",
                "Negative Valence",
                oddball_cycles=21,
            ),
        ),
        project_grid_observations=project_observations,
    )

    audit = build_preflight_condition_crop_grid_audit(scan)

    assert audit.reference_oddball_cycles == 144
    assert audit.reference_support == 2
    assert audit.reference_total == 3
    assert [row.participant_id for row in audit.review_candidates] == ["P4"]


def test_preflight_current_raw_grid_replaces_existing_pair_observation(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _condition_crop_result(
                tmp_path,
                "P1",
                "Faces",
                oddball_cycles=21,
            ),
        ),
        project_grid_observations=(
            PreflightConditionCropObservation(
                path=tmp_path / "P1_Faces_Results.xlsx",
                participant_id="P1",
                group_id="control",
                condition_label="Faces",
                condition_id=1,
                repetition_count=0,
                oddball_cycles=144,
                duration_s=120.0,
                issue=None,
            ),
            PreflightConditionCropObservation(
                path=tmp_path / "P2_Faces_Results.xlsx",
                participant_id="P2",
                group_id="control",
                condition_label="Faces",
                condition_id=1,
                repetition_count=0,
                oddball_cycles=144,
                duration_s=120.0,
                issue=None,
            ),
        ),
    )

    audit = build_preflight_condition_crop_grid_audit(scan)

    assert audit.reference_oddball_cycles is None
    assert audit.reference_total == 2
    assert sorted(row.oddball_cycles for row in audit.observations) == [21, 144]

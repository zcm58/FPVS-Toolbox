from __future__ import annotations

from pathlib import Path
import threading
import time

import mne
import numpy as np

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


def test_scan_preprocessing_qc_prepopulates_auto_removed_electrodes(
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
        lambda *_args, **_kwargs: _raw_with_removed_channel("P9"),
    )

    scan = scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P03", "patient")],
        {"stim_channel": "Status", "max_bad_chans": 20},
    )

    assert scan.cancelled is False
    assert scan.suggested_removed_electrodes == {"P03": ["P9"]}
    assert scan.hard_exclusion_candidates == ()
    assert scan.results[0].group_id == "patient"


def test_scan_preprocessing_qc_preserves_group_id_on_load_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P04.bdf"
    raw_path.write_bytes(b"not a real bdf for this unit test")
    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)

    def _raise_load_error(*_args, **_kwargs):
        raise RuntimeError("load failed")

    monkeypatch.setattr(
        preflight_qc.load_utils,
        "load_eeg_file",
        _raise_load_error,
    )

    scan = scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P04", "patient")],
        {"stim_channel": "Status", "max_bad_chans": 20},
    )

    assert scan.results[0].group_id == "patient"
    assert scan.results[0].load_error == "load failed"


def test_preflight_suggestions_include_review_only_removed_electrode_classes(
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

    assert scan.suggested_removed_electrodes == {"P37": ["FT7", "P9", "P10"]}
    assert scan.suspicious_results == scan.results


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

    class _RawQcResult:
        excluded = False
        reason = None
        message = ""

        def to_payload(self) -> dict[str, object]:
            return {"channels_to_interpolate": []}

    class _SpectralQcResult:
        def to_payload(self) -> dict[str, object]:
            return {"evaluated": True, "widespread": False, "flagged_channels": []}

    def _fake_load(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return object()
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(preflight_qc.load_utils, "load_eeg_file", _fake_load)
    monkeypatch.setattr(
        preflight_qc,
        "evaluate_raw_channel_qc",
        lambda *_args, **_kwargs: _RawQcResult(),
    )
    monkeypatch.setattr(
        preflight_qc,
        "evaluate_raw_spectral_qc",
        lambda *_args, **_kwargs: _SpectralQcResult(),
    )

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
) -> PreflightQcFileResult:
    sfreq = 256.0
    sample_count = int(round((oddball_cycles / 1.2) * sfreq))
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


def test_preflight_crop_grid_audit_excludes_saved_pairs_from_reference(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
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

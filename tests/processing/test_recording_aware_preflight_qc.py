from __future__ import annotations

from pathlib import Path

from Main_App.processing.preflight_qc import (
    PreflightQcFileResult,
    PreflightQcScan,
    _preflight_file_identity,
    build_preflight_condition_crop_grid_audit,
)


def _result(
    tmp_path: Path,
    *,
    recording_id: str,
    visit_index: int,
    oddball_cycles: int,
) -> PreflightQcFileResult:
    sfreq = 256.0
    sample_count = int(round((oddball_cycles / 1.2) * sfreq))
    return PreflightQcFileResult(
        path=tmp_path / f"{recording_id}.bdf",
        participant_id="P01",
        group_id="control",
        recording_id=recording_id,
        session_id=f"session_{visit_index}",
        session_label="Luteal" if visit_index == 1 else "Follicular",
        visit_index=visit_index,
        load_error=None,
        raw_channel_qc={"channels_to_interpolate": [f"P{visit_index}"]},
        raw_spectral_qc={},
        condition_qc={
            "event_plan": {
                "sfreq": sfreq,
                "spans": [
                    {
                        "condition_id": 1,
                        "condition_label": "Faces",
                        "spectral_start_sample": 0,
                        "spectral_stop_sample": sample_count,
                        "spectral_fallback_reason": None,
                    }
                ],
            }
        },
    )


def test_suggested_removed_electrodes_are_keyed_by_recording_not_participant(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _result(
                tmp_path,
                recording_id="P01__luteal",
                visit_index=1,
                oddball_cycles=144,
            ),
            _result(
                tmp_path,
                recording_id="P01__follicular",
                visit_index=2,
                oddball_cycles=21,
            ),
        )
    )

    assert scan.suggested_removed_electrodes == {
        "P01__luteal": ["P1"],
        "P01__follicular": ["P2"],
    }


def test_recording_condition_exclusion_removes_only_one_visit(
    tmp_path: Path,
) -> None:
    scan = PreflightQcScan(
        oddball_frequency_hz=1.2,
        results=(
            _result(
                tmp_path,
                recording_id="P01__luteal",
                visit_index=1,
                oddball_cycles=144,
            ),
            _result(
                tmp_path,
                recording_id="P01__follicular",
                visit_index=2,
                oddball_cycles=21,
            ),
        )
    )

    audit = build_preflight_condition_crop_grid_audit(
        scan,
        excluded_recording_conditions={"p01__follicular": ["faces"]},
    )

    by_recording = {
        observation.recording_id: observation for observation in audit.observations
    }
    assert by_recording["P01__luteal"].already_excluded is False
    assert by_recording["P01__follicular"].already_excluded is True
    assert audit.is_compatible_with_exclusions(
        {},
        recording_exclusions={"P01__follicular": ["Faces"]},
    ) is True


def test_cache_identity_adds_recording_to_source_stat_identity(
    tmp_path: Path,
) -> None:
    raw_file = tmp_path / "P01.bdf"
    raw_file.write_bytes(b"identity")

    legacy = _preflight_file_identity(raw_file)
    recording = _preflight_file_identity(
        raw_file,
        recording_id="P01__luteal",
    )

    assert set(legacy) == {"resolved_path", "size", "mtime_ns", "ctime_ns"}
    assert recording == {**legacy, "recording_id": "P01__luteal"}

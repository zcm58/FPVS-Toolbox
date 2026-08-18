from __future__ import annotations

from pathlib import Path

from Main_App.processing.full_fft_grid_qc import (
    FullFftGridAudit,
    FullFftGridObservation,
)


def _observation(recording_id: str, visit_index: int, cycles: int) -> FullFftGridObservation:
    duration = cycles / 1.2
    return FullFftGridObservation(
        participant_id="P01",
        recording_id=recording_id,
        session_id=f"session_{visit_index}",
        session_label="Luteal" if visit_index == 1 else "Follicular",
        visit_index=visit_index,
        condition="Faces",
        path=Path(f"{recording_id}_Faces_Results.xlsx"),
        group_id="control",
        group_label="No Birth Control",
        oddball_cycles=cycles,
        duration_s=duration,
        bin_spacing_hz=1.0 / duration,
        frequency_column_count=cycles * 10,
        issue=None,
        already_excluded=False,
    )


def test_full_fft_recording_exclusion_does_not_remove_sibling_visit() -> None:
    luteal = _observation("P01__luteal", 1, 144)
    follicular = _observation("P01__follicular", 2, 21)
    audit = FullFftGridAudit(
        observations=(luteal, follicular),
        reference_oddball_cycles=None,
        reference_support=1,
        reference_total=2,
    )

    assert luteal.pair_key == ("p01__luteal", "faces")
    assert follicular.participant_pair_key == ("p01", "faces")
    assert audit.is_compatible_with_exclusions({}) is False
    assert audit.is_compatible_with_exclusions(
        {},
        recording_exclusions={"P01__follicular": ["Faces"]},
    ) is True
    assert audit.is_compatible_with_exclusions({"P01": ["Faces"]}) is False

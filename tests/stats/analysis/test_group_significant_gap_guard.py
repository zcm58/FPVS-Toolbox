from __future__ import annotations

import pytest

from Tools.Stats.analysis import dv_policy_group_significant as group_policy
from Tools.Stats.analysis.dv_policy_group_significant import (
    GroupSignificantHarmonicRow,
    GroupSignificantHarmonicSelection,
)
from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
)

ODDBALL_HZ = 1.2
BASE_HZ = 6.0


def test_gap_guard_trims_the_reported_20_4_to_46_8_hz_case() -> None:
    selection = _selection(max_harmonic_index=39, detected_indices={17, 39})

    assert selection.detected_significant_harmonics_hz == pytest.approx([20.4, 46.8])
    assert selection.selected_harmonics_hz[-1] == pytest.approx(20.4)
    assert selection.selected_harmonics_hz == pytest.approx(
        [ODDBALL_HZ * index for index in range(1, 18) if index % 5]
    )

    lower_peak = _row(selection, 17)
    first_intermediate = _row(selection, 18)
    base_overlap = _row(selection, 20)
    isolated_highest = _row(selection, 39)
    assert lower_peak.selected is True
    assert lower_peak.included_in_summation is True
    assert first_intermediate.selected is False
    assert first_intermediate.included_in_summation is False
    assert base_overlap.excluded_base_rate is True
    assert base_overlap.included_in_summation is False
    assert isolated_highest.selected is True
    assert isolated_highest.included_in_summation is False

    metadata = selection.to_metadata()
    assert metadata["highest_significant_harmonic_hz"] == pytest.approx(46.8)
    assert metadata["highest_significant_harmonic_index"] == 39
    assert metadata["highest_included_harmonic_hz"] == pytest.approx(20.4)
    assert metadata["highest_included_harmonic_index"] == 17
    assert metadata["summation_gap_guard_applied"] is True
    assert metadata["summation_gap_guard_intervening_nonbase_harmonic_count"] == 17
    assert metadata["summation_gap_guard_lower_significant_harmonic_hz"] == pytest.approx(
        20.4
    )
    assert metadata[
        "summation_gap_guard_dropped_highest_significant_harmonic_hz"
    ] == pytest.approx(46.8)
    assert "17 eligible non-base harmonics" in metadata["methods_summary"]


@pytest.mark.parametrize(
    ("highest_index", "expected_count", "expected_applied", "expected_cutoff_index"),
    [
        (14, 10, False, 14),
        (16, 11, True, 1),
    ],
)
def test_gap_guard_uses_strictly_more_than_ten_eligible_nonbase_harmonics(
    highest_index: int,
    expected_count: int,
    expected_applied: bool,
    expected_cutoff_index: int,
) -> None:
    selection = _selection(
        max_harmonic_index=highest_index,
        detected_indices={1, highest_index},
    )
    metadata = selection.to_metadata()

    assert metadata["summation_gap_guard_intervening_nonbase_harmonic_count"] == (
        expected_count
    )
    assert metadata["summation_gap_guard_applied"] is expected_applied
    assert selection.selected_harmonics_hz[-1] == pytest.approx(
        ODDBALL_HZ * expected_cutoff_index
    )


def test_gap_guard_does_not_change_significant_only_summation() -> None:
    selection = _selection(
        max_harmonic_index=39,
        detected_indices={17, 39},
        summation_method=GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
    )
    metadata = selection.to_metadata()

    assert selection.selected_harmonics_hz == pytest.approx([20.4, 46.8])
    assert metadata["summation_gap_guard_enabled"] is False
    assert metadata["summation_gap_guard_applied"] is False


def test_gap_guard_requires_two_detected_significant_harmonics() -> None:
    selection = _selection(max_harmonic_index=39, detected_indices={39})
    metadata = selection.to_metadata()

    assert selection.selected_harmonics_hz[-1] == pytest.approx(46.8)
    assert metadata["summation_gap_guard_applied"] is False
    assert metadata["summation_gap_guard_intervening_nonbase_harmonic_count"] == 0
    assert metadata["summation_gap_guard_lower_significant_harmonic_hz"] is None


def test_gap_guard_is_one_pass_and_does_not_recheck_the_retained_peak() -> None:
    selection = _selection(
        max_harmonic_index=32,
        detected_indices={1, 16, 32},
    )
    metadata = selection.to_metadata()

    assert metadata["summation_gap_guard_applied"] is True
    assert metadata["summation_gap_guard_lower_significant_harmonic_hz"] == pytest.approx(
        19.2
    )
    assert selection.selected_harmonics_hz[-1] == pytest.approx(19.2)
    assert _row(selection, 16).included_in_summation is True
    assert _row(selection, 32).included_in_summation is False


def test_gap_guard_handles_an_empty_detection_set_without_a_cutoff() -> None:
    decision = group_policy._summation_gap_guard_decision(
        rows=_rows(max_harmonic_index=4, detected_indices=set()),
        detected_freqs=(),
        summation_method=GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    )

    assert decision.applied is False
    assert decision.retained_cutoff_harmonic_index is None


def _selection(
    *,
    max_harmonic_index: int,
    detected_indices: set[int],
    summation_method: str = GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
) -> GroupSignificantHarmonicSelection:
    rows = _rows(
        max_harmonic_index=max_harmonic_index,
        detected_indices=detected_indices,
    )
    detected_freqs = [
        ODDBALL_HZ * index
        for index in sorted(detected_indices)
    ]
    selected_freqs, selected_columns, selected_bin_indices, updated_rows = (
        group_policy._resolve_summation_harmonics(
            rows=rows,
            detected_freqs=detected_freqs,
            summation_method=summation_method,
        )
    )
    detected_rows = [
        row for row in updated_rows if row.harmonic_index in detected_indices
    ]
    return GroupSignificantHarmonicSelection(
        harmonic_domain_hz=[
            row.target_frequency_hz
            for row in updated_rows
            if not row.excluded_base_rate
        ],
        selected_harmonics_hz=selected_freqs,
        selected_columns=selected_columns,
        selected_bin_indices=selected_bin_indices,
        detected_significant_harmonics_hz=detected_freqs,
        detected_significant_columns=[row.matched_column or "" for row in detected_rows],
        detected_significant_bin_indices=[
            int(row.matched_bin_index) for row in detected_rows if row.matched_bin_index is not None
        ],
        z_by_harmonic={
            row.target_frequency_hz: float(row.z_score or 0.0)
            for row in updated_rows
            if not row.excluded_base_rate
        },
        excluded_base_harmonics_hz=[
            row.target_frequency_hz for row in updated_rows if row.excluded_base_rate
        ],
        oddball_frequency_hz=ODDBALL_HZ,
        base_frequency_hz=BASE_HZ,
        z_threshold=1.64,
        electrode_scope=GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        summation_method=summation_method,
        selection_scope="test_group_scope",
        selection_conditions=["Condition A"],
        selection_subjects=["P01"],
        selection_spectra_count=1,
        selection_electrode_count=3,
        frequency_resolution_hz=0.1,
        base_overlap_tolerance_hz=0.01,
        matching_tolerance_hz=0.01,
        noise_window_bins=10,
        rows=updated_rows,
    )


def _rows(
    *,
    max_harmonic_index: int,
    detected_indices: set[int],
) -> list[GroupSignificantHarmonicRow]:
    rows: list[GroupSignificantHarmonicRow] = []
    for harmonic_index in range(1, max_harmonic_index + 1):
        frequency = round(ODDBALL_HZ * harmonic_index, 10)
        excluded_base = harmonic_index % 5 == 0
        detected = harmonic_index in detected_indices
        rows.append(
            GroupSignificantHarmonicRow(
                harmonic_index=harmonic_index,
                target_frequency_hz=frequency,
                matched_frequency_hz=frequency,
                matched_column=f"{frequency:.4f}_Hz",
                matched_bin_index=harmonic_index,
                z_score=4.0 if detected else 0.0,
                selected=detected,
                excluded_base_rate=excluded_base,
                exclusion_reason="base_rate_overlap" if excluded_base else "",
                warning="",
            )
        )
    return rows


def _row(
    selection: GroupSignificantHarmonicSelection,
    harmonic_index: int,
) -> GroupSignificantHarmonicRow:
    return next(row for row in selection.rows if row.harmonic_index == harmonic_index)

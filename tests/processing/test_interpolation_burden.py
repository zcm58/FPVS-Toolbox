from __future__ import annotations

import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_AVAILABLE,
    INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    INTERPOLATION_BURDEN_UNAVAILABLE,
    InterpolationBurdenError,
    build_interpolation_burden,
    build_interpolation_burden_review_decision,
    interpolation_burden_decision_is_current,
    interpolation_burden_review_finding,
    normalize_interpolation_burden_review_decision,
    summarize_interpolation_burdens,
)
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_FAILED,
    INTERPOLATION_STATUS_NOT_NEEDED,
    INTERPOLATION_STATUS_SUCCEEDED,
    PROCESSING_STATUS_COMPLETED,
    build_preprocessing_outcome,
)


def _outcome(*, status: str, successful: tuple[str, ...] = ()):
    if status == INTERPOLATION_STATUS_SUCCEEDED:
        requested = successful
    elif status == INTERPOLATION_STATUS_FAILED:
        requested = ("Fp1",)
    else:
        requested = ()
    return build_preprocessing_outcome(
        processing_status=PROCESSING_STATUS_COMPLETED,
        interpolation_status=status,
        interpolation_requested_channels=requested,
        interpolation_successful_channels=successful,
        interpolation_detail=("interpolation failed" if status == INTERPOLATION_STATUS_FAILED else ""),
    )


@pytest.mark.parametrize(
    ("successful", "expected_percentage", "expected_review"),
    [
        ((), 0.0, False),
        (("Fp1", "AF7", "AF3"), 4.6875, False),
        (("Fp1", "AF7", "AF3", "F1"), 6.25, True),
    ],
)
def test_full_biosemi64_burden_uses_confirmed_success_only(
    successful: tuple[str, ...],
    expected_percentage: float,
    expected_review: bool,
) -> None:
    status = (
        INTERPOLATION_STATUS_SUCCEEDED
        if successful
        else INTERPOLATION_STATUS_NOT_NEEDED
    )

    result = build_interpolation_burden(
        _outcome(status=status, successful=successful),
        biosemi64_geometry_identity(),
    )

    assert result.status == INTERPOLATION_BURDEN_AVAILABLE
    assert result.denominator == 64
    assert result.numerator == len(successful)
    assert result.percentage == pytest.approx(expected_percentage)
    assert result.requires_review is expected_review


def test_exact_five_percent_on_reduced_set_does_not_flag() -> None:
    retained = BIOSEMI64_CHANNELS[:20]
    result = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=(retained[0],),
        ),
        biosemi64_geometry_identity(retained_channels=retained),
    )

    assert result.percentage == pytest.approx(5.0)
    assert result.requires_review is False


@pytest.mark.parametrize(
    ("outcome", "geometry"),
    [
        (None, biosemi64_geometry_identity()),
        (
            _outcome(status=INTERPOLATION_STATUS_FAILED),
            biosemi64_geometry_identity(),
        ),
        (_outcome(status=INTERPOLATION_STATUS_NOT_NEEDED), None),
    ],
)
def test_missing_failed_or_legacy_evidence_is_unavailable(outcome, geometry) -> None:
    result = build_interpolation_burden(outcome, geometry)

    assert result.status == INTERPOLATION_BURDEN_UNAVAILABLE
    assert result.percentage is None
    assert result.numerator is None
    assert result.denominator is None
    assert result.requires_review is False


def test_success_outside_eligible_set_is_unavailable() -> None:
    result = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "NotAChannel"),
        ),
        biosemi64_geometry_identity(),
    )

    assert result.status == INTERPOLATION_BURDEN_UNAVAILABLE
    assert "outside" in result.reason


def test_cohort_summary_does_not_zero_fill_unavailable_recordings() -> None:
    three = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "AF7", "AF3"),
        ),
        biosemi64_geometry_identity(),
    )
    four = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "AF7", "AF3", "F1"),
        ),
        biosemi64_geometry_identity(),
    )
    unavailable = build_interpolation_burden(None, biosemi64_geometry_identity())

    summary = summarize_interpolation_burdens((three, four, unavailable))

    assert summary.recording_count == 3
    assert summary.contributing_recording_count == 2
    assert summary.unavailable_recording_count == 1
    assert summary.mean_percentage == pytest.approx((4.6875 + 6.25) / 2)
    assert summary.minimum_percentage == pytest.approx(4.6875)
    assert summary.maximum_percentage == pytest.approx(6.25)
    assert summary.recordings_above_threshold == 1


def test_above_threshold_finding_is_review_only_and_recording_scoped() -> None:
    burden = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "AF7", "AF3", "F1"),
        ),
        biosemi64_geometry_identity(),
    )

    finding = interpolation_burden_review_finding("P01__visit2", burden)

    assert finding is not None
    assert finding.recording_id == "P01__visit2"
    assert finding.numerator == 4
    assert finding.denominator == 64
    assert "Review this recording" in finding.message
    assert "exclude" not in finding.message.casefold()


def test_below_threshold_burden_has_no_review_finding() -> None:
    burden = build_interpolation_burden(
        _outcome(status=INTERPOLATION_STATUS_NOT_NEEDED),
        biosemi64_geometry_identity(),
    )

    assert interpolation_burden_review_finding("P01", burden) is None


def test_review_decision_round_trips_and_is_tied_to_exact_burden() -> None:
    burden = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "AF7", "AF3", "F1"),
        ),
        biosemi64_geometry_identity(),
    )
    finding = interpolation_burden_review_finding("P01__visit2", burden)
    assert finding is not None
    decision = build_interpolation_burden_review_decision(
        finding,
        participant_id="P01",
        decision=INTERPOLATION_BURDEN_DECISION_EXCLUDE,
        reason="Reviewed electrode locations and excluded this recording.",
        reviewed_at_utc="2026-09-04T15:30:00Z",
    )

    reloaded = normalize_interpolation_burden_review_decision(decision.to_payload())

    assert interpolation_burden_decision_is_current(finding, reloaded) is True
    assert reloaded.reviewer_identity is None
    assert reloaded.reviewer_identity_status == "not_collected"


def test_review_decision_rejects_blank_reason_and_stale_evidence() -> None:
    burden = build_interpolation_burden(
        _outcome(
            status=INTERPOLATION_STATUS_SUCCEEDED,
            successful=("Fp1", "AF7", "AF3", "F1"),
        ),
        biosemi64_geometry_identity(),
    )
    finding = interpolation_burden_review_finding("P01", burden)
    assert finding is not None
    with pytest.raises(InterpolationBurdenError, match="requires a reason"):
        build_interpolation_burden_review_decision(
            finding,
            participant_id="P01",
            decision=INTERPOLATION_BURDEN_DECISION_EXCLUDE,
            reason="",
        )

    payload = build_interpolation_burden_review_decision(
        finding,
        participant_id="P01",
        decision=INTERPOLATION_BURDEN_DECISION_EXCLUDE,
        reason="Reviewed.",
        reviewed_at_utc="2026-09-04T15:30:00Z",
    ).to_payload()
    payload["burden_fingerprint"] = "0" * 64
    with pytest.raises(InterpolationBurdenError, match="fingerprint is stale"):
        normalize_interpolation_burden_review_decision(payload)

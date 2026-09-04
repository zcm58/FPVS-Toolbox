from __future__ import annotations

import pytest

from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_ATTEMPTED,
    INTERPOLATION_STATUS_FAILED,
    INTERPOLATION_STATUS_LEGACY_UNKNOWN,
    INTERPOLATION_STATUS_NOT_NEEDED,
    INTERPOLATION_STATUS_SKIPPED,
    INTERPOLATION_STATUS_SUCCEEDED,
    PREPROCESSING_OUTCOME_VERSION,
    PROCESSING_STATUS_COMPLETED,
    PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS,
    PROCESSING_STATUS_EXCLUDED,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_LEGACY_UNKNOWN,
    PROCESSING_STATUS_PENDING,
    PreprocessingOutcomeError,
    build_preprocessing_outcome,
    normalize_preprocessing_outcome,
)


def test_successful_interpolation_is_explicit_and_round_trips() -> None:
    outcome = build_preprocessing_outcome(
        processing_status=PROCESSING_STATUS_COMPLETED,
        interpolation_status=INTERPOLATION_STATUS_SUCCEEDED,
        interpolation_requested_channels=["P9", "Cz"],
        interpolation_successful_channels=["P9", "Cz"],
    )

    assert outcome.is_current is True
    assert outcome.interpolation_was_attempted is True
    assert outcome.interpolation_successful_channels == ("P9", "Cz")
    assert normalize_preprocessing_outcome(outcome.to_payload()) == outcome


def test_unversioned_flags_and_legacy_channel_lists_never_imply_success() -> None:
    outcome = normalize_preprocessing_outcome(
        {
            "status": "completed",
            "raw_qc_bad_channels": ["P9"],
            "kurtosis_bad_channels": ["Cz"],
            "interpolation_status": "succeeded",
            "interpolated_channels": ["P9", "Cz"],
        }
    )

    assert outcome.is_current is False
    assert outcome.processing_status == PROCESSING_STATUS_LEGACY_UNKNOWN
    assert outcome.interpolation_status == INTERPOLATION_STATUS_LEGACY_UNKNOWN
    assert outcome.interpolation_requested_channels == ()
    assert outcome.interpolation_successful_channels == ()


@pytest.mark.parametrize(
    ("processing_status", "processing_reason", "missing_conditions"),
    [
        (PROCESSING_STATUS_COMPLETED, "", []),
        (
            PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS,
            "",
            ["Faces"],
        ),
        (PROCESSING_STATUS_EXCLUDED, "Excluded before preprocessing.", []),
        (PROCESSING_STATUS_FAILED, "Filter failed.", []),
        (PROCESSING_STATUS_PENDING, "Waiting for review.", []),
        (PROCESSING_STATUS_LEGACY_UNKNOWN, "", []),
    ],
)
def test_all_processing_states_have_current_versioned_representations(
    processing_status: str,
    processing_reason: str,
    missing_conditions: list[str],
) -> None:
    outcome = build_preprocessing_outcome(
        processing_status=processing_status,
        processing_reason=processing_reason,
        missing_conditions=missing_conditions,
        interpolation_status=INTERPOLATION_STATUS_NOT_NEEDED,
    )

    assert outcome.outcome_version == PREPROCESSING_OUTCOME_VERSION
    assert outcome.processing_status == processing_status


@pytest.mark.parametrize(
    ("status", "requested", "detail", "attempted"),
    [
        (INTERPOLATION_STATUS_ATTEMPTED, ["P9"], "", True),
        (INTERPOLATION_STATUS_FAILED, ["P9"], "Spline solve failed.", True),
        (INTERPOLATION_STATUS_SKIPPED, ["P9"], "Stage not reached.", False),
        (INTERPOLATION_STATUS_NOT_NEEDED, [], "", False),
        (INTERPOLATION_STATUS_LEGACY_UNKNOWN, [], "", False),
    ],
)
def test_non_success_interpolation_states_cannot_claim_successful_channels(
    status: str,
    requested: list[str],
    detail: str,
    attempted: bool,
) -> None:
    outcome = build_preprocessing_outcome(
        processing_status=PROCESSING_STATUS_PENDING,
        interpolation_status=status,
        interpolation_requested_channels=requested,
        interpolation_detail=detail,
    )

    assert outcome.interpolation_was_attempted is attempted
    assert outcome.interpolation_successful_channels == ()


def test_current_failed_interpolation_requires_requested_channels_and_reason() -> None:
    with pytest.raises(PreprocessingOutcomeError, match="requested channels"):
        build_preprocessing_outcome(
            processing_status=PROCESSING_STATUS_FAILED,
            processing_reason="Preprocessing failed.",
            interpolation_status=INTERPOLATION_STATUS_FAILED,
            interpolation_detail="Spline solve failed.",
        )

    with pytest.raises(PreprocessingOutcomeError, match="interpolation_detail"):
        build_preprocessing_outcome(
            processing_status=PROCESSING_STATUS_FAILED,
            processing_reason="Preprocessing failed.",
            interpolation_status=INTERPOLATION_STATUS_FAILED,
            interpolation_requested_channels=["P9"],
        )


def test_success_requires_every_requested_channel_and_no_other_status_can_claim_it() -> None:
    with pytest.raises(PreprocessingOutcomeError, match="every requested channel"):
        build_preprocessing_outcome(
            processing_status=PROCESSING_STATUS_COMPLETED,
            interpolation_status=INTERPOLATION_STATUS_SUCCEEDED,
            interpolation_requested_channels=["P9", "Cz"],
            interpolation_successful_channels=["P9"],
        )

    with pytest.raises(PreprocessingOutcomeError, match="Only succeeded"):
        build_preprocessing_outcome(
            processing_status=PROCESSING_STATUS_PENDING,
            interpolation_status=INTERPOLATION_STATUS_ATTEMPTED,
            interpolation_requested_channels=["P9"],
            interpolation_successful_channels=["P9"],
        )

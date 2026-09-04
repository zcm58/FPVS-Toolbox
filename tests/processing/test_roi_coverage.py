from __future__ import annotations

from dataclasses import FrozenInstanceError
import math

import pytest

from Main_App.io import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.processing.roi_coverage import (
    ROI_SOURCE_COVERAGE_VERSION,
    ROI_SOURCE_VALIDATION_STAGE,
    RetainedScalpIdentity,
    RoiSourceCoverageError,
    freeze_retained_scalp_identity,
    validate_roi_source_rows,
)


def _rows(
    channels: tuple[str, ...] = BIOSEMI64_CHANNELS[:3],
) -> list[dict[str, object]]:
    return [
        {
            "Electrode": channel,
            "1.2 Hz BCA": index + 0.5,
            "SNR": index + 2.0,
        }
        for index, channel in enumerate(channels)
    ]


def _validate(rows: object, **kwargs: object):
    return validate_roi_source_rows(
        rows,
        retained_scalp=kwargs.pop("retained_scalp", BIOSEMI64_CHANNELS[:3]),
        required_columns=kwargs.pop("required_columns", ("1.2 Hz BCA", "SNR")),
        **kwargs,
    )


def test_source_rows_validate_before_exclusions_and_count_interpolation() -> None:
    rows = _rows()
    rows[1]["SNR"] = math.nan
    rows.append({"Electrode": " EXG1 ", "note": "outside scalp calculations"})

    evidence = _validate(
        list(reversed(rows)),
        allowed_auxiliary_rows=("EXG1", "Grand Average"),
        successfully_interpolated_channels=(" af7 ",),
        unavailable_columns=("snr",),
    )

    assert evidence.method_version == ROI_SOURCE_COVERAGE_VERSION
    assert evidence.validation_stage == ROI_SOURCE_VALIDATION_STAGE
    assert evidence.expected_scalp_channels == BIOSEMI64_CHANNELS[:3]
    assert evidence.observed_scalp_channels == BIOSEMI64_CHANNELS[:3]
    assert evidence.expected_scalp_count == evidence.observed_scalp_count == 3
    assert evidence.successfully_interpolated_channels == ("AF7",)
    assert evidence.successfully_interpolated_count == 1
    assert evidence.observed_auxiliary_rows == ("EXG1",)
    assert evidence.explicitly_unavailable_columns == ("SNR",)
    assert evidence.nonfinite_unavailable_values == (("SNR", ("AF7",)),)
    assert evidence.to_payload()["fingerprint"] == evidence.fingerprint
    with pytest.raises(FrozenInstanceError):
        evidence.required_columns = ()  # type: ignore[misc]


def test_source_evidence_fingerprint_ignores_harmless_row_order_and_case() -> None:
    canonical = _validate(
        _rows(),
        successfully_interpolated_channels=("AF7",),
    )
    reordered = [
        {
            " electrode ": str(row["Electrode"]).lower(),
            "snr": row["SNR"],
            "1.2 hz bca": row["1.2 Hz BCA"],
        }
        for row in reversed(_rows())
    ]
    normalized = _validate(
        reordered,
        retained_scalp=(" af3 ", "FP1", "af7"),
        required_columns=("1.2 Hz BCA", "SNR"),
        successfully_interpolated_channels=("af7",),
    )

    assert normalized.fingerprint == canonical.fingerprint


def test_qc15_geometry_identity_is_validated_and_frozen() -> None:
    qc15_identity = biosemi64_geometry_identity(
        retained_channels=BIOSEMI64_CHANNELS[:3]
    )

    frozen = freeze_retained_scalp_identity(qc15_identity)
    evidence = _validate(_rows(), retained_scalp=qc15_identity)

    assert isinstance(frozen, RetainedScalpIdentity)
    assert frozen.channels == BIOSEMI64_CHANNELS[:3]
    assert evidence.retained_scalp_identity == frozen

    from_frozen_set = freeze_retained_scalp_identity(
        frozenset(BIOSEMI64_CHANNELS[:3])
    )
    assert from_frozen_set.channels == BIOSEMI64_CHANNELS[:3]

    invalid = dict(qc15_identity)
    invalid["coordinate_fingerprint"] = "legacy-or-mixed"
    with pytest.raises(RoiSourceCoverageError, match="coordinate_fingerprint"):
        freeze_retained_scalp_identity(invalid)

    stale = dict(qc15_identity)
    stale["geometry_identity_fingerprint"] = "stale"
    with pytest.raises(RoiSourceCoverageError, match="geometry_identity_fingerprint"):
        freeze_retained_scalp_identity(stale)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (_rows()[:-1], "missing retained scalp"),
        (_rows() + [_rows()[0]], "repeat scalp channel"),
        (_rows() + [{"Electrode": "F1"}], "outside the frozen retained"),
        (_rows() + [{"Electrode": "Mystery"}], "undeclared or unknown"),
        (_rows() + [{"Electrode": "EXG1"}], "undeclared or unknown"),
    ],
)
def test_source_rows_reject_missing_duplicate_and_unexpected_rows(
    rows: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(RoiSourceCoverageError, match=message):
        _validate(rows)


def test_only_explicit_unique_auxiliary_rows_are_permitted() -> None:
    rows = _rows() + [
        {"Electrode": "EXG1"},
        {"Electrode": " exg1 "},
    ]
    with pytest.raises(RoiSourceCoverageError, match="repeat auxiliary"):
        _validate(rows, allowed_auxiliary_rows=("EXG1",))

    with pytest.raises(RoiSourceCoverageError, match="cannot be declared auxiliary"):
        _validate(_rows(), allowed_auxiliary_rows=("Fp1",))


def test_nonfinite_values_require_explicit_column_unavailability() -> None:
    rows = _rows()
    rows[0]["1.2 Hz BCA"] = float("inf")
    with pytest.raises(RoiSourceCoverageError, match="nonfinite value"):
        _validate(rows)

    evidence = _validate(rows, unavailable_columns=("1.2 Hz BCA",))
    assert evidence.nonfinite_unavailable_values == (("1.2 Hz BCA", ("Fp1",)),)

    del rows[1]["SNR"]
    with pytest.raises(RoiSourceCoverageError, match="missing required column"):
        _validate(rows, unavailable_columns=("1.2 Hz BCA", "SNR"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"required_columns": ()}, "At least one required"),
        ({"required_columns": ("SNR", " snr ")}, "repeats"),
        ({"unavailable_columns": ("Noise",)}, "not in the required"),
        ({"successfully_interpolated_channels": ("F1",)}, "outside the retained"),
        ({"successfully_interpolated_channels": ("Fp1", "fp1")}, "repeats"),
    ],
)
def test_source_contract_rejects_malformed_declarations(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RoiSourceCoverageError, match=message):
        _validate(_rows(), **kwargs)


def test_source_rows_reject_ambiguous_or_missing_columns() -> None:
    rows = _rows()
    rows[0][" snr "] = rows[0]["SNR"]
    with pytest.raises(RoiSourceCoverageError, match="repeats column"):
        _validate(rows)

    with pytest.raises(RoiSourceCoverageError, match="identity column"):
        _validate(_rows(), required_columns=("electrode",))


def test_interpolation_and_unavailability_are_fingerprint_evidence() -> None:
    base = _validate(_rows())
    interpolated = _validate(
        _rows(),
        successfully_interpolated_channels=("Fp1",),
    )
    unavailable = _validate(_rows(), unavailable_columns=("SNR",))

    assert len({base.fingerprint, interpolated.fingerprint, unavailable.fingerprint}) == 3

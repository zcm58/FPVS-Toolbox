from __future__ import annotations

import pytest

from Tools.Stats.analysis.sensitivity_summary import (
    SensitivityConclusion,
    summarize_sensitivity_agreement,
)


def _outcome(
    method_id: str,
    supported: bool | None,
    *,
    estimand: str = "arithmetic mean",
    status: str = "estimated",
    direction: str | None = None,
) -> SensitivityConclusion:
    return SensitivityConclusion(
        method_id=method_id,
        method_label=method_id.replace("_", " "),
        estimand=estimand,
        supported=supported,
        status=status,
        direction=direction,
    )


def test_disagreement_uses_explicit_method_dependent_language() -> None:
    result = summarize_sensitivity_agreement(
        _outcome("primary_t", True),
        (
            _outcome("trimmed_mean", False, estimand="20% trimmed mean"),
            _outcome("wilcoxon", True, estimand="rank distribution"),
        ),
    )

    assert result.status == "method_dependent"
    assert result.method_dependent
    assert result.plain_language.startswith(
        "The conclusion depended on the analysis method."
    )
    assert "primary t" in result.plain_language
    assert "trimmed mean" in result.plain_language
    assert "not identical estimands" in result.plain_language
    frame = result.to_frame()
    assert len(frame) == 3
    assert frame["method_dependent"].eq(True).all()


@pytest.mark.parametrize("supported", [True, False])
def test_consistent_conclusions_are_described_without_equivalence_claim(
    supported: bool,
) -> None:
    result = summarize_sensitivity_agreement(
        _outcome(
            "primary_t",
            supported,
            direction="positive" if supported else None,
        ),
        (
            _outcome(
                "trimmed_mean",
                supported,
                estimand="20% trimmed mean",
                direction="positive" if supported else None,
            ),
        ),
    )

    assert result.status == "consistent"
    if supported:
        assert "supported the same conclusion" in result.plain_language
    else:
        assert "did not meet the prespecified evidence threshold" in (
            result.plain_language
        )
        assert "no effect" not in result.plain_language.casefold()


def test_opposite_supported_directions_are_method_dependent() -> None:
    result = summarize_sensitivity_agreement(
        _outcome("primary_t", True, direction="positive"),
        (
            _outcome(
                "trimmed_mean",
                True,
                estimand="20% trimmed mean",
                direction="negative",
            ),
        ),
    )

    assert result.status == "method_dependent"
    assert "estimated directions differed" in result.plain_language
    assert "primary t: positive" in result.plain_language
    assert "trimmed mean: negative" in result.plain_language


def test_supported_results_without_directions_only_claim_threshold_agreement() -> None:
    result = summarize_sensitivity_agreement(
        _outcome("primary_t", True),
        (_outcome("wilcoxon", True),),
    )

    assert result.status == "consistent_threshold_only"
    assert "direction agreement was not fully specified" in result.plain_language
    assert "same conclusion" not in result.plain_language


def test_non_estimable_primary_or_sensitivities_are_not_forced_into_agreement() -> None:
    primary_failed = summarize_sensitivity_agreement(
        _outcome("primary_t", None, status="not_estimable"),
        (_outcome("wilcoxon", True),),
    )
    sensitivities_failed = summarize_sensitivity_agreement(
        _outcome("primary_t", True),
        (_outcome("wilcoxon", None, status="not_estimable"),),
    )

    assert primary_failed.status == "primary_not_estimable"
    assert sensitivities_failed.status == "no_estimable_sensitivities"


def test_invalid_supported_value_is_rejected() -> None:
    with pytest.raises(TypeError, match="supported"):
        SensitivityConclusion(
            method_id="bad",
            method_label="Bad",
            estimand="mean",
            supported=1,  # type: ignore[arg-type]
        )

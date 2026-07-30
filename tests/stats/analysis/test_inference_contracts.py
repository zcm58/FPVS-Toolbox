from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisResultMetadata,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    FollowupProvenance,
    HarmonicProvenance,
    InferenceRole,
    STANDARD_SCREENING_CORRECTION,
    STANDARD_SCREENING_RANDOM_EFFECTS,
    STANDARD_SCREENING_RESPONSE_ALTERNATIVE,
    STANDARD_SCREENING_SCOPE,
    TestMetadata,
    build_standard_screening_run_spec,
)


def test_fixed_unverified_harmonics_do_not_imply_confirmatory_inference() -> None:
    fixed_run = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
    )
    independent_run = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.INDEPENDENTLY_SELECTED,
    )
    adaptive_run = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    assert fixed_run.response_is_confirmatory is False
    assert fixed_run.response_inference_status == "provenance_unverified"
    assert independent_run.response_is_confirmatory is True
    assert independent_run.response_inference_status == "confirmatory"
    assert adaptive_run.response_is_confirmatory is False
    assert adaptive_run.response_inference_status == "exploratory_post_selection"
    assert fixed_run.response_alternative is Alternative.GREATER


def test_standard_screening_contract_locks_direction_correction_and_families() -> None:
    run = build_standard_screening_run_spec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    assert STANDARD_SCREENING_RESPONSE_ALTERNATIVE is Alternative.GREATER
    assert STANDARD_SCREENING_CORRECTION is CorrectionMethod.HOLM
    assert STANDARD_SCREENING_SCOPE == "available_case"
    assert STANDARD_SCREENING_RANDOM_EFFECTS == "participant_random_intercept"
    assert run.response_alternative is Alternative.GREATER
    assert set(run.family_map) == {
        "response_core_cells",
        "group_response_cells",
        "group_core_cells",
        "planned_contrasts",
        "omnibus_effects_strict",
        "anova_compatibility_effects",
    }
    assert all(
        family.method is CorrectionMethod.HOLM for family in run.families
    )


def test_run_spec_is_immutable_and_coerces_gui_safe_strings() -> None:
    run = AnalysisRunSpec(
        profile="published-style-exploratory",
        harmonic_provenance="same sample adaptive",
        response_alternative="two-sided",
        followup_provenance="omnibus-triggered",
    )

    assert run.profile is AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY
    assert run.harmonic_provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE
    assert run.response_alternative is Alternative.TWO_SIDED
    assert run.response_alternative.scipy_value == "two-sided"
    assert run.followup_provenance is FollowupProvenance.OMNIBUS_TRIGGERED
    with pytest.raises(FrozenInstanceError):
        run.alpha = 0.01  # type: ignore[misc]


def test_family_spec_validates_and_normalizes_correction_aliases() -> None:
    family = FamilySpec(
        family_id=" response_core_cells ",
        family_label=" Core response cells ",
        method="BH-FDR",
        alpha="0.05",
    )

    assert family.family_id == "response_core_cells"
    assert family.family_label == "Core response cells"
    assert family.method is CorrectionMethod.BH_FDR
    assert family.to_dict()["adjustment_method"] == "fdr_bh"

    with pytest.raises(ValueError, match="strictly between"):
        FamilySpec("bad", "Bad", alpha=1.0)
    with pytest.raises(ValueError, match="non-empty"):
        FamilySpec("", "Bad")


def test_run_spec_rejects_duplicate_family_ids_case_insensitively() -> None:
    with pytest.raises(ValueError, match="unique family_id"):
        AnalysisRunSpec(
            profile=AnalysisProfile.CONFIRMATORY,
            harmonic_provenance=HarmonicProvenance.INDEPENDENTLY_SELECTED,
            families=(
                FamilySpec("response_core_cells", "Core"),
                FamilySpec("Response_Core_Cells", "Duplicate"),
            ),
        )


def test_result_metadata_serializes_to_json_safe_dicts_and_explicit_frames() -> None:
    family = FamilySpec(
        "response_core_cells",
        "Complete-core Condition x ROI response tests",
        CorrectionMethod.HOLM,
    )
    run = AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
        response_alternative=Alternative.GREATER,
        families=(family,),
    )
    test = TestMetadata(
        test_id="response.central.angry",
        test_label="Angry / Central response versus zero",
        method="one-sample t-test",
        estimand="arithmetic mean Summed BCA minus zero",
        role=InferenceRole.EXPLORATORY,
        scope="complete_core",
        family_id=family.family_id,
        alternative=Alternative.GREATER,
        notes=("Same-sample adaptive harmonics.",),
    )
    metadata = AnalysisResultMetadata(
        run_spec=run,
        tests=(test,),
        warnings=("Response inference is post-selection.",),
    )

    encoded = json.dumps(metadata.to_dict())
    frames = metadata.to_frames()

    assert "exploratory_post_selection" in encoded
    assert set(frames) == {
        "Run Metadata",
        "Correction Families",
        "Test Inventory",
        "Warnings",
    }
    assert frames["Correction Families"].loc[0, "family_id"] == "response_core_cells"
    assert frames["Test Inventory"].loc[0, "role"] == "exploratory"
    assert (
        frames["Test Inventory"].loc[0, "notes"]
        == "Same-sample adaptive harmonics."
    )


def test_result_metadata_rejects_duplicate_test_ids() -> None:
    run = AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.UNKNOWN,
    )
    test = TestMetadata(
        test_id="duplicate",
        test_label="Duplicate",
        method="test",
        estimand="estimand",
        role=InferenceRole.EXPLORATORY,
        scope="core",
    )

    with pytest.raises(ValueError, match="unique test_id"):
        AnalysisResultMetadata(run_spec=run, tests=(test, test))

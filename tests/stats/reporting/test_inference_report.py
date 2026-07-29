from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.reporting.inference_report import (
    ADAPTIVE_HARMONIC_WARNING,
    METHOD_DEPENDENT_PHRASE,
    NativeInferenceReportBundle,
    build_native_inference_report,
    write_native_inference_workbook,
    write_native_numeric_workbook,
)


def _prepared_design(*, excluded: str = "incomplete") -> dict[str, pd.DataFrame]:
    return {
        "Analysis Design": pd.DataFrame(
            [
                {
                    "status": "ready",
                    "n_frozen_participants": 12,
                    "complete_conditions": "faces; objects",
                    "excluded_conditions": excluded,
                }
            ]
        ),
        "Coverage": pd.DataFrame(
            [
                {"condition": "faces", "roi": "left", "cell_complete": True},
                {"condition": "objects", "roi": "left", "cell_complete": True},
                {"condition": "incomplete", "roi": "left", "cell_complete": False},
            ]
        ),
    }


def _available_case_design() -> dict[str, pd.DataFrame]:
    return {
        "Analysis Design": pd.DataFrame(
            [
                {
                    "status": "ready",
                    "analysis_scope": "available_case",
                    "n_frozen_participants": 12,
                    "n_contributing_participants": 10,
                    "retained_conditions": "faces; objects",
                    "complete_conditions": "faces",
                    "excluded_conditions": "scrambled",
                    "n_observed_rows": 35,
                }
            ]
        ),
        "Coverage": pd.DataFrame(
            [
                {"condition": "faces", "roi": "left", "cell_complete": True},
                {"condition": "objects", "roi": "left", "cell_complete": False},
                {
                    "condition": "scrambled",
                    "roi": "left",
                    "cell_complete": False,
                },
            ]
        ),
        "Model Cell Coverage": pd.DataFrame(
            [
                {
                    "group_id": None,
                    "condition": "faces",
                    "roi": "left",
                    "n_finite_values": 10,
                    "structurally_observed": True,
                },
                {
                    "group_id": None,
                    "condition": "objects",
                    "roi": "left",
                    "n_finite_values": 8,
                    "structurally_observed": True,
                },
                {
                    "group_id": None,
                    "condition": "scrambled",
                    "roi": "left",
                    "n_finite_values": 0,
                    "structurally_observed": False,
                },
            ]
        ),
        "Participant Coverage": pd.DataFrame(
            [
                {
                    "participant_id": f"S{index:02d}",
                    "contributes_to_primary": index <= 10,
                }
                for index in range(1, 13)
            ]
        ),
        "Missing Observations": pd.DataFrame(
            [
                {
                    "participant_id": "S11",
                    "condition": "objects",
                    "roi": "left",
                    "condition_retained": True,
                },
                {
                    "participant_id": "S12",
                    "condition": "objects",
                    "roi": "left",
                    "condition_retained": True,
                },
                {
                    "participant_id": "S01",
                    "condition": "scrambled",
                    "roi": "left",
                    "condition_retained": False,
                },
            ]
        ),
    }


def _response_results(
    *,
    p_adjusted: float = 0.012,
    p_raw: float = 0.001,
    provenance: str = "independently_selected",
    status: str = "confirmatory",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "condition": "faces",
                "roi": "left",
                "N": 12,
                "mean": 0.72,
                "ci_mean_low": 0.30,
                "ci_mean_high": 1.14,
                "cohens_dz": 0.81,
                "p_raw": p_raw,
                "p_adjusted": p_adjusted,
                "adjustment_method": "holm",
                "family_id": "response_core_cells",
                "family_label": "Complete-core response cells",
                "alpha": 0.05,
                "inference_status": status,
                "harmonic_provenance": provenance,
            }
        ]
    )


def _rm_results(*, p_reported: float = 0.024) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Effect": "condition * roi",
                "Num DF": 2.0,
                "Den DF": 22.0,
                "F Value": 4.8,
                "p_raw_or_uncorrected": 0.008,
                "p_reported": p_reported,
                "p_correction": "greenhouse_geisser",
                "inference_status": "primary_greenhouse_geisser_sphericity_violated",
                "reportable": True,
            }
        ]
    )


def _group_cell_results() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "condition": "faces",
                "roi": "left",
                "group_a": "anxious",
                "group_b": "non-anxious",
                "contrast": "anxious - non-anxious",
                "n_group_a": 6,
                "n_group_b": 6,
                "mean_difference_a_minus_b": 0.84,
                "ci_difference_low": 0.18,
                "ci_difference_high": 1.50,
                "hedges_g": 0.92,
                "p_raw": 0.004,
                "p_adjusted": 0.016,
                "adjustment_method": "holm",
                "family_id": "group_core_cells",
                "alpha": 0.05,
                "inference_status": "estimated",
            },
            {
                "condition": "objects",
                "roi": "left",
                "group_a": "anxious",
                "group_b": "non-anxious",
                "contrast": "anxious - non-anxious",
                "n_group_a": 6,
                "n_group_b": 6,
                "mean_difference_a_minus_b": -0.10,
                "ci_difference_low": -0.70,
                "ci_difference_high": 0.50,
                "hedges_g": -0.12,
                "p_raw": 0.12,
                "p_adjusted": 0.24,
                "adjustment_method": "holm",
                "family_id": "group_core_cells",
                "alpha": 0.05,
                "inference_status": "estimated",
            },
        ]
    )


def _omnibus_results() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "effect_id": "any_group_related",
                "effect_label": "Any group-related effect (joint block)",
                "interpretation": (
                    "Jointly tests every fixed-effect term containing group; "
                    "this is not a pure group main-effect test."
                ),
                "full_formula": (
                    "value ~ C(group_id, Sum) * C(condition, Sum) * C(roi, Sum)"
                ),
                "reduced_formula": (
                    "value ~ C(condition, Sum) * C(roi, Sum)"
                ),
                "lr_statistic": 9.4,
                "df_difference": 4,
                "p_value_chi2": 0.018,
                "status": "ok",
                "reportable": True,
            },
            {
                "effect_id": "group_condition_roi_interaction",
                "effect_label": "Group x Condition x ROI interaction",
                "full_formula": "full formula",
                "reduced_formula": "reduced formula",
                "lr_statistic": np.nan,
                "df_difference": np.nan,
                "p_value_chi2": np.nan,
                "status": "failed",
                "reportable": False,
            },
        ]
    )


def test_single_report_uses_adjusted_and_canonical_reported_p_values() -> None:
    bundle = build_native_inference_report(
        "single",
        _prepared_design(),
        {
            "response_results": _response_results(p_adjusted=0.20, p_raw=0.001),
            "rm_anova": _rm_results(),
        },
        alpha=0.05,
    )

    response = bundle.test_inventory[
        bundle.test_inventory["section"].eq("response_detection")
    ].iloc[0]
    within = bundle.test_inventory[
        bundle.test_inventory["section"].eq("within_subject")
    ].iloc[0]

    assert response["p_value_column"] == "p_adjusted"
    assert response["p_value_used"] == pytest.approx(0.20)
    assert bool(response["significant"]) is False
    assert within["p_value_column"] == "p_reported"
    assert within["p_value_used"] == pytest.approx(0.024)
    assert "Holm family-wise error correction" in bundle.at_a_glance
    assert "Greenhouse–Geisser sphericity correction" in bundle.at_a_glance
    assert "did not provide evidence of a response" in bundle.at_a_glance
    assert "This does not prove that the response is absent" in bundle.at_a_glance
    assert "Not applicable in single-group mode" in bundle.at_a_glance
    assert "there was no effect" not in bundle.at_a_glance.casefold()


def test_nonestimable_result_is_retained_but_not_headlined() -> None:
    response = _response_results()
    response.loc[0, "p_adjusted"] = np.nan
    response.loc[0, "inference_status"] = "not_estimable"
    bundle = build_native_inference_report(
        "single",
        step_payloads={"response_results": response},
    )

    row = bundle.test_inventory.iloc[0]
    assert bool(row["reportable"]) is False
    assert pd.isna(row["significant"])
    assert "no primary conclusion was drawn" in bundle.at_a_glance
    assert bundle.limitations["code"].eq("non_estimable_or_failed_tests").any()


def test_multigroup_report_states_joint_block_and_signed_group_contrast() -> None:
    bundle = build_native_inference_report(
        "multigroup",
        _prepared_design(excluded=""),
        {
            "group_cell_comparisons": _group_cell_results(),
            "omnibus_lrt": _omnibus_results(),
        },
    )

    text = bundle.at_a_glance
    assert "anxious - non-anxious" in text
    assert "positive in the stated A - B direction" in text
    assert "negative in the stated A - B direction" in text
    assert "Hedges g=0.920" in text
    assert "95% CI [0.180, 1.500]" in text
    assert "joint block of all group-containing terms" in text
    assert "not a pure group main-effect test" in text
    assert "group main effect was found" not in text.casefold()
    assert "does not establish group equivalence" in text
    failed = bundle.test_inventory[
        bundle.test_inventory["test_label"].eq(
            "Group x Condition x ROI interaction"
        )
    ].iloc[0]
    assert bool(failed["reportable"]) is False
    assert "no primary conclusion was drawn" in text


def test_adaptive_and_sensitivity_results_are_explicitly_caveated() -> None:
    robust = _response_results(
        p_adjusted=0.01,
        provenance="same_sample_adaptive",
        status="exploratory_post_selection_sensitivity",
    )
    bundle = build_native_inference_report(
        "single",
        step_payloads={
            "robust_sensitivity": robust,
        },
    )

    assert "Sensitivity only" in bundle.at_a_glance
    assert ADAPTIVE_HARMONIC_WARNING in bundle.at_a_glance
    assert bundle.limitations["code"].eq("adaptive_harmonic_selection").any()
    assert (
        bundle.test_inventory.iloc[0]["harmonic_provenance"]
        == "same_sample_adaptive"
    )
    assert bundle.test_inventory.iloc[0]["role"] == "sensitivity"


def test_report_inventory_includes_formula_n_assumptions_corrections_and_provenance() -> None:
    declared_inventory = pd.DataFrame(
        [
            {
                "test_id": "declared_test",
                "test_label": "Declared test",
                "method": "declared method",
                "role": "primary",
                "scope": "complete core",
                "family_id": "declared_family",
                "notes": "predeclared",
            }
        ]
    )
    bundle = build_native_inference_report(
        "multi",
        prepared_payload=_prepared_design(),
        prior_results={
            "metadata": {
                "Run Metadata": pd.DataFrame(
                    [{"harmonic_provenance": "independently_selected"}]
                ),
                "Correction Families": pd.DataFrame(
                    [
                        {
                            "family_id": "group_core_cells",
                            "family_label": "All group cells",
                            "adjustment_method": "holm",
                            "alpha": 0.05,
                        }
                    ]
                ),
                "Test Inventory": declared_inventory,
            },
            "omnibus_lrt": _omnibus_results().iloc[[0]].copy(),
        },
    )

    assert "Run Metadata" in bundle.named_frames
    assert "Correction Families" in bundle.named_frames
    assert "Test Inventory" in bundle.named_frames
    assert bundle.test_inventory["test_id"].eq("declared_test").any()
    assert bundle.test_inventory["formula"].str.contains("full:").any()
    assert "N=12" in bundle.detailed_methods
    assert "assumptions:" in bundle.detailed_methods
    assert "family=group_core_cells" in bundle.detailed_methods
    assert METHOD_DEPENDENT_PHRASE in bundle.detailed_methods
    exported_frames = bundle.to_frames()
    assert "Test Inventory" in exported_frames
    assert "Source - Test Inventory" in exported_frames


def test_correction_name_is_read_from_results_not_hardcoded() -> None:
    response = _response_results()
    response["adjustment_method"] = "single_step_max_abs_t_fwer"
    response = response.rename(columns={"p_adjusted": "p_adjusted_max_t"})
    bundle = build_native_inference_report(
        "single",
        step_payloads={"response_resampling": response},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["p_value_column"] == "p_adjusted_max_t"
    assert "single-step max-|t| family-wise error correction" in bundle.at_a_glance
    assert "Benjamini" not in bundle.at_a_glance


def test_workbook_has_explicit_sanitized_deterministic_sheets(
    tmp_path: Path,
) -> None:
    bundle = build_native_inference_report(
        "single",
        _prepared_design(),
        {
            "response_results": _response_results(),
            "very_long_[invalid]/source_name_that_exceeds_excel_limit": pd.DataFrame(
                [{"p_raw": 0.5, "status": "estimated"}]
            ),
        },
        export_path=tmp_path / "requested.xlsx",
    )
    logs: list[str] = []
    path = write_native_inference_workbook(
        bundle,
        tmp_path / "native_inference.xlsx",
        logs.append,
    )

    assert path.exists()
    workbook = pd.ExcelFile(path)
    assert workbook.sheet_names[:8] == [
        "At a Glance",
        "Detailed Methods",
        "Run Summary",
        "Test Inventory",
        "Methods",
        "Limitations",
        "Correction Families",
        "Export Metadata",
    ]
    assert all(len(name) <= 31 for name in workbook.sheet_names)
    assert all(not any(char in name for char in "[]:*?/\\") for name in workbook.sheet_names)
    export_metadata = pd.read_excel(path, sheet_name="Export Metadata")
    assert export_metadata.loc[0, "export_path"] == str(path)
    assert any("Wrote inference report sheet" in message for message in logs)
    assert logs[-1].endswith(str(path))


def test_builder_validates_mode_alias_conflicts_and_alpha() -> None:
    assert build_native_inference_report("single_group").mode == "single"
    assert build_native_inference_report("multi-group").mode == "multi"
    with pytest.raises(ValueError, match="mode"):
        build_native_inference_report("pooled")
    with pytest.raises(ValueError, match="alpha"):
        build_native_inference_report("single", alpha=1.0)
    with pytest.raises(ValueError, match="prepared"):
        build_native_inference_report(
            "single",
            prepared=pd.DataFrame(),
            prepared_payload=pd.DataFrame(),
        )
    with pytest.raises(TypeError, match="mapping"):
        build_native_inference_report("single", step_payloads=[])  # type: ignore[arg-type]


def test_bundle_type_is_public_and_export_rejects_non_xlsx(tmp_path: Path) -> None:
    bundle = build_native_inference_report("single")
    assert isinstance(bundle, NativeInferenceReportBundle)
    with pytest.raises(ValueError, match=".xlsx"):
        write_native_inference_workbook(bundle, tmp_path / "report.csv")


def test_worker_aliases_are_collected_once() -> None:
    frame = _group_cell_results().iloc[[0]].copy()
    worker_result = {
        "frames": {"Group Cell Contrasts": frame},
        "export_frames": {"Group Cell Contrasts": frame},
        "primary_object": {"results": frame},
        "result": {"results": frame},
    }

    bundle = build_native_inference_report(
        "multi",
        prior_results={"group_cell_step": worker_result},
    )

    assert bundle.test_inventory["test_label"].tolist() == [
        "faces / left: anxious - non-anxious"
    ]
    assert list(bundle.named_frames) == ["Group Cell Contrasts"]


def test_raw_wald_and_raw_sensitivity_rows_are_detailed_only() -> None:
    bundle = build_native_inference_report(
        "multi",
        step_payloads={
            "Fixed Effects": pd.DataFrame(
                [
                    {
                        "term": "Intercept",
                        "estimate": 1.0,
                        "p_value_wald": 0.001,
                        "status": "ok",
                    }
                ]
            ),
            "Marginal Group Contrasts": pd.DataFrame(
                [
                    {
                        "reference_group_id": "control",
                        "comparison_group_id": "anxious",
                        "estimate": 0.5,
                        "p_value_wald": 0.02,
                        "status": "ok",
                    }
                ]
            ),
            "Robust Sensitivity Results": pd.DataFrame(
                [
                    {
                        "test_id": "trimmed",
                        "test_label": "Trimmed sensitivity",
                        "condition": "faces",
                        "roi": "left",
                        "p_raw": 0.01,
                        "inference_status": "sensitivity",
                    }
                ]
            ),
            "Group Cell Contrasts": _group_cell_results().iloc[[1]].copy(),
        },
    )

    assert {"Intercept", "anxious - control", "Trimmed sensitivity"}.issubset(
        set(bundle.test_inventory["test_label"])
    )
    assert not bundle.test_inventory.loc[
        bundle.test_inventory["source_frame"].isin(
            [
                "Fixed Effects",
                "Marginal Group Contrasts",
                "Robust Sensitivity Results",
            ]
        ),
        "headline_eligible",
    ].any()
    assert "Intercept: evidence" not in bundle.at_a_glance
    assert "anxious - control: evidence" not in bundle.at_a_glance
    assert "Trimmed sensitivity: evidence" not in bundle.at_a_glance
    assert "unadjusted p-value; p=0.0010" not in bundle.at_a_glance


def test_single_lmm_wald_alias_is_inventoried_but_never_headlined() -> None:
    fixed_effects = pd.DataFrame(
        [
            {
                "Effect": "condition[T.B]",
                "Coef.": 0.4,
                "P>|z|": 0.01,
                "CI Low": 0.1,
                "CI High": 0.7,
                "LRT Status": "ok",
            }
        ]
    )
    bundle = build_native_inference_report(
        "single",
        _prepared_design(excluded=""),
        {"Mixed Model": fixed_effects},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["p_value_column"] == "P>|z|"
    assert row["p_value_source"] == "wald"
    assert row["estimate"] == pytest.approx(0.4)
    assert row["n"] == 12
    assert not bool(row["headline_eligible"])
    assert "condition[T.B]: evidence" not in bundle.at_a_glance
    assert "condition[T.B]" in bundle.detailed_methods


def test_single_mixed_model_lrt_is_detailed_secondary() -> None:
    lrt = pd.DataFrame(
        [
            {
                "Effect": "condition * roi",
                "p_value_chi2": 0.01,
                "status": "ok",
                "reportable": True,
                "headline_eligible": True,
                "analysis_scope": "complete_core",
            }
        ]
    )

    bundle = build_native_inference_report(
        "single",
        _prepared_design(excluded=""),
        {"Mixed Model LRT": lrt},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["p_value_source"] == "likelihood_ratio"
    assert not bool(row["headline_eligible"])
    assert row["headline_reason"] == "single_mixed_model_lrt_is_secondary"


def test_available_case_single_mixed_model_lrt_can_be_headlined_explicitly() -> None:
    lrt = pd.DataFrame(
        [
            {
                "Effect": "condition * roi",
                "p_value_chi2": 0.01,
                "p_adjusted": 0.03,
                "adjustment_method": "holm",
                "family_id": "omnibus_effects_strict",
                "family_size": 3,
                "status": "ok",
                "reportable": True,
                "headline_eligible": True,
                "analysis_scope": "available_case",
            }
        ]
    )

    bundle = build_native_inference_report(
        "single",
        _available_case_design(),
        {"Mixed Model LRT": lrt},
    )

    row = bundle.test_inventory.iloc[0]
    assert bool(row["headline_eligible"])
    assert row["headline_reason"] == (
        "available_case_lmm_lrt_marked_headline_eligible"
    )
    assert "condition * roi: evidence of a within-subject effect" in (
        bundle.at_a_glance
    )


def test_available_case_reporting_discloses_missing_data_contract() -> None:
    bundle = build_native_inference_report(
        "single",
        _available_case_design(),
        {
            "Mixed Model LRT": pd.DataFrame(
                [
                    {
                        "Effect": "condition",
                        "p_value_chi2": 0.20,
                        "status": "ok",
                        "reportable": True,
                        "headline_eligible": True,
                        "analysis_scope": "available_case",
                    }
                ]
            )
        },
    )

    text = f"{bundle.at_a_glance}\n{bundle.detailed_methods}"
    assert "frozen at N=12" in text
    assert "N=10 participant(s) contributed" in text
    assert "Conditions retained for available-case modeling: faces; objects" in text
    assert "Fully complete conditions: faces" in text
    assert "Partially observed conditions retained in the model: objects" in text
    assert "required fixed-effect cell" in text
    assert "No imputation was performed" in text
    assert "varied from N=8 to N=10" in text
    assert "Repeated-measures ANOVA and paired post-hoc tests" in text
    assert "missing at random, MAR" in text
    assert "missing not at random, MNAR" in text
    assert {
        "available_case_no_imputation",
        "available_case_mar_assumption",
        "available_case_mnar_bias",
        "balanced_methods_omitted",
        "frozen_vs_contributing_participants",
        "varying_cell_sample_sizes",
    }.issubset(set(bundle.limitations["code"]))
    summary = bundle.run_summary.iloc[0]
    assert summary["analysis_scope"] == "available_case"
    assert summary["n_frozen_participants"] == 12
    assert summary["n_contributing_participants"] == 10
    assert summary["partial_conditions"] == "objects"
    assert summary["imputation_method"] == "none"


def test_available_case_wald_row_remains_detailed_only_when_explicitly_marked() -> None:
    fixed_effect = pd.DataFrame(
        [
            {
                "Effect": "condition[T.objects]",
                "P>|z|": 0.01,
                "status": "ok",
                "headline_eligible": True,
                "analysis_scope": "available_case",
            }
        ]
    )

    bundle = build_native_inference_report(
        "single",
        _available_case_design(),
        {"Mixed Model": fixed_effect},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["p_value_source"] == "wald"
    assert not bool(row["headline_eligible"])
    assert row["headline_reason"] == "raw_wald_p_is_detailed_only"


def test_analysis_can_mark_unadjusted_omnibus_decomposition_detailed_only() -> None:
    omnibus = _omnibus_results().iloc[[0]].copy()
    omnibus["headline_eligible"] = False
    omnibus["inference_role"] = "exploratory"

    bundle = build_native_inference_report(
        "multi",
        step_payloads={"Omnibus LRT": omnibus},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["role"] == "exploratory"
    assert not bool(row["headline_eligible"])
    assert row["headline_reason"] == "analysis_marked_detailed_only"


def test_actual_group_worker_response_is_not_duplicated() -> None:
    from Tools.Stats.analysis.inference_contracts import (
        AnalysisProfile,
        AnalysisRunSpec,
        HarmonicProvenance,
    )
    from Tools.Stats.analysis.prepared_analysis import prepare_analysis_payload
    from Tools.Stats.workers.multigroup_workers import run_group_cell_step

    rows: list[dict[str, object]] = []
    assignments = {
        "P1": "control",
        "P2": "control",
        "P3": "control",
        "P4": "anxious",
        "P5": "anxious",
        "P6": "anxious",
    }
    for participant_index, (participant, group) in enumerate(
        assignments.items()
    ):
        for condition_index, condition in enumerate(("faces", "objects")):
            rows.append(
                {
                    "participant": participant,
                    "condition": condition,
                    "roi": "left",
                    "value": (
                        participant_index * 0.1
                        + condition_index * 0.2
                        + (0.6 if group == "anxious" else 0.0)
                    ),
                }
            )
    prepared = prepare_analysis_payload(
        pd.DataFrame(rows),
        mode="multi",
        run_spec=AnalysisRunSpec(
            profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
            harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
        ),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        canonical_group_ids=assignments,
        selected_group_pair=("anxious", "control"),
        preparation_id="report-integration",
    )
    worker_result = run_group_cell_step(prepared_payload=prepared)
    bundle = build_native_inference_report(
        "multi",
        prepared_payload=prepared,
        prior_results={"group_cell_comparisons": worker_result},
    )

    contrasts = bundle.test_inventory[
        bundle.test_inventory["source_frame"].eq("Group Cell Contrasts")
    ]
    assert len(contrasts) == 2
    assert contrasts["test_label"].is_unique
    assert not bundle.test_inventory["source_frame"].str.contains(
        r"\(\d+\)$",
        regex=True,
    ).any()


def test_declared_metadata_merges_and_schema_adapters_preserve_details() -> None:
    declared = pd.DataFrame(
        [
            {
                "test_id": "paired_followup",
                "test_label": "Declared paired follow-up",
                "method": "paired t-test",
                "estimand": "mean paired A minus B",
                "alternative": "two_sided",
                "profile": "confirmatory",
                "role": "primary",
                "family_id": "planned_contrasts",
                "followup_provenance": "planned",
                "condition": "faces",
                "roi": "left",
            }
        ]
    )
    computed = pd.DataFrame(
        [
            {
                "test_id": "paired_followup",
                "condition": "faces",
                "roi": "left",
                "Level_A": "fear",
                "Level_B": "neutral",
                "Stratum": "left ROI",
                "N_Pairs": 12,
                "mean_diff": 0.4,
                "ci95_low": 0.1,
                "ci95_high": 0.7,
                "cohens_dz": 0.6,
                "p_raw": 0.01,
                "p_adjusted": 0.04,
                "reject_adjusted": True,
                "family_id": "planned_contrasts",
                "family_size": 4,
                "adjustment_method": "holm",
                "alpha": 0.05,
                "inference_status": "estimated",
            }
        ]
    )
    bundle = build_native_inference_report(
        "single",
        step_payloads={
            "Test Inventory": declared,
            "Interaction Posthocs": computed,
        },
    )

    assert len(bundle.test_inventory) == 1
    row = bundle.test_inventory.iloc[0]
    assert row["test_label"] == "left ROI: fear - neutral"
    assert row["estimand"] == "mean paired A minus B"
    assert row["alternative"] == "two_sided"
    assert row["profile"] == "confirmatory"
    assert row["followup_provenance"] == "planned"
    assert row["family_size"] == 4
    assert row["n"] == 12
    assert row["ci_low"] == pytest.approx(0.1)
    assert row["ci_high"] == pytest.approx(0.7)
    assert "left ROI: fear - neutral" in bundle.at_a_glance


def test_canonical_reject_uses_inclusive_alpha_and_validates_export() -> None:
    response = _response_results(p_adjusted=0.05)
    response["reject_adjusted"] = False
    bundle = build_native_inference_report(
        "single",
        step_payloads={"response_results": response},
        alpha=0.05,
    )

    row = bundle.test_inventory.iloc[0]
    assert bool(row["canonical_reject"]) is True
    assert bool(row["significant"]) is True
    assert row["reject_source"] == (
        "recomputed_from_selected_p_le_alpha_export_mismatch"
    )
    assert "evidence of a response was found" in bundle.at_a_glance


def test_invalid_probability_is_retained_without_a_claim() -> None:
    response = _response_results(p_adjusted=-0.1)
    bundle = build_native_inference_report(
        "single",
        step_payloads={"response_results": response},
    )

    row = bundle.test_inventory.iloc[0]
    assert not bool(row["reportable"])
    assert pd.isna(row["p_value_used"])
    assert "invalid_p_value" in row["status"]
    assert "no primary conclusion was drawn" in bundle.at_a_glance


def test_one_sample_resampling_is_response_detection() -> None:
    resampling = pd.DataFrame(
        [
            {
                "condition": "faces",
                "roi": "left",
                "n_participants": 12,
                "estimate": 0.5,
                "statistic_name": "one_sample_t",
                "p_raw_resampling": 0.01,
                "p_adjusted_max_t": 0.04,
                "reject_adjusted": True,
                "family_id": "response_core_cells",
                "family_size": 2,
                "adjustment_method": "single_step_max_abs_t_fwer",
                "inference_status": "estimated",
            }
        ]
    )
    bundle = build_native_inference_report(
        "single",
        step_payloads={"Resampling Cell Results": resampling},
    )

    row = bundle.test_inventory.iloc[0]
    assert row["section"] == "response_detection"
    assert row["role"] == "sensitivity"
    assert "Sensitivity only" in bundle.at_a_glance
    assert "evidence of a response was found" in bundle.at_a_glance


def test_export_path_is_visible_and_numeric_fallback_preserves_sources(
    tmp_path: Path,
) -> None:
    requested = tmp_path / "full.xlsx"
    bundle = build_native_inference_report(
        "single",
        _prepared_design(),
        {"response_results": _response_results()},
        export_path=requested,
    )
    assert f"Detailed workbook: {requested}." in bundle.at_a_glance

    source = pd.DataFrame(
        [{"label": "=1+1", "items": {"b", "a"}, "p_adjusted": 0.2}]
    )
    fallback = tmp_path / "fallback.xlsx"
    write_native_numeric_workbook(
        None,
        {
            "step": {
                "frames": {"Numeric Results": source},
                "export_frames": {"Numeric Results": source},
            }
        },
        fallback,
        report_error=RuntimeError("narrative failed"),
    )

    workbook = pd.ExcelFile(fallback)
    assert workbook.sheet_names[:2] == [
        "Numeric Export Metadata",
        "Report Failure",
    ]
    assert workbook.sheet_names.count("Numeric Results") == 1
    failure = pd.read_excel(fallback, sheet_name="Report Failure")
    assert bool(failure.loc[0, "numeric_results_preserved"])
    numeric = pd.read_excel(fallback, sheet_name="Numeric Results")
    assert numeric.loc[0, "label"] == "=1+1"
    assert numeric.loc[0, "items"] == "a; b"
    with ZipFile(fallback) as archive:
        worksheet_xml = "".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
        )
    assert "<f>" not in worksheet_xml


def test_workbook_is_deterministic_and_atomic_on_writer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "deterministic.xlsx"
    source = pd.DataFrame([{"items": {"z", "a"}, "p_adjusted": 0.2}])
    write_native_numeric_workbook(None, {"results": source}, path)
    first_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    write_native_numeric_workbook(None, {"results": source}, path)
    second_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert first_hash == second_hash

    path.write_bytes(b"existing-complete-workbook")

    def fail_writer(*_args, **_kwargs):
        raise RuntimeError("writer failed")

    monkeypatch.setattr(pd, "ExcelWriter", fail_writer)
    with pytest.raises(RuntimeError, match="writer failed"):
        write_native_numeric_workbook(None, {"results": source}, path)
    assert path.read_bytes() == b"existing-complete-workbook"
    assert not list(tmp_path.glob(".deterministic.*.tmp.xlsx"))

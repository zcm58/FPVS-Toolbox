import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.baseline_vs_zero import (
    export_baseline_vs_zero_results_to_excel,
    run_baseline_vs_zero_tests,
)
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME
from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    HarmonicProvenance,
    build_standard_screening_run_spec,
)
from Tools.Stats.controller.stats_controller import SINGLE_PIPELINE_STEPS, WORKER_FN_BY_STEP
from Tools.Stats.common.stats_core import StepId
from Tools.Stats.workers.stats_workers import run_baseline_vs_zero as run_baseline_worker


def _build_df() -> pd.DataFrame:
    rows = []
    subjects = ["S1", "S2", "S3"]
    for subject, base in zip(subjects, [0.6, 0.5, 0.7]):
        rows.append({"subject": subject, "condition": "A", "roi": "R1", "value": base})
        rows.append({"subject": subject, "condition": "B", "roi": "R1", "value": base - 0.8})
        rows.append({"subject": subject, "condition": "A", "roi": "R2", "value": base + 0.3})
        rows.append({"subject": subject, "condition": "B", "roi": "R2", "value": base + 0.1})
    return pd.DataFrame(rows)


def test_baseline_vs_zero_duplicate_keys_raise() -> None:
    df = _build_df()
    duplicated = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate rows detected"):
        run_baseline_vs_zero_tests(
            duplicated,
            dv_col="value",
            subject_col="subject",
            condition_col="condition",
            roi_col="roi",
        )


def test_baseline_vs_zero_correction_scope_outputs() -> None:
    df = _build_df()

    _, global_df = run_baseline_vs_zero_tests(
        df,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        correction_scope="global",
    )
    _, within_roi_df = run_baseline_vs_zero_tests(
        df,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        correction_scope="within_roi",
    )

    for col in ["p_corr", "reject"]:
        assert col in global_df.columns
        assert col in within_roi_df.columns

    merged = global_df.merge(
        within_roi_df,
        on=["condition", "roi"],
        suffixes=("_global", "_within"),
    )
    assert not np.allclose(
        merged["p_corr_global"].to_numpy(dtype=float),
        merged["p_corr_within"].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_baseline_vs_zero_output_uses_readable_summary_text() -> None:
    df = _build_df()

    output_text, _ = run_baseline_vs_zero_tests(
        df,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        correction_scope="global",
    )

    assert "Summary:" in output_text
    assert "Corrected significant findings:" in output_text
    assert "corrected p=" in output_text
    assert "condition=" not in output_text
    assert "roi=" not in output_text


def test_single_pipeline_registers_baseline_vs_zero_step() -> None:
    assert StepId.BASELINE_VS_ZERO in SINGLE_PIPELINE_STEPS
    assert StepId.BASELINE_VS_ZERO in WORKER_FN_BY_STEP


def test_single_pipeline_does_not_register_removed_harmonic_check() -> None:
    assert "HARMONIC_CHECK" not in StepId.__members__
    assert all(step.name != "HARMONIC_CHECK" for step in SINGLE_PIPELINE_STEPS)


def test_baseline_worker_reports_fixed_predefined_dv_metadata(monkeypatch) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.set_rois", lambda _rois: None)
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_qc_screening",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None),
    )
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_manual_exclusions",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], []),
    )

    def _prepare_summed_bca_data(**kwargs):  # noqa: ANN003
        seen["dv_policy"] = kwargs["dv_policy"]
        kwargs["dv_metadata"].update(
            {
                "policy_name": FIXED_PREDEFINED_POLICY_NAME,
                "fixed_predefined_harmonics": {
                    "harmonic_policy": "fixed_predefined_harmonic_list",
                    "harmonic_policy_label": (
                        "Fixed predefined harmonic list applied uniformly across "
                        "participants, conditions, and ROIs"
                    ),
                    "fixed_harmonic_included_frequencies_hz": [1.2, 2.4, 3.6, 4.8, 7.2],
                    "snr_used_for_statistics": False,
                    "applied_uniformly_across_participants": True,
                    "applied_uniformly_across_conditions": True,
                    "applied_uniformly_across_rois": True,
                },
            }
        )
        return {
            "S1": {"A": {"ROI1": 0.4}},
            "S2": {"A": {"ROI1": 0.5}},
            "S3": {"A": {"ROI1": 0.6}},
        }

    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers.prepare_summed_bca_data",
        _prepare_summed_bca_data,
    )
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_outlier_exclusion",
        lambda df, **kwargs: (df, None),
    )
    monkeypatch.setattr("Tools.Stats.workers.stats_workers.merge_exclusion_reports", lambda a, b: None)
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._extract_required_exclusions",
        lambda _report: [],
    )

    result = run_baseline_worker(
        lambda _progress: None,
        lambda _message: None,
        subjects=["S1", "S2", "S3"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"S1": {"A": "unused"}, "S2": {"A": "unused"}, "S3": {"A": "unused"}},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        dv_policy={
            "name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4, 3.6, 4.8, 7.2",
        },
    )

    assert seen["dv_policy"]["name"] == FIXED_PREDEFINED_POLICY_NAME
    assert result["metadata"]["dv_policy_name"] == FIXED_PREDEFINED_POLICY_NAME
    assert result["metadata"]["selected_harmonics_hz"] == "1.2;2.4;3.6;4.8;7.2"
    assert result["metadata"]["snr_used_for_statistics"] is False
    assert result["metadata"]["harmonic_provenance"] == "user_fixed_unverified"
    assert result["metadata"]["inference_status"] == "provenance_unverified"
    assert result["dv_metadata"]["fixed_predefined_harmonics"][
        "applied_uniformly_across_conditions"
    ] is True


def test_legacy_defaults_and_result_aliases_remain_compatible() -> None:
    _, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
    )

    assert set(results["alternative"]) == {"greater"}
    assert set(results["adjustment_method"]) == {"fdr_bh"}
    np.testing.assert_allclose(
        results["p_corr"],
        results["p_adjusted"],
        equal_nan=True,
    )
    np.testing.assert_array_equal(results["reject"], results["reject_adjusted"])
    assert set(results["harmonic_provenance"]) == {"unknown"}
    assert set(results["inference_status"]) == {"provenance_unverified"}


def test_confirmatory_independent_run_uses_declared_holm_family() -> None:
    family = FamilySpec(
        "response_core_cells",
        "Complete-core responses",
        CorrectionMethod.HOLM,
    )
    run_spec = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.INDEPENDENTLY_SELECTED,
        response_alternative=Alternative.TWO_SIDED,
        families=(family,),
    )

    output, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        run_spec=run_spec,
    )
    finite = results["p_raw"].notna()
    expected_reject, expected_adjusted, _, _ = multipletests(
        results.loc[finite, "p_raw"],
        method="holm",
    )

    np.testing.assert_allclose(
        results.loc[finite, "p_adjusted"],
        expected_adjusted,
    )
    np.testing.assert_array_equal(
        results.loc[finite, "reject_adjusted"],
        expected_reject,
    )
    assert set(results["family_id"]) == {"response_core_cells"}
    assert set(results["family_size"]) == {int(finite.sum())}
    assert set(results["alternative"]) == {"two_sided"}
    assert set(results["inference_status"]) == {"confirmatory"}
    assert set(results["harmonic_provenance"]) == {"independently_selected"}
    assert "correction=holm" in output


def test_confirmatory_profile_does_not_override_unverified_provenance() -> None:
    run_spec = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
    )

    _, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        run_spec=run_spec,
    )

    assert set(results["adjustment_method"]) == {"holm"}
    assert set(results["inference_status"]) == {"provenance_unverified"}
    assert not (results["inference_status"] == "confirmatory").any()


def test_standard_screening_only_calls_positive_cells_responses() -> None:
    run_spec = build_standard_screening_run_spec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    _, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        run_spec=run_spec,
    )
    negative = results.loc[
        results["condition"].eq("B") & results["roi"].eq("R1")
    ].iloc[0]

    assert set(results["alternative"]) == {"greater"}
    assert set(results["adjustment_method"]) == {"holm"}
    assert negative["mean"] < 0.0
    assert negative["t"] < 0.0
    assert negative["p_raw"] > 0.5
    assert not bool(negative["reject_adjusted"])


def test_same_sample_provenance_is_explicitly_post_selection() -> None:
    _, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    assert set(results["harmonic_provenance"]) == {"same_sample_adaptive"}
    assert set(results["inference_status"]) == {"exploratory_post_selection"}


def test_tiny_n_zero_variance_and_nonfinite_cells_are_non_estimable() -> None:
    data = pd.DataFrame(
        [
            {"subject": "S1", "condition": "constant", "roi": "R1", "value": 1.0},
            {"subject": "S2", "condition": "constant", "roi": "R1", "value": 1.0},
            {"subject": "S3", "condition": "constant", "roi": "R1", "value": 1.0},
            {"subject": "S1", "condition": "tiny", "roi": "R1", "value": 0.1},
            {"subject": "S2", "condition": "tiny", "roi": "R1", "value": np.inf},
        ]
    )

    _, results = run_baseline_vs_zero_tests(
        data,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
    )
    constant = results.loc[results["condition"] == "constant"].iloc[0]
    tiny = results.loc[results["condition"] == "tiny"].iloc[0]

    assert constant["note"] == "zero_variance"
    assert tiny["note"] == (
        "nonfinite_or_nonnumeric_values_dropped;insufficient_n"
    )
    for row in (constant, tiny):
        assert pd.isna(row["t"])
        assert pd.isna(row["df"])
        assert pd.isna(row["p_raw"])
        assert pd.isna(row["p_adjusted"])
        assert pd.isna(row["cohens_d"])
        assert pd.isna(row["cohens_dz"])
        assert pd.isna(row["ci_mean_low"])
        assert pd.isna(row["ci_mean_high"])
        assert not row["reject_adjusted"]
    assert set(results["family_size"]) == {0}


def test_baseline_export_uses_generic_holm_label_and_keeps_alias(
    tmp_path,
) -> None:
    family = FamilySpec("response_core_cells", "Core responses", "holm")
    _, results = run_baseline_vs_zero_tests(
        _build_df(),
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        family_spec=family,
    )
    target = tmp_path / "baseline.xlsx"

    export_baseline_vs_zero_results_to_excel(
        {"results_df": results, "metadata": {}},
        target,
        lambda _message: None,
    )
    exported = pd.read_excel(target, sheet_name="Baseline_vs_Zero")
    metadata = pd.read_excel(target, sheet_name="Metadata")
    metadata_map = dict(zip(metadata["field"], metadata["value"]))

    assert "p (adjusted: Holm)" in exported.columns
    assert "p (BH-FDR corrected)" not in exported.columns
    assert "p_corr" in exported.columns
    assert metadata_map["corrected_p_value_column"] == "p_adjusted"
    assert (
        metadata_map["corrected_p_value_column_in_sheet"]
        == "p (adjusted: Holm)"
    )

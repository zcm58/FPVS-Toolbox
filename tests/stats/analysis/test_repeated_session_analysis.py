from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.repeated_session_analysis import (
    RepeatedSessionDesignError,
    audit_repeated_session_design,
    run_repeated_session_analysis,
)
from Tools.Stats.analysis.repeated_session_contracts import (
    FIXED_ORDER_CONFOUNDING,
    REPEATED_SESSION_INFERENCE_CONTRACT_VERSION,
    SESSION_PHASE_AT_VISIT_TERM,
    RepeatedSessionInferenceContract,
)


OUTCOMES = (("Angry", "Occipital"), ("Happy", "Occipital"))
DELTA_VALUES = {
    ("birth_control", "Angry"): [1.0, 1.2, 1.4, 1.8],
    ("control", "Angry"): [0.1, 0.3, 0.4, 0.8, 1.0],
    ("birth_control", "Happy"): [0.2, 0.4, 0.5, 0.7],
    ("control", "Happy"): [-0.2, 0.0, 0.1, 0.3, 0.5],
}


def _contract() -> RepeatedSessionInferenceContract:
    return RepeatedSessionInferenceContract(
        group_ids=("birth_control", "control"),
        group_labels=("Birth control", "No birth control"),
        session_ids=("luteal", "follicular"),
        session_labels=("Luteal", "Follicular"),
    )


def _complete_data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    participants = {
        "birth_control": ["B1", "B2", "B3", "B4"],
        "control": ["C1", "C2", "C3", "C4", "C5"],
    }
    group_labels = {
        "birth_control": "Birth control",
        "control": "No birth control",
    }
    for group_id, group_participants in participants.items():
        for participant_index, participant in enumerate(group_participants):
            for condition_index, (condition, roi) in enumerate(OUTCOMES):
                visit_1_value = 1.0 + participant_index * 0.25 + condition_index
                delta = DELTA_VALUES[(group_id, condition)][participant_index]
                for session_id, session_label, visit_index, value in (
                    ("luteal", "Luteal", 1, visit_1_value),
                    ("follicular", "Follicular", 2, visit_1_value + delta),
                ):
                    rows.append(
                        {
                            "participant_id": participant,
                            "recording_id": f"{participant}__{session_id}",
                            "session_id": session_id,
                            "session_label": session_label,
                            "visit_index": visit_index,
                            "group_id": group_id,
                            "group_label": group_labels[group_id],
                            "condition": condition,
                            "roi": roi,
                            "summed_bca_uv": value,
                            "qc_flag": False,
                            "qc_notes": "",
                            "excluded": False,
                            "exclusion_reason": "",
                        }
                    )
    return pd.DataFrame(rows)


def test_contract_is_versioned_ordered_and_exposes_fixed_order_confounding() -> None:
    contract = _contract()
    metadata = contract.to_metadata()

    assert contract.schema_version == REPEATED_SESSION_INFERENCE_CONTRACT_VERSION
    assert contract.visit_indices == (1, 2)
    assert SESSION_PHASE_AT_VISIT_TERM in contract.session_contrast_label
    assert metadata["fixed_order_confounding"] == FIXED_ORDER_CONFOUNDING
    assert "cannot isolate physiological phase" in FIXED_ORDER_CONFOUNDING
    assert contract.primary_family.method.value == "holm"
    assert contract.secondary_family.method.value == "holm"

    with pytest.raises(ValueError, match="distinct stable groups"):
        RepeatedSessionInferenceContract(
            group_ids=("same", "SAME"),
            session_ids=("first", "second"),
            session_labels=("First", "Second"),
        )
    with pytest.raises(ValueError, match=r"visit_indices=\(1, 2\)"):
        RepeatedSessionInferenceContract(
            group_ids=("a", "b"),
            session_ids=("first", "second"),
            session_labels=("First", "Second"),
            visit_indices=(2, 1),
        )


def test_primary_welch_compares_participant_deltas_and_holm_spans_outcomes() -> None:
    result = run_repeated_session_analysis(
        _complete_data(),
        contract=_contract(),
        outcomes=OUTCOMES,
    )
    primary = result.primary_results.set_index("condition")
    angry = primary.loc["Angry"]
    expected = stats.ttest_ind(
        DELTA_VALUES[("birth_control", "Angry")],
        DELTA_VALUES[("control", "Angry")],
        equal_var=False,
    )

    assert angry["n_pairs_group_a"] == 4
    assert angry["n_pairs_group_b"] == 5
    assert angry["welch_t"] == pytest.approx(float(expected.statistic))
    assert angry["p_raw"] == pytest.approx(float(expected.pvalue))
    assert angry["estimate_delta_difference_group_a_minus_group_b"] == pytest.approx(
        np.mean(DELTA_VALUES[("birth_control", "Angry")])
        - np.mean(DELTA_VALUES[("control", "Angry")])
    )
    assert angry["ci_difference_low"] < angry[
        "estimate_delta_difference_group_a_minus_group_b"
    ]
    assert angry["ci_difference_high"] > angry[
        "estimate_delta_difference_group_a_minus_group_b"
    ]
    assert angry["hedges_g"] > 0
    expected_adjusted = multipletests(
        result.primary_results["p_raw"].to_numpy(dtype=float),
        method="holm",
    )[1]
    np.testing.assert_allclose(
        result.primary_results["p_adjusted"],
        expected_adjusted,
    )
    assert result.primary_results["family_size"].eq(len(OUTCOMES)).all()
    assert result.primary_results["adjustment_method"].eq("holm").all()
    assert result.primary_results["missing_values_imputed"].eq(False).all()
    assert result.primary_results["fallback_method"].eq("none").all()
    assert result.primary_results["estimand_label"].str.contains(
        SESSION_PHASE_AT_VISIT_TERM,
        regex=False,
    ).all()
    assert result.primary_results["fixed_order_confounding"].eq(
        FIXED_ORDER_CONFOUNDING
    ).all()


def test_secondary_family_uses_paired_deltas_with_ci_and_cohens_dz() -> None:
    result = run_repeated_session_analysis(
        _complete_data(),
        contract=_contract(),
        outcomes=OUTCOMES,
    )
    secondary = result.secondary_results
    row = secondary[
        secondary["condition"].eq("Angry")
        & secondary["group_id"].eq("birth_control")
    ].iloc[0]
    values = np.asarray(DELTA_VALUES[("birth_control", "Angry")], dtype=float)
    expected = stats.ttest_1samp(values, popmean=0.0)

    assert row["n_complete_pairs"] == len(values)
    assert row["paired_t"] == pytest.approx(float(expected.statistic))
    assert row["p_raw"] == pytest.approx(float(expected.pvalue))
    assert row["cohens_dz"] == pytest.approx(
        float(np.mean(values) / np.std(values, ddof=1))
    )
    assert row["ci_delta_low"] < row["mean_delta_session2_minus_session1"]
    assert row["ci_delta_high"] > row["mean_delta_session2_minus_session1"]
    assert len(secondary) == len(OUTCOMES) * 2
    assert secondary["family_size"].eq(len(OUTCOMES) * 2).all()
    expected_adjusted = multipletests(
        secondary["p_raw"].to_numpy(dtype=float),
        method="holm",
    )[1]
    np.testing.assert_allclose(secondary["p_adjusted"], expected_adjusted)
    assert secondary["estimand_label"].str.contains(
        SESSION_PHASE_AT_VISIT_TERM,
        regex=False,
    ).all()


def test_missing_sessions_exclusions_and_nonfinite_values_remain_explicit() -> None:
    data = _complete_data()
    data = data[
        ~(data["participant_id"].eq("B4") & data["visit_index"].eq(2))
    ].copy()
    excluded = (
        data["participant_id"].eq("C5")
        & data["condition"].eq("Angry")
        & data["visit_index"].eq(2)
    )
    data.loc[excluded, "excluded"] = True
    data.loc[excluded, "exclusion_reason"] = "Recording-condition QC exclusion"
    nonfinite = (
        data["participant_id"].eq("C4")
        & data["condition"].eq("Happy")
        & data["visit_index"].eq(1)
    )
    data.loc[nonfinite, "summed_bca_uv"] = np.nan

    audit = audit_repeated_session_design(
        data,
        contract=_contract(),
        outcomes=OUTCOMES,
    )
    participant = audit.participant_sessions.set_index("participant_id").loc["B4"]
    assert participant["pair_status"] == "missing_visit_2_recording"
    assert not bool(participant["complete_recording_pair"])
    assert SESSION_PHASE_AT_VISIT_TERM in participant["pair_status_label"]

    pairs = audit.outcome_pairs.set_index(["participant_id", "condition"])
    assert "missing_visit_2_session" in pairs.loc[("B4", "Angry"), "pair_status"]
    assert "excluded_visit_2" in pairs.loc[("C5", "Angry"), "pair_status"]
    assert "nonfinite_visit_1" in pairs.loc[("C4", "Happy"), "pair_status"]
    assert not bool(pairs.loc[("C5", "Angry"), "complete_usable_pair"])
    assert not audit.normalized_data["summed_bca_uv"].notna().all()
    assert audit.outcome_pairs["missing_values_imputed"].eq(False).all()

    coverage = audit.coverage.set_index(["condition", "group_id"])
    assert coverage.loc[("Angry", "birth_control"), "n_missing_visit_2_sessions"] == 1
    assert coverage.loc[("Angry", "control"), "n_visit_2_excluded"] == 1
    assert coverage.loc[("Happy", "control"), "n_visit_1_nonfinite"] == 1

    result = run_repeated_session_analysis(
        data,
        contract=_contract(),
        outcomes=OUTCOMES,
    )
    angry = result.primary_results.set_index("condition").loc["Angry"]
    assert angry["n_pairs_group_a"] == 3
    assert angry["n_pairs_group_b"] == 4
    assert result.metadata.loc[0, "n_missing_recording_pairs"] == 1
    assert result.metadata.loc[0, "missing_values_imputed"] == False  # noqa: E712


def test_stable_group_recording_grain_and_visit_order_are_hard_requirements() -> None:
    data = _complete_data()
    conflict = data.copy()
    mask = conflict["participant_id"].eq("B1") & conflict["session_id"].eq(
        "follicular"
    )
    conflict.loc[mask, "group_id"] = "control"
    conflict.loc[mask, "group_label"] = "No birth control"
    with pytest.raises(RepeatedSessionDesignError, match="stable across sessions"):
        run_repeated_session_analysis(
            conflict,
            contract=_contract(),
            outcomes=OUTCOMES,
        )

    duplicate = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    with pytest.raises(RepeatedSessionDesignError, match="Exactly one row"):
        run_repeated_session_analysis(
            duplicate,
            contract=_contract(),
            outcomes=OUTCOMES,
        )

    wrong_visit = data.copy()
    wrong_visit.loc[wrong_visit["session_id"].eq("follicular"), "visit_index"] = 1
    with pytest.raises(RepeatedSessionDesignError, match="disagree"):
        run_repeated_session_analysis(
            wrong_visit,
            contract=_contract(),
            outcomes=OUTCOMES,
        )


def test_nonestimable_declared_outcome_stays_in_full_holm_family() -> None:
    declared = (*OUTCOMES, ("Sad", "Occipital"))
    result = run_repeated_session_analysis(
        _complete_data(),
        contract=_contract(),
        outcomes=declared,
    )
    primary = result.primary_results.set_index("condition")
    assert primary.loc["Sad", "inference_status"] == "not_estimable"
    assert np.isnan(float(primary.loc["Sad", "p_raw"]))
    assert np.isnan(float(primary.loc["Sad", "p_adjusted"]))
    assert result.primary_results["family_size"].eq(len(declared)).all()

    estimated = result.primary_results["p_raw"].to_numpy(dtype=float)
    conservative_input = np.where(np.isfinite(estimated), estimated, 1.0)
    expected = multipletests(conservative_input, method="holm")[1]
    finite = np.isfinite(estimated)
    np.testing.assert_allclose(
        result.primary_results.loc[finite, "p_adjusted"],
        expected[finite],
    )
    assert not bool(primary.loc["Sad", "reject_adjusted"])


def test_result_bundle_exposes_primary_secondary_and_all_pair_audits() -> None:
    result = run_repeated_session_analysis(
        _complete_data(),
        contract=_contract(),
        outcomes=OUTCOMES,
    )
    frames = result.to_frames()

    assert set(frames) == {
        "Repeated Session Primary",
        "Repeated Session Secondary",
        "Repeated Session Metadata",
        "Participant Session Audit",
        "Outcome Pair Audit",
        "Repeated Session Deltas",
        "Session Pair Coverage",
    }
    assert result.metadata.loc[0, "fallback_method"] == "none"
    assert result.metadata.loc[0, "analysis_scope"] == (
        "complete_pair_per_declared_outcome"
    )

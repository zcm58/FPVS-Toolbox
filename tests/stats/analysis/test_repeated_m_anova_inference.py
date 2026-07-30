from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.repeated_m_anova import (
    _apply_reported_p_contract,
    _check_balance,
    resolve_rm_anova_interaction_gate,
    resolve_rm_anova_inference,
    run_repeated_measures_anova,
)


def _balanced_three_level_data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for subject_index in range(5):
        for condition_index, condition in enumerate(("A", "B", "C")):
            rows.append(
                {
                    "subject": f"S{subject_index + 1}",
                    "condition": condition,
                    "value": (
                        0.2 * subject_index
                        + 0.4 * condition_index
                        + 0.03 * subject_index * condition_index
                    ),
                }
            )
    return pd.DataFrame(rows)


def test_constant_participant_is_not_misclassified_as_unbalanced() -> None:
    data = _balanced_three_level_data()
    data.loc[data["subject"].eq("S1"), "value"] = 1.0

    _check_balance(
        data,
        subject_col="subject",
        within_cols=["condition"],
        dv_col="value",
    )


def test_two_level_effect_reports_uncorrected_p_even_if_sphericity_flag_is_false() -> None:
    decision = resolve_rm_anova_inference(
        p_uncorrected=0.012,
        numerator_df=1,
        p_greenhouse_geisser=0.021,
        sphericity_met=False,
    )

    assert decision.p_raw_or_uncorrected == pytest.approx(0.012)
    assert decision.p_reported == pytest.approx(0.012)
    assert decision.p_correction == "none_two_level_effect"
    assert decision.inference_status == "primary_uncorrected_two_level_effect"
    assert decision.reportable is True


def test_higher_order_effect_reports_uncorrected_p_when_sphericity_is_met() -> None:
    decision = resolve_rm_anova_inference(
        p_uncorrected=0.031,
        numerator_df=2,
        p_greenhouse_geisser=0.047,
        sphericity_met=True,
    )

    assert decision.p_reported == pytest.approx(0.031)
    assert decision.p_correction == "none_sphericity_met"
    assert decision.inference_status == "primary_uncorrected_sphericity_met"
    assert decision.reportable is True


def test_higher_order_effect_reports_gg_when_sphericity_is_violated() -> None:
    decision = resolve_rm_anova_inference(
        p_uncorrected=0.008,
        numerator_df=3,
        p_greenhouse_geisser=0.024,
        sphericity_met=False,
    )

    assert decision.p_raw_or_uncorrected == pytest.approx(0.008)
    assert decision.p_reported == pytest.approx(0.024)
    assert decision.p_correction == "greenhouse_geisser"
    assert (
        decision.inference_status
        == "primary_greenhouse_geisser_sphericity_violated"
    )
    assert decision.reportable is True


def test_higher_order_effect_uses_available_gg_when_sphericity_is_not_available() -> None:
    decision = resolve_rm_anova_inference(
        p_uncorrected=0.008,
        numerator_df=3,
        p_greenhouse_geisser=0.024,
        sphericity_met=None,
    )

    assert decision.p_reported == pytest.approx(0.024)
    assert (
        decision.inference_status
        == "primary_greenhouse_geisser_sphericity_not_available"
    )
    assert decision.reportable is True


def test_required_but_unavailable_gg_blocks_primary_interpretation() -> None:
    decision = resolve_rm_anova_inference(
        p_uncorrected=0.008,
        numerator_df=2,
        p_greenhouse_geisser=np.nan,
        sphericity_met=False,
    )

    assert decision.p_raw_or_uncorrected == pytest.approx(0.008)
    assert np.isnan(decision.p_reported)
    assert decision.p_correction == "required_but_unavailable"
    assert (
        decision.inference_status
        == "blocked_primary_correction_unavailable_secondary_uncorrected_only"
    )
    assert decision.reportable is False


def test_interaction_gate_uses_only_canonical_reportable_p() -> None:
    table = pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition * roi"],
            "p_reported": [0.4, 0.3, 0.012],
            "reportable": [True, True, True],
            "inference_status": ["ok", "ok", "ok"],
            "Pr > F": [0.4, 0.3, 0.001],
        }
    )
    blocked = table.copy()
    blocked.loc[2, "p_reported"] = np.nan
    blocked.loc[2, "reportable"] = False
    blocked.loc[2, "inference_status"] = "blocked_primary_correction_unavailable"

    gate = resolve_rm_anova_interaction_gate(table, alpha=0.05)
    blocked_gate = resolve_rm_anova_interaction_gate(blocked, alpha=0.05)

    assert gate.effect == "condition * roi"
    assert gate.p_value == pytest.approx(0.012)
    assert gate.significant is True
    assert gate.reportable is True
    assert blocked_gate.p_value is None
    assert blocked_gate.significant is None
    assert blocked_gate.reportable is False
    assert blocked_gate.status == "blocked_primary_correction_unavailable"


def test_interaction_gate_prefers_multiplicity_adjusted_omnibus_decision() -> None:
    table = pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition * roi"],
            "p_reported": [0.40, 0.30, 0.018],
            "p_adjusted": [0.40, 0.40, 0.054],
            "reject_adjusted": [False, False, False],
            "reportable": [True, True, True],
            "inference_status": ["ok", "ok", "ok"],
        }
    )

    gate = resolve_rm_anova_interaction_gate(table, alpha=0.05)

    assert gate.p_value == pytest.approx(0.054)
    assert gate.significant is False
    assert gate.reportable is True
    assert gate.status == "omnibus_reportable_multiplicity_adjusted"


def test_contract_appends_canonical_fields_without_replacing_legacy_values() -> None:
    legacy = pd.DataFrame(
        {
            "Effect": ["two_level", "higher_order"],
            "Num DF": [1.0, 2.0],
            "Pr > F": [0.02, 0.01],
        }
    )

    result = _apply_reported_p_contract(legacy)

    assert list(result["Pr > F"]) == pytest.approx([0.02, 0.01])
    assert set(legacy.columns).issubset(result.columns)
    assert result.loc[0, "p_reported"] == pytest.approx(0.02)
    assert bool(result.loc[0, "reportable"]) is True
    assert np.isnan(result.loc[1, "p_reported"])
    assert bool(result.loc[1, "reportable"]) is False


def test_pingouin_path_keeps_legacy_columns_and_reports_gg(monkeypatch) -> None:
    pg_table = pd.DataFrame(
        {
            "Source": ["condition"],
            "ddof1": [2.0],
            "ddof2": [8.0],
            "F": [7.4],
            "p-unc": [0.011],
            "p-GG-corr": [0.028],
            "eps": [0.63],
            "sphericity": [False],
            "W-spher": [0.54],
            "p-spher": [0.02],
            "np2": [0.41],
        }
    )
    fake_pingouin = SimpleNamespace(rm_anova=lambda **_kwargs: pg_table.copy())
    monkeypatch.setitem(sys.modules, "pingouin", fake_pingouin)

    result = run_repeated_measures_anova(
        _balanced_three_level_data(),
        dv_col="value",
        within_cols=["condition"],
        subject_col="subject",
    )

    assert result.loc[0, "Pr > F"] == pytest.approx(0.011)
    assert result.loc[0, "Pr > F (GG)"] == pytest.approx(0.028)
    assert result.loc[0, "p_reported"] == pytest.approx(0.028)
    assert bool(result.loc[0, "reportable"]) is True
    assert result.attrs["rm_anova_backend"] == "pingouin"
    assert result.attrs["rm_anova_correction_outputs_requested"] is True
    assert result.attrs["rm_anova_inference_contract_version"] == 1
    assert result.attrs["rm_anova_primary_reportable"] is True


def test_statsmodels_fallback_blocks_higher_order_uncorrected_p(
    monkeypatch,
) -> None:
    class FailingPingouin:
        @staticmethod
        def rm_anova(**_kwargs):
            raise RuntimeError("synthetic Pingouin failure")

    class FakeAnovaRM:
        def __init__(self, **_kwargs):
            pass

        @staticmethod
        def fit():
            table = pd.DataFrame(
                {
                    "F Value": [7.4],
                    "Num DF": [2.0],
                    "Den DF": [8.0],
                    "Pr > F": [0.011],
                },
                index=["condition"],
            )
            return SimpleNamespace(anova_table=table)

    import statsmodels.stats.anova as statsmodels_anova

    monkeypatch.setitem(sys.modules, "pingouin", FailingPingouin)
    monkeypatch.setattr(statsmodels_anova, "AnovaRM", FakeAnovaRM)

    result = run_repeated_measures_anova(
        _balanced_three_level_data(),
        dv_col="value",
        within_cols=["condition"],
        subject_col="subject",
    )

    assert result.loc[0, "Pr > F"] == pytest.approx(0.011)
    assert np.isnan(result.loc[0, "p_reported"])
    assert bool(result.loc[0, "reportable"]) is False
    assert result.loc[0, "p_correction"] == "required_but_unavailable"
    assert result.attrs["rm_anova_backend"] == "statsmodels"
    assert result.attrs["rm_anova_pingouin_failed"] is True
    assert result.attrs["rm_anova_primary_reportable"] is False
    assert result.attrs["rm_anova_blocked_effects"] == ["condition"]

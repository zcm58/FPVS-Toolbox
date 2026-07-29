"""Deterministic scientific-validation checks for the native inference engines.

The Monte Carlo checks use fixed seeds and deliberately broad, predeclared
tolerances.  They are regression guards for gross calibration or direction
errors, not claims that a finite simulation proves exact Type-I error or power.

Numerical reference values were recorded from SciPy 1.16.0, Pingouin 0.5.5,
and statsmodels 0.14.5.  The tolerances allow harmless floating-point drift
while retaining independently inspectable expected values.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.baseline_vs_zero import (
    _one_sample_ttest,
    run_baseline_vs_zero_tests,
)
from Tools.Stats.analysis.group_comparisons import _welch_statistics
from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    HarmonicProvenance,
)
from Tools.Stats.analysis.repeated_m_anova import run_repeated_measures_anova


NULL_SIMULATION_SEED = 831_204
NULL_SIMULATIONS = 800
NULL_PARTICIPANTS = 24
NULL_CANDIDATES = 12

KNOWN_EFFECT_SEED = 92_517
KNOWN_EFFECT_SIMULATIONS = 300
KNOWN_EFFECT_PARTICIPANTS_PER_GROUP = 30

RM_REFERENCE_SEED = 20_260_729
RM_REFERENCE = {
    "condition": {
        "f": 199.0522115218067,
        "p": 2.9325314916186426e-09,
        "partial_eta_squared": 0.9386943436868455,
    },
    "roi": {
        "f": 62.84556369254987,
        "p": 2.470117865146726e-06,
        "partial_eta_squared": 0.8285990720209125,
    },
    "condition * roi": {
        "f": 5.2780473937734325,
        "p": 0.038845754158191796,
        "partial_eta_squared": 0.2887642908493359,
    },
}


@pytest.fixture(scope="module")
def null_selection_simulation() -> dict[str, object]:
    """Return fixed- and adaptive-selection one-sided null results."""

    rng = np.random.default_rng(NULL_SIMULATION_SEED)
    samples = rng.normal(
        loc=0.0,
        scale=1.0,
        size=(NULL_SIMULATIONS, NULL_CANDIDATES, NULL_PARTICIPANTS),
    )
    selected_indices = samples.mean(axis=2).argmax(axis=1)

    fixed_p_values = np.asarray(
        [
            _one_sample_ttest(
                simulation[0],
                alternative=Alternative.GREATER,
            )[1]
            for simulation in samples
        ],
        dtype=float,
    )
    adaptive_p_values = np.asarray(
        [
            _one_sample_ttest(
                samples[simulation_index, selected_index],
                alternative=Alternative.GREATER,
            )[1]
            for simulation_index, selected_index in enumerate(selected_indices)
        ],
        dtype=float,
    )
    return {
        "fixed_p_values": fixed_p_values,
        "adaptive_p_values": adaptive_p_values,
        "example_selected_values": samples[0, selected_indices[0]],
    }


def test_fixed_predeclared_null_response_has_nominal_type_i_behavior(
    null_selection_simulation: dict[str, object],
) -> None:
    """A fixed candidate should reject near alpha under the Gaussian null."""

    fixed_p_values = np.asarray(
        null_selection_simulation["fixed_p_values"],
        dtype=float,
    )
    rejection_rate = float(np.mean(fixed_p_values < 0.05))

    # With 800 simulations, the binomial Monte Carlo SE at alpha=.05 is
    # about .0077.  This interval is wider than three SE and is intentionally
    # tolerant of minor numerical/library variation.
    assert 0.02 <= rejection_rate <= 0.08


def test_same_sample_adaptive_selection_inflates_null_rejections_and_is_labelled(
    null_selection_simulation: dict[str, object],
) -> None:
    """Selecting the largest null response must remain explicitly exploratory."""

    fixed_p_values = np.asarray(
        null_selection_simulation["fixed_p_values"],
        dtype=float,
    )
    adaptive_p_values = np.asarray(
        null_selection_simulation["adaptive_p_values"],
        dtype=float,
    )
    fixed_rate = float(np.mean(fixed_p_values < 0.05))
    adaptive_rate = float(np.mean(adaptive_p_values < 0.05))

    # This deliberately adverse same-sample procedure selects the largest of
    # 12 null candidate means.  The large separation makes the guard stable
    # while demonstrating why ordinary post-selection p-values are not
    # confirmatory.
    assert adaptive_rate >= 0.30
    assert adaptive_rate - fixed_rate >= 0.25

    values = np.asarray(
        null_selection_simulation["example_selected_values"],
        dtype=float,
    )
    frame = pd.DataFrame(
        {
            "participant": [f"P{index + 1:02d}" for index in range(len(values))],
            "condition": "selected_null_candidate",
            "roi": "occipital",
            "value": values,
        }
    )
    _, result = run_baseline_vs_zero_tests(
        frame,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        alternative=Alternative.GREATER,
        correction="none",
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    assert set(result["harmonic_provenance"]) == {"same_sample_adaptive"}
    assert set(result["inference_status"]) == {"exploratory_post_selection"}


def test_known_unequal_variance_group_effect_has_power_and_correct_direction() -> None:
    """Welch inference should recover a large positive group effect."""

    rng = np.random.default_rng(KNOWN_EFFECT_SEED)
    group_a = rng.normal(
        loc=1.0,
        scale=1.0,
        size=(
            KNOWN_EFFECT_SIMULATIONS,
            KNOWN_EFFECT_PARTICIPANTS_PER_GROUP,
        ),
    )
    group_b = rng.normal(
        loc=0.0,
        scale=1.4,
        size=(
            KNOWN_EFFECT_SIMULATIONS,
            KNOWN_EFFECT_PARTICIPANTS_PER_GROUP,
        ),
    )
    results = [
        _welch_statistics(group_a[index], group_b[index], alpha=0.05)
        for index in range(KNOWN_EFFECT_SIMULATIONS)
    ]

    p_values = np.asarray([result["p_raw"] for result in results], dtype=float)
    differences = np.asarray(
        [result["mean_difference_a_minus_b"] for result in results],
        dtype=float,
    )
    hedges_g = np.asarray(
        [result["hedges_g"] for result in results],
        dtype=float,
    )

    assert all(result["status_code"] == "ok" for result in results)
    assert float(np.mean(p_values < 0.05)) >= 0.80
    assert float(np.mean(differences > 0.0)) >= 0.98
    assert float(np.median(hedges_g)) > 0.65


def test_scipy_one_sample_golden_reference() -> None:
    """The public response table should retain the recorded SciPy result."""

    values = np.asarray([0.1, 0.4, 0.8, 1.0, 1.5, -0.2, 0.7, 1.2])
    frame = pd.DataFrame(
        {
            "participant": [f"S{index + 1}" for index in range(len(values))],
            "condition": "faces",
            "roi": "occipital",
            "value": values,
        }
    )

    _, result = run_baseline_vs_zero_tests(
        frame,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        alternative=Alternative.TWO_SIDED,
        correction="none",
    )
    row = result.iloc[0]

    assert row["mean"] == pytest.approx(0.6875, abs=1e-12)
    assert row["sd"] == pytest.approx(0.5667892024377317, rel=1e-12)
    assert row["t"] == pytest.approx(3.4308057385349295, rel=1e-12)
    assert row["df"] == pytest.approx(7.0)
    assert row["p_raw"] == pytest.approx(0.010973204443957602, rel=1e-12)
    assert row["cohens_dz"] == pytest.approx(1.212973001325885, rel=1e-12)
    assert row["ci_mean_low"] == pytest.approx(
        0.21365236860823855,
        rel=1e-12,
    )
    assert row["ci_mean_high"] == pytest.approx(
        1.1613476313917614,
        rel=1e-12,
    )


def _rm_reference_frame() -> pd.DataFrame:
    """Return the balanced 2 x 2 repeated-measures reference fixture."""

    rng = np.random.default_rng(RM_REFERENCE_SEED)
    participant_effects = rng.normal(0.0, 0.7, 14)
    residuals = rng.normal(0.0, 0.22, (14, 2, 2))
    rows: list[dict[str, object]] = []
    for participant_index in range(14):
        for condition_index, condition in enumerate(("faces", "objects")):
            for roi_index, roi in enumerate(("left", "right")):
                rows.append(
                    {
                        "participant": f"S{participant_index + 1:02d}",
                        "condition": condition,
                        "roi": roi,
                        "value": (
                            1.2
                            + participant_effects[participant_index]
                            + 0.55 * condition_index
                            + 0.30 * roi_index
                            + 0.25 * condition_index * roi_index
                            + residuals[
                                participant_index,
                                condition_index,
                                roi_index,
                            ]
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _assert_rm_reference_rows(
    result: pd.DataFrame,
    *,
    interaction_label: str,
) -> None:
    expected_by_effect = {
        (
            interaction_label
            if effect == "condition * roi"
            else effect
        ): expected
        for effect, expected in RM_REFERENCE.items()
    }
    indexed = result.set_index("Effect")

    assert set(indexed.index) == set(expected_by_effect)
    for effect, expected in expected_by_effect.items():
        row = indexed.loc[effect]
        assert row["F Value"] == pytest.approx(expected["f"], rel=1e-10)
        assert row["Num DF"] == pytest.approx(1.0)
        assert row["Den DF"] == pytest.approx(13.0)
        assert row["Pr > F"] == pytest.approx(
            expected["p"],
            rel=1e-9,
            abs=1e-15,
        )
        assert row["partial eta squared"] == pytest.approx(
            expected["partial_eta_squared"],
            rel=1e-10,
        )


@pytest.mark.filterwarnings(
    "ignore:DataFrame.groupby with axis=1 is deprecated:FutureWarning"
)
@pytest.mark.filterwarnings(
    "ignore:DataFrameGroupBy.diff with axis=1 is deprecated:FutureWarning"
)
def test_pingouin_rm_anova_golden_reference() -> None:
    """The preferred RM-ANOVA path should match the stored Pingouin fixture."""

    pytest.importorskip("pingouin")

    result = run_repeated_measures_anova(
        _rm_reference_frame(),
        dv_col="value",
        within_cols=["condition", "roi"],
        subject_col="participant",
    )

    assert result.attrs["rm_anova_backend"] == "pingouin"
    _assert_rm_reference_rows(result, interaction_label="condition * roi")


def test_statsmodels_anovarm_fallback_golden_reference(monkeypatch) -> None:
    """The fallback mapping should retain the stored statsmodels result."""

    class FailingPingouin:
        @staticmethod
        def rm_anova(**_kwargs):
            raise RuntimeError("force statsmodels golden-reference path")

    monkeypatch.setitem(
        sys.modules,
        "pingouin",
        SimpleNamespace(rm_anova=FailingPingouin.rm_anova),
    )
    result = run_repeated_measures_anova(
        _rm_reference_frame(),
        dv_col="value",
        within_cols=["condition", "roi"],
        subject_col="participant",
    )

    assert result.attrs["rm_anova_backend"] == "statsmodels"
    assert result.attrs["rm_anova_pingouin_failed"] is True
    _assert_rm_reference_rows(result, interaction_label="condition:roi")

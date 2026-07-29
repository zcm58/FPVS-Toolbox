from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.inference_contracts import CorrectionMethod, FamilySpec
from Tools.Stats.analysis.multiple_comparisons import (
    adjust_p_values,
    apply_declared_families,
    apply_family_correction,
)


@pytest.mark.parametrize(
    ("method", "statsmodels_method"),
    [
        (CorrectionMethod.HOLM, "holm"),
        (CorrectionMethod.BH_FDR, "fdr_bh"),
    ],
)
def test_family_correction_matches_statsmodels_reference(
    method: CorrectionMethod,
    statsmodels_method: str,
) -> None:
    p_values = np.array([0.001, 0.02, 0.04, 0.30], dtype=float)
    family = FamilySpec("response_core_cells", "Core responses", method, alpha=0.05)

    out = adjust_p_values(p_values, family)
    expected_reject, expected_adjusted, _, _ = multipletests(
        p_values,
        alpha=0.05,
        method=statsmodels_method,
    )

    np.testing.assert_allclose(out["p_adjusted"], expected_adjusted)
    np.testing.assert_array_equal(out["reject_adjusted"], expected_reject)
    assert set(out["family_id"]) == {"response_core_cells"}
    assert set(out["family_size"]) == {4}
    assert set(out["adjustment_method"]) == {method.value}
    assert set(out["alpha"]) == {0.05}


def test_no_adjustment_preserves_raw_p_values_and_alpha_decisions() -> None:
    family = FamilySpec(
        "planned_contrasts",
        "Planned contrasts",
        CorrectionMethod.NONE,
        alpha=0.05,
    )

    out = adjust_p_values([0.01, 0.05, 0.051], family)

    np.testing.assert_allclose(out["p_adjusted"], [0.01, 0.05, 0.051])
    assert out["reject_adjusted"].tolist() == [True, True, False]
    assert set(out["adjustment_method"]) == {"none"}


def test_non_estimable_rows_and_original_columns_are_preserved() -> None:
    source = pd.DataFrame(
        {
            "contrast": ["A", "B", "C", "D"],
            "source_p": [0.01, np.nan, np.inf, None],
            "note": ["", "insufficient_n", "nonfinite", "not_tested"],
        },
        index=[10, 20, 30, 40],
    )
    family = FamilySpec("group_core_cells", "Group cell contrasts", "holm")

    out = apply_family_correction(source, family, p_col="source_p")

    assert out.index.tolist() == [10, 20, 30, 40]
    assert out["contrast"].tolist() == source["contrast"].tolist()
    assert out["note"].tolist() == source["note"].tolist()
    assert out["family_size"].tolist() == [1, 1, 1, 1]
    assert out.loc[10, "p_adjusted"] == pytest.approx(0.01)
    assert out.loc[10, "reject_adjusted"]
    assert out.loc[[20, 30, 40], "p_adjusted"].isna().all()
    assert not out.loc[[20, 30, 40], "reject_adjusted"].any()
    assert out.loc[[20, 30, 40], "p_raw"].isna().all()


def test_invalid_finite_p_value_hard_fails() -> None:
    family = FamilySpec("bad_values", "Bad values")

    with pytest.raises(ValueError, match="between 0 and 1"):
        adjust_p_values([0.1, 1.2], family)


def test_declared_families_adjust_independently_and_preserve_row_order() -> None:
    source = pd.DataFrame(
        {
            "contrast": ["a1", "b1", "a2", "b2", "b3"],
            "family_id": ["a", "b", "a", "b", "b"],
            "p_raw": [0.01, 0.02, 0.04, 0.10, np.nan],
        },
        index=[9, 3, 8, 2, 7],
    )
    family_a = FamilySpec("a", "Family A", "holm")
    family_b = FamilySpec("b", "Family B", "fdr")

    out = apply_declared_families(source, (family_a, family_b))

    assert out.index.tolist() == source.index.tolist()
    assert out["contrast"].tolist() == source["contrast"].tolist()
    expected_a = multipletests([0.01, 0.04], method="holm")[1]
    expected_b = multipletests([0.02, 0.10], method="fdr_bh")[1]
    np.testing.assert_allclose(out.loc[[9, 8], "p_adjusted"], expected_a)
    np.testing.assert_allclose(out.loc[[3, 2], "p_adjusted"], expected_b)
    assert out.loc[[9, 8], "family_size"].tolist() == [2, 2]
    assert out.loc[[3, 2, 7], "family_size"].tolist() == [2, 2, 2]


def test_declared_families_reject_unknown_family_ids() -> None:
    source = pd.DataFrame({"family_id": ["known", "unknown"], "p_raw": [0.1, 0.2]})

    with pytest.raises(ValueError, match="No FamilySpec"):
        apply_declared_families(
            source,
            (FamilySpec("known", "Known"),),
        )


def test_declared_families_reject_missing_family_ids_without_dropping_rows() -> None:
    source = pd.DataFrame({"family_id": ["known", None], "p_raw": [0.1, np.nan]})

    with pytest.raises(ValueError, match="non-missing family ID"):
        apply_declared_families(
            source,
            (FamilySpec("known", "Known"),),
        )

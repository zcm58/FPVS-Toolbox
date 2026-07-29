from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import mixed_effects_model as lmm


def _minimal_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "subject": ["S1", "S1", "S2", "S2"],
            "condition": ["A", "B", "A", "B"],
            "roi": ["R1", "R1", "R1", "R1"],
            "value": [1.0, 1.5, 1.2, 1.6],
        }
    )


def _fake_main_fit() -> lmm._FitResult:
    return lmm._FitResult(
        table=pd.DataFrame(
            {
                "Effect": ["Intercept"],
                "Coef.": [1.0],
                "SE": [0.1],
                "Z": [10.0],
                "P>|z|": [0.001],
                "CI Low": [0.8],
                "CI High": [1.2],
                "Note": [""],
            }
        ),
        model=SimpleNamespace(
            converged=True,
            llf=10.0,
            aic=1.0,
            bic=2.0,
            cov_re=[[1.0]],
        ),
        used_re_formula="1",
        singular=False,
        converged=True,
    )


def test_single_group_lrt_formulas_are_hierarchy_preserving() -> None:
    terms = ["C(condition, Sum) * C(roi, Sum)", "age"]

    comparisons = lmm._build_single_group_lrt_comparisons("value", terms)
    by_id = {comparison.effect_id: comparison for comparison in comparisons}

    assert set(by_id) == {
        "condition_roi_interaction",
        "condition_related_block",
        "roi_related_block",
    }
    assert (
        by_id["condition_roi_interaction"].reduced_formula
        == "value ~ age + C(condition, Sum) + C(roi, Sum)"
    )
    assert (
        by_id["condition_related_block"].reduced_formula
        == "value ~ age + C(roi, Sum)"
    )
    assert (
        by_id["roi_related_block"].reduced_formula
        == "value ~ age + C(condition, Sum)"
    )
    assert lmm._make_reduced_terms(terms[:1], "condition") == ["C(roi, Sum)"]
    assert lmm._make_reduced_terms(terms[:1], "roi") == ["C(condition, Sum)"]


def test_do_lrt_attaches_explicit_success_rows(monkeypatch) -> None:
    monkeypatch.setattr(lmm, "_fit_mixedlm", lambda *args, **kwargs: _fake_main_fit())

    def _fake_lrt_fit(_df, formula, _group_col, _re_formula):
        is_full = "*" in formula
        return SimpleNamespace(
            llf=10.0 if is_full else 8.0,
            df_modelwc=6 if is_full else 4,
            converged=True,
        )

    monkeypatch.setattr(lmm, "_fit_formula_for_lrt", _fake_lrt_fit)

    table = lmm.run_mixed_effects_model(
        _minimal_data(),
        dv_col="value",
        group_col="subject",
        fixed_effects=["condition * roi"],
        do_lrt=True,
    )

    lrt_table = table.attrs["lrt_table"]
    assert table["LRT Status"].eq("ok").all()
    assert lrt_table["status"].eq("ok").all()
    assert lrt_table["p (chi2)"].notna().all()
    assert lrt_table["full_formula"].str.contains(r"\*").all()
    assert lrt_table["reduced_formula"].str.strip().ne("value ~").all()


def test_do_lrt_keeps_failed_comparisons_visible(monkeypatch) -> None:
    monkeypatch.setattr(lmm, "_fit_mixedlm", lambda *args, **kwargs: _fake_main_fit())

    def _fail_lrt_fit(*_args, **_kwargs):
        raise RuntimeError("synthetic optimizer failure")

    monkeypatch.setattr(lmm, "_fit_formula_for_lrt", _fail_lrt_fit)

    table = lmm.run_mixed_effects_model(
        _minimal_data(),
        dv_col="value",
        group_col="subject",
        fixed_effects=["condition * roi"],
        do_lrt=True,
    )

    lrt_table = table.attrs["lrt_table"]
    assert table["LRT Status"].eq("failed").all()
    assert lrt_table["status"].eq("failed").all()
    assert lrt_table["error"].str.contains("synthetic optimizer failure").all()


def test_available_case_lmm_uses_sparse_observed_rows_for_every_lrt() -> None:
    rng = np.random.default_rng(20260729)
    rows: list[dict[str, object]] = []
    for participant_index in range(12):
        participant = f"P{participant_index + 1:02d}"
        participant_effect = float(rng.normal(0.0, 0.45))
        for condition_index, condition in enumerate(("A", "B", "C")):
            for roi_index, roi in enumerate(("left", "right")):
                if (
                    (participant_index == 2 and condition == "B")
                    or (
                        participant_index == 8
                        and condition == "C"
                        and roi == "right"
                    )
                ):
                    continue
                rows.append(
                    {
                        "subject": participant,
                        "condition": condition,
                        "roi": roi,
                        "value": (
                            1.0
                            + participant_effect
                            + 0.18 * condition_index
                            + 0.09 * roi_index
                            + float(rng.normal(0.0, 0.08))
                        ),
                    }
                )

    table = lmm.run_mixed_effects_model(
        pd.DataFrame(rows),
        dv_col="value",
        group_col="subject",
        fixed_effects=["condition * roi"],
        do_lrt=True,
        analysis_scope="available_case",
    )

    assert table["Analysis Scope"].eq("available_case").all()
    assert table["Observations"].eq(len(rows)).all()
    assert table["Missing Participant Cells"].eq(3).all()
    diagnostics = table.attrs["model_diagnostics"].set_index("check_id")
    assert diagnostics.loc["participant_cell_coverage", "status"] == "warning"
    lrt_table = table.attrs["lrt_table"]
    assert lrt_table["status"].eq("ok").all()
    assert lrt_table["same_observed_rows"].all()
    assert lrt_table["n_observations_full"].eq(len(rows)).all()
    assert lrt_table["n_observations_reduced"].eq(len(rows)).all()


def test_available_case_lmm_blocks_structurally_empty_factorial_cell() -> None:
    data = pd.DataFrame(
        [
            {
                "subject": participant,
                "condition": condition,
                "roi": roi,
                "value": float(index),
            }
            for index, (participant, condition, roi) in enumerate(
                (
                    ("P1", "A", "left"),
                    ("P1", "A", "right"),
                    ("P1", "B", "left"),
                    ("P2", "A", "left"),
                    ("P2", "A", "right"),
                    ("P2", "B", "left"),
                )
            )
        ]
    )

    with pytest.raises(ValueError, match="structurally empty"):
        lmm.run_mixed_effects_model(
            data,
            dv_col="value",
            group_col="subject",
            fixed_effects=["condition * roi"],
            analysis_scope="available_case",
        )

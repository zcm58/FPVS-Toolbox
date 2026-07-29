from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

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

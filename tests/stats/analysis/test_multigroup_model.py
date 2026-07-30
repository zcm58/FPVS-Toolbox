from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import multigroup_model as model


def _complete_core_data(
    *,
    groups: tuple[str, ...] = ("control", "anxious"),
    participants_per_group: int = 2,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_index, group_id in enumerate(groups):
        for participant_index in range(participants_per_group):
            participant_id = f"{group_id}_{participant_index + 1}"
            for condition_index, condition in enumerate(("faces", "objects")):
                for roi_index, roi in enumerate(("left", "right")):
                    rows.append(
                        {
                            "participant_id": participant_id,
                            "group_id": group_id,
                            "condition": condition,
                            "roi": roi,
                            "value": (
                                1.0
                                + 0.4 * group_index
                                + 0.2 * condition_index
                                + 0.1 * roi_index
                                + 0.03 * participant_index
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def _fake_result(
    *,
    formula: str,
    converged: bool = True,
    singular: bool = False,
    llf: float = 100.0,
    parameter_count: int = 12,
) -> SimpleNamespace:
    covariance = [[0.0 if singular else 0.5]]
    terms = ["Intercept", "C(group_id, Sum)[S.anxious]"]
    return SimpleNamespace(
        converged=converged,
        cov_re=covariance,
        fe_params=pd.Series([1.0, 0.2], index=terms),
        bse_fe=np.array([0.1, 0.08]),
        llf=llf,
        df_modelwc=parameter_count,
        params=np.zeros(parameter_count),
        model=SimpleNamespace(exog_names=terms, formula=formula),
    )


def _mock_fit_for_formula_specs(**kwargs):
    comparisons = model.build_multigroup_omnibus_comparisons()
    formula = kwargs["formula"]
    if kwargs["reml"]:
        return _fake_result(formula=formula)

    full_formula = comparisons[0].full_formula
    reduced_values = {
        comparisons[0].reduced_formula: (90.0, 4),
        comparisons[1].reduced_formula: (99.0, 11),
        comparisons[2].reduced_formula: (96.0, 8),
        comparisons[3].reduced_formula: (95.0, 8),
    }
    if formula == full_formula:
        return _fake_result(formula=formula, llf=100.0, parameter_count=12)
    llf, parameters = reduced_values[formula]
    return _fake_result(formula=formula, llf=llf, parameter_count=parameters)


def test_omnibus_formulas_are_exact_and_hierarchy_preserving() -> None:
    comparisons = model.build_multigroup_omnibus_comparisons()
    by_id = {comparison.effect_id: comparison for comparison in comparisons}
    group = "C(group_id, Sum)"
    condition = "C(condition, Sum)"
    roi = "C(roi, Sum)"
    full = f"value ~ {group} * {condition} * {roi}"

    assert tuple(by_id) == (
        "any_group_related",
        "group_condition_roi_interaction",
        "group_condition_block",
        "group_roi_block",
    )
    assert all(comparison.full_formula == full for comparison in comparisons)
    assert by_id["any_group_related"].reduced_formula == (
        f"value ~ {condition} * {roi}"
    )
    assert by_id["group_condition_roi_interaction"].reduced_formula == (
        f"value ~ {group} * {condition} + {group} * {roi} + {condition} * {roi}"
    )
    assert by_id["group_condition_block"].reduced_formula == (
        f"value ~ {group} * {roi} + {condition} * {roi}"
    )
    assert by_id["group_roi_block"].reduced_formula == (
        f"value ~ {group} * {condition} + {condition} * {roi}"
    )
    assert "not a pure group main-effect test" in (
        by_id["any_group_related"].interpretation
    )


def test_duplicate_grain_is_a_hard_validation_error() -> None:
    data = _complete_core_data()
    data = pd.concat([data, data.iloc[[0]]], ignore_index=True)

    with pytest.raises(
        model.MultigroupModelValidationError,
        match="Duplicate participant x Condition x ROI",
    ) as caught:
        model.run_multigroup_mixed_model(data)

    diagnostics = caught.value.diagnostics
    row = diagnostics.loc[
        diagnostics["check_id"] == "participant_condition_roi_grain"
    ].iloc[0]
    assert row["status"] == "failed"


def test_incomplete_core_is_blocked_without_dropping_participant() -> None:
    data = _complete_core_data().iloc[1:].copy()

    with pytest.raises(
        model.MultigroupModelValidationError,
        match="do not drop participants",
    ):
        model.run_multigroup_mixed_model(data)


def test_available_case_keeps_incomplete_participants_and_exact_lrt_rows() -> None:
    rng = np.random.default_rng(20260729)
    rows: list[dict[str, object]] = []
    for group_index, group_id in enumerate(("control", "anxious")):
        for participant_index in range(8):
            participant_id = f"{group_id}_{participant_index + 1}"
            participant_effect = float(rng.normal(0.0, 0.5))
            for condition_index, condition in enumerate(
                ("faces", "objects", "words")
            ):
                for roi_index, roi in enumerate(("left", "right")):
                    if (
                        group_id == "control"
                        and participant_index == 1
                        and condition == "objects"
                    ) or (
                        group_id == "anxious"
                        and participant_index == 5
                        and condition == "words"
                        and roi == "right"
                    ):
                        continue
                    rows.append(
                        {
                            "participant_id": participant_id,
                            "group_id": group_id,
                            "condition": condition,
                            "roi": roi,
                            "value": (
                                1.2
                                + participant_effect
                                + 0.22 * group_index
                                + 0.16 * condition_index
                                + 0.1 * roi_index
                                + float(rng.normal(0.0, 0.1))
                            ),
                        }
                    )

    result = model.run_multigroup_mixed_model(
        pd.DataFrame(rows),
        known_group_ids=("control", "anxious"),
        analysis_scope="available_case",
    )

    assert result.status == "ok"
    assert result.omnibus["status"].eq("ok").all()
    assert result.omnibus["same_observed_rows"].all()
    assert result.omnibus["n_observations_full"].eq(len(rows)).all()
    assert result.omnibus["n_observations_reduced"].eq(len(rows)).all()
    diagnostics = result.diagnostics.set_index("check_id")
    assert diagnostics.loc["participant_cell_coverage", "status"] == "warning"
    metadata = result.metadata.set_index("field")["value"]
    assert metadata["analysis_scope"] == "available_case"
    assert int(metadata["n_observations"]) == len(rows)


def test_available_case_blocks_empty_group_condition_roi_cell() -> None:
    data = _complete_core_data()
    data = data.loc[
        ~(
            data["group_id"].eq("anxious")
            & data["condition"].eq("objects")
            & data["roi"].eq("right")
        )
    ].copy()

    with pytest.raises(
        model.MultigroupModelValidationError,
        match="Structurally empty Group x Condition x ROI",
    ) as caught:
        model.run_multigroup_mixed_model(
            data,
            analysis_scope="available_case",
        )

    diagnostic = caught.value.diagnostics.set_index("check_id").loc[
        "factorial_cells_observed"
    ]
    assert diagnostic["status"] == "failed"


def test_unknown_canonical_group_id_is_blocked() -> None:
    with pytest.raises(
        model.MultigroupModelValidationError,
        match="Unknown canonical group_id",
    ):
        model.run_multigroup_mixed_model(
            _complete_core_data(),
            known_group_ids=("control", "comparison"),
        )


def test_unresolved_group_placeholder_is_blocked_without_registry() -> None:
    data = _complete_core_data(groups=("control", "unknown"))

    with pytest.raises(
        model.MultigroupModelValidationError,
        match="Unresolved canonical group_id",
    ):
        model.run_multigroup_mixed_model(data)


@pytest.mark.parametrize(
    ("slope_converged", "slope_singular", "expected_status"),
    [
        (False, False, "nonconverged"),
        (True, True, "singular"),
    ],
)
def test_unacceptable_random_slope_falls_back_and_exports_every_attempt(
    monkeypatch,
    slope_converged: bool,
    slope_singular: bool,
    expected_status: str,
) -> None:
    def fake_fit(**kwargs):
        if kwargs["reml"] and kwargs["re_formula"] != "1":
            return _fake_result(
                formula=kwargs["formula"],
                converged=slope_converged,
                singular=slope_singular,
            )
        return _mock_fit_for_formula_specs(**kwargs)

    monkeypatch.setattr(model, "_fit_mixedlm_once", fake_fit)

    result = model.run_multigroup_mixed_model(
        _complete_core_data(),
        known_group_ids=("control", "anxious"),
        random_slope_formula="1 + C(condition, Sum)",
    )

    assert result.status == "ok"
    assert result.fitted_model is not None
    assert "fitted_model" not in result.to_frames()
    assert not result.estimates.empty
    assert result.omnibus["status"].eq("ok").all()
    assert result.omnibus["reportable"].all()
    required_attempt_columns = {
        "requested_re_formula",
        "used_re_formula",
        "optimizer",
        "converged",
        "singular",
        "fallback_reason",
        "status",
    }
    assert required_attempt_columns.issubset(result.attempts.columns)
    slope_attempts = result.attempts[
        result.attempts["stage"].eq("final_reml_random_slope")
    ]
    assert len(slope_attempts) == 2
    assert slope_attempts["status"].eq(expected_status).all()
    fallback = result.attempts[
        result.attempts["stage"].eq("final_reml_random_intercept_fallback")
    ]
    assert len(fallback) == 1
    assert fallback.iloc[0]["status"] == "accepted"
    assert fallback.iloc[0]["requested_re_formula"] == "1 + C(condition, Sum)"
    assert fallback.iloc[0]["used_re_formula"] == "1"
    assert "random slopes" in fallback.iloc[0]["fallback_reason"]
    metadata = result.metadata.set_index("field")["value"]
    assert metadata["final_estimation"] == "REML"
    assert metadata["used_re_formula"] == "1"
    assert "not a pure group main effect" in metadata[
        "any_group_related_definition"
    ]


def test_failed_reduced_ml_fit_remains_visible(monkeypatch) -> None:
    comparisons = model.build_multigroup_omnibus_comparisons()
    failed_formula = comparisons[2].reduced_formula

    def fake_fit(**kwargs):
        if not kwargs["reml"] and kwargs["formula"] == failed_formula:
            raise RuntimeError("synthetic reduced-model failure")
        return _mock_fit_for_formula_specs(**kwargs)

    monkeypatch.setattr(model, "_fit_mixedlm_once", fake_fit)

    result = model.run_multigroup_mixed_model(_complete_core_data())

    failed = result.omnibus.set_index("effect_id").loc["group_condition_block"]
    assert result.status == "partial"
    assert failed["status"] == "failed"
    assert bool(failed["reportable"]) is False
    assert "Reduced ML model failed" in failed["error"]
    attempts = result.attempts[
        (result.attempts["formula"] == failed_formula)
        & (result.attempts["method"] == "ML")
    ]
    assert len(attempts) == 2
    assert attempts["status"].eq("error").all()
    assert attempts["error"].str.contains("synthetic reduced-model failure").all()
    assert result.omnibus["caveat"].str.contains("asymptotic chi-square").all()


def test_ml_row_identity_mismatch_is_nonreportable(monkeypatch) -> None:
    comparisons = model.build_multigroup_omnibus_comparisons()
    mismatched_formula = comparisons[1].reduced_formula
    expected_rows = tuple(range(len(_complete_core_data())))

    def fake_fit(**kwargs):
        result = _mock_fit_for_formula_specs(**kwargs)
        row_labels = (
            expected_rows[:-1]
            if kwargs["formula"] == mismatched_formula
            else expected_rows
        )
        result.model.data = SimpleNamespace(row_labels=row_labels)
        return result

    monkeypatch.setattr(model, "_fit_mixedlm_once", fake_fit)
    result = model.run_multigroup_mixed_model(_complete_core_data())

    mismatch = result.omnibus.set_index("effect_id").loc[
        "group_condition_roi_interaction"
    ]
    assert result.status == "partial"
    assert mismatch["status"] == "failed"
    assert bool(mismatch["reportable"]) is False
    assert "exact same validated observed rows" in mismatch["error"]


def test_failed_final_reml_fit_returns_explicit_failed_bundle(monkeypatch) -> None:
    monkeypatch.setattr(
        model,
        "_fit_mixedlm_once",
        lambda **kwargs: _fake_result(
            formula=kwargs["formula"],
            converged=False,
            singular=True,
        ),
    )

    result = model.run_multigroup_mixed_model(_complete_core_data())

    assert result.status == "failed"
    assert result.fitted_model is None
    assert "fitted_model" not in result.to_frames()
    assert result.estimates.empty
    assert len(result.omnibus) == 4
    assert result.omnibus["status"].eq("failed").all()
    assert result.attempts["status"].eq("nonconverged_and_singular").all()
    assert (
        result.diagnostics.set_index("check_id").loc["final_reml_fit", "status"]
        == "failed"
    )


def test_deterministic_small_actual_model_returns_reml_estimates() -> None:
    rng = np.random.default_rng(20260729)
    rows: list[dict[str, object]] = []
    conditions = ("faces", "objects", "words")
    rois = ("left", "right")
    for group_index, group_id in enumerate(("control", "anxious")):
        for participant_index in range(8):
            participant_id = f"{group_id}_{participant_index + 1}"
            participant_effect = float(rng.normal(0.0, 0.65))
            for condition_index, condition in enumerate(conditions):
                for roi_index, roi in enumerate(rois):
                    rows.append(
                        {
                            "participant_id": participant_id,
                            "group_id": group_id,
                            "condition": condition,
                            "roi": roi,
                            "value": (
                                1.5
                                + participant_effect
                                + 0.25 * group_index
                                + 0.18 * condition_index
                                + 0.12 * roi_index
                                + 0.04 * group_index * condition_index
                                + float(rng.normal(0.0, 0.12))
                            ),
                        }
                    )

    result = model.run_multigroup_mixed_model(
        pd.DataFrame(rows),
        known_group_ids=("control", "anxious"),
        optimizers=("lbfgs", "powell"),
        marginal_grid=pd.DataFrame(
            [
                {"condition": condition, "roi": roi}
                for condition in conditions
                for roi in rois
            ]
        ),
        reference_group_id="control",
    )

    assert result.status == "ok"
    assert not result.estimates.empty
    assert result.estimates["estimation_method"].eq("REML").all()
    assert result.omnibus["status"].eq("ok").all()
    assert (
        (
            result.attempts["stage"].eq("final_reml_random_intercept")
            & result.attempts["accepted"]
        ).any()
    )
    marginal = result.marginal_group_contrasts.iloc[0]
    assert marginal["status"] == "ok"
    assert marginal["contrast_sign"] == "anxious - control"
    assert marginal["grid_cell_count"] == 6
    assert np.isfinite(marginal["estimate"])

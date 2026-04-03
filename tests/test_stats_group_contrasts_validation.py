import pandas as pd
import pytest

from Tools.Stats.PySide6.stats_workers import (
    _validate_group_contrasts_input,
    run_group_contrasts,
)


@pytest.fixture
def valid_df():
    return pd.DataFrame(
        [
            {"group": "A", "condition": "c1", "roi": "r1", "value": 1.0},
            {"group": "A", "condition": "c1", "roi": "r1", "value": 2.0},
            {"group": "B", "condition": "c1", "roi": "r1", "value": 3.0},
            {"group": "B", "condition": "c1", "roi": "r1", "value": 4.0},
        ]
    )


def test_validate_group_contrasts_rejects_non_finite(valid_df):
    invalid = valid_df.copy()
    invalid.loc[0, "value"] = float("nan")

    with pytest.raises(ValueError, match="non-finite BCA values"):
        _validate_group_contrasts_input(
            invalid,
            group_col="group",
            condition_col="condition",
            roi_col="roi",
            dv_col="value",
        )


def test_validate_group_contrasts_rejects_too_few_observations(valid_df):
    sparse = valid_df.iloc[[0, 2, 3]].copy()

    with pytest.raises(ValueError, match="fewer than 2 observations"):
        _validate_group_contrasts_input(
            sparse,
            group_col="group",
            condition_col="condition",
            roi_col="roi",
            dv_col="value",
        )


def test_validate_group_contrasts_happy_path(valid_df):
    _validate_group_contrasts_input(
        valid_df,
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )


def test_run_group_contrasts_blocks_invalid_data(monkeypatch):
    called = False

    def fake_prepare_summed_bca_data(**kwargs):  # noqa: ARG001
        return {
            "s1": {"c1": {"r1": float("inf")}},
            "s2": {"c1": {"r1": 2.0}},
        }

    def fake_compute_group_contrasts(*args, **kwargs):  # noqa: ARG001
        nonlocal called
        called = True
        raise AssertionError("Legacy compute_group_contrasts should not be called")

    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.prepare_summed_bca_data",
        fake_prepare_summed_bca_data,
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.compute_group_contrasts",
        fake_compute_group_contrasts,
    )

    with pytest.raises(RuntimeError, match="at least two groups"):
        run_group_contrasts(
            lambda _x: None,
            lambda _x: None,
            subjects=["s1", "s2"],
            conditions=["c1"],
            subject_data={},
            base_freq=6.0,
            alpha=0.05,
            rois={"r1": ["O1"]},
            subject_groups={"s1": "A", "s2": "B"},
        )

    assert called is False


def test_run_group_contrasts_shared_contract_keeps_invalidity_downstream(monkeypatch):
    called = False
    shared_payload: dict[str, object] = {}
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P2"],
            "condition": ["c1", "c1"],
            "roi": ["r1", "r1"],
            "dv_value": [1.0, 2.0],
        }
    )

    def fake_compute_group_contrasts(*args, **kwargs):  # noqa: ARG001
        nonlocal called
        called = True
        raise AssertionError("compute_group_contrasts should not run when validation fails")

    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.compute_group_contrasts",
        fake_compute_group_contrasts,
    )

    with pytest.raises(ValueError, match="fewer than 2 observations"):
        run_group_contrasts(
            lambda _x: None,
            lambda _x: None,
            subjects=["P01", "P02"],
            conditions=["c1"],
            conditions_all=["c1"],
            subject_data={},
            base_freq=6.0,
            alpha=0.05,
            rois={"r1": ["O1"]},
            rois_all={"r1": ["O1"]},
            subject_groups={"P01": "A", "P02": "B"},
            fixed_harmonic_dv_table=fixed_dv,
            required_conditions=["c1"],
            subject_to_group={"P01": "A", "P02": "B"},
            prepared_multigroup_dv_payload=shared_payload,
        )

    assert called is False
    assert isinstance(shared_payload.get("prepared_dv_table"), pd.DataFrame)
    assert shared_payload["run_report"].final_modeled_pids == ["P1", "P2"]

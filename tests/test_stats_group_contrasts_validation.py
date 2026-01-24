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

    with pytest.raises(ValueError):
        run_group_contrasts(
            lambda _x: None,
            lambda _x: None,
            subjects=[],
            conditions=[],
            subject_data={},
            base_freq=6.0,
            alpha=0.05,
            rois=[],
            subject_groups={"s1": "A", "s2": "B"},
        )

    assert called is False

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from Tools.Stats.io import stats_ready_export


def _legacy_merge_wide(
    long_df: pd.DataFrame,
    *,
    conditions: list[str],
    rois: list[str],
) -> pd.DataFrame:
    column_map = stats_ready_export._wide_column_names(conditions, rois)
    id_columns = ["subject_id", "group_id"]
    subjects_df = (
        long_df.loc[:, id_columns]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    wide = subjects_df.copy()
    for condition in conditions:
        for roi in rois:
            column = column_map[(condition, roi)]
            values = long_df[
                (long_df["condition"] == condition)
                & (long_df["roi"] == roi)
            ].loc[:, id_columns + ["summed_bca_uv"]]
            values = values.rename(columns={"summed_bca_uv": column})
            wide = wide.merge(values, on=id_columns, how="left")
    return wide


def _long_frame(
    *,
    subjects: list[str],
    conditions: list[str],
    rois: list[str],
) -> pd.DataFrame:
    values = np.random.default_rng(20260729).normal(
        size=len(subjects) * len(conditions) * len(rois)
    )
    values[1] = -0.0
    values[-2] = np.nan
    rows = []
    value_index = 0
    for subject_index, subject in enumerate(subjects):
        for condition in conditions:
            for roi in rois:
                rows.append(
                    {
                        "subject_id": subject,
                        "group_id": f"Group {subject_index % 2}",
                        "condition": condition,
                        "roi": roi,
                        "summed_bca_uv": values[value_index],
                    }
                )
                value_index += 1
    return pd.DataFrame(rows)


def test_stats_ready_wide_reshape_matches_merge_exactly() -> None:
    conditions = ["Face A", "Face-A", "Object"]
    rois = ["Posterior ROI", "Posterior-ROI", "Central"]
    long_df = _long_frame(
        subjects=[f"P{index:03d}" for index in range(40)],
        conditions=conditions,
        rois=rois,
    )

    expected = _legacy_merge_wide(
        long_df,
        conditions=conditions,
        rois=rois,
    )
    actual = stats_ready_export._build_jasp_wide_frame(
        long_df,
        conditions=conditions,
        rois=rois,
    )

    assert_frame_equal(actual, expected, check_exact=True)
    assert (
        actual.iloc[:, 2:].to_numpy().tobytes()
        == expected.iloc[:, 2:].to_numpy().tobytes()
    )


def test_stats_ready_wide_irregular_order_retains_merge_fallback() -> None:
    conditions = ["Face", "Object"]
    rois = ["Posterior", "Central"]
    long_df = _long_frame(
        subjects=["P01", "P02", "P03"],
        conditions=conditions,
        rois=rois,
    )
    irregular = pd.concat(
        [long_df.iloc[2:], long_df.iloc[:2]],
        ignore_index=True,
    )

    expected = _legacy_merge_wide(
        irregular,
        conditions=conditions,
        rois=rois,
    )
    actual = stats_ready_export._build_jasp_wide_frame(
        irregular,
        conditions=conditions,
        rois=rois,
    )

    assert_frame_equal(actual, expected, check_exact=True)

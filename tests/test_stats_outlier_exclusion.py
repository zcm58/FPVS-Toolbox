import numpy as np
import pandas as pd

from Tools.Stats.PySide6.stats_outlier_exclusion import (
    OUTLIER_REASON_LIMIT,
    OUTLIER_REASON_NONFINITE,
    apply_hard_dv_exclusion,
)


def test_apply_hard_dv_exclusion_filters_participants() -> None:
    df = pd.DataFrame(
        [
            {"subject": "P1", "condition": "A", "roi": "R1", "value": 51.0},
            {"subject": "P2", "condition": "A", "roi": "R1", "value": 49.0},
            {"subject": "P3", "condition": "A", "roi": "R1", "value": np.nan},
        ]
    )

    filtered, report = apply_hard_dv_exclusion(df, 50.0)

    assert set(filtered["subject"].unique()) == {"P1", "P2"}
    assert report.summary.n_subjects_before == 3
    assert report.summary.n_subjects_excluded == 1
    assert report.summary.n_subjects_after == 2

    reasons_by_pid = {item.participant_id: set(item.reasons) for item in report.participants}
    assert reasons_by_pid["P1"] == {OUTLIER_REASON_LIMIT}
    assert reasons_by_pid["P3"] == {OUTLIER_REASON_NONFINITE}

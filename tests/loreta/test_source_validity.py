"""Undefined source measurements remain missing throughout producer outputs."""

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    ELORETAVolumeParticipantZScoreValues,
    summarize_eloreta_volume_participant_zscores,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    L2MNEHaukParticipantZScoreValues,
    summarize_l2_mne_hauk_participant_zscores,
)
from Tools.LORETA_Visualizer.source_producers.source_validity import (
    complete_valid_source_support,
    source_values_to_json,
    validated_source_values,
)

from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    compute_hauk_source_zscores,
)


def test_undefined_noise_sd_is_missing_not_neutral_zero():
    amplitudes = np.array([[2.0] + [1.0] * 18, [20.0] + list(range(1, 19))])
    result = compute_hauk_source_zscores(amplitudes)

    assert np.isnan(result.values[0])
    np.testing.assert_array_equal(result.valid_source_mask, [False, True])
    assert result.zero_noise_sd_source_count == 1
    expected = (20.0 - np.mean(np.arange(2, 18))) / np.std(np.arange(2, 18))
    assert result.values[1] == expected


@pytest.mark.parametrize("aggregation", ["mean", "median", "trimmed_mean"])
@pytest.mark.parametrize("row_type,summarize", [
    (L2MNEHaukParticipantZScoreValues, summarize_l2_mne_hauk_participant_zscores),
    (ELORETAVolumeParticipantZScoreValues, summarize_eloreta_volume_participant_zscores),
])
def test_group_summaries_keep_fixed_cohort_on_intersection(row_type, summarize, aggregation):
    rows = []
    for index, first in enumerate([1.0, 2.0, 3.0, 4.0, 100.0]):
        values = np.array([first, 0.0, 200.0, 300.0])
        values[2 + index % 2] = np.nan
        rows.append(row_type(
            participant_id=str(index), values=values,
            target_source_values=np.ones(4), noise_mean_values=np.ones(4),
            noise_std_values=np.ones(4), noise_offsets_used=(-2, 2),
            zero_noise_sd_source_count=1, valid_source_mask=np.isfinite(values),
        ))

    summary = summarize(rows, aggregation=aggregation)

    assert summary.participant_count == 5
    assert summary.valid_source_mask.tolist() == [True, True, False, False]
    expected = 22.0 if aggregation == "mean" else 3.0
    assert source_values_to_json(summary.values, summary.valid_source_mask) == [expected, 0.0, None, None]


def test_disjoint_valid_support_does_not_reduce_cohort_per_vertex():
    from types import SimpleNamespace

    rows = [SimpleNamespace(values=np.array(values), valid_source_mask=np.isfinite(values))
            for values in ([1.0, np.nan], [np.nan, 2.0])]
    with pytest.raises(ValueError, match="valid for every participant"):
        complete_valid_source_support(rows)


@pytest.mark.parametrize("values,mask,count", [
    ([1.0, np.nan], None, 1),
    ([1.0, 0.0], [True, False], 1),
    ([1.0, np.nan], [True, True], 0),
    ([1.0, np.inf], [True, False], 1),
    ([1.0, np.nan], [True, False], 0),
    ([1.0, np.nan], [1, 0], 1),
])
def test_validity_rejects_ambiguous_or_inconsistent_missingness(values, mask, count):
    with pytest.raises(ValueError):
        validated_source_values(values, mask, invalid_count=count)


def test_all_undefined_source_noise_fails_clearly():
    with pytest.raises(ValueError, match="No source points"):
        compute_hauk_source_zscores(np.ones((2, 19)))

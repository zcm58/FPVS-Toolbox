from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering.reporting import build_repeated_session_report
from tests.free_harmonic_clustering.test_repeated_session_batch_inference import _batch_fixture


@pytest.mark.parametrize(
    ("global_p", "family_p", "batch_p", "expected"),
    [
        (0.0402, 0.1608, 0.6029, True),
        (0.04999999, 0.05000001, 0.2, True),
        (float(np.nextafter(0.05, 0.0)), float(np.nextafter(0.05, 1.0)), 0.2, True),
        (0.05, 0.16, 0.6, False),
        (0.0402, 0.05, 0.6029, False),
        (0.01, 0.04, 0.12, False),
        (0.01, 0.04, 0.04, False),
        (1.0, 1.0, 1.0, False),
    ],
)
def test_exploratory_filter_uses_stored_p_and_primary_family_holm(
    tmp_path: Path,
    global_p: float,
    family_p: float,
    batch_p: float,
    expected: bool,
) -> None:
    _, result = _batch_fixture(tmp_path)
    original = result.outcomes[0]
    outcome = replace(
        original,
        global_two_sided_p_value=global_p,
        holm_within_family_p_value=family_p,
        holm_all_batch_p_value=batch_p,
    )
    report = build_repeated_session_report(replace(result, outcomes=(outcome,)))
    row = report.rows[0]

    assert row.is_exploratory is expected
    assert report.exploratory_count == int(expected)
    assert (row.global_p, row.holm_family_p, row.holm_batch_p) == (global_p, family_p, batch_p)
    assert row.exploratory_cluster_ids == ((1,) if expected else ())
    if global_p == 0.04999999:
        assert "0.04999999" in row.detail_text
    if global_p == np.nextafter(0.05, 0.0):
        assert repr(global_p) in row.detail_text
        assert repr(family_p) in row.detail_text


def test_details_preserve_exact_membership_and_two_sided_cluster_threshold(tmp_path: Path) -> None:
    _, result = _batch_fixture(tmp_path)
    outcome = result.outcomes[0]
    cluster = replace(
        outcome.result.clusters[0],
        p_value=0.0201,
        adjusted_two_sided_p_value=0.0402,
        node_indices=(0, 3),
        sensor_indices=(0, 1),
        harmonic_indices=(0, 1),
    )
    tail_only = replace(cluster, cluster_id=2, p_value=0.04, adjusted_two_sided_p_value=0.08, significant=False)
    boundary = replace(cluster, cluster_id=3, p_value=0.025, adjusted_two_sided_p_value=0.05)
    outcome = replace(
        outcome,
        result=replace(outcome.result, clusters=(cluster, tail_only, boundary)),
        global_two_sided_p_value=0.0402,
        holm_within_family_p_value=0.1608,
        holm_all_batch_p_value=0.6029,
    )
    row = build_repeated_session_report(replace(result, outcomes=(outcome,))).rows[0]

    assert row.exploratory_cluster_ids == (1,)
    assert "Within-run two-sided cluster p = 0.0402" in row.detail_text
    assert "Signed-tail cluster p = 0.0201" in row.detail_text
    assert "Cluster 2" not in row.detail_text
    assert "Cluster 3" not in row.detail_text
    assert "H1 (1.2 Hz): Fp1\n  H2 (2.4 Hz): Fp2" in row.detail_text
    assert "H1 (1.2 Hz): Fp1, Fp2" not in row.detail_text
    assert "estimated from the selected cluster" in row.detail_text
    assert "not established as pointwise significant" in row.detail_text


def test_report_preserves_order_is_immutable_and_does_not_retain_or_change_arrays(tmp_path: Path) -> None:
    _, result = _batch_fixture(tmp_path)
    outcomes_before = result.outcomes
    arrays_before = [
        (outcome.prepared_run.prepared.values_a.copy(), outcome.result.null_positive_max_mass.copy())
        for outcome in result.outcomes
    ]
    report = build_repeated_session_report(result)

    assert tuple((row.run_index, row.family_id, row.condition) for row in report.rows) == tuple(
        (index, outcome.family_id, outcome.condition) for index, outcome in enumerate(result.outcomes)
    )
    assert result.outcomes is outcomes_before
    for outcome, (values, null) in zip(result.outcomes, arrays_before, strict=True):
        np.testing.assert_array_equal(outcome.prepared_run.prepared.values_a, values)
        np.testing.assert_array_equal(outcome.result.null_positive_max_mass, null)
    for row in report.rows:
        assert all(isinstance(value, (str, int, float, bool, tuple)) for value in asdict(row).values())
    with pytest.raises(FrozenInstanceError):
        report.rows[0].is_exploratory = True


def test_detail_direction_uses_stored_labels_and_paired_n_without_double_counting(tmp_path: Path) -> None:
    _, result = _batch_fixture(tmp_path)
    paired = result.outcomes[1]
    prepared = replace(paired.prepared_run.prepared, arm_a_label="Early session", arm_b_label="Late session")
    paired = replace(paired, prepared_run=replace(paired.prepared_run, prepared=prepared))
    rows = build_repeated_session_report(replace(result, outcomes=(paired, result.outcomes[-1]))).rows

    assert "A: Early session\nB: Late session" in rows[0].detail_text
    assert "Complete participants: 2 paired" in rows[0].detail_text
    assert "later visit minus earlier" not in rows[0].detail_text
    assert "A n = 2; B n = 2" in rows[1].detail_text
    assert "sign alone does not tell you whether either group increased or decreased" in rows[1].detail_text
    assert "not total response amplitude" in rows[1].detail_text


def test_no_cluster_result_has_explicit_empty_exploratory_report(tmp_path: Path) -> None:
    _, result = _batch_fixture(tmp_path)
    outcome = result.outcomes[0]
    outcome = replace(
        outcome,
        result=replace(outcome.result, clusters=(), cluster_labels=np.zeros_like(outcome.result.cluster_labels)),
        global_two_sided_p_value=1.0,
        holm_within_family_p_value=1.0,
        holm_all_batch_p_value=1.0,
    )
    report = build_repeated_session_report(replace(result, outcomes=(outcome,)))

    assert report.exploratory_count == 0
    assert report.rows[0].exploratory_cluster_ids == ()
    assert "No clusters meet this strict reporting threshold" in report.rows[0].detail_text

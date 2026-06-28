from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.gui import _cluster_mask_display_status_text
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_SURFACE_MESH, make_source_payload


def _surface_payload(*, mask_indices: list[int], participant_count: int = 24):
    return make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([2.4, 4.0], dtype=float),
        label="surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": mask_indices,
            "cluster_mask_vertex_count": len(mask_indices),
            "participant_count": participant_count,
            "cluster_permutation_count": 10000,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )


def test_cluster_mask_status_describes_group_significant_vertices() -> None:
    status = _cluster_mask_display_status_text(_surface_payload(mask_indices=[1]), use_cluster_mask=True)

    assert status == (
        "The vertices displayed here were significant across the group after the cluster-based permutation test.",
        "info",
    )


def test_cluster_mask_status_warns_when_significant_mask_is_disabled() -> None:
    status = _cluster_mask_display_status_text(_surface_payload(mask_indices=[1]), use_cluster_mask=False)

    assert status == (
        "Warning: disabling the cluster-based permutation mask will likely show vertices "
        "that were not significant at the group level.",
        "warning",
    )


def test_cluster_mask_status_warns_empty_mask_is_uncorrected() -> None:
    status = _cluster_mask_display_status_text(_surface_payload(mask_indices=[]), use_cluster_mask=False)

    assert status == (
        "Warning: no vertices survived the group-level permutation mask. The current view is uncorrected.",
        "warning",
    )

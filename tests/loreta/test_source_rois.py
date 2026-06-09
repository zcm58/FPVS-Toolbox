from __future__ import annotations

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.source_rois import (
    DESIKAN_KILLIANY_TEMPORAL_HAUK_ROI_ID,
    desikan_killiany_temporal_hauk_roi_from_label_vertices,
)


def test_desikan_killiany_temporal_roi_maps_labels_to_source_indices() -> None:
    roi = desikan_killiany_temporal_hauk_roi_from_label_vertices(
        source_vertex_ids=(10, 20, 30, 40, 50, 60),
        source_hemispheres=("lh", "lh", "lh", "rh", "rh", "rh"),
        labels_by_hemi={
            "lh": {
                "inferiortemporal": (10,),
                "middletemporal": (99,),
                "superiortemporal": (30,),
            },
            "rh": {
                "inferiortemporal": (40,),
                "middletemporal": (60,),
                "superiortemporal": (999,),
            },
        },
    )

    assert roi.roi_id == DESIKAN_KILLIANY_TEMPORAL_HAUK_ROI_ID
    assert np.array_equal(roi.left_mask, np.asarray([True, False, True, False, False, False]))
    assert np.array_equal(roi.right_mask, np.asarray([False, False, False, True, False, True]))
    assert roi.metadata["left_roi_source_count"] == 2
    assert roi.metadata["right_roi_source_count"] == 2


def test_desikan_killiany_temporal_roi_requires_all_temporal_labels() -> None:
    with pytest.raises(ValueError, match="Missing Desikan-Killiany temporal"):
        desikan_killiany_temporal_hauk_roi_from_label_vertices(
            source_vertex_ids=(10, 20),
            source_hemispheres=("lh", "rh"),
            labels_by_hemi={
                "lh": {
                    "inferiortemporal": (10,),
                    "middletemporal": (20,),
                },
                "rh": {
                    "inferiortemporal": (10,),
                    "middletemporal": (20,),
                    "superiortemporal": (30,),
                },
            },
        )

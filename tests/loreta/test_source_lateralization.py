from __future__ import annotations

import csv
import json
from dataclasses import dataclass

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.source_lateralization import (
    SOURCE_LATERALIZATION_ROI_DESIKAN_KILLIANY_TEMPORAL_HAUK,
    SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT,
    SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE,
    SOURCE_LATERALIZATION_MASK_CLUSTER,
    SOURCE_LATERALIZATION_SUMMARY_FORMAT,
    build_source_lateralization_rows,
    write_source_lateralization_summary_files,
)
from Tools.LORETA_Visualizer.source_producers.source_rois import SourceRoiMaskPair


@dataclass(frozen=True)
class _ParticipantMap:
    participant_id: str
    values: np.ndarray


@dataclass(frozen=True)
class _GroupMap:
    aggregation: str
    values: np.ndarray


def test_source_lateralization_uses_cluster_mask_and_positive_source_values() -> None:
    rows = build_source_lateralization_rows(
        source_points=np.asarray(
            [
                [-1.0, 0.0, 0.0],
                [-2.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
            dtype=float,
        ),
        condition_id="semantic_response",
        condition_label="Semantic Response",
        participant_values=(
            _ParticipantMap("P1", np.asarray([2.0, -10.0, 6.0, 4.0, 99.0], dtype=float)),
        ),
        group_summaries=(
            _GroupMap("mean", np.asarray([1.0, 3.0, 5.0, 7.0, 99.0], dtype=float)),
        ),
        cluster_mask=np.asarray([True, True, True, False, True], dtype=bool),
    )

    participant_row = rows[0]
    group_row = rows[1]
    assert participant_row["roi_id"] == SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE
    assert participant_row["mask_policy"] == SOURCE_LATERALIZATION_MASK_CLUSTER
    assert participant_row["left_sum_positive_z"] == pytest.approx(2.0)
    assert participant_row["right_sum_positive_z"] == pytest.approx(6.0)
    assert participant_row["lateralization_index_sum"] == pytest.approx(0.5)
    assert participant_row["dominant_hemisphere"] == "right"
    assert group_row["left_sum_positive_z"] == pytest.approx(4.0)
    assert group_row["right_sum_positive_z"] == pytest.approx(5.0)
    assert rows[2]["roi_id"] == SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT


def test_source_lateralization_writer_emits_json_and_csv(tmp_path) -> None:
    rows = [
        {
            "condition_id": "color_response",
            "condition_label": "Color Response",
            "map_type": "group_summary",
            "participant_id": "",
            "aggregation": "mean",
            "mask_policy": SOURCE_LATERALIZATION_MASK_CLUSTER,
            "value_policy": "positive_z_magnitude",
            "left_selected_source_count": 1,
            "right_selected_source_count": 1,
            "left_nonzero_source_count": 1,
            "right_nonzero_source_count": 1,
            "left_sum_positive_z": 2.0,
            "right_sum_positive_z": 6.0,
            "left_mean_positive_z": 2.0,
            "right_mean_positive_z": 6.0,
            "right_minus_left_sum_positive_z": 4.0,
            "lateralization_index_sum": 0.5,
            "dominant_hemisphere": "right",
        }
    ]

    json_path = tmp_path / "summary.json"
    csv_path = tmp_path / "summary.csv"
    write_source_lateralization_summary_files(
        json_path=json_path,
        csv_path=csv_path,
        rows=rows,
        metadata={"source_map_model": "participant_first"},
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["format"] == SOURCE_LATERALIZATION_SUMMARY_FORMAT
    assert payload["metadata"]["positive_lateralization_index"] == "right_lateralized"
    assert payload["rows"][0]["lateralization_index_sum"] == pytest.approx(0.5)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[0]["condition_label"] == "Color Response"
    assert csv_rows[0]["lateralization_index_sum"] == "0.5"


def test_source_lateralization_emits_precomputed_desikan_killiany_roi_first() -> None:
    rows = build_source_lateralization_rows(
        source_points=np.asarray(
            [
                [-1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ],
            dtype=float,
        ),
        condition_id="semantic_response",
        condition_label="Semantic Response",
        participant_values=(
            _ParticipantMap("P1", np.asarray([2.0, 6.0], dtype=float)),
        ),
        group_summaries=(),
        cluster_mask=np.asarray([True, True], dtype=bool),
        precomputed_rois=(
            SourceRoiMaskPair(
                roi_id=SOURCE_LATERALIZATION_ROI_DESIKAN_KILLIANY_TEMPORAL_HAUK,
                label="DK temporal",
                definition="test",
                left_mask=np.asarray([True, False], dtype=bool),
                right_mask=np.asarray([False, True], dtype=bool),
                metadata={"roi_source": "fsaverage_aparc_desikan_killiany"},
            ),
        ),
    )

    assert rows[0]["roi_id"] == SOURCE_LATERALIZATION_ROI_DESIKAN_KILLIANY_TEMPORAL_HAUK
    assert rows[0]["roi_source"] == "fsaverage_aparc_desikan_killiany"
    assert rows[0]["lateralization_index_sum"] == pytest.approx(0.5)
    assert rows[1]["roi_id"] == SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE

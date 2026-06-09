"""Source-space lateralization summaries for prepared source-map producers.

This module computes descriptive left/right source summaries from already
computed source values. It does not render, estimate sources, or perform
statistical tests.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SOURCE_LATERALIZATION_SUMMARY_FORMAT = "fpvs_loreta_source_lateralization_summary_v1"
DEFAULT_SOURCE_LATERALIZATION_JSON_NAME = "source_lateralization_summary.json"
DEFAULT_SOURCE_LATERALIZATION_CSV_NAME = "source_lateralization_summary.csv"
SOURCE_LATERALIZATION_MASK_CLUSTER = "source_space_cluster_permutation"
SOURCE_LATERALIZATION_MASK_POSITIVE_FALLBACK = "positive_z_fallback"
SOURCE_LATERALIZATION_VALUE_POLICY = "positive_z_magnitude"
SOURCE_LATERALIZATION_INDEX_FORMULA = "(right_sum_positive_z - left_sum_positive_z) / (right_sum_positive_z + left_sum_positive_z)"
SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE = "whole_hemisphere"
SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT = "occipitotemporal_lot_rot"
DEFAULT_SOURCE_LATERALIZATION_ROIS = (
    SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE,
    SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT,
)
SOURCE_LATERALIZATION_ROI_DEFINITIONS = {
    SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE: {
        "label": "Whole left/right hemisphere",
        "definition": "all source vertices split by x coordinate; x < 0 is left and x > 0 is right",
    },
    SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT: {
        "label": "LOT vs ROT coordinate ROI",
        "definition": (
            "posterior lateral occipito-temporal source vertices: abs(x) >= 20 mm, "
            "y <= -35 mm, z <= 35 mm; split by x coordinate"
        ),
        "x_abs_min_mm": 20.0,
        "y_max_mm": -35.0,
        "z_max_mm": 35.0,
    },
}

_CSV_FIELDS = (
    "condition_id",
    "condition_label",
    "roi_id",
    "roi_label",
    "roi_definition",
    "map_type",
    "participant_id",
    "aggregation",
    "mask_policy",
    "value_policy",
    "left_selected_source_count",
    "right_selected_source_count",
    "left_nonzero_source_count",
    "right_nonzero_source_count",
    "left_sum_positive_z",
    "right_sum_positive_z",
    "left_mean_positive_z",
    "right_mean_positive_z",
    "right_minus_left_sum_positive_z",
    "lateralization_index_sum",
    "dominant_hemisphere",
)


def build_source_lateralization_rows(
    *,
    source_points: Sequence[Sequence[float]],
    condition_id: str,
    condition_label: str,
    participant_values: Sequence[Any],
    group_summaries: Sequence[Any],
    cluster_mask: Sequence[bool] | np.ndarray | None,
    roi_ids: Sequence[str] = DEFAULT_SOURCE_LATERALIZATION_ROIS,
    midline_tolerance: float = 0.0,
) -> list[dict[str, Any]]:
    """Build source lateralization rows for one condition.

    Positive lateralization index values indicate stronger right-hemisphere
    source activation. Negative values indicate stronger left-hemisphere source
    activation. The values are descriptive summaries of already-computed source
    z-scores, not a new inferential test.
    """
    points = _validate_source_points(source_points)
    rows: list[dict[str, Any]] = []
    mask = _validate_cluster_mask(cluster_mask, source_count=len(points))

    for roi_id in roi_ids:
        roi = _roi_masks(points, roi_id=roi_id, midline_tolerance=midline_tolerance)
        for participant in participant_values:
            rows.append(
                _source_lateralization_row(
                    source_values=getattr(participant, "values"),
                    source_count=len(points),
                    condition_id=condition_id,
                    condition_label=condition_label,
                    roi_id=roi["id"],
                    roi_label=roi["label"],
                    roi_definition=roi["definition"],
                    map_type="participant",
                    participant_id=str(getattr(participant, "participant_id")),
                    aggregation="participant",
                    left_mask=roi["left_mask"],
                    right_mask=roi["right_mask"],
                    cluster_mask=mask,
                )
            )

        for summary in group_summaries:
            rows.append(
                _source_lateralization_row(
                    source_values=getattr(summary, "values"),
                    source_count=len(points),
                    condition_id=condition_id,
                    condition_label=condition_label,
                    roi_id=roi["id"],
                    roi_label=roi["label"],
                    roi_definition=roi["definition"],
                    map_type="group_summary",
                    participant_id="",
                    aggregation=str(getattr(summary, "aggregation")),
                    left_mask=roi["left_mask"],
                    right_mask=roi["right_mask"],
                    cluster_mask=mask,
                )
            )

    return rows


def write_source_lateralization_summary_files(
    *,
    json_path: str | Path,
    csv_path: str | Path,
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> None:
    """Write JSON and CSV source lateralization summary files."""
    row_list = [dict(row) for row in rows]
    payload = {
        "format": SOURCE_LATERALIZATION_SUMMARY_FORMAT,
        "label": "L2-MNE source-space lateralization summary",
        "metadata": {
            "value_policy": SOURCE_LATERALIZATION_VALUE_POLICY,
            "lateralization_index_formula": SOURCE_LATERALIZATION_INDEX_FORMULA,
            "positive_lateralization_index": "right_lateralized",
            "negative_lateralization_index": "left_lateralized",
            "hemisphere_split": "source coordinate x < 0 is left; x > 0 is right; midline sources are ignored",
            "roi_definitions": SOURCE_LATERALIZATION_ROI_DEFINITIONS,
            **dict(metadata),
        },
        "rows": row_list,
    }
    json_file = Path(json_path)
    csv_file = Path(csv_path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with json_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    with csv_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in row_list:
            writer.writerow({field: _csv_value(row.get(field)) for field in _CSV_FIELDS})


def _source_lateralization_row(
    *,
    source_values: Sequence[float],
    source_count: int,
    condition_id: str,
    condition_label: str,
    roi_id: str,
    roi_label: str,
    roi_definition: str,
    map_type: str,
    participant_id: str,
    aggregation: str,
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    cluster_mask: np.ndarray | None,
) -> dict[str, Any]:
    values = _validate_source_values(source_values, source_count=source_count)
    positive_values = np.clip(values, 0.0, None)
    finite_mask = np.isfinite(values)
    if cluster_mask is None:
        active_mask = finite_mask & (positive_values > 0.0)
        mask_policy = SOURCE_LATERALIZATION_MASK_POSITIVE_FALLBACK
    else:
        active_mask = finite_mask & cluster_mask & (positive_values > 0.0)
        mask_policy = SOURCE_LATERALIZATION_MASK_CLUSTER

    left_active = active_mask & left_mask
    right_active = active_mask & right_mask
    left_values = positive_values[left_active]
    right_values = positive_values[right_active]
    left_sum = float(np.sum(left_values)) if left_values.size else 0.0
    right_sum = float(np.sum(right_values)) if right_values.size else 0.0
    denominator = left_sum + right_sum
    lateralization = None if denominator <= 0.0 else float((right_sum - left_sum) / denominator)
    return {
        "condition_id": str(condition_id),
        "condition_label": str(condition_label),
        "roi_id": roi_id,
        "roi_label": roi_label,
        "roi_definition": roi_definition,
        "map_type": map_type,
        "participant_id": participant_id,
        "aggregation": aggregation,
        "mask_policy": mask_policy,
        "value_policy": SOURCE_LATERALIZATION_VALUE_POLICY,
        "left_selected_source_count": int(np.count_nonzero(left_active)),
        "right_selected_source_count": int(np.count_nonzero(right_active)),
        "left_nonzero_source_count": int(np.count_nonzero(left_values > 0.0)),
        "right_nonzero_source_count": int(np.count_nonzero(right_values > 0.0)),
        "left_sum_positive_z": left_sum,
        "right_sum_positive_z": right_sum,
        "left_mean_positive_z": _mean_or_none(left_values),
        "right_mean_positive_z": _mean_or_none(right_values),
        "right_minus_left_sum_positive_z": float(right_sum - left_sum),
        "lateralization_index_sum": lateralization,
        "dominant_hemisphere": _dominant_hemisphere(lateralization),
    }


def _roi_masks(
    points: np.ndarray,
    *,
    roi_id: str,
    midline_tolerance: float,
) -> dict[str, Any]:
    roi_key = str(roi_id).strip().lower()
    midline = abs(float(midline_tolerance))
    definition = SOURCE_LATERALIZATION_ROI_DEFINITIONS.get(roi_key)
    if definition is None:
        valid = ", ".join(DEFAULT_SOURCE_LATERALIZATION_ROIS)
        raise ValueError(f"Unsupported source lateralization ROI {roi_id!r}; expected one of: {valid}.")
    if roi_key == SOURCE_LATERALIZATION_ROI_WHOLE_HEMISPHERE:
        roi_mask = np.ones(len(points), dtype=bool)
    elif roi_key == SOURCE_LATERALIZATION_ROI_OCCIPITOTEMPORAL_LOT_ROT:
        roi_mask = (
            (np.abs(points[:, 0]) >= float(definition["x_abs_min_mm"]))
            & (points[:, 1] <= float(definition["y_max_mm"]))
            & (points[:, 2] <= float(definition["z_max_mm"]))
        )
    else:
        valid = ", ".join(DEFAULT_SOURCE_LATERALIZATION_ROIS)
        raise ValueError(f"Unsupported source lateralization ROI {roi_id!r}; expected one of: {valid}.")
    return {
        "id": roi_key,
        "label": str(definition["label"]),
        "definition": str(definition["definition"]),
        "left_mask": roi_mask & (points[:, 0] < -midline),
        "right_mask": roi_mask & (points[:, 0] > midline),
    }


def _validate_source_points(source_points: Sequence[Sequence[float]]) -> np.ndarray:
    points = np.asarray(source_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Source lateralization requires source_points shaped source_count x 3.")
    if not np.all(np.isfinite(points)):
        raise ValueError("Source lateralization requires finite source coordinates.")
    return points


def _validate_source_values(source_values: Sequence[float], *, source_count: int) -> np.ndarray:
    values = np.asarray(source_values, dtype=float).reshape(-1)
    if values.shape != (source_count,):
        raise ValueError(
            f"Source lateralization received {len(values)} values; {source_count} source points expected."
        )
    return values


def _validate_cluster_mask(
    cluster_mask: Sequence[bool] | np.ndarray | None,
    *,
    source_count: int,
) -> np.ndarray | None:
    if cluster_mask is None:
        return None
    mask = np.asarray(cluster_mask, dtype=bool).reshape(-1)
    if mask.shape != (source_count,):
        raise ValueError(
            f"Source lateralization cluster mask has {len(mask)} values; {source_count} source points expected."
        )
    return mask


def _mean_or_none(values: np.ndarray) -> float | None:
    return None if values.size == 0 else float(np.mean(values))


def _dominant_hemisphere(lateralization: float | None) -> str:
    if lateralization is None:
        return "none"
    if lateralization > 0.0:
        return "right"
    if lateralization < 0.0:
        return "left"
    return "balanced"


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and not np.isfinite(value):
        return ""
    return value

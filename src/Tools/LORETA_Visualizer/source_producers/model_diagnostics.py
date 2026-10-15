"""Read-only facts about the inverse model and its committed EEG inputs.

These diagnostics describe the model that was constructed. They do not infer
participant data rank, covariance suitability, or localization accuracy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


def summarize_inverse_model(info: Any, inverse_operator: Any) -> dict[str, Any]:
    """Extract recorded channels, projectors, and model covariance facts."""
    names = list(info["ch_names"])
    projections = [
        {
            "description": str(projection.get("desc", "")),
            "active": bool(projection.get("active", False)),
            "kind": int(projection["kind"]) if projection.get("kind") is not None else None,
        }
        for projection in info["projs"]
    ]
    summary: dict[str, Any] = {
        "channel_count": len(names),
        "channel_names": names,
        "bad_channels": list(info["bads"]),
        "custom_ref_applied": int(info["custom_ref_applied"]),
        "projections": projections,
        "participant_data_rank_status": "not_measured",
        "electrode_geometry": "standard BioSemi64 template coordinates",
        "participant_coregistration": "not_performed",
    }
    covariance = inverse_operator.get("noise_cov") if isinstance(inverse_operator, Mapping) else None
    if isinstance(covariance, Mapping) and covariance.get("data") is not None:
        data = np.asarray(covariance["data"], dtype=float)
        variances = data if data.ndim == 1 else np.diag(data)
        if variances.size and np.all(np.isfinite(variances)):
            summary["model_noise_covariance"] = {
                "source": "mne_ad_hoc_diagonal_eeg",
                "estimated_from_recorded_noise": False,
                "channel_names": list(covariance.get("names", [])),
                "diagonal": bool(covariance.get("diag", data.ndim == 1)),
                "variance_unit": "V^2",
                "variance_min": float(np.min(variances)),
                "variance_max": float(np.max(variances)),
            }
    return summary


def summarize_time_domain_inputs(records: Sequence[Any]) -> list[dict[str, Any]]:
    """Copy committed reference/interpolation provenance without loading EEG."""
    rows: list[dict[str, Any]] = []
    for record in records:
        sidecar = record.sidecar
        processing = sidecar.get("processing", {})
        provenance = processing.get("provenance", {}) if isinstance(processing, Mapping) else {}
        interpolation = provenance.get("condition_electrode_interpolation") if isinstance(provenance, Mapping) else None
        rows.append(
            {
                "participant_id": record.participant_id,
                "group_id": record.group_id,
                "condition_id": record.condition_id,
                "condition_label": record.condition_label,
                "channel_count": len(record.channel_names),
                "bad_channels": list(record.bad_channels),
                "reference": dict(sidecar.get("reference", {})),
                "geometry": dict(sidecar.get("geometry", {})),
                "condition_electrode_interpolation": interpolation,
                "interpolation_provenance_status": "recorded" if interpolation is not None else "not_recorded",
                "participant_data_rank_status": "not_measured",
            }
        )
    return rows

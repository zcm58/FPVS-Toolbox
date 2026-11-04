"""Read-only facts about the inverse model and its committed EEG inputs.

These diagnostics describe the model and, when samples are supplied, numerical
rank of the source-ready derivative. They do not establish covariance suitability,
rank of the original recording, or localization accuracy.
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
            names_covariance = list(covariance.get("names", []))
            good_names = [name for name in names if name not in info["bads"]]
            if names_covariance and names_covariance not in (names, good_names):
                raise ValueError("Inverse covariance channels do not match the ordered model channels.")
            matrix = np.diag(data) if data.ndim == 1 else data
            projection = _projection_matrix(info)
            if names_covariance == good_names and len(good_names) != len(names):
                indices = [names.index(name) for name in good_names]
                projection = projection[np.ix_(indices, indices)]
            summary["model_noise_covariance"].update({
                "unprojected_numerical_rank": numerical_rank_summary(matrix),
                "projected_numerical_rank": numerical_rank_summary(projection @ matrix @ projection.T),
                "suitability_status": "not_established_by_rank_diagnostic",
            })
    return summary


def numerical_rank_summary(values: np.ndarray) -> dict[str, Any]:
    """Report SVD rank with NumPy's dimension-scaled floating-point threshold."""
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or not all(matrix.shape) or not np.all(np.isfinite(matrix)):
        raise ValueError("Rank diagnostic requires a finite nonempty two-dimensional array.")
    singular = np.linalg.svd(matrix, compute_uv=False)
    tolerance = float(singular[0] * max(matrix.shape) * np.finfo(float).eps)
    retained = singular[singular > tolerance]
    return {
        "rank": int(len(retained)), "shape": list(matrix.shape),
        "singular_values": singular.tolist(), "absolute_tolerance": tolerance,
        "tolerance_rule": "largest_singular_value * max(shape) * float64_epsilon",
        "condition_number_on_retained_subspace": float(retained[0] / retained[-1]) if len(retained) else None,
        "full_rank": len(retained) == min(matrix.shape),
    }


def _projection_matrix(info: Any) -> np.ndarray:
    import mne

    probe_info = info.copy()
    # The identity probe has not been projected even if recorded samples were.
    for projection in probe_info["projs"]:
        projection["active"] = False
    probe = mne.EvokedArray(np.eye(len(info["ch_names"])), probe_info, verbose=False)
    probe.apply_proj(verbose=False)
    return np.asarray(probe.data)


def summarize_recorded_data_rank(raw: Any, *, expected_info: Any | None = None) -> dict[str, Any]:
    """Measure derivative rank and reject established model/input mismatches.

    Samples are not substituted into the inverse covariance. Mean removal is
    explicit; reference projection is applied only to the diagnostic copy.
    """
    data = np.asarray(raw.get_data(), dtype=float)
    names = list(raw.info["ch_names"])
    if data.ndim != 2 or data.shape[0] != len(names) or not np.all(np.isfinite(data)):
        raise ValueError("Rank diagnostic data must be finite and match its channel metadata.")
    geometry_status = "model_not_supplied"
    reference_status = "model_not_supplied"
    projection = _projection_matrix(raw.info)
    if expected_info is not None:
        if names != list(expected_info["ch_names"]):
            raise ValueError("Source derivative channels do not match the ordered inverse channels.")
        if any(actual["kind"] != expected["kind"] or actual["unit"] != expected["unit"] for actual, expected in zip(raw.info["chs"], expected_info["chs"], strict=True)):
            raise ValueError("Source derivative channel types or units differ from the inverse model.")
        frame_pairs = [(int(actual["coord_frame"]), int(expected["coord_frame"])) for actual, expected in zip(raw.info["chs"], expected_info["chs"], strict=True)]
        if any(actual and expected and actual != expected for actual, expected in frame_pairs):
            raise ValueError("Source derivative electrode coordinate frames differ from the inverse model.")
        actual = np.asarray([channel["loc"][:3] for channel in raw.info["chs"]])
        expected = np.asarray([channel["loc"][:3] for channel in expected_info["chs"]])
        finite = np.all(np.isfinite(actual), axis=1) & np.all(np.isfinite(expected), axis=1)
        comparable = finite & np.asarray([bool(left and right) for left, right in frame_pairs])
        if np.any(comparable) and not np.allclose(actual[comparable], expected[comparable], rtol=0., atol=1e-7):
            raise ValueError("Source derivative electrode coordinates differ from the admitted inverse geometry.")
        geometry_status = "matched_recorded_coordinates" if np.all(finite) and all(actual and expected for actual, expected in frame_pairs) else "incomplete_coordinates_unverified"
        expected_projection = _projection_matrix(expected_info)
        if not np.allclose(projection, expected_projection, rtol=0., atol=1e-12):
            raise ValueError("Source derivative reference projectors differ from the inverse model.")
        reference_status = "matching_projection_operator"
    centered = data - data.mean(axis=1, keepdims=True)
    return {
        "participant_data_rank_status": "measured_source_ready_derivative",
        "scope": "signed_repetition_averaged_source_ready_samples_not_original_recording",
        "unit": "V", "channel_count": len(names), "sample_count": int(data.shape[1]),
        "mean_removed_per_channel": True,
        "unprojected": numerical_rank_summary(centered),
        "after_recorded_projectors": numerical_rank_summary(projection @ centered),
        "model_geometry_status": geometry_status, "model_reference_status": reference_status,
        "limitations": [
            "Numerical rank depends on the recorded derivative, precision and stated tolerance.",
            "Averaging, reference, interpolation and earlier processing can reduce rank.",
            "This diagnostic does not establish biological rank or noise covariance suitability.",
        ],
    }


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

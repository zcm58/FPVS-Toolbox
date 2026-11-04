"""Qualification of source-Z sign-flip outputs, separate from their arithmetic.

No registered source spectral pipeline currently establishes a symmetric null
or population error control. Published precedent and small synthetic experiments
must not silently promote algorithmic p-values to confirmatory inference.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SOURCE_INFERENCE_QUALIFICATION_VERSION = 1


def source_inference_qualification_metadata(
    selection_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return fail-closed, JSON-safe qualifications for a single source map."""
    selection = dict(selection_metadata or {})
    independence = str(selection.get("selection_independence", "")).lower()
    profile = str(selection.get("method_profile_id", selection.get("profile_id", selection.get("harmonic_selection_profile", "")))).lower()
    adaptive = bool(selection.get("same_sample_adaptive", False)) or independence == "same_sample_adaptive"
    adaptive = adaptive or profile in {
        "legacy_fpvs_toolbox", "significant_only_exploratory",
        "dzhelyova_poncet_two_consecutive_failures",
    }
    fixed = independence in {"fixed", "a_priori", "independent", "preregistered"}
    fixed = fixed or profile in {"fixed", "fixed_preregistered", "fixed_preregistered_domain"}
    basis = "same_sample_adaptive" if adaptive else "fixed_or_independent" if fixed else "unknown"
    reasons = [
        "Spectral source-Z null centering and participant sign symmetry have not been established.",
        "Full source-ready spectral-pipeline error control has not been qualified for project data.",
    ]
    if basis == "same_sample_adaptive":
        reasons.append("Harmonics were selected using the same sample; sign flips do not repeat selection.")
    elif basis == "unknown":
        reasons.append("Independence of harmonic selection is not established by the saved provenance.")
    return {
        "source_inference_qualification_version": SOURCE_INFERENCE_QUALIFICATION_VERSION,
        "source_inference_status": "exploratory_full_pipeline_unvalidated",
        "source_inference_exploratory": True,
        "source_inference_confirmatory": False,
        "source_inference_selection_basis": basis,
        "source_inference_null_assumption": "independent_participant_maps_sign_symmetric_about_zero_unverified",
        "source_inference_family_scope": "one_method_group_condition_on_complete_valid_source_support",
        "source_inference_correction_scope": "max_cluster_mass_within_map_only_no_across_condition_group_or_method_correction",
        "source_inference_display_summary_scope": "mean_t_mask_shared_by_mean_median_and_trimmed_mean_displays",
        "source_inference_reasons": reasons,
    }


def require_confirmatory_source_inference() -> None:
    """Reject a confirmatory request until a reviewed qualification is registered."""
    raise ValueError(
        "Confirmatory source-Z inference is unavailable: the full spectral pipeline "
        "and harmonic-selection procedure are not qualified. Existing masks are exploratory."
    )

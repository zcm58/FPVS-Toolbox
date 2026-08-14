"""Canonical Main App processing import surface."""

from Main_App.processing.processing import process_data
from Main_App.processing.preprocess import (
    begin_preproc_audit,
    finalize_preproc_audit,
    perform_preprocessing,
)
from Main_App.processing.artifact_freshness import (
    activate_selection_freshness,
    canonical_artifact_path,
    load_active_selection_fingerprint,
    load_artifact_freshness_registry,
    mark_artifact_current,
    mark_artifact_failed,
    mark_selection_derivatives_stale,
    require_current_artifact,
    selection_fingerprint_from_metadata,
)

__all__ = [
    "begin_preproc_audit",
    "activate_selection_freshness",
    "canonical_artifact_path",
    "finalize_preproc_audit",
    "load_active_selection_fingerprint",
    "load_artifact_freshness_registry",
    "mark_artifact_current",
    "mark_artifact_failed",
    "mark_selection_derivatives_stale",
    "perform_preprocessing",
    "process_data",
    "require_current_artifact",
    "selection_fingerprint_from_metadata",
]

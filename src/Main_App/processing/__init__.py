"""Canonical Main App processing import surface."""

from importlib import import_module

__all__ = [
    "begin_preproc_audit",
    "activate_selection_freshness",
    "ALL_ROIS_OPTION",
    "canonical_artifact_path",
    "finalize_preproc_audit",
    "load_active_selection_fingerprint",
    "load_artifact_freshness_registry",
    "load_rois_from_settings",
    "mark_artifact_current",
    "mark_artifact_failed",
    "mark_selection_derivatives_stale",
    "perform_preprocessing",
    "process_data",
    "require_current_artifact",
    "selection_fingerprint_from_metadata",
]


def __getattr__(name: str):
    """Keep lightweight contracts independent of the EEG execution stack."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name == "process_data":
        module = "processing"
    elif name in {"begin_preproc_audit", "finalize_preproc_audit", "perform_preprocessing"}:
        module = "preprocess"
    elif name in {"ALL_ROIS_OPTION", "load_rois_from_settings"}:
        module = "roi_settings"
    else:
        module = "artifact_freshness"
    return getattr(import_module(f"Main_App.processing.{module}"), name)

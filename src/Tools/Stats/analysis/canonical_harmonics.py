"""Compatibility exports for the processing-owned harmonic contract."""

from Main_App.processing.canonical_harmonics import (
    __all__ as __all__,
    CANONICAL_HARMONIC_SOURCE as CANONICAL_HARMONIC_SOURCE,
    CUSTOM_HARMONIC_SOURCE as CUSTOM_HARMONIC_SOURCE,
    SharedHarmonicSelection as SharedHarmonicSelection,
    CanonicalHarmonicSelectionError as CanonicalHarmonicSelectionError,
    load_project_processing_harmonics as load_project_processing_harmonics,
    shared_selection_from_metadata as shared_selection_from_metadata,
    custom_harmonic_selection as custom_harmonic_selection,
    harmonic_selection_fingerprint as harmonic_selection_fingerprint,
    compute_selection_fingerprint as compute_selection_fingerprint,
    format_harmonic_selection_fingerprint as format_harmonic_selection_fingerprint,
    _float_tuple as _float_tuple,
    _string_list as _string_list,
    _is_number as _is_number,
    _json_safe as _json_safe,
)

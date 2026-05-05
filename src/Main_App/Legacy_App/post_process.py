"""Compatibility wrapper for post-processing exports.

The implementation lives in :mod:`Main_App.Shared.post_process`.
Keep this module thin while callers migrate away from ``Legacy_App``.
"""

from Main_App.Shared.post_process import (  # noqa: F401
    ODDBALL_FREQ,
    _attempt_legacy_55_onbin_crop,
    _load_events_for_file,
    _read_analysis_float,
    _read_analysis_setting,
    _resolve_condition_id,
    _resolve_target_frequencies,
    post_process,
)

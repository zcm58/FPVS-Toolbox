"""Compatibility wrapper for the Main App processing mixin.

The implementation lives in :mod:`Main_App.Shared.processing_mixin`.
Keep this module thin while stale callers migrate away from ``Legacy_App``.
"""

from Main_App.Shared.processing_mixin import ProcessingMixin  # noqa: F401

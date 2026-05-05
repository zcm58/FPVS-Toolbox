"""Compatibility wrapper for :mod:`Main_App.exports.post_export_adapter`."""

from Main_App.exports.post_export_adapter import (  # noqa: F401
    LegacyCtx,
    run_post_export,
)

__all__ = ["LegacyCtx", "run_post_export"]

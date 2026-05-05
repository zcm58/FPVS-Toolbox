"""Canonical Main App runtime diagnostics import surface."""

from __future__ import annotations

import importlib
from typing import Any

_AUDIT_NAMES = {
    "compare_preproc",
    "end_preproc_audit",
    "fingerprint",
    "format_audit_summary",
    "start_preproc_audit",
    "write_audit_json",
}

__all__ = sorted(_AUDIT_NAMES | {"event_time_lock_report"})


def __getattr__(name: str) -> Any:
    if name in _AUDIT_NAMES:
        audit = importlib.import_module("Main_App.diagnostics.audit")

        return getattr(audit, name)
    if name == "event_time_lock_report":
        return importlib.import_module("Main_App.diagnostics.event_time_lock_report")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

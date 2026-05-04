"""Fail-fast stub for quarantined legacy Stats runner UI helpers."""
from __future__ import annotations

from Tools.Stats.Legacy import quarantined_stats_ui_message

_QUARANTINE_MESSAGE = quarantined_stats_ui_message()
ROIS = {}
HARMONIC_CHECK_ALPHA = 0.05


def __getattr__(name: str):
    raise RuntimeError(f"{_QUARANTINE_MESSAGE}\nUnsupported runner: {name}")

"""Fail-fast stub for quarantined legacy Stats file-scanner UI helpers."""
from __future__ import annotations

from Tools.Stats.Legacy import quarantined_stats_ui_message

_QUARANTINE_MESSAGE = quarantined_stats_ui_message()


def browse_folder(*_args, **_kwargs):
    """Fail fast when stale code tries to browse folders through the old UI."""
    raise RuntimeError(_QUARANTINE_MESSAGE)


def scan_folder(*_args, **_kwargs):
    """Fail fast when stale code tries to scan folders through the old UI."""
    raise RuntimeError(_QUARANTINE_MESSAGE)


def update_condition_menus(*_args, **_kwargs):
    """Fail fast when stale code tries to update old condition menus."""
    raise RuntimeError(_QUARANTINE_MESSAGE)


def update_condition_B_options(*_args, **_kwargs):
    """Fail fast when stale code tries to update old condition menus."""
    raise RuntimeError(_QUARANTINE_MESSAGE)

"""Fail-fast stub for the quarantined legacy CustomTkinter Stats UI builder."""

from __future__ import annotations

from Tools.Stats.Legacy import quarantined_stats_ui_message

_QUARANTINE_MESSAGE = quarantined_stats_ui_message()


def create_widgets(*_args, **_kwargs):
    """Fail fast when stale code tries to build the removed CTk Stats UI."""
    raise RuntimeError(_QUARANTINE_MESSAGE)

"""Fail-fast stub for the quarantined legacy CustomTkinter Stats window."""

from __future__ import annotations

import sys

from Tools.Stats.Legacy import quarantined_stats_window_message

_QUARANTINE_MESSAGE = quarantined_stats_window_message()


class StatsAnalysisWindow:
    """Fail fast when stale code tries to launch the removed CTk Stats window."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise RuntimeError(_QUARANTINE_MESSAGE)


def main() -> None:
    """Fail fast if the quarantined module is executed directly."""
    raise RuntimeError(_QUARANTINE_MESSAGE)


if __name__ == "__main__":
    print(_QUARANTINE_MESSAGE, file=sys.stderr)
    sys.exit(2)

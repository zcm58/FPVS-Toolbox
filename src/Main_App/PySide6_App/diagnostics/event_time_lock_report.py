"""Compatibility wrapper for :mod:`Main_App.diagnostics.event_time_lock_report`."""

from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module("Main_App.diagnostics.event_time_lock_report")

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        raise SystemExit(_impl._run_gui())

    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl

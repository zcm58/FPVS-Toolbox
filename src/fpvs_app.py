#!/usr/bin/env python3
"""Quarantined legacy entry point.

`fpvs_app.py` used to launch the old CustomTkinter GUI. The active app now
launches from `src/main.py` and uses PySide6. This file is no longer in active use.
"""

from __future__ import annotations

import sys

_QUARANTINE_MESSAGE = (
    "The legacy CustomTkinter entry point `fpvs_app.py` has been quarantined and "
    "is no longer supported.\n"
    "Use `python src/main.py` (or the packaged `FPVS_Toolbox.exe`) for the "
    "current PySide6 application.\n"
    "Legacy source is preserved at "
    "`src/quarantine/Main_App/Legacy_App/fpvs_app_legacy.py` for reference only."
)


def main() -> None:
    """Fail fast if a stale launcher still calls this module."""
    raise RuntimeError(_QUARANTINE_MESSAGE)


if __name__ == "__main__":
    print(_QUARANTINE_MESSAGE, file=sys.stderr)
    sys.exit(2)

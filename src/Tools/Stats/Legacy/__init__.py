"""Compatibility namespace for old Stats Legacy imports.

Active statistical engines live under ``Tools.Stats`` functional packages.
The old CustomTkinter UI entry points have been quarantined and must fail
fast if stale code tries to access them.
"""

from __future__ import annotations


def quarantined_stats_window_message() -> str:
    return (
        "The legacy CustomTkinter Stats UI at `Tools.Stats.Legacy.stats` has been "
        "quarantined and is no longer supported.\n"
        "Use the PySide6 Stats tool instead.\n"
        "Reference source is preserved at "
        "`src/quarantine/Tools/Stats/Legacy_UI/stats.py`."
    )


def quarantined_stats_ui_message() -> str:
    return (
        "The legacy CustomTkinter Stats UI helpers at `Tools.Stats.Legacy.stats_ui` "
        "have been quarantined and are no longer supported.\n"
        "Reference source is preserved at "
        "`src/quarantine/Tools/Stats/Legacy_UI/stats_ui.py`."
    )


def __getattr__(name: str):
    if name == "StatsAnalysisWindow":
        raise RuntimeError(quarantined_stats_window_message())
    if name == "create_widgets":
        raise RuntimeError(quarantined_stats_ui_message())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

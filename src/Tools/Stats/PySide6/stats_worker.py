"""
Backwards-compatibility shim for StatsWorker.

StatsWorker is now defined in stats_workers.py.
New code should import from src.Tools.Stats.PySide6.stats_workers instead.
"""

from __future__ import annotations

from .stats_workers import StatsWorker

__all__ = ["StatsWorker"]

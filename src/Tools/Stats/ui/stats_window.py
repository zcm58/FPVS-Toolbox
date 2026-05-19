"""Thin wrapper exposing :class:`StatsWindow` for the Stats tool."""
from __future__ import annotations

from Tools.Stats.workers import stats_workers as _stats_workers
from .stats_main_window import StatsWindow

# Test hook exports for callers that monkeypatch worker entry points directly
# on this module.
_rm_anova_calc = _stats_workers.run_rm_anova
_lmm_calc = _stats_workers.run_lmm
_posthoc_calc = _stats_workers.run_posthoc

__all__ = ["StatsWindow"]

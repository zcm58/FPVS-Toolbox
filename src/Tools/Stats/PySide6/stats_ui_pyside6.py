"""Thin wrapper exposing :class:`StatsWindow` for the Stats tool."""
from __future__ import annotations

from . import stats_workers as _stats_workers
from .stats_main_window import StatsWindow

# Compatibility exports for existing tests and callers that monkeypatch
# worker entry points directly on this module.
_rm_anova_calc = _stats_workers.run_rm_anova
_lmm_calc = _stats_workers.run_lmm
_posthoc_calc = _stats_workers.run_posthoc
_between_group_anova_calc = _stats_workers.run_between_group_anova
_group_contrasts_calc = _stats_workers.run_group_contrasts

__all__ = ["StatsWindow"]

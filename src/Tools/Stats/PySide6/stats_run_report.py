"""Run report structures for Stats flagging/exclusion workflow."""

from __future__ import annotations

from dataclasses import dataclass

from Tools.Stats.PySide6.stats_outlier_exclusion import OutlierExclusionReport, DvViolation
from Tools.Stats.PySide6.stats_qc_exclusion import QcExclusionReport


@dataclass(frozen=True)
class StatsRunReport:
    """Represent the StatsRunReport part of the Stats PySide6 tool."""
    manual_excluded_pids: list[str]
    qc_report: QcExclusionReport | None
    dv_report: OutlierExclusionReport | None
    required_exclusions: list[DvViolation]
    final_modeled_pids: list[str]

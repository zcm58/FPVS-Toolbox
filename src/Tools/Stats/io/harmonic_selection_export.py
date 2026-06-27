"""Standalone harmonic-selection workbook export helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from Tools.Stats.io.stats_ready_export import (
    HARMONIC_SELECTION_SHEET,
    SELECTION_SUMMARY_SHEET,
    _build_harmonic_selection_frame,
    _build_selection_summary_frame,
    write_stats_ready_workbook,
)

HARMONIC_SELECTION_QC_WORKBOOK_NAME = "Harmonic_Selection_Summary.xlsx"


def build_harmonic_selection_frames(
    selection_metadata: Mapping[str, object],
) -> dict[str, pd.DataFrame]:
    """Build user-facing harmonic-selection summary frames."""
    dv_metadata = {"group_significant_harmonics": dict(selection_metadata)}
    return {
        SELECTION_SUMMARY_SHEET: _build_selection_summary_frame(dv_metadata),
        HARMONIC_SELECTION_SHEET: _build_harmonic_selection_frame(dv_metadata),
    }


def write_harmonic_selection_workbook(
    save_path: str | Path,
    selection_metadata: Mapping[str, object],
) -> Path:
    """Write a compact harmonic-selection QC workbook."""
    frames = build_harmonic_selection_frames(selection_metadata)
    return write_stats_ready_workbook(save_path, frames)


__all__ = [
    "HARMONIC_SELECTION_QC_WORKBOOK_NAME",
    "build_harmonic_selection_frames",
    "write_harmonic_selection_workbook",
]

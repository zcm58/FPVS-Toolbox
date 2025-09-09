import logging
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
from Main_App import SettingsManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ROI:
    name: str
    channels: List[str]


DEFAULT_ROIS: Dict[str, List[str]] = {
    "Frontal Lobe": ["F3", "F4", "Fz"],
    "Occipital Lobe": ["O1", "O2", "Oz"],
    "Parietal Lobe": ["P3", "P4", "Pz"],
    "Central Lobe": ["C3", "C4", "Cz"],
}


def resolve_active_rois() -> List[ROI]:
    """Return the current ROI set defined in the Settings UI.

    ROIs are taken from current Settings at runtime via resolve_active_rois().
    Source of truth matches the harmonic check path.
    Raise ``ValueError`` if no ROI definitions are found.
    """
    mgr = SettingsManager()
    pairs = mgr.get_roi_pairs() if hasattr(mgr, "get_roi_pairs") else []
    rois: List[ROI] = []
    for name, electrodes in pairs:
        if name and electrodes:
            rois.append(ROI(name=name, channels=[e.upper() for e in electrodes]))
    existing = {r.name for r in rois}
    for name, chans in DEFAULT_ROIS.items():
        if name not in existing:
            rois.append(ROI(name=name, channels=chans))
    if not rois:
        raise ValueError("No ROI definitions found in Settings.")
    return rois


def apply_roi_aggregation(
    df: pd.DataFrame,
    rois: List[ROI],
    ch_col: str,
    val_col: str,
) -> pd.DataFrame:
    """Aggregate channel-level data to ROI-level by mean across channels.

    Given long-format channel-level data, produce ROI-level rows by aggregating over
    channels per subject/condition/harmonic using the same mean rule as the harmonic
    checks.

    ROIs are taken from current Settings at runtime via resolve_active_rois().
    """
    other_cols = [c for c in df.columns if c not in {ch_col, val_col}]
    out_frames: List[pd.DataFrame] = []
    for roi in rois:
        mask = df[ch_col].str.upper().isin(roi.channels)
        if not mask.any():
            continue
        grouped = (
            df.loc[mask]
            .groupby(other_cols, dropna=False)[val_col]
            .mean()
            .reset_index()
        )
        grouped["roi"] = roi.name
        out_frames.append(grouped)
    if out_frames:
        return pd.concat(out_frames, ignore_index=True)
    return pd.DataFrame(columns=other_cols + ["roi", val_col])


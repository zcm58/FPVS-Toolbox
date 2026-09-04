import logging
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
import numpy as np
from Main_App import SettingsManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ROI:
    name: str
    channels: List[str]


DEFAULT_ROIS: Dict[str, List[str]] = {
    "LOT": ["P7", "P9", "PO7", "PO3", "O1"],
    "ROT": ["P8", "P10", "PO8", "PO4", "O2"],
    "Central": ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"],
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
    source = df.copy()
    source[ch_col] = source[ch_col].astype(str).str.strip().str.upper()
    source[val_col] = pd.to_numeric(source[val_col], errors="coerce")
    groups = source.loc[:, other_cols].drop_duplicates()
    out_frames: List[pd.DataFrame] = []
    for roi in rois:
        channels = [str(channel).strip().upper() for channel in roi.channels]
        if not channels or len(channels) != len(set(channels)):
            raise ValueError(
                f"ROI {roi.name!r} must contain a nonempty unique electrode set."
            )
        selected = source.loc[source[ch_col].isin(channels)].copy()
        duplicate_keys = [*other_cols, ch_col]
        if selected.duplicated(duplicate_keys, keep=False).any():
            raise ValueError(
                f"ROI {roi.name!r} has duplicate electrode rows within an analysis cell."
            )
        expected = groups.assign(_join=1).merge(
            pd.DataFrame({ch_col: channels, "_join": 1}),
            on="_join",
            how="inner",
        ).drop(columns="_join")
        checked = expected.merge(
            selected.loc[:, [*other_cols, ch_col, val_col]],
            on=[*other_cols, ch_col],
            how="left",
            validate="one_to_one",
        )
        if not np.isfinite(checked[val_col].to_numpy(dtype=float)).all():
            raise ValueError(
                f"ROI {roi.name!r} lacks one finite value for every configured "
                "electrode in an analysis cell."
            )
        grouped = checked.groupby(other_cols, dropna=False, sort=False)[
            val_col
        ].mean().reset_index()
        grouped["roi"] = roi.name
        out_frames.append(grouped)
    if out_frames:
        return pd.concat(out_frames, ignore_index=True)
    return pd.DataFrame(columns=other_cols + ["roi", val_col])


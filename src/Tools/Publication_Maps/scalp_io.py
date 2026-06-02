"""BioSemi64 alignment and source-frame helpers for publication scalp maps."""

from __future__ import annotations

from functools import lru_cache

import mne
import numpy as np
import pandas as pd

from Tools.Publication_Maps.models import Diagnostic


def normalize_electrode_name(value: object) -> str:
    """Normalize workbook electrode labels for montage alignment."""

    return str(value).strip().upper()


@lru_cache(maxsize=1)
def biosemi64_info() -> mne.io.Info:
    """Return a cached BioSemi64 info object for topomap rendering."""

    montage = mne.channels.make_standard_montage("biosemi64")
    info = mne.create_info(ch_names=montage.ch_names, sfreq=100, ch_types="eeg")
    info.set_montage(montage)
    return info


@lru_cache(maxsize=1)
def biosemi64_names_upper() -> frozenset[str]:
    """Return normalized BioSemi64 channel names."""

    return frozenset(name.upper() for name in biosemi64_info().ch_names)


def align_render_values(
    values: pd.DataFrame,
    *,
    value_column: str = "render_value",
) -> tuple[np.ndarray, mne.io.Info, int, list[Diagnostic]]:
    """Align condition/electrode values to BioSemi64 order for rendering."""

    info = biosemi64_info().copy()
    name_to_idx = {name.upper(): idx for idx, name in enumerate(info.ch_names)}
    data = np.full(len(info.ch_names), np.nan, dtype=float)
    diagnostics: list[Diagnostic] = []
    unmapped = 0
    for row in values.itertuples(index=False):
        electrode = normalize_electrode_name(getattr(row, "electrode"))
        idx = name_to_idx.get(electrode)
        if idx is None:
            unmapped += 1
            continue
        try:
            data[idx] = float(getattr(row, value_column))
        except (TypeError, ValueError):
            data[idx] = np.nan
    missing_count = int(np.sum(np.isnan(data)))
    if unmapped:
        diagnostics.append(
            Diagnostic(
                level="warning",
                message="Workbook electrodes were not in the BioSemi64 montage.",
                detail=str(unmapped),
            )
        )
    data = np.nan_to_num(data, nan=0.0)
    return data, info, missing_count, diagnostics

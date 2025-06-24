"""Utility functions for sLORETA source localization."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import mne
from Tools.SourceLocalization.eloreta_runner import fetch_fsaverage_with_progress


def prepare_head_model(raw: mne.io.BaseRaw, template: str = "fsaverage") -> tuple[mne.Forward, str, str]:
    """Compute a forward model using the provided raw data.

    Parameters
    ----------
    raw : mne.io.BaseRaw
        Preprocessed raw data with correct montage.
    template : str
        Template subject name to use when no individual MRI is available.
    Returns
    -------
    tuple
        forward solution, subject name, subjects_dir
    """
    subjects_dir = fetch_fsaverage_with_progress(os.getcwd(), log_func=print)
    src = mne.setup_source_space(template, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    model = mne.make_bem_model(subject=template, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)
    trans = "fsaverage"  # template transformation
    fwd = mne.make_forward_solution(raw.info, trans=trans, src=src, bem=bem, eeg=True)
    return fwd, template, subjects_dir


def estimate_noise_cov(raw: mne.io.BaseRaw, tmin: float = 0.0, tmax: Optional[float] = None) -> mne.Covariance:
    """Estimate noise covariance from a segment of raw data."""
    return mne.compute_raw_covariance(raw, tmin=tmin, tmax=tmax)


def make_inverse_operator(raw: mne.io.BaseRaw, fwd: mne.Forward, noise_cov: mne.Covariance) -> mne.minimum_norm.InverseOperator:
    """Build an inverse operator configured for sLORETA."""
    return mne.minimum_norm.make_inverse_operator(raw.info, fwd, noise_cov, loose=0.2, depth=0.8)


def apply_sloreta(epochs_dict: Dict[str, List[mne.Epochs]], inv: mne.minimum_norm.InverseOperator, snr: float = 3.0) -> Dict[str, mne.SourceEstimate]:
    """Apply sLORETA to each condition's epochs and return SourceEstimates."""
    lambda2 = 1.0 / snr ** 2
    stcs: Dict[str, mne.SourceEstimate] = {}
    for label, ep_list in epochs_dict.items():
        if not ep_list:
            continue
        ep = ep_list[0]
        if isinstance(ep, mne.Epochs):
            evoked = ep.average()
        else:
            evoked = ep
        stc = mne.minimum_norm.apply_inverse(evoked, inv, lambda2=lambda2, method="sLORETA")
        stcs[label] = stc
    return stcs


def source_to_dataframe(stc: mne.SourceEstimate):
    """Convert a SourceEstimate to a simple DataFrame of vertex amplitudes."""
    import pandas as pd

    peak = stc.data.max(axis=1)
    return pd.DataFrame({"Vertex": range(len(peak)), "Amplitude": peak})


def append_source_to_excel(excel_path: str, sheet_name: str, df):
    """Append DataFrame ``df`` to ``excel_path`` under ``sheet_name``."""
    import pandas as pd

    with pd.ExcelWriter(excel_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)

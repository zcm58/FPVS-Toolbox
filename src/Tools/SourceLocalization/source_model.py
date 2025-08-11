# src/Tools/SourceLocalization/source_model.py
"""Utility functions for sLORETA/eLORETA source localization.

This module provides a thin, stable surface that the processing pipeline can call
during batch runs. It handles fetching/normalizing the fsaverage template,
building a forward/inverse model, applying sLORETA, and exporting simple tables.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import mne

from Tools.SourceLocalization.data_utils import (
    fetch_fsaverage_with_progress,
    _resolve_subjects_dir,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Forward / inverse building
# ---------------------------------------------------------------------
def prepare_head_model(
    raw: mne.io.BaseRaw,
    template: str = "fsaverage",
) -> tuple[mne.Forward, str, str]:
    """Compute a forward model using the provided raw data.

    Parameters
    ----------
    raw
        Preprocessed Raw with a valid EEG montage and info.
    template
        The template subject name. Default: "fsaverage".

    Returns
    -------
    (fwd, subject, subjects_dir)
        Forward solution, subject name, and the *parent* subjects_dir that contains
        `<subjects_dir>/<subject>/...`.

    Notes
    -----
    `fetch_fsaverage_with_progress()` returns a nested folder ending in
    `.../fsaverage/fsaverage`. MNE APIs expect `subjects_dir` to be the PARENT that
    contains `<subjects_dir>/<subject>`. We therefore normalize the returned path
    via `_resolve_subjects_dir` before calling MNE functions.
    """
    logger.debug("Fetching fsaverage template to prepare head model")

    # Download/locate fsaverage. This typically returns ".../fsaverage/fsaverage".
    fetched = Path(fetch_fsaverage_with_progress(Path.cwd(), log_func=logger.info))

    # Normalize to the parent subjects_dir that contains <subjects_dir>/<subject>
    subjects_dir = str(_resolve_subjects_dir(fetched, template))
    logger.debug("Normalized subjects_dir resolved to: %s", subjects_dir)

    # Build source space & BEM for the template subject
    src = mne.setup_source_space(
        template, spacing="oct6", subjects_dir=subjects_dir, add_dist=False
    )
    model = mne.make_bem_model(subject=template, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)

    # For template workflows, use the "fsaverage" trans (spherical registration)
    trans = "fsaverage"
    fwd = mne.make_forward_solution(
        raw.info, trans=trans, src=src, bem=bem, eeg=True
    )

    return fwd, template, subjects_dir


def estimate_noise_cov(
    raw: mne.io.BaseRaw,
    tmin: float = 0.0,
    tmax: Optional[float] = None,
) -> mne.Covariance:
    """Estimate a noise covariance matrix from a segment of Raw.

    Parameters
    ----------
    raw
        Preprocessed Raw.
    tmin, tmax
        Time range in seconds to use for the covariance. A common choice is
        `tmax=0.0` to use pre-stim baseline for epoched designs.
    """
    logger.debug("Estimating noise covariance (tmin=%s, tmax=%s)", tmin, tmax)
    return mne.compute_raw_covariance(raw, tmin=tmin, tmax=tmax)


def make_inverse_operator(
    raw: mne.io.BaseRaw,
    fwd: mne.Forward,
    noise_cov: mne.Covariance,
) -> mne.minimum_norm.InverseOperator:
    """Build an inverse operator configured for distributed solutions.

    Uses moderate looseness/depth weighting which are common defaults for
    EEG-only inverse solutions on template anatomy.
    """
    logger.debug("Building inverse operator (loose=0.2, depth=0.8)")
    inv = mne.minimum_norm.make_inverse_operator(
        raw.info, fwd, noise_cov, loose=0.2, depth=0.8
    )
    return inv


# ---------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------
def apply_sloreta(
    epochs_dict: Dict[str, List[mne.Epochs]],
    inv: mne.minimum_norm.InverseOperator,
    snr: float = 3.0,
) -> Dict[str, mne.SourceEstimate]:
    """Apply sLORETA to each condition and return SourceEstimates.

    Parameters
    ----------
    epochs_dict
        Mapping from condition label to a list containing one `mne.Epochs`
        (or an Evoked). Only the first item per condition is used.
    inv
        Inverse operator from :func:`make_inverse_operator`.
    snr
        Signal-to-noise ratio used to set lambda2 (regularization). Default 3.0.

    Returns
    -------
    dict
        { condition_label: SourceEstimate }
    """
    logger.debug("Applying sLORETA (snr=%.3f)", snr)
    lambda2 = 1.0 / (snr ** 2)
    out: Dict[str, mne.SourceEstimate] = {}

    for label, items in epochs_dict.items():
        if not items:
            continue

        ep_or_evoked = items[0]
        if isinstance(ep_or_evoked, mne.Epochs):
            evoked = ep_or_evoked.average()
        else:
            evoked = ep_or_evoked  # already an Evoked

        stc = mne.minimum_norm.apply_inverse(evoked, inv, lambda2=lambda2, method="sLORETA")
        out[label] = stc
        logger.debug("sLORETA computed for condition '%s' (n_times=%d)", label, stc.data.shape[1])

    return out


# ---------------------------------------------------------------------
# Lightweight export helpers
# ---------------------------------------------------------------------
def source_to_dataframe(stc: mne.SourceEstimate):
    """Convert a SourceEstimate into a simple per-vertex amplitude table.

    The "Amplitude" is the maximum over time for each vertex, which is useful
    for quick summaries and sanity checks.
    """
    import pandas as pd  # local import to keep module import-time light

    peak = stc.data.max(axis=1)
    return pd.DataFrame({"Vertex": range(len(peak)), "Amplitude": peak})


def append_source_to_excel(excel_path: str, sheet_name: str, df) -> None:
    """Append or replace a sheet in an Excel file with the provided DataFrame."""
    import pandas as pd  # local import
    from openpyxl import load_workbook  # ensure engine present (raises if missing)

    logger.debug("Appending source data to %s (sheet=%s)", excel_path, sheet_name)

    # If the file exists, open in append mode; otherwise write a new file.
    mode = "a" if Path(excel_path).exists() else "w"
    with pd.ExcelWriter(excel_path, engine="openpyxl", mode=mode, if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)

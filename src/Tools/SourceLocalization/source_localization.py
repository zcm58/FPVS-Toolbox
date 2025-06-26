"""Helper routines for FPVS source localization."""

from __future__ import annotations
import os
from typing import Iterable
import mne
import numpy as np
import pandas as pd
from typing import Sequence


def morph_to_fsaverage(
    stc: mne.SourceEstimate,
    subject: str,
    subjects_dir: str,
    smooth: float = 5.0,
) -> mne.SourceEstimate:
    """Morph ``stc`` from ``subject`` to ``fsaverage``.

    Parameters
    ----------
    stc
        The source estimate to morph.
    subject
        Name of the subject the estimate belongs to.
    subjects_dir
        Directory containing the ``subject`` MRI and ``fsaverage`` template.
    smooth
        Optional smoothing (FWHM in mm) applied during morphing. Defaults to
        ``5.0``.

    Returns
    -------
    :class:`mne.SourceEstimate`
        The morphed source estimate.
    """

    return stc.morph(
        subject_to="fsaverage",
        subject_from=subject,
        subjects_dir=subjects_dir,
        smooth=smooth,
    )



def extract_cycles(epochs: mne.Epochs, oddball_freq: float) -> mne.Epochs:
    """Segment epochs into single oddball cycles aligned to the trigger."""
    if oddball_freq <= 0:
        raise ValueError("oddball_freq must be positive")

    cycle_dur = 1.0 / oddball_freq
    sfreq = epochs.info["sfreq"]
    n_samples = int(round(cycle_dur * sfreq))
    event_idx = int(np.argmin(np.abs(epochs.times)))

    data = []
    for ep in epochs.get_data():
        start = event_idx
        while start + n_samples <= ep.shape[1]:
            stop = start + n_samples
            data.append(ep[:, start:stop])
            start += n_samples

    data = np.array(data)
    return mne.EpochsArray(data, epochs.info, tmin=0.0)


def average_cycles(cycle_epochs: mne.Epochs) -> mne.Evoked:
    """Return an Evoked obtained by averaging cycle epochs."""
    return cycle_epochs.average()



def reconstruct_harmonics(evoked: mne.Evoked, harmonics: Sequence[float]) -> mne.Evoked:

    """Reconstruct an evoked signal using only the specified harmonic frequencies."""
    sfreq = evoked.info["sfreq"]
    data = np.fft.fft(evoked.data)
    freqs = np.fft.fftfreq(evoked.data.shape[1], d=1.0 / sfreq)
    mask = np.zeros_like(freqs, dtype=bool)
    tol = sfreq / evoked.data.shape[1]
    for h in harmonics:
        mask |= np.isclose(freqs, h, atol=tol)
        mask |= np.isclose(freqs, -h, atol=tol)
    data[:, ~mask] = 0
    filtered = np.fft.ifft(data).real
    return mne.EvokedArray(filtered, evoked.info, tmin=evoked.times[0])


def build_inverse_operator(evoked: mne.Evoked, subjects_dir: str) -> mne.minimum_norm.InverseOperator:
    """Construct an inverse operator for the given evoked data."""
    subject = "fsaverage"
    src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)
    fwd = mne.make_forward_solution(evoked.info, trans="fsaverage", src=src, bem=bem, eeg=True)
    noise_cov = mne.make_ad_hoc_cov(evoked.info)
    return mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)


def apply_sloreta(evoked: mne.Evoked, inv: mne.minimum_norm.InverseOperator, snr: float) -> mne.SourceEstimate:
    """Apply sLORETA to evoked data using the provided inverse operator."""
    lambda2 = 1.0 / (snr ** 2)
    return mne.minimum_norm.apply_inverse(evoked, inv, method="sLORETA", lambda2=lambda2)


def export_roi_means(
    stc: mne.SourceEstimate,
    subject: str,
    subjects_dir: str,
    output_path: str,
    labels: Iterable[str] | None = None,
) -> str:
    """Export mean current density for each ROI to ``output_path``.

    Parameters
    ----------
    stc
        Source estimate with data to summarise.
    subject
        Subject name (usually ``fsaverage``) for the atlas lookup.
    subjects_dir
        Directory containing the MRI subject folders.
    output_path
        CSV file path where the ROI amplitudes will be written.
    labels
        Optional list of label names. If ``None`` all ``aparc`` labels are used.
    Returns
    -------
    str
        The path to the saved CSV file.
    """

    if labels is None:
        atlas_labels = mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir)
    else:
        atlas_labels = [lab for lab in mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir) if lab.name in labels]

    src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    tc = mne.extract_label_time_course(stc, atlas_labels, src, mode="mean")
    mean_vals = tc.mean(axis=1)
    df = pd.DataFrame({"ROI": [label.name for label in atlas_labels], "MeanCurrent": mean_vals})
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path

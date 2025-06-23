"""Backend routines for running eLORETA or sLORETA source localization."""

from __future__ import annotations

import os
import logging
from typing import Callable, Optional

import mne
from Main_App.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


def _load_data(fif_path: str) -> mne.Evoked:
    """Load epochs or evoked data and return an Evoked instance."""
    if fif_path.endswith("-epo.fif"):
        epochs = mne.read_epochs(fif_path, preload=True)
        return epochs.average()
    return mne.read_evokeds(fif_path, condition=0, baseline=(None, 0))


def _prepare_forward(evoked: mne.Evoked, settings: SettingsManager) -> tuple[mne.Forward, str, str]:
    """Construct a forward model using MRI info from settings or fsaverage."""
    subjects_dir = settings.get("paths", "mri_subjects_dir", "")
    subject = settings.get("paths", "mri_subject", "fsaverage")
    if not subjects_dir or not os.path.isdir(subjects_dir):
        subjects_dir = mne.datasets.fetch_fsaverage(verbose=True)
        subject = "fsaverage"
    # Use fsaverage transformation if no custom trans file is specified
    trans = settings.get("paths", "trans_file", "fsaverage")
    src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)
    fwd = mne.make_forward_solution(evoked.info, trans=trans, src=src, bem=bem, eeg=True)
    return fwd, subject, subjects_dir


def run_source_localization(
    fif_path: str,
    output_dir: str,
    method: str = "eLORETA",
    threshold: Optional[float] = None,
    log_func: Optional[Callable[[str], None]] = None,
) -> str:
    """Run source localization on ``fif_path`` and save results to ``output_dir``.

    Returns the path to the saved :class:`~mne.SourceEstimate` file.
    """
    if log_func is None:
        log_func = logger.info
    log_func(f"Loading data from {fif_path}")
    settings = SettingsManager()
    evoked = _load_data(fif_path)

    log_func("Preparing forward model ...")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings)

    noise_cov = mne.compute_covariance([evoked], tmax=0.0)
    inv = mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)

    method = method.lower()
    if method not in {"eloreta", "sloreta"}:
        raise ValueError("Method must be 'eLORETA' or 'sLORETA'")

    log_func(f"Applying {method} ...")
    stc = mne.minimum_norm.apply_inverse(evoked, inv, method=method)
    if threshold:
        stc = stc.threshold(threshold)

    os.makedirs(output_dir, exist_ok=True)
    stc_path = os.path.join(output_dir, "source")
    stc.save(stc_path)

    # Visualise in a separate Brain window
    brain = stc.plot(subject=subject, subjects_dir=subjects_dir, time_viewer=False)
    try:
        labels = mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir)
        for label in labels:
            brain.add_label(label, borders=True)
    except Exception:
        # If annotations aren't available just continue without borders
        pass

    for view, name in [("lat", "side"), ("rostral", "frontal"), ("dorsal", "top")]:
        brain.show_view(view)
        brain.save_image(os.path.join(output_dir, f"{name}.png"))
    # Save the current view as an additional screenshot
    brain.save_image(os.path.join(output_dir, "overview.png"))
    brain.close()

    log_func(f"Results saved to {output_dir}")
    return stc_path

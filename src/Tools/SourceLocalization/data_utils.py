"""Utility functions for preparing data for source localization."""

from __future__ import annotations

import os
import threading
import time
import logging
from typing import Callable

import numpy as np
import mne
from Main_App.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


def _load_data(fif_path: str) -> mne.Evoked:
    """Load epochs or evoked data and return an Evoked instance."""
    if fif_path.endswith("-epo.fif"):
        epochs = mne.read_epochs(fif_path, preload=True)
        return epochs.average()
    return mne.read_evokeds(fif_path, condition=0, baseline=(None, 0))


def _default_template_location() -> str:
    """Return the directory where the template MRI should reside."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "fsaverage")


def _dir_size_mb(path: str) -> float:
    """Return the size of ``path`` in megabytes."""
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                pass
    return total / (1024 * 1024)


def _threshold_stc(stc: mne.SourceEstimate, thr: float) -> mne.SourceEstimate:
    """Return a copy of ``stc`` with values below ``thr`` zeroed."""
    stc = stc.copy()
    if 0 < thr < 1:
        thr_val = thr * np.max(np.abs(stc.data))
    else:
        thr_val = thr
    stc.data[np.abs(stc.data) < thr_val] = 0
    return stc


def _estimate_epochs_covariance(
    epochs: mne.Epochs, log_func: Callable[[str], None] = logger.info
) -> mne.Covariance:
    """Return a noise covariance estimated from ``epochs``.

    If more than one epoch is available, ``mne.compute_covariance`` is used
    with ``tmax=0.0``. Otherwise an ad-hoc covariance is returned and a log
    message is emitted.
    """

    if len(epochs) > 1:
        return mne.compute_covariance(epochs, tmax=0.0)

    log_func("Only one epoch available. Using ad-hoc covariance.")
    return mne.make_ad_hoc_cov(epochs.info)


def fetch_fsaverage_with_progress(
    subjects_dir: str, log_func: Callable[[str], None] = logger.info
) -> str:
    """Download ``fsaverage`` while logging progress to ``log_func``."""
    stop_event = threading.Event()

    def _report():
        dest = os.path.join(subjects_dir, "fsaverage")
        last = -1.0
        while not stop_event.is_set():
            if os.path.isdir(dest):
                size = _dir_size_mb(dest)
                if size != last:
                    log_func(f"Downloaded {size:.1f} MB...")
                    last = size
            time.sleep(1)

    thread = threading.Thread(target=_report, daemon=True)
    thread.start()
    try:
        path = mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose=True)
    finally:
        stop_event.set()
        thread.join()

    log_func(f"Download complete. Total size: {_dir_size_mb(path):.1f} MB")
    return path


def _prepare_forward(
    evoked: mne.Evoked,
    settings: SettingsManager,
    log_func: Callable[[str], None],
) -> tuple[mne.Forward, str, str]:
    """Construct a forward model using MRI info from settings or fsaverage."""
    stored_dir = settings.get("loreta", "mri_path", "")
    if stored_dir:
        stored_dir = os.path.normpath(stored_dir)
    subject = "fsaverage"

    log_func(f"Initial stored MRI directory: {stored_dir}")

    if not stored_dir or not os.path.isdir(stored_dir):
        log_func(
            "Default MRI template not found. Downloading 'fsaverage'. This may take a few minutes..."
        )

        install_parent = os.path.dirname(_default_template_location())
        log_func(f"Attempting download to: {install_parent}")
        try:
            fs_path = fetch_fsaverage_with_progress(install_parent, log_func)
        except Exception as err:
            log_func(
                f"Progress download failed ({err}). Falling back to mne.datasets.fetch_fsaverage"
            )
            fs_path = mne.datasets.fetch_fsaverage(
                subjects_dir=install_parent, verbose=True
            )
        settings.set("loreta", "mri_path", str(fs_path))

        try:
            settings.save()
        except Exception:
            pass

        log_func(f"Template downloaded to: {fs_path}")

        stored_dir = fs_path
    else:
        log_func(f"Using existing MRI directory: {stored_dir}")

    if os.path.basename(stored_dir) == subject:
        subjects_dir = os.path.dirname(stored_dir)
        log_func(f"Parent directory for subjects set to: {subjects_dir}")
    else:
        subjects_dir = stored_dir
        log_func(f"Subjects directory resolved to: {subjects_dir}")

    surf_dir = os.path.join(subjects_dir, subject, "surf")
    log_func(f"Expecting surface files in: {surf_dir}")

    trans = settings.get("paths", "trans_file", "fsaverage")
    log_func(f"Using trans file: {trans}")
    log_func(
        f"Building source space using subjects_dir={subjects_dir}, subject={subject}"
    )
    src = mne.setup_source_space(
        subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False
    )
    cache_dir = os.path.join(subjects_dir, "fpvs_cache")
    os.makedirs(cache_dir, exist_ok=True)
    fwd_file = os.path.join(cache_dir, f"forward-{subject}.fif")

    if os.path.isfile(fwd_file):
        log_func(f"Loading cached forward model from {fwd_file}")
        fwd = mne.read_forward_solution(fwd_file)
    else:
        log_func("Creating BEM model ...")
        model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
        bem = mne.make_bem_solution(model)
        log_func("Computing forward solution ...")
        fwd = mne.make_forward_solution(
            evoked.info, trans=trans, src=src, bem=bem, eeg=True
        )
        mne.write_forward_solution(fwd_file, fwd, overwrite=True)
    return fwd, subject, subjects_dir

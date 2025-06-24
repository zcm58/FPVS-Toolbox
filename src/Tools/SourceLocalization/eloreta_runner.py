"""Backend routines for running eLORETA or sLORETA source localization."""

from __future__ import annotations

import os
import logging
import threading
import time
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


def fetch_fsaverage_with_progress(subjects_dir: str, log_func: Callable[[str], None] = logger.info) -> str:
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
            log_func(f"Progress download failed ({err}). Falling back to mne.datasets.fetch_fsaverage")
            fs_path = mne.datasets.fetch_fsaverage(subjects_dir=install_parent, verbose=True)
        # ``configparser.ConfigParser`` requires string values
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


    # Use fsaverage transformation if no custom trans file is specified
    trans = settings.get("paths", "trans_file", "fsaverage")
    log_func(f"Using trans file: {trans}")
    log_func(f"Building source space using subjects_dir={subjects_dir}, subject={subject}")
    src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    log_func("Creating BEM model ...")
    model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)
    log_func("Computing forward solution ...")
    fwd = mne.make_forward_solution(evoked.info, trans=trans, src=src, bem=bem, eeg=True)
    return fwd, subject, subjects_dir


def run_source_localization(
    fif_path: str,
    output_dir: str,
    method: str = "eLORETA",
    threshold: Optional[float] = None,
    log_func: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> str:
    """Run source localization on ``fif_path`` and save results to ``output_dir``.

    Returns the path to the saved :class:`~mne.SourceEstimate` file.
    """
    if log_func is None:
        log_func = logger.info
    step = 0
    total = 7
    if progress_cb:
        progress_cb(0.0)
    log_func(f"Loading data from {fif_path}")
    settings = SettingsManager()
    evoked = _load_data(fif_path)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    log_func("Preparing forward model ...")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward model ready. subjects_dir={subjects_dir}, subject={subject}")
    step += 1
    if progress_cb:
        progress_cb(step / total)

    noise_cov = mne.compute_covariance([evoked], tmax=0.0)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    inv = mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    method_lower = method.lower()
    if method_lower not in {"eloreta", "sloreta"}:
        raise ValueError("Method must be 'eLORETA' or 'sLORETA'")

    log_func(f"Applying {method_lower} ...")
    mne_method = "eLORETA" if method_lower == "eloreta" else "sLORETA"
    stc = mne.minimum_norm.apply_inverse(evoked, inv, method=mne_method)
    if threshold:
        stc = stc.threshold(threshold)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    os.makedirs(output_dir, exist_ok=True)
    stc_path = os.path.join(output_dir, "source")
    stc.save(stc_path)
    step += 1
    if progress_cb:
        progress_cb(step / total)

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
    step += 1
    if progress_cb:
        progress_cb(step / total)

    log_func(f"Results saved to {output_dir}")
    if progress_cb:
        progress_cb(1.0)
    return stc_path

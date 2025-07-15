"""Utility functions for preparing data for source localization."""

from __future__ import annotations

import threading
import time
import logging
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple

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


def _default_template_location() -> Path:
    """Return the directory where the template MRI should reside."""
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "fsaverage"


def _wrap_fsaverage(subjects_dir: Path, subject: str = "fsaverage") -> None:
    """Ensure ``subjects_dir/subject`` contains a nested ``subject`` folder."""
    flat = subjects_dir / subject
    nested = flat / subject
    if flat.is_dir() and not nested.exists():
        nested.mkdir()
        for child in flat.iterdir():
            if child.name == subject:
                continue
            shutil.move(str(child), str(nested / child.name))


def _resolve_subjects_dir(path: Path | None, subject: str) -> Path:
    """Normalize ``path`` so that it points to the subjects directory.

    If ``path`` directly references the subject folder or redundantly includes
    the subject name twice (``.../fsaverage/fsaverage``), the parent directory is
    returned so that MNE can locate files using ``<subjects_dir>/<subject>``.
    """

    if path is None:
        return _default_template_location().parent

    path = path.resolve()

    if (path / subject).is_dir():
        return path
    if path.parts[-2:] == (subject, subject):
        return path.parent
    if path.name.lower() == subject.lower():
        return path.parent
    return path


def _dir_size_mb(path: str | Path) -> float:
    """Return the size of ``path`` in megabytes."""
    path = Path(path)
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
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
    if SettingsManager().debug_enabled():
        active = int(np.count_nonzero(np.any(stc.data != 0, axis=1)))
        logger.debug(
            "threshold_stc: thr=%s cutoff=%.5f active_vertices=%s",
            thr,
            thr_val,
            active,
        )
    return stc


def _estimate_epochs_covariance(
    epochs: mne.Epochs,
    log_func: Callable[[str], None] = logger.info,
    baseline: Optional[Tuple[float | None, float | None]] = None,
) -> mne.Covariance:
    """Return a noise covariance estimated from ``epochs``.

    If more than one epoch is available ``mne.compute_covariance`` is used.
    When ``baseline`` is provided the same time window is passed to
    :func:`mne.compute_covariance` via ``tmin``/``tmax``. Otherwise ``tmax=0.0``
    is used. If only a single epoch is present an ad-hoc covariance is returned
    and a message logged via ``log_func``.
    """

    if len(epochs) > 1:
        if baseline is not None:
            tmin, tmax = baseline
            return mne.compute_covariance(epochs, tmin=tmin, tmax=tmax)
        return mne.compute_covariance(epochs, tmax=0.0)

    log_func("Only one epoch available. Using ad-hoc covariance.")
    return mne.make_ad_hoc_cov(epochs.info)


def fetch_fsaverage_with_progress(
    subjects_dir: str | Path, log_func: Callable[[str], None] = logger.info
) -> str:
    """Download ``fsaverage`` while logging progress to ``log_func``.

    Returns the path to the downloaded ``fsaverage`` directory. The folder is
    wrapped so that ``subjects_dir/fsaverage`` contains another ``fsaverage``
    directory holding the actual template files.
    """
    subjects_dir = Path(subjects_dir)
    dest = subjects_dir / "fsaverage"

    if (dest / "fsaverage" / "surf" / "lh.white").exists() and (
        dest / "fsaverage" / "bem" / "fsaverage-5120-bem.fif"
    ).exists():
        _wrap_fsaverage(subjects_dir, subject="fsaverage")
        return str(dest / "fsaverage")

    stop_event = threading.Event()

    def _report():
        dest = subjects_dir / "fsaverage"
        last = -1.0
        while not stop_event.is_set():
            if dest.is_dir():
                size = _dir_size_mb(dest)
                if size != last:
                    log_func(f"Downloaded {size:.1f} MB...")
                    last = size
            time.sleep(1)

    thread = threading.Thread(target=_report, daemon=True)
    thread.start()
    try:
        path = Path(
            mne.datasets.fetch_fsaverage(subjects_dir=str(subjects_dir), verbose=True)
        )
    finally:
        stop_event.set()
        thread.join()

    _wrap_fsaverage(subjects_dir, subject="fsaverage")

    log_func(f"Download complete. Total size: {_dir_size_mb(path):.1f} MB")
    return str(path)


def _prepare_forward(
    evoked: mne.Evoked,
    settings: SettingsManager,
    log_func: Callable[[str], None],
) -> tuple[mne.Forward, str, str]:
    """Construct a forward model using MRI info from settings or fsaverage."""
    stored_dir = settings.get("loreta", "mri_path", "")
    stored_dir_path: Path | None = None
    if stored_dir:
        stored_dir_path = Path(stored_dir).resolve()
    subject = "fsaverage"

    log_func(f"Initial stored MRI directory: {stored_dir_path or stored_dir}")

    if stored_dir_path is None or not stored_dir_path.is_dir():
        log_func(
            "Default MRI template not found. Downloading 'fsaverage'. This may take a few minutes..."
        )

        install_parent = _default_template_location().parent
        log_func(f"Attempting download to: {install_parent}")
        try:
            fs_path = fetch_fsaverage_with_progress(install_parent, log_func)
        except Exception as err:
            log_func(
                f"Progress download failed ({err}). Falling back to mne.datasets.fetch_fsaverage"
            )
            fs_path = Path(
                mne.datasets.fetch_fsaverage(subjects_dir=str(install_parent), verbose=True)
            )
        settings.set("loreta", "mri_path", str(fs_path))

        try:
            settings.save()
        except Exception:
            pass

        log_func(f"Template downloaded to: {fs_path}")

        stored_dir_path = Path(fs_path)
    else:
        log_func(f"Using existing MRI directory: {stored_dir_path}")

    subjects_dir_path = _resolve_subjects_dir(stored_dir_path, subject)
    log_func(f"Subjects directory resolved to: {subjects_dir_path}")

    surf_dir = subjects_dir_path / subject / "surf"
    log_func(f"Expecting surface files in: {surf_dir}")
    for fname in ["lh.pial", "rh.pial", "lh.white", "rh.white"]:
        path = surf_dir / fname
        log_func(f"Surface file {path} {'found' if path.exists() else 'MISSING'}")
    bem_file = subjects_dir_path / subject / "bem" / f"{subject}-5120-bem.fif"
    log_func(
        f"BEM file {bem_file} {'found' if bem_file.exists() else 'MISSING'}"
    )

    trans = settings.get("paths", "trans_file", "fsaverage")
    log_func(f"Using trans file: {trans}")

    cache_dir = subjects_dir_path / "fpvs_cache"
    cache_dir.mkdir(exist_ok=True)
    fwd_file = cache_dir / f"forward-{subject}.fif"

    if fwd_file.is_file():
        log_func(f"Loading cached forward model from {fwd_file}")
        fwd = mne.read_forward_solution(str(fwd_file))
        return fwd, subject, str(subjects_dir_path)

    log_func(
        f"Building source space using subjects_dir={subjects_dir_path}, subject={subject}"
    )
    src = mne.setup_source_space(
        subject, spacing="oct6", subjects_dir=str(subjects_dir_path), add_dist=False
    )

    log_func("Creating BEM model ...")
    model = mne.make_bem_model(subject=subject, subjects_dir=str(subjects_dir_path), ico=4)
    bem = mne.make_bem_solution(model)
    log_func("Computing forward solution ...")
    fwd = mne.make_forward_solution(
        evoked.info, trans=trans, src=src, bem=bem, eeg=True
    )
    mne.write_forward_solution(str(fwd_file), fwd, overwrite=True)
    return fwd, subject, str(subjects_dir_path)

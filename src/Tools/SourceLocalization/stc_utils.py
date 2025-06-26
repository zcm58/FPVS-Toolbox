"""Helper functions for averaging and morphing source estimates."""

from __future__ import annotations

import os
from typing import Callable

import mne
from mne import compute_source_morph
import numpy as np

from . import source_localization

morph_to_fsaverage = source_localization.morph_to_fsaverage

__all__ = [
    "average_stc_files",
    "average_stc_directory",
    "average_conditions_dir",
    "average_conditions_to_fsaverage",
    "morph_to_fsaverage",
]


def average_stc_files(stcs: list) -> mne.SourceEstimate:
    """Return the element-wise mean of multiple :class:`mne.SourceEstimate` objects."""

    if not stcs:
        raise ValueError("No source estimates provided")

    loaded = []
    for stc in stcs:
        if isinstance(stc, str):
            loaded.append(mne.read_source_estimate(stc))
        else:
            loaded.append(stc)

    template = loaded[0].copy()
    sum_data = np.zeros_like(template.data)
    for stc in loaded:
        sum_data += stc.data
    template.data = sum_data / len(loaded)
    return template


def _infer_average_name(files: list[str]) -> str:
    """Return a descriptive base name for averaged STC files."""

    if not files:
        return "Average"

    # use the first file as template to derive the condition name
    name = os.path.basename(files[0])
    if name.endswith(('-lh.stc', '-rh.stc')):
        name = name[:-7]

    # drop subject specific prefixes by splitting on the first two underscores
    parts = name.split('_', 2)
    if len(parts) == 3:
        cond = parts[2]
    else:
        cond = parts[-1]

    cond = cond.replace('_', ' ').strip()
    return f"Average {cond} Response"


def average_stc_directory(
    condition_dir: str,
    *,
    output_basename: str | None = None,
    log_func: Callable[[str], None] = print,
    subjects_dir: str = "",
    smooth: float = 5.0,
) -> str:
    """Average all ``*-lh.stc`` and ``*-rh.stc`` files in ``condition_dir``."""

    stc_paths = [
        os.path.join(condition_dir, f)
        for f in os.listdir(condition_dir)
        if f.endswith("-lh.stc") or f.endswith("-rh.stc")
    ]
    if not stc_paths:
        raise FileNotFoundError("No STC files found in directory")

    groups: dict[str, list[mne.SourceEstimate]] = {"lh": [], "rh": []}
    for path in stc_paths:
        stc = mne.read_source_estimate(path)
        hemi = "lh" if path.endswith("-lh.stc") else "rh"
        subject = os.path.basename(path).rsplit("-", 1)[0]
        stc = source_localization.morph_to_fsaverage(
            stc,
            subject,
            subjects_dir,
            smooth=smooth,
        )
        groups[hemi].append(stc)

    if output_basename is None:
        base = _infer_average_name(stc_paths)
    else:
        base = output_basename
    out_path = os.path.join(condition_dir, base)

    lh_stc = rh_stc = None
    if groups["lh"]:
        log_func(f"Averaging {len(groups['lh'])} LH files in {condition_dir}")
        lh_stc = average_stc_files(groups["lh"])
    if groups["rh"]:
        log_func(f"Averaging {len(groups['rh'])} RH files in {condition_dir}")
        rh_stc = average_stc_files(groups["rh"])

    if lh_stc is not None:
        lh_stc.save(out_path)
    if rh_stc is not None:
        rh_stc.save(out_path)

    return out_path


def average_conditions_dir(
    results_dir: str,
    *,
    log_func: Callable[[str], None] = print,
    subjects_dir: str = "",
    smooth: float = 5.0,
) -> list[str]:
    """Average STC files in each subdirectory of ``results_dir``."""

    averaged = []
    for name in sorted(os.listdir(results_dir)):
        subdir = os.path.join(results_dir, name)
        if not os.path.isdir(subdir):
            continue
        try:
            path = average_stc_directory(
                subdir,
                log_func=log_func,
                subjects_dir=subjects_dir,
                smooth=smooth,
            )
        except Exception as err:
            log_func(f"Skipping {subdir}: {err}")
        else:
            averaged.append(path)
    return averaged


def _morph_to_fsaverage(
    stc: mne.SourceEstimate,
    subjects_dir: str,
    smooth: int = 20,
    *,
    subject: str | None = None,
) -> mne.SourceEstimate:
    """Return ``stc`` morphed to the ``fsaverage`` template.

    Older ``.stc`` files may miss the subject information entirely.  In that
    case ``fsaverage`` is assumed to avoid ``compute_source_morph`` failing with
    ``subject_from could not be inferred``.
    """

    subj = subject or stc.subject or "fsaverage"

    morph = compute_source_morph(
        stc,
        subject_from=subj,
        subject_to="fsaverage",
        subjects_dir=subjects_dir,
        smooth=smooth,
    )
    return morph.apply(stc)


def average_conditions_to_fsaverage(
    results_dir: str,
    subjects_dir: str,
    *,
    log_func: Callable[[str], None] = print,
) -> list[str]:
    """Morph and average condition STCs to ``fsaverage``."""

    averaged: list[str] = []
    for name in sorted(os.listdir(results_dir)):
        subdir = os.path.join(results_dir, name)
        if not os.path.isdir(subdir):
            continue

        bases = {
            os.path.join(subdir, f[:-7])
            for f in os.listdir(subdir)
            if f.endswith(("-lh.stc", "-rh.stc"))
        }
        bases = [
            b
            for b in bases
            if not os.path.basename(b).startswith("Average ")
            and os.path.basename(b) != "fsaverage"
        ]

        morphed = []
        for base in sorted(bases):
            try:
                stc = mne.read_source_estimate(base)
                fs_stc = _morph_to_fsaverage(stc, subjects_dir)
                morphed.append(fs_stc)
            except Exception as err:
                log_func(f"Skipping {base}: {err}")

        if morphed:
            log_func(f"Averaging {len(morphed)} morphed files in {subdir}")
            avg = average_stc_files(morphed)
            out_path = os.path.join(subdir, "fsaverage")
            avg.save(out_path)
            averaged.append(out_path)
    return averaged

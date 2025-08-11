""""Helper routines for FPVS source localization (trimmed for oddball ERP)."""

from __future__ import annotations

from typing import Iterable, Sequence, Optional
import os
import mne
import numpy as np
import pandas as pd


def morph_to_fsaverage(
    stc: mne.SourceEstimate,
    subject: str,
    subjects_dir: str,
    smooth: float = 5.0,
) -> mne.SourceEstimate:
    """Morph STC from subject to fsaverage."""
    return stc.morph(
        subject_to="fsaverage",
        subject_from=subject,
        subjects_dir=subjects_dir,
        smooth=smooth,
    )


def export_roi_means(
    stc: mne.SourceEstimate,
    subject: str,
    subjects_dir: str,
    output_path: str,
    src: Optional[mne.SourceSpaces] = None,
    labels: Iterable[str] | None = None,
) -> str:
    """Export mean |current| per ROI to ``output_path`` (fsaverage aparc)."""
    if labels is None:
        atlas_labels = mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir)
    else:
        atlas_labels = [
            lab for lab in mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir)
            if lab.name in labels
        ]

    # Use provided src if available; else derive from STC vertices (slower)
    if src is None:
        # Reconstruct a source space matching STC vertex IDs for fsaverage/oct6
        src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)

    # Use magnitude to avoid sign cancellation
    mag = stc.copy()
    mag._data = np.abs(mag._data)

    tc = mne.extract_label_time_course(mag, atlas_labels, src, mode="mean")
    mean_vals = tc.mean(axis=1)
    df = pd.DataFrame({"ROI": [label.name for label in atlas_labels], "MeanAbsCurrent": mean_vals})
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


__all__ = ["morph_to_fsaverage", "export_roi_means"]

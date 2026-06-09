"""Source-space ROI helpers for source-localization producer summaries.

These helpers map anatomical label definitions onto already-computed source
spaces. They do not estimate sources, render payloads, or perform statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

DESIKAN_KILLIANY_TEMPORAL_HAUK_ROI_ID = "desikan_killiany_temporal_hauk"
DESIKAN_KILLIANY_TEMPORAL_HAUK_LABEL = "Desikan-Killiany inferior/middle/superior temporal"
DESIKAN_KILLIANY_TEMPORAL_HAUK_DEFINITION = (
    "FreeSurfer fsaverage aparc labels inferiortemporal, middletemporal, "
    "and superiortemporal in each hemisphere"
)
DESIKAN_KILLIANY_TEMPORAL_LABELS = (
    "inferiortemporal",
    "middletemporal",
    "superiortemporal",
)


@dataclass(frozen=True)
class SourceRoiMaskPair:
    """Left/right source-vertex masks for one named ROI."""

    roi_id: str
    label: str
    definition: str
    left_mask: np.ndarray
    right_mask: np.ndarray
    metadata: Mapping[str, object]


def desikan_killiany_temporal_hauk_roi(
    *,
    source_vertex_ids: Sequence[int],
    source_hemispheres: Sequence[str],
    subjects_dir: str | Path,
    subject: str = "fsaverage",
) -> SourceRoiMaskPair:
    """Build Hauk-style temporal ROI masks from fsaverage aparc labels."""
    labels_by_hemi = _read_desikan_killiany_temporal_label_vertices(
        subjects_dir=subjects_dir,
        subject=subject,
    )
    return desikan_killiany_temporal_hauk_roi_from_label_vertices(
        source_vertex_ids=source_vertex_ids,
        source_hemispheres=source_hemispheres,
        labels_by_hemi=labels_by_hemi,
        subjects_dir=str(Path(subjects_dir)),
        subject=subject,
    )


def desikan_killiany_temporal_hauk_roi_from_label_vertices(
    *,
    source_vertex_ids: Sequence[int],
    source_hemispheres: Sequence[str],
    labels_by_hemi: Mapping[str, Mapping[str, Sequence[int]]],
    subjects_dir: str | Path | None = None,
    subject: str = "fsaverage",
) -> SourceRoiMaskPair:
    """Build Hauk-style temporal ROI masks from pre-read label vertices."""
    vertex_ids = tuple(int(value) for value in source_vertex_ids)
    hemispheres = tuple(str(value).strip().lower() for value in source_hemispheres)
    if len(vertex_ids) != len(hemispheres):
        raise ValueError("Source ROI vertex IDs and hemisphere labels must have the same length.")
    source_count = len(vertex_ids)
    if source_count == 0:
        raise ValueError("Source ROI masks require at least one source vertex.")
    if any(hemi not in {"lh", "rh"} for hemi in hemispheres):
        raise ValueError("Source ROI hemisphere labels must be 'lh' or 'rh'.")
    label_sets = _temporal_label_sets(labels_by_hemi)
    left_mask = np.zeros(source_count, dtype=bool)
    right_mask = np.zeros(source_count, dtype=bool)
    for index, (vertex_id, hemi) in enumerate(zip(vertex_ids, hemispheres, strict=True)):
        if hemi == "lh" and vertex_id in label_sets["lh"]:
            left_mask[index] = True
        elif hemi == "rh" and vertex_id in label_sets["rh"]:
            right_mask[index] = True
    if not np.any(left_mask) or not np.any(right_mask):
        raise ValueError(
            "Desikan-Killiany temporal ROI did not overlap both hemispheres of the source space."
        )
    return SourceRoiMaskPair(
        roi_id=DESIKAN_KILLIANY_TEMPORAL_HAUK_ROI_ID,
        label=DESIKAN_KILLIANY_TEMPORAL_HAUK_LABEL,
        definition=DESIKAN_KILLIANY_TEMPORAL_HAUK_DEFINITION,
        left_mask=left_mask,
        right_mask=right_mask,
        metadata={
            "roi_source": "fsaverage_aparc_desikan_killiany",
            "roi_subject": str(subject),
            "roi_subjects_dir": "" if subjects_dir is None else str(subjects_dir),
            "roi_labels": list(DESIKAN_KILLIANY_TEMPORAL_LABELS),
            "left_roi_source_count": int(np.count_nonzero(left_mask)),
            "right_roi_source_count": int(np.count_nonzero(right_mask)),
        },
    )


def _read_desikan_killiany_temporal_label_vertices(
    *,
    subjects_dir: str | Path,
    subject: str,
) -> dict[str, dict[str, tuple[int, ...]]]:
    try:
        import mne
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("MNE is required to read fsaverage aparc labels for source ROIs.") from exc
    try:
        labels = mne.read_labels_from_annot(
            subject,
            parc="aparc",
            subjects_dir=subjects_dir,
            verbose=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Unable to read fsaverage aparc labels for source ROIs: {exc}") from exc
    out: dict[str, dict[str, tuple[int, ...]]] = {"lh": {}, "rh": {}}
    wanted = set(DESIKAN_KILLIANY_TEMPORAL_LABELS)
    for label in labels:
        name = str(label.name).removesuffix("-lh").removesuffix("-rh")
        hemi = str(label.hemi)
        if hemi in out and name in wanted:
            out[hemi][name] = tuple(int(vertex) for vertex in label.vertices)
    _temporal_label_sets(out)
    return out


def _temporal_label_sets(
    labels_by_hemi: Mapping[str, Mapping[str, Sequence[int]]],
) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for hemi in ("lh", "rh"):
        hemi_labels = labels_by_hemi.get(hemi, {})
        missing = sorted(set(DESIKAN_KILLIANY_TEMPORAL_LABELS) - set(hemi_labels))
        if missing:
            raise ValueError(f"Missing Desikan-Killiany temporal label(s) for {hemi}: {missing}.")
        vertices: set[int] = set()
        for label_name in DESIKAN_KILLIANY_TEMPORAL_LABELS:
            vertices.update(int(vertex) for vertex in hemi_labels[label_name])
        out[hemi] = vertices
    return out

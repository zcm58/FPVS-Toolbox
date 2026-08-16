"""Collision-safe, cross-platform artifact names for SNR figure rendering."""

from __future__ import annotations

import hashlib
import re


GROUP_OVERLAY_SUFFIX = "_group_overlay"
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\\\|?*\x00-\x1f]+')
# Leave headroom for both figure extensions on Windows installations that still
# enforce conservative path limits.
_MAX_FIGURE_STEM_CHARS = 96
_STEM_HASH_CHARS = 12


def _stem_with_hash(stem: str, *, identity: str, salt: str = "") -> str:
    digest = hashlib.sha256(
        f"{identity}\x00{salt}".encode("utf-8")
    ).hexdigest()[:_STEM_HASH_CHARS]
    suffix = f"__{digest}"
    prefix = stem[: _MAX_FIGURE_STEM_CHARS - len(suffix)].rstrip(" ._")
    return f"{prefix or 'SNR Plot'}{suffix}"


def safe_figure_stem(*, base_title: str, roi: str) -> str:
    """Return a Windows-safe figure stem while preserving the title/ROI shape."""

    title = str(base_title or "").strip() or "SNR Plot"
    roi_label = str(roi or "").strip() or "ROI"
    stem = f"{title} - {roi_label}"
    stem = _ILLEGAL_FILENAME_CHARS.sub("_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._")
    stem = stem or "SNR Plot"
    if len(stem) <= _MAX_FIGURE_STEM_CHARS:
        return stem
    return _stem_with_hash(
        stem,
        identity=f"{title}\x00{roi_label}",
    )


def claim_figure_stem(
    owner: object,
    *,
    base_title: str,
    roi: str,
    suffix: str = "",
) -> str:
    """Return one unique, stable stem for this rendering run."""

    title = str(base_title or "").strip() or "SNR Plot"
    roi_label = str(roi or "").strip() or "ROI"
    identity = f"{title}\x00{roi_label}\x00{suffix}"
    base_stem = safe_figure_stem(base_title=title, roi=roi_label)
    candidate = f"{base_stem}{suffix}"
    if len(candidate) > _MAX_FIGURE_STEM_CHARS:
        candidate = _stem_with_hash(candidate, identity=identity)

    claimed = getattr(owner, "_snr_claimed_figure_stems", None)
    if claimed is None:
        claimed = set()
        setattr(owner, "_snr_claimed_figure_stems", claimed)
    if candidate not in claimed:
        claimed.add(candidate)
        return candidate

    attempt = 0
    while True:
        alternate = _stem_with_hash(
            candidate,
            identity=identity,
            salt=str(attempt),
        )
        if alternate not in claimed:
            claimed.add(alternate)
            return alternate
        attempt += 1


__all__ = ["GROUP_OVERLAY_SUFFIX", "claim_figure_stem", "safe_figure_stem"]

"""Shared participant identity parsing for canonical raw-recording workflows."""

from __future__ import annotations

import re
from pathlib import Path


_PARTICIPANT_ID_REGEX = re.compile(
    r"(?<![A-Za-z0-9])(P\d+|Sub\d+|S\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RAW_SUFFIX_REGEX = re.compile(
    r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$",
    re.IGNORECASE,
)


def infer_raw_participant_id(file_path: str | Path) -> str:
    """Infer the stable participant label used by processing and import audit."""

    path = Path(file_path)
    base = path.stem
    match = _PARTICIPANT_ID_REGEX.search(base)
    if match:
        return match.group(1).upper()

    cleaned = _RAW_SUFFIX_REGEX.sub("", base)
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned if cleaned else base


__all__ = ["infer_raw_participant_id"]

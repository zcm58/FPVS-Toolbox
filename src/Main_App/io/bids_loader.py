"""Project-owned BIDS admission shared by full, lazy, and prefetched reads."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def project_import_root(app: Any, settings: Mapping[str, Any]) -> Path:
    """Require explicit project context; never create a dataset beside a source."""
    project = getattr(app, "currentProject", None)
    value = settings.get("project_root") or getattr(project, "project_root", None)
    if not value:
        raise ValueError("Open a project before importing an EEG recording into BIDS.")
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("The EEG import project root must be absolute.")
    if not root.is_dir():
        raise ValueError("The EEG import project root does not exist.")
    return root.resolve(strict=True)


def read_project_bids_raw(
    app: Any,
    path: str | Path,
    *,
    settings: Mapping[str, Any],
    preload: bool | str = False,
    stim_channel: str = "Status",
    include: Sequence[str] | None = None,
) -> Any:
    """Prepare a verified BIDS import, then return the shared MNE recording."""
    from Main_App.io.bids_import import prepare_bids_recording, read_bids_recording

    import_settings = {**settings, "stim_channel": stim_channel}
    descriptor = prepare_bids_recording(
        path, project_root=project_import_root(app, settings), settings=import_settings,
    )
    extra = {}
    if Path(path).suffix.lower() == ".bdf":
        extra["stim_channel"] = stim_channel
        if include is not None:
            extra["include"] = list(include)
    raw = read_bids_recording(
        descriptor, preload=preload, extra_params=extra, stim_channel=stim_channel,
    )
    raw._fpvs_bids_import = {
        **getattr(raw, "_fpvs_bids_import", {}),
        "dataset_root": str(descriptor.dataset_root),
        "conversion_seconds": descriptor.conversion_seconds,
        "reused": descriptor.reused,
    }
    logger.info(
        "bids_import_ready source=%s dataset=%s reused=%s conversion_seconds=%.6f",
        path, descriptor.dataset_root, descriptor.reused, descriptor.conversion_seconds,
    )
    return raw
